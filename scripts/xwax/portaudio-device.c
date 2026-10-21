/* Copyright (C) 2026 Tim Herzig. SPDX-License-Identifier: GPL-3.0-only
 * Optional macOS I/O adapter. The Pi continues to use native ALSA.
 */
#include <assert.h>
#include <errno.h>
#include <limits.h>
#include <pthread.h>
#include <time.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <portaudio.h>
#include <pa_mac_core.h>
#include "device.h"
#include "thread.h"
#include "portaudio-device.h"

#define MAX_DECKS 4
#define BLOCK 256
#define MAX_CHANNELS 64
struct route { struct device *device; unsigned input, output; };
static struct route routes[MAX_DECKS];
static unsigned count, rate, buffer_frames, live;
static int input_channels, output_channels;
static PaDeviceIndex selected = paNoDevice;
static PaStream *stream;
static bool initialized;

/* Host shutdown can deadlock inside Core Audio. Never cancel that thread or
 * free callback-owned state on a timeout: fail the entire native process.
 * 75 distinguishes a contained shutdown failure from a clean exit. */
#ifndef COREAUDIO_SHUTDOWN_SECONDS
#define COREAUDIO_SHUTDOWN_SECONDS 5.0
#endif
_Static_assert(ATOMIC_BOOL_LOCK_FREE == 2, "Shutdown watchdog needs lock-free state");
struct shutdown_guard { atomic_bool done; pthread_t thread; double deadline; };
static double monotonic_seconds(void)
{
    struct timespec now;
    if (clock_gettime(CLOCK_MONOTONIC, &now)) _Exit(75);
    return now.tv_sec + now.tv_nsec / 1e9;
}
static void *shutdown_watch(void *argument)
{
    struct shutdown_guard *guard = argument;
    while (!atomic_load_explicit(&guard->done, memory_order_acquire)) {
        if (monotonic_seconds() >= guard->deadline) {
            /* No stdio/write/flush: even stderr can be blocked. */
            _Exit(75);
        }
        struct timespec pause = { .tv_sec=0, .tv_nsec=10000000 };
        nanosleep(&pause, NULL);
    }
    return NULL;
}
static void shutdown_begin(struct shutdown_guard *guard)
{
    atomic_init(&guard->done, false);
    guard->deadline = monotonic_seconds() + COREAUDIO_SHUTDOWN_SECONDS;
    if (pthread_create(&guard->thread, NULL, shutdown_watch, guard)) _Exit(75);
}
static void shutdown_end(struct shutdown_guard *guard)
{
    atomic_store_explicit(&guard->done, true, memory_order_release);
    if (pthread_join(guard->thread, NULL)) _Exit(75);
}

static int error(PaError result, const char *operation)
{
    if (result == paNoError) return 0;
    fprintf(stderr, "Core Audio %s: %s\n", operation, Pa_GetErrorText(result));
    return -1;
}

/* No allocation, locks, logging or host API calls. All routes are immutable
 * between Pa_StartStream and the completed Pa_StopStream/Pa_CloseStream. */
static int process(const void *input, void *output, unsigned long frames,
                   const PaStreamCallbackTimeInfo *timing,
                   PaStreamCallbackFlags flags, void *unused)
{
    const short *in = input;
    short *out = output;
    (void)timing; (void)unused;
    if (!out) return paAbort;
    memset(out, 0, frames * (size_t)output_channels * sizeof *out);
    for (unsigned d = 0; d < count; d++) {
        struct route *route = &routes[d];
        if (flags & (paInputOverflow | paInputUnderflow))
            atomic_fetch_add_explicit(&route->device->capture_xruns, 1, memory_order_relaxed);
        if (flags & (paOutputUnderflow | paOutputOverflow))
            atomic_fetch_add_explicit(&route->device->playback_xruns, 1, memory_order_relaxed);
        for (unsigned long offset = 0; offset < frames; offset += BLOCK) {
            short pcm[BLOCK * 2];
            unsigned n = frames - offset < BLOCK ? (unsigned)(frames - offset) : BLOCK;
            for (unsigned f = 0; f < n; f++) {
                size_t at = (offset + f) * (size_t)input_channels + route->input;
                pcm[2*f] = in ? in[at] : 0;
                pcm[2*f+1] = in ? in[at+1] : 0;
            }
            device_submit(route->device, pcm, n);
            device_collect(route->device, pcm, n);
            for (unsigned f = 0; f < n; f++) {
                size_t at = (offset + f) * (size_t)output_channels + route->output;
                out[at] = pcm[2*f];
                out[at+1] = pcm[2*f+1];
            }
        }
    }
    return paContinue;
}

static unsigned sample_rate(struct device *device) { (void)device; return rate; }
static void stop(struct device *device)
{
    (void)device;
    if (stream) {
        /* Close also joins a failed/stopped stream's host callbacks. Never
         * release deck memory while any callback can still access it. */
        struct shutdown_guard guard;
        shutdown_begin(&guard);
        PaError result = Pa_StopStream(stream);
        if (result != paStreamIsStopped) error(result, "stop");
        if (error(Pa_CloseStream(stream), "close") != 0) abort();
        stream = NULL;
        shutdown_end(&guard);
    }
}
static void clear(struct device *device)
{
    assert(!stream);
    (void)device;
    assert(live);
    if (--live == 0) {
        struct shutdown_guard guard;
        shutdown_begin(&guard);
        error(Pa_Terminate(), "terminate");
        shutdown_end(&guard);
        initialized = false;
        selected = paNoDevice;
        count = 0;
    }
}
static struct device_ops ops = { .sample_rate = sample_rate, .stop = stop, .clear = clear };

static int channel(const char *text, unsigned *result)
{
    char *end;
    if (!text[0] || text[0] < '0' || text[0] > '9') return -1;
    errno = 0;
    unsigned long value = strtoul(text, &end, 10);
    if (errno || *end || value > MAX_CHANNELS - 2) return -1;
    *result = (unsigned)value;
    return 0;
}

int coreaudio_init(struct device *device, const char *name, const char *input,
                   const char *output, unsigned requested_rate, unsigned frames)
{
    unsigned in, out;
    if (count == MAX_DECKS || channel(input, &in) || channel(output, &out) ||
        frames < 32 || frames > 4096) {
        fprintf(stderr, "Core Audio requires zero-based stereo channel offsets and a 32..4096 frame buffer\n");
        return -1;
    }
    if (!initialized) {
        if (error(Pa_Initialize(), "initialize")) return -1;
        initialized = true;
    }
    PaDeviceIndex match = paNoDevice;
    int devices = Pa_GetDeviceCount();
    if (devices < 0) return error(devices, "enumerate");
    for (int i = 0; i < devices; i++) {
        const PaDeviceInfo *info = Pa_GetDeviceInfo(i);
        const PaHostApiInfo *api = Pa_GetHostApiInfo(info->hostApi);
        if (api->type == paCoreAudio && !strcmp(name, info->name)) {
            if (match != paNoDevice) {
                fprintf(stderr, "Core Audio device name is ambiguous: %s\n", name);
                return -1;
            }
            match = i;
        }
    }
    if (match == paNoDevice) {
        fprintf(stderr, "Core Audio device not found: %s (no default-device fallback)\n", name);
        return -1;
    }
    const PaDeviceInfo *info = Pa_GetDeviceInfo(match);
    unsigned hz = requested_rate ? requested_rate : (unsigned)info->defaultSampleRate;
    if (info->maxInputChannels > MAX_CHANNELS || info->maxOutputChannels > MAX_CHANNELS ||
        in + 2 > (unsigned)info->maxInputChannels || out + 2 > (unsigned)info->maxOutputChannels ||
        hz < 8000 || hz > 192000) {
        fprintf(stderr, "Core Audio channel map or sample rate is outside device limits\n");
        return -1;
    }
    if (count && (selected != match || rate != hz || buffer_frames != frames)) {
        fprintf(stderr, "Core Audio decks must share one device, rate and buffer size\n");
        return -1;
    }
    for (unsigned i = 0; i < count; i++) {
        if ((in < routes[i].input + 2 && routes[i].input < in + 2) ||
            (out < routes[i].output + 2 && routes[i].output < out + 2)) {
            fprintf(stderr, "Core Audio stereo channel maps must not overlap\n");
            return -1;
        }
    }
    selected = match; rate = hz; buffer_frames = frames;
    input_channels = info->maxInputChannels; output_channels = info->maxOutputChannels;
    device_init(device, &ops);
    routes[count++] = (struct route){ device, in, out };
    live++;
    return 0;
}

int coreaudio_start(void)
{
    if (!count) return 0;
    PaMacCoreStreamInfo mac;
    PaMacCore_SetupStreamInfo(&mac, paMacCoreChangeDeviceParameters | paMacCoreFailIfConversionRequired);
    PaStreamParameters input = { selected, input_channels, paInt16, 0, &mac };
    PaStreamParameters output = { selected, output_channels, paInt16, 0, &mac };
    input.suggestedLatency = output.suggestedLatency = (double)buffer_frames / rate;
    if (error(Pa_IsFormatSupported(&input, &output, rate), "format")) return -1;
    if (error(Pa_OpenStream(&stream, &input, &output, rate, buffer_frames,
                            paDitherOff, process, NULL), "open")) {
        stream = NULL;
        return -1;
    }
    const PaStreamInfo *info = Pa_GetStreamInfo(stream);
    fprintf(stderr, "Core Audio: %u Hz, %u frames, reported input/output latency %.3f/%.3f ms\n",
            rate, buffer_frames, info->inputLatency * 1000, info->outputLatency * 1000);
    return error(Pa_StartStream(stream), "start");
}
