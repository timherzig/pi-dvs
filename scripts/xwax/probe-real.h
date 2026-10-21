/* Test build only: wrappers delegate to libc (Darwin has no GNU ld --wrap). */
#define __real_malloc malloc
#define __real_calloc calloc
#define __real_realloc realloc
#define __real_free free
#define __real_pthread_mutex_lock pthread_mutex_lock
#define __real_pthread_spin_lock pthread_spin_lock
#define __real_pthread_spin_trylock pthread_spin_trylock
#define __real_poll poll
#define __real_send send
#define __real_recv recv
#define __real_read read
#define __real_write write
#define __real_fputs fputs
#define __real_puts puts
#define __real_fflush fflush
#define __real_fwrite fwrite
#define __real_strdup strdup
#ifndef MSG_NOSIGNAL
#define MSG_NOSIGNAL 0
#endif
