#!/bin/sh
# Build the selected GPL-3.0 engine separately from the Python distribution.
set -eu
revision=1.10
archive_sha=589144364d0fea2cc7cbbc21ded25fd376c4c71819a126b8f5864e76eaebcdf3
platform=$(uname -s)
script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
destination=${1:?Usage: build.sh NEW_OUTPUT_DIRECTORY}
test ! -e "$destination" || { echo 'Output directory must not exist' >&2; exit 1; }
scratch=$(mktemp -d)
trap 'rm -rf "$scratch"' EXIT HUP INT TERM
curl --fail --location --retry 3 "https://xwax.org/releases/xwax-$revision.tar.gz" -o "$scratch/source.tar.gz"
if [ "$platform" = Darwin ]; then
    printf '%s  %s\n' "$archive_sha" "$scratch/source.tar.gz" | shasum -a 256 --check
else
    printf '%s  %s\n' "$archive_sha" "$scratch/source.tar.gz" | sha256sum --check
fi
mkdir "$scratch/source"
tar -xzf "$scratch/source.tar.gz" --strip-components=1 -C "$scratch/source"
patch --batch --fuzz=0 -d "$scratch/source" -p1 < "$script_dir/confirmed-state.patch"
cp "$script_dir/remote.c" "$script_dir/remote.h" "$scratch/source/"
if [ "$platform" = Darwin ]; then
    patch --batch --fuzz=0 -d "$scratch/source" -p1 < "$script_dir/macos.patch"
    cp "$script_dir/portaudio-device.c" "$script_dir/portaudio-device.h" \
        "$script_dir/macos-compat.h" "$script_dir/probe-guard.h" \
        "$script_dir/probe-real.h" "$script_dir/check-coreaudio.c" \
        "$script_dir/check-coreaudio-native.c" "$script_dir/check-macos-process.c" "$scratch/source/"
    CFLAGS="-O3 -Wall -Werror=implicit-function-declaration" \
        make -C "$scratch/source" -j2 PORTAUDIO=yes VERSION="$revision+pi-dvs2" \
        LDFLAGS="$(pkg-config --libs-only-L sdl2 SDL2_ttf)" xwax
    cp "$script_dir/check-realtime.c" "$scratch/source/"
    (cd "$scratch/source" && mkdir probe &&
        for unit in remote player device dummy timecoder lut rig track excrate external index library status thread; do
            cc -O2 -I. -include macos-compat.h -include probe-guard.h \
                -c "$unit.c" -o "probe/$unit.o" || exit 1
        done &&
        cc -O2 -I. -include macos-compat.h -include probe-real.h \
            check-realtime.c probe/*.o -pthread -lm -liconv -o check-realtime &&
        cc -O1 -g -fsanitize=address,undefined $(pkg-config --cflags portaudio-2.0) \
            -include macos-compat.h check-coreaudio.c -o check-coreaudio &&
        ./check-coreaudio &&
        cc -O2 -I. $(pkg-config --cflags portaudio-2.0) \
            -include macos-compat.h -include probe-real.h check-coreaudio-native.c \
            probe/*.o $(pkg-config --libs portaudio-2.0) -liconv -o check-coreaudio-native &&
        cc -O2 -I. -include macos-compat.h check-macos-process.c external.o -o check-macos-process &&
        ./check-macos-process)
else
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
fi
mkdir -p "$destination"
cp "$scratch/source/check-realtime" "$scratch/source/xwax" "$scratch/source/import" "$scratch/source/COPYING" "$scratch/source/README" "$destination/"
mv "$destination/import" "$destination/import-original"
cp "$script_dir/../../src/pi_dvs/stream_audio.py" "$destination/stream-import.py"
cat > "$destination/import" <<'IMPORT'
#!/bin/sh
set -eu
here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
case "$1" in
  *.pidvs-stream) exec python3 "$here/stream-import.py" "$@" ;;
  *) exec "$here/import-original" "$@" ;;
esac
IMPORT
chmod +x "$destination/import"
printf '%s\n' "$revision" > "$destination/REVISION"
if [ "$platform" = Darwin ]; then
    cp "$scratch/source/check-coreaudio" "$scratch/source/check-coreaudio-native" "$destination/"
    (cd "$script_dir" && shasum -a 256 confirmed-state.patch macos.patch \
        remote.c remote.h portaudio-device.c portaudio-device.h macos-compat.h \
        ../../src/pi_dvs/stream_audio.py build.sh) > "$destination/PATCH.sha256"
else
    (cd "$script_dir" && sha256sum confirmed-state.patch remote.c remote.h ../../src/pi_dvs/stream_audio.py build.sh) > "$destination/PATCH.sha256"
fi
