/* Copyright (C) 2026 Tim Herzig. SPDX-License-Identifier: GPL-3.0-only
 * Drive the ACTUAL Core Audio callback through the guarded native engine,
 * without initializing PortAudio or opening hardware. */
#define main decoder_probe_main
#include "check-realtime.c"
#undef main
#include "probe-guard.h"
#include "portaudio-device.c"

int main(int argc, char **argv)
{
    assert(argc == 3);
    assert(thread_global_init() == 0 && rig_init() == 0);
    pthread_t worker;
    assert(pthread_create(&worker, NULL, rig_thread, NULL) == 0);
    rig_lock();
    struct track *track = track_acquire_by_import(argv[1], argv[2]);
    rig_unlock();
    assert(track);
    double deadline = now() + 10;
    while (__atomic_load_n(&track->import_result, __ATOMIC_ACQUIRE) == 0 && now() < deadline)
        usleep(1000);
    assert(__atomic_load_n(&track->import_result, __ATOMIC_ACQUIRE) == 1);
    struct deck decks[2] = {0};
    struct timecode_def *def = timecoder_find_definition("serato_2a");
    assert(def);
    for (unsigned i=0; i<2; i++) {
        struct deck *d = &decks[i];
        dummy_init(&d->device);
        timecoder_init(&d->timecoder, def, 1.0, 48000, false);
        rig_lock();
        struct track *t;
        if (i == 0) { track_acquire(track); t=track; } else t=track_acquire_empty();
        rig_unlock();
        player_init(&d->player, 48000, t, &d->timecoder);
        device_connect_timecoder(&d->device, &d->timecoder);
        device_connect_player(&d->device, &d->player);
        d->player.remote.enabled = true;
        routes[i]=(struct route){&d->device, i ? 6 : 0, i ? 6 : 0};
    }
    count=2; input_channels=output_channels=10;
    short input_pcm[5130], output_pcm[5130];
    unsigned audible=0;
    for (unsigned iteration=0; iteration<200; iteration++) {
        for (unsigned f=0; f<513; f++) {
            for (unsigned c=0; c<10; c++) input_pcm[10*f+c]=0;
            double phase=2*M_PI*(iteration*513+f)/48;
            input_pcm[10*f]=16000*sin(phase);
            input_pcm[10*f+1]=16000*cos(phase);
        }
        decks[0].player.position=0.25;
        in_audio=true;
        assert(process(input_pcm, output_pcm, 513, NULL, 0, NULL) == paContinue);
        in_audio=false;
        for (unsigned f=0; f<513; f++) {
            audible += output_pcm[10*f] != 0;
            for (unsigned c=2; c<10; c++) assert(output_pcm[10*f+c]==0);
        }
    }
    assert(audible>10000 && decks[0].player.pitch>0.9 && decks[0].player.pitch<1.1);
    assert(decks[1].player.pitch==0);
    rig_lock();
    struct track *replacement=track_acquire_empty();
    remote_submit(&decks[0].player, replacement, true);
    rig_unlock();
    in_audio=true;
    process(input_pcm, output_pcm, 513, NULL, 0, NULL);
    in_audio=false;
    assert(atomic_load(&decks[0].player.remote.result)==REMOTE_LOCKED);
    rig_lock(); track_release(replacement); rig_unlock();
    atomic_store(&decks[0].player.remote.result, REMOTE_IDLE);
    /* A busy player lock must produce bounded silence, never wait. */
    spin_lock(&decks[0].player.lock);
    in_audio=true;
    process(input_pcm, output_pcm, 513, NULL, 0, NULL);
    in_audio=false;
    spin_unlock(&decks[0].player.lock);
    for (unsigned i=0;i<5130;i++) assert(output_pcm[i]==0);
    /* Empty deck accepts a stopped handoff inside the actual callback. */
    rig_lock(); track_acquire(track); remote_submit(&decks[1].player, track, true); rig_unlock();
    in_audio=true;
    process(input_pcm, output_pcm, 513, NULL, 0, NULL);
    in_audio=false;
    assert(atomic_load(&decks[1].player.remote.result)==REMOTE_OK);
    rig_lock(); track_release(decks[1].player.remote.retired); rig_unlock();
    atomic_store(&decks[1].player.remote.result, REMOTE_IDLE);
    assert(decks[0].player.remote.callbacks && decks[1].player.remote.callbacks);
    for (unsigned i=0;i<2;i++) {
        rig_lock(); player_clear(&decks[i].player); rig_unlock();
        timecoder_clear(&decks[i].timecoder);
    }
    timecoder_free_lookup();
    rig_lock(); track_release(track); rig_unlock();
    assert(rig_quit()==0 && pthread_join(worker,NULL)==0);
    rig_clear(); thread_global_clear();
    puts("Actual Core Audio callback: guarded decoding/rendering, isolated empty deck, motion protection and held-lock silence passed");
}
