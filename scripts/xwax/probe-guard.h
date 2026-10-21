/* Test builds only: source-level equivalent of GNU ld --wrap on Darwin. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <poll.h>
#include <pthread.h>
#include <unistd.h>
#include <sys/socket.h>
#define DECLARE(name) __typeof__(name) __wrap_##name;
DECLARE(malloc) DECLARE(calloc) DECLARE(realloc) DECLARE(free)
DECLARE(pthread_mutex_lock) DECLARE(pthread_spin_lock) DECLARE(pthread_spin_trylock)
DECLARE(poll) DECLARE(send) DECLARE(recv) DECLARE(read) DECLARE(write)
DECLARE(fprintf) DECLARE(fputs) DECLARE(printf) DECLARE(puts)
DECLARE(fwrite) DECLARE(fflush) DECLARE(strdup)
#undef DECLARE
#define malloc __wrap_malloc
#define calloc __wrap_calloc
#define realloc __wrap_realloc
#define free __wrap_free
#define pthread_mutex_lock __wrap_pthread_mutex_lock
#define pthread_spin_lock __wrap_pthread_spin_lock
#define pthread_spin_trylock __wrap_pthread_spin_trylock
#define poll __wrap_poll
#define send __wrap_send
#define recv __wrap_recv
#define read __wrap_read
#define write __wrap_write
#define fprintf __wrap_fprintf
#define fputs __wrap_fputs
#define printf __wrap_printf
#define puts __wrap_puts
#define fwrite __wrap_fwrite
#define fflush __wrap_fflush
#define strdup __wrap_strdup
