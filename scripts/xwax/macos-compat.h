/* Copyright (C) 2026 Tim Herzig. SPDX-License-Identifier: GPL-3.0-only
 * Included only by the Darwin native build. No effect on Linux/ALSA.
 */
#ifndef PI_DVS_MACOS_COMPAT_H
#define PI_DVS_MACOS_COMPAT_H
#include <alloca.h>
#include <errno.h>
#include <pthread.h>
#include <stdatomic.h>
#include <string.h>
#include <sched.h>
#include <signal.h>
/* Darwin has no pthread spinlocks. The audio path makes one bounded attempt;
 * only non-audio callers may wait. C11 atomic_flag is guaranteed lock-free. */
typedef struct { atomic_flag flag; } pthread_spinlock_t;
static inline int pthread_spin_init(pthread_spinlock_t *p, int shared)
{ (void)shared; *p = (pthread_spinlock_t){ ATOMIC_FLAG_INIT }; return 0; }
static inline int pthread_spin_destroy(pthread_spinlock_t *p) { (void)p; return 0; }
static inline int pthread_spin_trylock(pthread_spinlock_t *p)
{ return atomic_flag_test_and_set_explicit(&p->flag, memory_order_acquire) ? EBUSY : 0; }
static inline int pthread_spin_lock(pthread_spinlock_t *p)
{ while (pthread_spin_trylock(p)) sched_yield(); return 0; }
static inline int pthread_spin_unlock(pthread_spinlock_t *p)
{ atomic_flag_clear_explicit(&p->flag, memory_order_release); return 0; }
#define strdupa(text) __extension__ ({ const char *s_ = (text); \
    size_t n_ = strlen(s_) + 1; char *p_ = alloca(n_); memcpy(p_, s_, n_); p_; })
#endif
