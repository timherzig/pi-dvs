/* Copyright (C) 2026 Tim Herzig. SPDX-License-Identifier: GPL-3.0-only
 * pi-dvs headless control for upstream xwax 1.10. Socket work is NEVER registered
 * with rt_add_controller: this is an ordinary SCHED_OTHER service thread.
 */
#define _GNU_SOURCE /* accept4 */
#include <assert.h>
#include <errno.h>
#include <fcntl.h>
#include <fcntl.h>
#include <math.h>
#include <poll.h>
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/un.h>
#include <time.h>
#include <unistd.h>
#include "deck.h"
#include "player.h"
#include "remote.h"
#include "rig.h"

_Static_assert(ATOMIC_INT_LOCK_FREE == 2, "Control handoff requires lock-free integers");
#define DIRTY 4u
#define MAX_LINE 1024

void remote_player_init(struct player *pl)
{
    struct remote_player *r = &pl->remote;
    memset(r, 0, sizeof *r);
    r->writer = 2;
    r->reader = 0;
    atomic_init(&r->middle, 1);
    atomic_init(&r->result, REMOTE_IDLE);
    for (unsigned i = 0; i < 3; i++)
        r->snapshot[i].timecode_control = true;
}

void remote_submit(struct player *pl, struct track *track, bool protect)
{
    struct remote_player *r = &pl->remote;
    assert(atomic_load_explicit(&r->result, memory_order_acquire) == REMOTE_IDLE);
    r->incoming = track;
    r->retired = NULL;
    r->protect = protect;
    atomic_store_explicit(&r->result, REMOTE_PENDING, memory_order_release);
}

void remote_apply(struct player *pl)
{
    struct remote_player *r = &pl->remote;
    if (atomic_load_explicit(&r->result, memory_order_acquire) != REMOTE_PENDING)
        return;
    /* This runs AFTER this buffer's native timecode/speed update. No control
     * thread writes player state or takes the player's audio-source spinlock. */
    if (r->protect && player_is_active(pl)) {
        atomic_store_explicit(&r->result, REMOTE_LOCKED, memory_order_release);
        return;
    }
    r->retired = pl->track;
    pl->track = r->incoming;
    atomic_store_explicit(&r->result, REMOTE_OK, memory_order_release);
}

static void publish(struct player *pl, bool known)
{
    struct remote_player *r = &pl->remote;
    r->snapshot[r->writer] = (struct remote_snapshot) {
        .elapsed = player_get_elapsed(pl), .pitch = pl->pitch,
        .timecode_control = pl->timecode_control, .position_known = known,
        .callbacks = r->callbacks,
    };
    r->writer = atomic_exchange_explicit(&r->middle, r->writer | DIRTY,
                                         memory_order_acq_rel) & ~DIRTY;
}

void remote_publish(struct player *pl, bool position_known)
{
    pl->remote.callbacks++;
    publish(pl, position_known);
}

struct remote_snapshot remote_read(struct player *pl)
{
    struct remote_player *r = &pl->remote;
    if (atomic_load_explicit(&r->middle, memory_order_acquire) & DIRTY)
        r->reader = atomic_exchange_explicit(&r->middle, r->reader,
                                             memory_order_acq_rel) & ~DIRTY;
    return r->snapshot[r->reader];
}

struct remote {
    struct deck *deck;
    struct track *track, *preparing;
    bool streaming, pending_streaming;
    double total_duration, pending_duration;
    char *path, *pending_path;
    char id[33];
    const char *result;
    bool pending, submitted, unload, dummy;
    int listener, client;
    char socket_path[sizeof(((struct sockaddr_un*)0)->sun_path)];
    char input[MAX_LINE];
    size_t fill;
    pthread_t thread;
    atomic_bool stop;
    uint64_t last_callbacks;
    double last_audio;
};

static double now(void)
{
    struct timespec t;
    clock_gettime(CLOCK_MONOTONIC, &t);
    return t.tv_sec + t.tv_nsec / 1e9;
}

static void disconnect(struct remote *r)
{
    if (r->client != -1)
        close(r->client);
    r->client = -1;
    r->fill = 0;
}

static void reply(struct remote *r, const char *line)
{
    size_t n = strlen(line);
    /* Nonblocking, bounded output. Never spin on a slow reader. */
    if (send(r->client, line, n,
#ifdef __APPLE__
             0
#else
             MSG_NOSIGNAL
#endif
             ) != (ssize_t)n)
        disconnect(r);
}

static void ack(struct remote *r, const char *id, const char *result)
{
    char line[128];
    snprintf(line, sizeof line, "DVS2 ACK %s %s\n", id, result);
    reply(r, line);
}

static void finish_pending(struct remote *r)
{
    if (!r->pending)
        return;
    struct player *pl = &r->deck->player;
    if (!r->submitted) {
        struct track *track;
        rig_lock();
        if (!r->preparing)
            r->preparing = r->unload ? track_acquire_empty()
                : track_acquire_by_import(r->deck->importer, r->pending_path);
        track = r->preparing;
        rig_unlock();
        if (!track) {
            r->result = "ERROR";
            r->pending = false;
            free(r->pending_path);
            r->pending_path = NULL;
            return;
        }
        if (r->pending_streaming) {
            int imported = __atomic_load_n(&track->import_result, __ATOMIC_ACQUIRE);
            double decoded = (double)__atomic_load_n(&track->length,
                __ATOMIC_ACQUIRE) / track->rate;
            if (imported < 0 || (imported > 0
                && fabs(decoded - r->pending_duration) > 1.0 / track->rate)) {
                rig_lock();
                track_release(track);
                rig_unlock();
                r->preparing = NULL;
                r->result = "ERROR";
                r->pending = false;
                free(r->pending_path);
                r->pending_path = NULL;
                return;
            }
            if (imported == 0 && decoded < fmin(10.0, r->pending_duration))
                return;
        }
        remote_submit(pl, track, r->deck->protect);
        r->preparing = NULL;
        r->submitted = true;
    }
    /* A dummy has no audio callback; only its stopped, no-audio state is applied
     * here. Real devices ALWAYS apply the request in their native callback. */
    if (r->dummy) {
        remote_apply(pl);
        publish(pl, false);
    }
    int result = atomic_load_explicit(&pl->remote.result, memory_order_acquire);
    if (result == REMOTE_PENDING)
        return;
    rig_lock();
    if (result == REMOTE_OK) {
        track_release(pl->remote.retired);
        r->track = pl->remote.incoming;
        free(r->path);
        r->path = r->pending_path;
        r->streaming = r->pending_streaming && !r->unload;
        r->total_duration = r->pending_duration;
        r->result = r->unload ? "OK" : "LOADED";
    } else {
        track_release(pl->remote.incoming);
        free(r->pending_path);
        r->result = "LOCKED";
    }
    rig_unlock();
    r->pending_path = NULL;
    r->pending = r->submitted = false;
    atomic_store_explicit(&pl->remote.result, REMOTE_IDLE, memory_order_release);
}

static bool fresh(struct remote *r, const struct remote_snapshot *s)
{
    if (s->callbacks != r->last_callbacks) {
        r->last_callbacks = s->callbacks;
        r->last_audio = now();
    }
    return r->dummy || now() - r->last_audio < 0.5;
}

static void status(struct remote *r)
{
    struct remote_snapshot s = remote_read(&r->deck->player);
    char line[4600];
    if (!fresh(r, &s)) {
        reply(r, "DVS2 STALE\n");
        return;
    }
    int imported = __atomic_load_n(&r->track->import_result, __ATOMIC_ACQUIRE);
    const char *state = !r->path ? "EMPTY" : imported == 0
        ? (r->streaming ? "STREAMING" : "IMPORTING")
        : imported < 0 ? "ERROR" : "READY";
    const char *result = r->result;
    if (!strcmp(result, "LOADED"))
        result = imported < 0 ? "ERROR" : imported == 0 && !r->streaming ? "PENDING" : "OK";
    double decoded = (double)__atomic_load_n(&r->track->length,
        __ATOMIC_ACQUIRE) / r->track->rate;
    if (r->streaming && imported > 0
        && fabs(decoded - r->total_duration) > 1.0 / r->track->rate) {
        state = "ERROR";
        result = "ERROR";
    }
    int n;
    if (r->streaming)
        n = snprintf(line, sizeof line,
            "DVS2 STREAM_STATE %s %s %s %d %d %d %d %.6f %.6f %.6f %.6f %s\n",
            r->id, result, state, fabs(s.pitch) > 0.01, r->deck->protect,
            s.timecode_control, s.position_known, s.elapsed, r->total_duration,
            s.pitch, decoded, r->path ? r->path : "");
    else n = snprintf(line, sizeof line,
        "DVS2 STATE %s %s %s %d %d %d %d %.6f %.6f %.6f %s\n",
        r->id, result, state, fabs(s.pitch) > 0.01, r->deck->protect,
        s.timecode_control, s.position_known, s.elapsed,
        (double)__atomic_load_n(&r->track->length, __ATOMIC_ACQUIRE) / r->track->rate,
        s.pitch, r->path ? r->path : "");
    if (n < 0 || (size_t)n >= sizeof line)
        disconnect(r);
    else
        reply(r, line);
}

static void command(struct remote *r, char *args, bool unload, bool streaming)
{
    double duration = 0.0;
    char *path = strchr(args, ' ');
    if (path)
        *path++ = '\0';
    if (strlen(args) != 32 || strspn(args, "0123456789abcdef") != 32) {
        ack(r, "-", "INVALID");
        return;
    }
    if (streaming) {
        char *end = NULL;
        duration = path ? strtod(path, &end) : 0.0;
        if (!path || end == path || *end != ' ' || !isfinite(duration)
            || duration <= 0.0 || duration > 3600.0) {
            ack(r, args, "INVALID");
            return;
        }
        path = end + 1;
    }
    struct remote_snapshot s = remote_read(&r->deck->player);
    const char *result = "ACCEPTED";
    if ((unload && path) || (!unload && (!path || path[0] != '/' || strchr(path, '\r'))))
        result = "INVALID";
    else if (!r->deck->protect)
        result = "UNPROTECTED";
    else if (r->pending
        || (r->path && !r->streaming
            && __atomic_load_n(&r->track->import_result, __ATOMIC_ACQUIRE) == 0)
        || !fresh(r, &s))
        result = "BUSY";
    else if (fabs(s.pitch) > 0.01)
        result = "LOCKED";
    else {
        char *copy = unload ? NULL : strdup(path);
        if (!unload && !copy)
            result = "ERROR";
        else {
            strcpy(r->id, args);
            r->result = "PENDING";
            r->pending_path = copy;
            r->pending = true;
            r->unload = unload;
            r->pending_streaming = streaming;
            r->pending_duration = duration;
        }
    }
    ack(r, args, result);
}

static void handle(struct remote *r, char *line)
{
    if (!strcmp(line, "DVS2 STATUS"))
        status(r);
    else if (!strcmp(line, "DVS2 METRICS")) {
        struct remote_snapshot s = remote_read(&r->deck->player);
        char output[200];
        snprintf(output, sizeof output, "DVS2 METRICS %llu %u %u\n",
            (unsigned long long)s.callbacks,
            atomic_load_explicit(&r->deck->device.capture_xruns, memory_order_relaxed),
            atomic_load_explicit(&r->deck->device.playback_xruns, memory_order_relaxed));
        reply(r, output);
    } else if (!strncmp(line, "DVS2 LOAD ", 10))
        command(r, line + 10, false, false);
    else if (!strncmp(line, "DVS2 UNLOAD ", 12))
        command(r, line + 12, true, false);
    else if (!strncmp(line, "DVS2 STREAM ", 12))
        command(r, line + 12, false, true);
    else
        reply(r, "DVS2 UNSUPPORTED\n");
}

/* Darwin lacks atomic socket flags and accept4. CLOEXEC_DEFAULT on importer
 * posix_spawn closes the fcntl race; SO_NOSIGPIPE is socket-local. */
static int control_socket(int listener)
{
#ifdef __APPLE__
    int fd = listener < 0 ? socket(AF_UNIX, SOCK_STREAM, 0) : accept(listener, NULL, NULL);
    if (fd < 0) return -1;
    int one = 1;
    if (fcntl(fd, F_SETFD, FD_CLOEXEC) == -1 ||
        fcntl(fd, F_SETFL, O_NONBLOCK) == -1 ||
        setsockopt(fd, SOL_SOCKET, SO_NOSIGPIPE, &one, sizeof one) == -1) {
        int saved = errno;
        close(fd);
        errno = saved;
        return -1;
    }
    return fd;
#else
    return listener < 0 ? socket(AF_UNIX, SOCK_STREAM | SOCK_NONBLOCK | SOCK_CLOEXEC, 0)
        : accept4(listener, NULL, NULL, SOCK_NONBLOCK | SOCK_CLOEXEC);
#endif
}

static void *serve(void *argument)
{
    struct remote *r = argument;
    while (!atomic_load_explicit(&r->stop, memory_order_relaxed)) {
        finish_pending(r);
        struct pollfd fds[2] = {
            { .fd = r->listener, .events = POLLIN },
            { .fd = r->client, .events = POLLIN },
        };
        if (poll(fds, 2, 10) < 0 && errno != EINTR)
            break;
        if (fds[0].revents & POLLIN) {
            int client = control_socket(r->listener);
            if (client >= 0) {
                disconnect(r);
                r->client = client;
            }
        }
        if (r->client == -1)
            continue;
        /* One bounded read per turn; flooding cannot starve mailbox completion. */
        ssize_t n = recv(r->client, r->input + r->fill, sizeof r->input - 1 - r->fill, 0);
        if (n < 0 && (errno == EAGAIN || errno == EINTR))
            continue;
        if (n <= 0 || memchr(r->input + r->fill, '\0', (size_t)n)) {
            disconnect(r);
            continue;
        }
        r->fill += n;
        r->input[r->fill] = '\0';
        char *newline;
        while ((newline = memchr(r->input, '\n', r->fill))) {
            *newline = '\0';
            handle(r, r->input);
            if (r->client == -1)
                break;
            size_t used = newline - r->input + 1;
            memmove(r->input, newline + 1, r->fill - used);
            r->fill -= used;
        }
        if (r->fill == sizeof r->input - 1)
            disconnect(r);
    }
    return NULL;
}

struct remote *remote_start(struct deck *deck, const char *path, bool dummy)
{
    struct sockaddr_un address = { .sun_family = AF_UNIX };
    if (strlen(path) >= sizeof address.sun_path) {
        errno = ENAMETOOLONG;
        return NULL;
    }
    struct remote *r = calloc(1, sizeof *r);
    if (!r)
        return NULL;
    r->deck = deck;
    r->track = deck->player.track;
    r->dummy = dummy;
    r->client = -1;
    r->result = "NONE";
    strcpy(r->id, "-");
    strcpy(r->socket_path, path);
    strcpy(address.sun_path, path);
    atomic_init(&r->stop, false);
    r->last_audio = now();
    r->listener = control_socket(-1);
    if (r->listener == -1)
        goto failed;
    /* Never remove an existing/live socket. The owner removes stale sockets. */
    if (bind(r->listener, (struct sockaddr*)&address, sizeof address) == -1)
        goto failed_socket;
    if (chmod(path, S_IRUSR | S_IWUSR) == -1 || listen(r->listener, 4) == -1)
        goto failed_bound;
    /* Do not inherit realtime scheduling even if the launcher used chrt. */
    pthread_attr_t attr;
    int error = pthread_attr_init(&attr);
    if (error == 0) {
        struct sched_param scheduling = { .sched_priority = 0 };
        error = pthread_attr_setinheritsched(&attr, PTHREAD_EXPLICIT_SCHED);
        if (!error)
            error = pthread_attr_setschedpolicy(&attr, SCHED_OTHER);
        if (!error)
            error = pthread_attr_setschedparam(&attr, &scheduling);
        if (!error)
            error = pthread_create(&r->thread, &attr, serve, r);
        pthread_attr_destroy(&attr);
    }
    if (error) {
        errno = error;
        goto failed_bound;
    }
    return r;
failed_bound:
    unlink(path);
failed_socket:
    close(r->listener);
failed:
    free(r);
    return NULL;
}

void remote_stop(struct remote *r)
{
    if (!r)
        return;
    atomic_store_explicit(&r->stop, true, memory_order_relaxed);
    pthread_join(r->thread, NULL);
    /* Audio has stopped, so a pending handoff can now be retired safely. */
    struct remote_player *mail = &r->deck->player.remote;
    if (r->submitted) {
        rig_lock();
        int result = atomic_load_explicit(&mail->result, memory_order_acquire);
        track_release(result == REMOTE_OK ? mail->retired : mail->incoming);
        rig_unlock();
    }
    if (r->preparing) {
        rig_lock();
        track_release(r->preparing);
        rig_unlock();
    }
    disconnect(r);
    close(r->listener);
    unlink(r->socket_path);
    free(r->path);
    free(r->pending_path);
    free(r);
}
