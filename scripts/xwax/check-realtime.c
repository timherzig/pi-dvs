/* Copyright (C) 2026 Tim Herzig. SPDX-License-Identifier: GPL-3.0-only
 * Native regression probe, not a soundcard or end-to-end latency measurement.
 */
#include <assert.h>
#include <errno.h>
#include <math.h>
#include <pthread.h>
#include <stdarg.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <time.h>
#include <unistd.h>
#include "deck.h"
#include "dummy.h"
#include "remote.h"
#include "rig.h"
#include "thread.h"

static _Thread_local bool in_audio;
static unsigned contended;
#define GUARD() assert(!in_audio)
#define WRAP(ret, name, params, args) \
    ret __real_##name params; \
    ret __wrap_##name params { GUARD(); return __real_##name args; }
WRAP(void *, malloc, (size_t n), (n))
WRAP(void *, calloc, (size_t n, size_t s), (n, s))
WRAP(void *, realloc, (void *p, size_t n), (p, n))
WRAP(int, pthread_mutex_lock, (pthread_mutex_t *p), (p))
WRAP(int, pthread_spin_lock, (pthread_spinlock_t *p), (p))
WRAP(int, poll, (struct pollfd *p, nfds_t n, int t), (p, n, t))
WRAP(ssize_t, send, (int f, const void *p, size_t n, int flags), (f, p, n, flags))
WRAP(ssize_t, recv, (int f, void *p, size_t n, int flags), (f, p, n, flags))
WRAP(ssize_t, read, (int f, void *p, size_t n), (f, p, n))
WRAP(ssize_t, write, (int f, const void *p, size_t n), (f, p, n))
WRAP(int, fputs, (const char *p, FILE *f), (p, f))
WRAP(int, puts, (const char *p), (p))
WRAP(int, fflush, (FILE *f), (f))
WRAP(size_t, fwrite, (const void *p, size_t n, size_t count, FILE *f), (p, n, count, f))
WRAP(char *, strdup, (const char *p), (p))
void __real_free(void *p);
void __wrap_free(void *p) { GUARD(); __real_free(p); }
int __wrap_fprintf(FILE *f, const char *format, ...)
{
    GUARD();
    va_list ap;
    va_start(ap, format);
    int r = vfprintf(f, format, ap);
    va_end(ap);
    return r;
}
int __wrap_printf(const char *format, ...)
{
    GUARD();
    va_list ap;
    va_start(ap, format);
    int r = vprintf(format, ap);
    va_end(ap);
    return r;
}
int __real_pthread_spin_trylock(pthread_spinlock_t *p);
int __wrap_pthread_spin_trylock(pthread_spinlock_t *p)
{
    int r = __real_pthread_spin_trylock(p);
    if (in_audio && r == EBUSY)
        contended++;
    return r;
}

static double now(void)
{
    struct timespec t;
    assert(clock_gettime(CLOCK_MONOTONIC, &t) == 0);
    return t.tv_sec + t.tv_nsec / 1e9;
}

static void *rig_thread(void *unused) { assert(rig_main() == 0); return NULL; }

static void collect(struct deck *d)
{
    short output[480];
    in_audio = true;
    player_collect(&d->player, output, 240);
    in_audio = false;
}

static void mailbox_tests(struct deck *d)
{
    struct player *p = &d->player;
    struct track *original = p->track;
    /* The old published speed says stopped. This callback's native timecoder
     * speed must decide; neither stale telemetry nor an accepted ACK suffices. */
    for (int direction = -1; direction <= 1; direction += 2) {
        p->pitch = 0;
        d->timecoder.pitch.v = direction;
        remote_submit(p, track_acquire_empty(), true);
        collect(d);
        assert(atomic_load(&p->remote.result) == REMOTE_LOCKED);
        assert(p->track == original);
        track_release(p->remote.incoming);
        atomic_store(&p->remote.result, REMOTE_IDLE);
    }
    d->timecoder.pitch.v = 0;
    remote_submit(p, track_acquire_empty(), true);
    collect(d);
    assert(atomic_load(&p->remote.result) == REMOTE_OK);
    assert(p->track != original && p->remote.retired == original);
    /* Old PCM survives until the ordinary control thread retires it. */
    assert(original->refcount > 0 && original->length > 0);
    track_release(p->remote.retired);
    atomic_store(&p->remote.result, REMOTE_IDLE);
    track_acquire(original); /* The caller retains its own original reference. */
    remote_submit(p, original, true);
    collect(d);
    assert(atomic_load(&p->remote.result) == REMOTE_OK);
    track_release(p->remote.retired);
    atomic_store(&p->remote.result, REMOTE_IDLE);
    assert(p->timecode_control);
    player_set_internal_playback(p);
    collect(d);
    struct remote_snapshot s = remote_read(p);
    assert(!s.timecode_control && s.pitch == 1.0 && !s.position_known);
    /* An absolute jump must also stay free of callback log I/O. */
    p->target_position = 10;
    p->recalibrate = false;
    collect(d);
    assert(p->position >= 10);
    player_set_timecode_control(p, true);
}

struct client { const char *path; bool stalled; atomic_bool stop; unsigned replies; };
static void *flood(void *arg)
{
    struct client *c = arg;
    int fd = socket(AF_UNIX, SOCK_STREAM, 0);
    assert(fd >= 0);
    struct sockaddr_un address = { .sun_family = AF_UNIX };
    strcpy(address.sun_path, c->path);
    assert(connect(fd, (struct sockaddr *)&address, sizeof address) == 0);
    struct timeval timeout = { .tv_sec = 1 };
    setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &timeout, sizeof timeout);
    const char query[] = "DVS2 STATUS\n";
    while (!atomic_load(&c->stop)) {
        ssize_t n = send(fd, query, sizeof query - 1, MSG_NOSIGNAL | MSG_DONTWAIT);
        if (n != sizeof query - 1) {
            /* A non-reading peer fills the socket buffers. Darwin may report
             * ENOBUFS instead of EAGAIN; a short write is also backpressure. */
            if (c->stalled && (n >= 0 || errno == EAGAIN || errno == EWOULDBLOCK ||
                              errno == ENOBUFS || errno == EPIPE || errno == ECONNRESET))
                break;
            if (n < 0 && errno == EINTR)
                continue;
            fprintf(stderr, "status flood send failed: bytes=%zd errno=%d\n", n, errno);
            assert(false);
        }
        if (!c->stalled) {
            char line[4600];
            n = recv(fd, line, sizeof line, 0);
            assert(n > 0);
            c->replies++;
        }
    }
    while (c->stalled && !atomic_load(&c->stop))
        usleep(1000);
    close(fd);
    return NULL;
}

#define ITERATIONS 30000
static double times[ITERATIONS];
static short input[480];
static int compare(const void *a, const void *b)
{
    double x = *(const double *)a, y = *(const double *)b;
    return (x > y) - (x < y);
}

static void probe(struct deck *d, const char *label, struct client *client)
{
    pthread_t worker;
    if (client)
        assert(pthread_create(&worker, NULL, flood, client) == 0);
    short output[480];
    unsigned audible = 0;
    for (unsigned i = 0; i < ITERATIONS; i++) {
        d->player.position = 0.25; /* Keep the one-second fixture within range. */
        double start = now();
        in_audio = true;
        device_submit(&d->device, input, 240);
        device_collect(&d->device, output, 240);
        in_audio = false;
        times[i] = (now() - start) * 1e6;
        for (unsigned j = 0; j < 480; j++)
            audible += output[j] != 0;
    }
    if (client) {
        atomic_store(&client->stop, true);
        assert(pthread_join(worker, NULL) == 0);
        if (!client->stalled)
            assert(client->replies > 100);
    }
    assert(audible > ITERATIONS * 200);
    assert(contended == 0); /* Polling must never force trylock-generated silence. */
    qsort(times, ITERATIONS, sizeof *times, compare);
    printf("%s: 240 frames/48kHz, callback wall time us p50=%.2f p99=%.2f max=%.2f; replies=%u\n",
        label, times[ITERATIONS / 2], times[ITERATIONS * 99 / 100],
        times[ITERATIONS - 1], client ? client->replies : 0);
}

int main(int argc, char **argv)
{
    assert(argc == 3);
    assert(thread_global_init() == 0 && rig_init() == 0);
    pthread_t rig;
    assert(pthread_create(&rig, NULL, rig_thread, NULL) == 0);
    rig_lock();
    struct track *track = track_acquire_by_import(argv[1], argv[2]);
    rig_unlock();
    assert(track);
    double deadline = now() + 10;
    while (__atomic_load_n(&track->import_result, __ATOMIC_ACQUIRE) == 0 && now() < deadline)
        usleep(1000);
    assert(__atomic_load_n(&track->import_result, __ATOMIC_ACQUIRE) == 1);
    struct deck d = { .protect = true, .importer = argv[1] };
    dummy_init(&d.device);
    struct timecode_def *def = timecoder_find_definition("serato_2a");
    assert(def);
    timecoder_init(&d.timecoder, def, 1.0, 48000, false);
    rig_lock();
    track_acquire(track);
    rig_unlock();
    player_init(&d.player, 48000, track, &d.timecoder);
    device_connect_timecoder(&d.device, &d.timecoder);
    device_connect_player(&d.device, &d.player);
    d.player.remote.enabled = true;
    rig_lock();
    mailbox_tests(&d);
    rig_unlock();
    for (unsigned i = 0; i < 240; i++) {
        input[2*i] = 16000 * sin(2 * M_PI * i / 48);
        input[2*i+1] = 16000 * cos(2 * M_PI * i / 48);
    }
    d.player.remote.enabled = false;
    probe(&d, "control disabled", NULL);
    d.player.remote.enabled = true;
    char directory[] = "/tmp/dvs-native-XXXXXX", path[108];
    assert(mkdtemp(directory));
    snprintf(path, sizeof path, "%s/deck", directory);
    struct remote *remote = remote_start(&d, path, false);
    assert(remote);
    probe(&d, "control idle", NULL);
    struct client normal = { .path = path, .stop = false };
    probe(&d, "socket flood", &normal);
    struct client stalled = { .path = path, .stalled = true, .stop = false };
    probe(&d, "client not reading", &stalled);
    remote_stop(remote); /* No callback can run after this point. */
    rmdir(directory);
    rig_lock();
    player_clear(&d.player);
    rig_unlock();
    timecoder_clear(&d.timecoder);
    timecoder_free_lookup();
    rig_lock();
    track_release(track);
    rig_unlock();
    assert(rig_quit() == 0 && pthread_join(rig, NULL) == 0);
    rig_clear();
    thread_global_clear();
    puts("Native handoff/protection and callback guards passed. No hardware latency claim.");
    return 0;
}
