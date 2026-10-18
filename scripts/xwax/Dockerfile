FROM ubuntu:24.04@sha256:68ee22004a9109b44973313b02ff7b1de250f1de0f5ecb628d73f579aaff33ac
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential pkg-config libsdl2-dev libsdl2-ttf-dev \
    libasound2-dev ffmpeg curl ca-certificates patch python3 \
    && rm -rf /var/lib/apt/lists/*
COPY build.sh confirmed-state.patch remote.c remote.h check-realtime.c /build/
RUN sh /build/build.sh /opt/xwax
WORKDIR /app
ENV PYTHONPATH=/app/src
CMD ["sh", "-c", "/opt/xwax/check-realtime /opt/xwax/import '/app/tests/fixtures/usb/Contents/Élise/Café 東京.wav' && python3 scripts/check_xwax.py --engine /opt/xwax/xwax --importer /opt/xwax/import"]
