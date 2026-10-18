/* Copyright (C) 2026 Tim Herzig. SPDX-License-Identifier: GPL-3.0-only */
#ifndef PI_DVS_REMOTE_H
#define PI_DVS_REMOTE_H
#include <stdatomic.h>
#include <stdbool.h>
#include <stdint.h>

struct player;
struct deck;
struct track;
struct remote;

/* One audio writer, one control reader. These buffers contain telemetry, NOT PCM. */
struct remote_snapshot {
    double elapsed, pitch;
    bool timecode_control, position_known;
    uint64_t callbacks;
};

enum remote_result { REMOTE_IDLE, REMOTE_PENDING, REMOTE_OK, REMOTE_LOCKED };
struct remote_player {
    bool enabled;
    struct remote_snapshot snapshot[3];
    unsigned writer, reader;
    atomic_uint middle;
    uint64_t callbacks;
    atomic_int result;
    struct track *incoming, *retired;
    bool protect;
};

void remote_player_init(struct player *pl);
/* Audio thread: bounded work, no locks, allocation, free, sockets or waiting. */
void remote_apply(struct player *pl);
void remote_publish(struct player *pl, bool position_known);
/* Control thread only. Audio must be stopped before remote_stop. */
struct remote_snapshot remote_read(struct player *pl);
void remote_submit(struct player *pl, struct track *track, bool protect);
struct remote *remote_start(struct deck *deck, const char *path, bool dummy);
void remote_stop(struct remote *remote);
#endif
