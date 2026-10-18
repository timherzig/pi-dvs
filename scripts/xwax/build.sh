#!/bin/sh
# Build the selected GPL-3.0 engine separately from the Python distribution.
set -eu
revision=1.10
archive_sha=589144364d0fea2cc7cbbc21ded25fd376c4c71819a126b8f5864e76eaebcdf3
script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
destination=${1:?Usage: build.sh NEW_OUTPUT_DIRECTORY}
test ! -e "$destination" || { echo 'Output directory must not exist' >&2; exit 1; }
scratch=$(mktemp -d)
trap 'rm -rf "$scratch"' EXIT HUP INT TERM
curl --fail --location --retry 3 "https://xwax.org/releases/xwax-$revision.tar.gz" -o "$scratch/source.tar.gz"
printf '%s  %s\n' "$archive_sha" "$scratch/source.tar.gz" | sha256sum --check
mkdir "$scratch/source"
tar -xzf "$scratch/source.tar.gz" --strip-components=1 -C "$scratch/source"
patch --batch --fuzz=0 -d "$scratch/source" -p1 < "$script_dir/confirmed-state.patch"
cp "$script_dir/remote.c" "$script_dir/remote.h" "$scratch/source/"
CFLAGS="-O3 -Wall -Werror=implicit-function-declaration" make -C "$scratch/source" -j2 ALSA=yes VERSION="$revision+pi-dvs2" xwax
# Link the native probe against the exact production objects, wrapping forbidden
# callback operations. Test code is never linked into the engine itself.
cp "$script_dir/check-realtime.c" "$scratch/source/"
(cd "$scratch/source" && cc -O2 -D_GNU_SOURCE -I. check-realtime.c \
    remote.o player.o device.o dummy.o timecoder.o lut.o rig.o track.o \
    excrate.o external.o index.o library.o status.o thread.o -pthread -lm \
    -Wl,--wrap=malloc,--wrap=calloc,--wrap=realloc,--wrap=free \
    -Wl,--wrap=pthread_mutex_lock,--wrap=pthread_spin_lock,--wrap=pthread_spin_trylock \
    -Wl,--wrap=poll,--wrap=send,--wrap=recv,--wrap=read,--wrap=write \
    -Wl,--wrap=fprintf,--wrap=fputs,--wrap=printf,--wrap=puts \
    -Wl,--wrap=fwrite,--wrap=fflush,--wrap=strdup -o check-realtime)
mkdir -p "$destination"
cp "$scratch/source/check-realtime" "$scratch/source/xwax" "$scratch/source/import" "$scratch/source/COPYING" "$scratch/source/README" "$destination/"
printf '%s\n' "$revision" > "$destination/REVISION"
(cd "$script_dir" && sha256sum confirmed-state.patch remote.c remote.h) > "$destination/PATCH.sha256"
