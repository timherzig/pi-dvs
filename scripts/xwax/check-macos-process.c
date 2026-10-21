/* Copyright (C) 2026 Tim Herzig. SPDX-License-Identifier: GPL-3.0-only */
#include <assert.h>
#include <errno.h>
#include <fcntl.h>
#include <poll.h>
#include <stdio.h>
#include <stdbool.h>
#include <string.h>
#include <sys/wait.h>
#include <unistd.h>
#include "external.h"
static void check_import(bool closed_stdout)
{
    int saved=-1;
    if (closed_stdout) { saved=dup(STDOUT_FILENO); assert(saved>=0); close(STDOUT_FILENO); }
    int fd;
    pid_t child=fork_pipe_nb(&fd, "/bin/sh", "sh", "-c",
        "if [ -e /dev/fd/99 ]; then exit 9; fi; printf abcd; printf 'expected importer diagnostic\\n' >&2", NULL);
    assert(child>0);
    char pcm[64]; size_t used=0;
    for (;;) {
        struct pollfd p={.fd=fd,.events=POLLIN};
        assert(poll(&p,1,2000)>0);
        ssize_t n=read(fd,pcm+used,sizeof pcm-used);
        if (n<0 && errno==EAGAIN) continue;
        assert(n>=0);
        if (!n) break;
        used+=(size_t)n; assert(used<sizeof pcm);
    }
    close(fd);
    int status; assert(waitpid(child,&status,0)==child);
    assert(WIFEXITED(status) && WEXITSTATUS(status)==0);
    assert(used==4 && !memcmp(pcm,"abcd",4));
    if (closed_stdout) { assert(dup2(saved,STDOUT_FILENO)==STDOUT_FILENO); close(saved); }
}
int main(void)
{
    int sentinel=open("/dev/null",O_RDONLY);assert(sentinel>=0);
    assert(dup2(sentinel,99)==99);close(sentinel);
    check_import(false);check_import(true);close(99);
    int fd=-1;
    assert(fork_pipe_nb(&fd,"/no/such/pi-dvs-importer","import",NULL)==-1 && errno==ENOENT);
    puts("Darwin spawn: PCM/stderr separation, closed stdout, descriptor isolation and failed exec passed");
}
