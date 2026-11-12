FROM bluenviron/mediamtx:1.21.3 AS media
FROM debian:bookworm-slim AS build
RUN apt-get update && apt-get install -y --no-install-recommends gcc-mingw-w64-i686 && rm -rf /var/lib/apt/lists/*
COPY bridge/tunnel.c /src/tunnel.c
RUN i686-w64-mingw32-gcc -Os -Wall -Wextra /src/tunnel.c -o /tunnel.exe
FROM debian:bookworm-slim
RUN dpkg --add-architecture i386 && apt-get update && apt-get install -y --no-install-recommends wine wine32:i386 python3 ca-certificates tini && rm -rf /var/lib/apt/lists/*
COPY --from=media /mediamtx /usr/local/bin/mediamtx
COPY --from=build /tunnel.exe /opt/bridge/tunnel.exe
COPY bridge/ /opt/bridge/
RUN useradd -m -u 10001 bridge && mkdir /run/bridge && chown bridge:bridge /run/bridge
COPY vendor/ /vendor/
ENV WINEDEBUG=-all WINEARCH=win32 WINEPREFIX=/home/bridge/.wine PYTHONUNBUFFERED=1
EXPOSE 8554
ENTRYPOINT ["/usr/bin/tini", "--", "python3", "/opt/bridge/start.py"]
