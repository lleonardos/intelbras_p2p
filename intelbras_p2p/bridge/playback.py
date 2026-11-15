"""Bounded DVR playback clips for the Home Assistant ingress player."""
from datetime import datetime, timedelta
from pathlib import Path
import subprocess
import tempfile
import threading
import time
from urllib.parse import quote

SLOTS = threading.BoundedSemaphore(2)
MAX_SECONDS = 30
MAX_BYTES = 12 * 1024 * 1024


def convert(args, start_limit=20, stall_limit=4, total_limit=65):
    """Run ffmpeg and return whether it left usable video.

    When the recording ends before the requested range the recorder stops sending video but keeps the
    session open, and ffmpeg would wait forever. Its -progress output shows whether video is still
    advancing; once it stalls ffmpeg is stopped. It does not finish the file in time when interrupted
    during an RTSP read, which is why the output is fragmented MP4: what was written stays playable."""
    process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    began = time.monotonic()
    advanced = [None]

    def watch():
        position = '0'
        for line in process.stdout:
            key, _, value = line.strip().partition('=')
            if key == 'out_time_us' and value.isdigit() and value not in ('0', position):
                position, advanced[0] = value, time.monotonic()

    threading.Thread(target=watch, daemon=True).start()
    stopped = False
    while process.poll() is None:
        time.sleep(0.2)
        now = time.monotonic()
        stalled = now - advanced[0] > stall_limit if advanced[0] else now - began > start_limit
        if stalled or now - began > total_limit:
            stopped = True
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
    return advanced[0] is not None if stopped else process.returncode == 0


def arguments(url, seconds, output):
    """ffmpeg command line: at most `seconds` of H.264 video, small enough to hand to the browser at once."""
    return ['ffmpeg', '-nostdin', '-loglevel', 'quiet', '-nostats', '-progress', 'pipe:1', '-rtsp_transport', 'tcp',
            '-timeout', '7000000', '-i', url, '-t', str(seconds), '-map', '0:v:0', '-an', '-vf',
            "scale=w='min(960,iw)':h=-2", '-c:v', 'libx264', '-threads', '2', '-preset', 'ultrafast',
            '-pix_fmt', 'yuv420p', '-maxrate', '2M', '-bufsize', '4M', '-g', '25', '-fs', str(MAX_BYTES),
            # One fragment per keyframe, so a conversion that is cut short still leaves a valid file.
            '-movflags', 'frag_keyframe+empty_moov+default_base_moof', '-flush_packets', '1', str(output)]


def clip(device, channels, data):
    channel = int(data['channel'])
    start = datetime.strptime(data['start'], '%Y-%m-%d %H:%M:%S')
    seconds = int(data['seconds'])
    if channel not in channels or not 1 <= seconds <= MAX_SECONDS:
        raise ValueError('Canal ou duração inválida.')
    # The recorder delivers slightly less video than the range asked for and then keeps the session open,
    # so ask for a little more and let ffmpeg's -t make the cut.
    end = start + timedelta(seconds=seconds + 2)
    stamp = '%Y_%m_%d_%H_%M_%S'
    port = device['p2p']['local_port']
    url = (f"rtsp://{quote(device['username'], safe='')}:{quote(device['password'], safe='')}"
           f"@127.0.0.1:{port}/cam/playback?channel={channel}"
           f"&starttime={start.strftime(stamp)}&endtime={end.strftime(stamp)}")
    if not SLOTS.acquire(blocking=False):
        raise ValueError('Reprodutor ocupado.')
    try:
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / 'clip.mp4'
            if not convert(arguments(url, seconds, output)) or not output.exists():
                raise ValueError('Trecho indisponível.')
            if not 0 < output.stat().st_size <= MAX_BYTES + 65536:
                raise ValueError('Trecho indisponível.')
            # A DVR can accept PLAY but send zero frames. Some MP4 muxers still write a header.
            probe = subprocess.run(['ffprobe', '-v', 'quiet', '-select_streams', 'v:0', '-count_packets',
                                    '-show_entries', 'stream=nb_read_packets', '-of', 'csv=p=0', str(output)],
                                   capture_output=True, timeout=10, check=True)
            if not probe.stdout.strip().isdigit() or int(probe.stdout) == 0:
                raise ValueError('Sem vídeo neste horário.')
            return output.read_bytes()
    finally:
        SLOTS.release()
