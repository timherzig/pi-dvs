/* Copyright (C) 2026 Tim Herzig. SPDX-License-Identifier: GPL-3.0-only */
#ifndef PI_DVS_PORTAUDIO_DEVICE_H
#define PI_DVS_PORTAUDIO_DEVICE_H
struct device;
int coreaudio_init(struct device *, const char *, const char *, const char *, unsigned, unsigned);
int coreaudio_start(void);
#endif
