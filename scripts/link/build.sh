#!/bin/sh
set -eu
cd "$(dirname "$0")"
revision=7fb4dad3f88a2cc0cecec0e718b4dde408fd7448
if [ ! -d build/rbxport/.git ]; then
    mkdir -p build/rbxport
    git -C build/rbxport init -q
    git -C build/rbxport fetch --depth 1 https://github.com/chrisle/rbxport "$revision"
    git -C build/rbxport checkout --detach FETCH_HEAD
fi
if [ "$(git -C build/rbxport rev-parse HEAD)" != "$revision" ]; then
    echo 'Unexpected helper dependency revision; use a fresh build directory.' >&2
    exit 1
fi
if ! git -C build/rbxport apply --reverse --check ../../cdj-compat.patch 2>/dev/null; then
    git -C build/rbxport apply --check ../../cdj-compat.patch
    git -C build/rbxport apply ../../cdj-compat.patch
fi
if [ "${1:-}" = --prepare ]; then
    exit 0
fi
cargo build --locked --release --manifest-path Cargo.toml
