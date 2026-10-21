/* Copyright (C) 2026 Tim Herzig. SPDX-License-Identifier: GPL-3.0-only
 * Actual backend with a fake host API; never opens an audio device. */
#include <assert.h>
#include <unistd.h>
#include <signal.h>
#include <sys/wait.h>
#include <fcntl.h>
#define COREAUDIO_SHUTDOWN_SECONDS 0.15
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include "device.h"
#include <portaudio.h>
#include <pa_mac_core.h>
static unsigned opens, starts, stops, closes, submits[2], collects[2];
static int fail_open, fail_start, fail_stop, hang_host;
static pthread_t background;
static atomic_bool hold_callback, entered_callback, release_callback;
static atomic_bool callback_running;
static PaStreamCallback *callback;
static const unsigned pair[2] = {0, 6};
static struct device devices[2];
static unsigned expected_offset[2];
static bool null_input;

static short value(unsigned frame, unsigned channel)
{ return (short)(1000 * (channel + 1) + frame % 999); }
void device_init(struct device *dv, struct device_ops *ops)
{
    dv->ops = ops;
    atomic_init(&dv->capture_xruns, 0);
    atomic_init(&dv->playback_xruns, 0);
}
void device_submit(struct device *dv, short *pcm, size_t n)
{
    assert(callback_running);
    if (atomic_load(&hold_callback)) {
        atomic_store(&entered_callback, true);
        while (!atomic_load(&release_callback)) sched_yield();
    }
    unsigned d = dv == &devices[0] ? 0 : 1;
    for (unsigned i = 0; i < n; i++)
        for (unsigned c = 0; c < 2; c++)
            assert(pcm[2*i+c] == (null_input ? 0 : value(expected_offset[d]+i, pair[d]+c)));
    expected_offset[d] += n;
    submits[d] += n;
}
void device_collect(struct device *dv, short *pcm, size_t n)
{
    assert(callback_running);
    unsigned d = dv == &devices[0] ? 0 : 1;
    /* An empty/stopped deck outputs silence, independent from the other deck. */
    for (unsigned i = 0; i < n * 2; i++) pcm[i] = d ? 0 : -pcm[i];
    collects[d] += n;
}
static void route_check(unsigned frames, bool missing);

PaError Pa_Initialize(void) { assert(!callback_running); return 0; }
PaError Pa_Terminate(void) { assert(!callback_running); if (hang_host==3) for (;;) pause(); return 0; }
PaDeviceIndex Pa_GetDeviceCount(void) { return 1; }
const PaDeviceInfo *Pa_GetDeviceInfo(PaDeviceIndex i)
{
    static PaDeviceInfo info = { .name="Test PX5", .hostApi=0,
        .maxInputChannels=10, .maxOutputChannels=10, .defaultSampleRate=44100 };
    assert(i == 0); return &info;
}
const PaHostApiInfo *Pa_GetHostApiInfo(PaHostApiIndex i)
{ static PaHostApiInfo info = { .type=paCoreAudio }; assert(i == 0); return &info; }
const char *Pa_GetErrorText(PaError e) { (void)e; return "injected failure"; }
void PaMacCore_SetupStreamInfo(PaMacCoreStreamInfo *p, unsigned long flags)
{ memset(p, 0, sizeof *p); p->flags=flags; }
PaError Pa_IsFormatSupported(const PaStreamParameters *i, const PaStreamParameters *o, double hz)
{ assert(i->device == 0 && o->device == 0 && hz == 44100); return 0; }
PaError Pa_OpenStream(PaStream **stream, const PaStreamParameters *i,
    const PaStreamParameters *o, double hz, unsigned long frames, PaStreamFlags flags,
    PaStreamCallback *fn, void *data)
{
    assert(!callback_running && i->channelCount == 10 && o->channelCount == 10);
    assert(hz == 44100 && frames == 512 && flags == paDitherOff && !data);
    opens++; callback=fn;
    if (fail_open) return paDeviceUnavailable;
    *stream=(PaStream *)(uintptr_t)1; return 0;
}
const PaStreamInfo *Pa_GetStreamInfo(PaStream *stream)
{ static PaStreamInfo info={.sampleRate=44100}; assert(stream); return &info; }
PaError Pa_StartStream(PaStream *stream)
{
    assert(stream && !callback_running); starts++;
    if (fail_start) return paDeviceUnavailable;
    route_check(513, false); /* Callback may run before start returns. */
    return 0;
}
PaError Pa_StopStream(PaStream *stream) { assert(stream); stops++; if (hang_host==1) for (;;) pause(); return fail_stop ? paInternalError : 0; }
PaError Pa_CloseStream(PaStream *stream) {
    assert(stream);
    if (hang_host==2) for (;;) pause();
    if (atomic_load(&hold_callback)) {
        atomic_store(&release_callback, true);
        assert(pthread_join(background, NULL)==0);
    }
    assert(!callback_running); closes++; return 0;
}
#include "portaudio-device.c"

static void route_check(unsigned frames, bool missing)
{
    size_t n = (size_t)frames * 10;
    short *input = malloc((n+2) * sizeof(short));
    short *output = malloc((n+2) * sizeof(short));
    assert(input && output);
    for (unsigned f=0; f<frames; f++)
        for (unsigned c=0; c<10; c++) input[1+10*f+c]=value(f,c);
    for (size_t i=0; i<n+2; i++) output[i]=12345;
    expected_offset[0]=expected_offset[1]=0; null_input=missing;
    callback_running=true;
    assert(callback(missing ? NULL : input+1, output+1, frames, NULL, 0, NULL) == paContinue);
    callback_running=false;
    assert(output[0] == 12345 && output[n+1] == 12345);
    for (unsigned f=0; f<frames; f++)
        for (unsigned c=0; c<10; c++)
            assert(output[1+10*f+c] == (c<2 && !missing ? -value(f,c) : 0));
    free(input); free(output);
}
static void *in_flight(void *unused) { (void)unused; route_check(32, false); return NULL; }
static void blocked_shutdown_check(int mode)
{
    pid_t child = fork();
    assert(child >= 0);
    if (child == 0) {
        fail_open=fail_start=fail_stop=0;
        atomic_store(&hold_callback, false);
        assert(coreaudio_init(&devices[0], "Test PX5", "0", "0", 44100, 512)==0);
        assert(coreaudio_start()==0);
        hang_host=mode;
        if (mode==4) {
            /* Error logging to a full pipe must not defeat process containment. */
            int pipes[2]; assert(pipe(pipes)==0);
            assert(fcntl(pipes[1], F_SETFL, O_NONBLOCK)==0);
            char bytes[1024]={0};
            while (write(pipes[1],bytes,sizeof bytes)>0) {}
            assert(errno==EAGAIN);
            assert(fcntl(pipes[1],F_SETFL,0)==0);
            assert(dup2(pipes[1],STDERR_FILENO)>=0);
            fail_stop=1;
        }
        stop(&devices[0]);
        clear(&devices[0]);
        _Exit(0); /* Must never reach cleanup completion after a blocked host. */
    }
    double deadline=monotonic_seconds()+3;
    int status=0;
    for (;;) {
        pid_t result=waitpid(child,&status,WNOHANG);
        assert(result>=0);
        if (result==child) break;
        if (monotonic_seconds()>deadline) {
            kill(child,SIGKILL); waitpid(child,&status,0);
            assert(!"Shutdown containment failed");
        }
        usleep(1000);
    }
    assert(WIFEXITED(status) && WEXITSTATUS(status)==75);
}

int main(void)
{
    assert(coreaudio_init(&devices[0], "missing", "0", "0", 44100, 512) == -1);
    assert(coreaudio_init(&devices[0], "Test PX5", "9", "0", 44100, 512) == -1);
    assert(coreaudio_init(&devices[0], "Test PX5", "-1", "0", 44100, 512) == -1);
    assert(coreaudio_init(&devices[0], "Test PX5", "0", "0", 44100, 512) == 0);
    assert(coreaudio_init(&devices[1], "Test PX5", "1", "6", 44100, 512) == -1);
    assert(coreaudio_init(&devices[1], "Test PX5", "6", "1", 44100, 512) == -1);
    assert(coreaudio_init(&devices[1], "Test PX5", "6", "6", 48000, 512) == -1);
    assert(coreaudio_init(&devices[1], "Test PX5", "6", "6", 44100, 512) == 0);
    fail_open=1; assert(coreaudio_start() == -1); assert(!stream);
    fail_open=0; fail_start=1; assert(coreaudio_start() == -1);
    stop(&devices[0]); assert(!stream && closes == 1);
    fail_start=0; assert(coreaudio_start() == 0);
    const unsigned sizes[]={0,1,255,256,511,512,513,4097};
    for (unsigned i=0; i<sizeof sizes/sizeof sizes[0]; i++) {
        route_check(sizes[i], false); route_check(sizes[i], true);
    }
    short out[10]; callback_running=true;
    assert(callback(NULL, out, 1, NULL, paInputOverflow|paOutputUnderflow, NULL) == paContinue);
    callback_running=false;
    assert(atomic_load(&devices[0].capture_xruns)==1 && atomic_load(&devices[1].playback_xruns)==1);
    assert(submits[0]==collects[0] && submits[1]==collects[1] && submits[0]==submits[1]);
    atomic_store(&hold_callback, true);
    assert(pthread_create(&background, NULL, in_flight, NULL)==0);
    while (!atomic_load(&entered_callback)) sched_yield();
    fail_stop=1;
    stop(&devices[0]); stop(&devices[1]);
    assert(opens==3 && starts==2 && stops==2 && closes==2);
    clear(&devices[0]); clear(&devices[1]);
    assert(!initialized && count==0 && live==0);
    for (int mode=1;mode<=4;mode++) blocked_shutdown_check(mode);
    puts("Core Audio routing/lifecycle and bounded blocked Stop/Close/Terminate/stderr passed (fake host)");
}
