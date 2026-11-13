FROM bluenviron/mediamtx:1.21.3 AS media
FROM debian:bookworm-slim AS build
RUN apt-get update && apt-get install -y --no-install-recommends gcc-mingw-w64-i686 && rm -rf /var/lib/apt/lists/*
COPY bridge/tunnel.c /src/tunnel.c
RUN i686-w64-mingw32-gcc -Os -s -Wall -Wextra /src/tunnel.c -o /tunnel.exe
FROM debian:bookworm-slim
RUN dpkg --add-architecture i386 && apt-get update && apt-get install -y --no-install-recommends wine wine32:i386 python3 ca-certificates tini ffmpeg && rm -rf /var/lib/apt/lists/*
ENV WINEDEBUG=-all WINEARCH=win32 WINEPREFIX=/home/bridge/.wine PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
RUN useradd -m -u 10001 bridge && mkdir /run/bridge && chown bridge:bridge /run/bridge
# Create the Wine prefix at build time; the bridge then skips wineboot on every start.
RUN su bridge -c 'wineboot -i && wineserver -w' && test -f /home/bridge/.wine/system.reg
COPY --from=media /mediamtx /usr/local/bin/mediamtx
COPY --from=build /tunnel.exe /opt/bridge/tunnel.exe
COPY bridge/*.py /opt/bridge/
COPY vendor/ /vendor/
EXPOSE 8554
ENTRYPOINT ["/usr/bin/tini", "--", "python3", "/opt/bridge/start.py"]
