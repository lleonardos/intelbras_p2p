import json
import os
import re
import signal
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path
from urllib.parse import quote

RUN_DIR = Path('/run/bridge')
MEDIA_CONFIG = RUN_DIR / 'mediamtx.json'
VENDOR_DIR = Path('/vendor')
RTSP_PORT = 8554
API_PORT = 9997
API_PAGE_SIZE = 1000
API_URL = f'http://127.0.0.1:{API_PORT}/v3/paths/list?itemsPerPage={API_PAGE_SIZE}&page='
POLL_SECONDS = 2
# Once every stream is up, the API is polled less often; child exits are still checked every POLL_SECONDS.
READY_HEALTH_SECONDS = 10
# Home Assistant kills an add-on 10 s after SIGTERM; stay well inside that budget.
# Nothing here keeps state worth waiting for, so a child that stalls is simply killed.
SHUTDOWN_SECONDS = 3

HOST_RE = re.compile(r'[A-Za-z0-9.-]+:[0-9]+')
NAME_RE = re.compile(r'[A-Za-z0-9_-]+')


def prepare(config):
    auth = config['output_auth']
    if not auth.get('username') or auth['username'] == 'any' or not auth.get('password'):
        raise ValueError('output_auth requires a named user and password')
    paths, tunnels, ports = {}, [], set()
    for device in config['devices']:
        mode = device.get('mode', 'p2p')
        if mode not in ('p2p', 'rtsp'):
            raise ValueError('mode must be p2p or rtsp')
        if mode == 'p2p':
            p = device['p2p']
            for key in ('server', 'server_key', 'uuid', 'remote_ip'):
                if not isinstance(p.get(key), str) or not p[key] or p[key].startswith('REPLACE_'):
                    raise ValueError('Missing verified P2P setting: ' + key)
            for key in ('server_port', 'remote_port', 'local_port'):
                if type(p.get(key)) is not int or not 1 <= p[key] <= 65535:
                    raise ValueError('Invalid port: ' + key)
            if p['local_port'] in ports or p['local_port'] in (RTSP_PORT, API_PORT):
                raise ValueError('Duplicate or reserved local port')
            ports.add(p['local_port'])
            tunnels.append({'T2U_' + k.upper(): str(v) for k, v in p.items()})
            host = '127.0.0.1:' + str(p['local_port'])
        else:
            host = device['host']
            if not HOST_RE.fullmatch(host):
                raise ValueError('host must be hostname:port')
        user = quote(device['username'], safe='')
        password = quote(device['password'], safe='')
        base = f'rtsp://{user}:{password}@{host}'
        for stream in device['streams']:
            name, path = stream['name'], stream['path']
            if not NAME_RE.fullmatch(name) or name in paths:
                raise ValueError('Invalid or duplicate stream name')
            if not path.startswith('/') or any(c in path for c in '\r\n#'):
                raise ValueError('Invalid RTSP path')
            paths[name] = {'source': base + path, 'rtspTransport': 'tcp'}
            if stream.get('on_demand', False):
                paths[name].update(sourceOnDemand=True, sourceOnDemandStartTimeout='30s',
                                   sourceOnDemandCloseAfter='10s')
    if not paths:
        raise ValueError('At least one stream is required')
    return {
        'logLevel': 'error', 'rtspAddress': f':{RTSP_PORT}', 'rtspTransports': ['tcp'],
        # MoQ is on by default in mediamtx 1.21 and its server blocks shutdown after SIGTERM.
        'rtmp': False, 'hls': False, 'webrtc': False, 'srt': False, 'moq': False,
        'api': True, 'apiAddress': f'127.0.0.1:{API_PORT}',
        'authInternalUsers': [
            {'user': auth['username'], 'pass': auth['password'], 'permissions': [{'action': 'read'}]},
            {'user': 'any', 'ips': ['127.0.0.1', '::1'], 'permissions': [{'action': 'api'}]},
        ], 'paths': paths,
    }, tunnels


def required_paths(paths):
    # Dormant on-demand paths are intentionally not connected to the NVR.
    return {name for name, settings in paths.items() if not settings.get('sourceOnDemand')}


def healthy(required=None):
    """True when every always-on path is ready. Reads the saved config when `required` is omitted."""
    try:
        if required is None:
            required = required_paths(json.loads(MEDIA_CONFIG.read_text())['paths'])
        missing = set(required)
        page = 0
        while missing:
            with urllib.request.urlopen(API_URL + str(page), timeout=3) as response:
                data = json.load(response)
            missing.difference_update(p['name'] for p in data['items'] if p.get('ready'))
            page += 1
            if page >= data.get('pageCount', 1):
                break
        return not missing
    except (OSError, ValueError, KeyError, TypeError):
        return False


def wine_prefix_ready():
    # The image ships an initialized prefix; wineboot (about 5 s) is only needed when it is absent.
    prefix = os.environ.get('WINEPREFIX') or str(Path.home() / '.wine')
    return Path(prefix, 'system.reg').is_file()


def shutdown(children, timeout=SHUTDOWN_SECONDS):
    for child in children:
        if child.poll() is None:
            child.terminate()
    # One deadline shared by all children, so many tunnels do not multiply the wait.
    deadline = time.monotonic() + timeout
    for child in children:
        try:
            child.wait(timeout=max(0, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait()


def main(config=None):
    if '--health' in sys.argv:
        return 0 if healthy() else 1
    try:
        if config is None:
            config = json.loads(Path('/config/config.json').read_text())
        media, tunnels = prepare(config)
        if tunnels and not (VENDOR_DIR / 'libt2u.dll').is_file():
            raise ValueError('Mount the extracted libt2u.dll in /vendor')
    except (OSError, ValueError, KeyError, TypeError) as exc:
        # Only ValueError text is ours and known to be free of credentials and serials.
        detail = str(exc) if type(exc) is ValueError else 'check required fields'
        print(f'Configuration rejected ({type(exc).__name__}): {detail}.', flush=True)
        return 2
    os.umask(0o077)
    if tunnels:
        # Wine must map DLLs from its Linux filesystem, not a Windows bind mount.
        sdk = RUN_DIR / 'sdk'
        sdk.mkdir(exist_ok=True)
        for library in VENDOR_DIR.glob('*.dll'):
            shutil.copyfile(library, sdk / library.name)
    MEDIA_CONFIG.write_text(json.dumps(media))
    required = required_paths(media['paths'])
    children = []
    stopping = threading.Event()

    def stop(*_):
        stopping.set()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    quiet = {'stdout': subprocess.DEVNULL, 'stderr': subprocess.DEVNULL}
    try:
        if tunnels and not wine_prefix_ready():
            # Initialize the shared Wine prefix once before concurrent DVR workers.
            try:
                subprocess.run(['wineboot', '-u'], check=True, timeout=90, **quiet)
            except (OSError, subprocess.SubprocessError) as exc:
                print(f'Wine initialization failed ({type(exc).__name__}); stopping for container restart.',
                      flush=True)
                return 1
        if tunnels:
            # Start one wineserver up front so concurrent tunnels do not race to launch it.
            try:
                subprocess.run(['wineserver', '-p'], check=True, timeout=30, **quiet)
            except (OSError, subprocess.SubprocessError) as exc:
                print(f'Wine server failed to start ({type(exc).__name__}); stopping for container restart.',
                      flush=True)
                return 1
        for env in tunnels:
            if stopping.is_set():
                return 0
            # The SDK may log device identifiers; keep its raw output private.
            children.append(subprocess.Popen(['wine', '/opt/bridge/tunnel.exe'],
                                             env={**os.environ, **env}, **quiet))
        children.append(subprocess.Popen(['mediamtx', str(MEDIA_CONFIG)], **quiet))
        print(f'Bridge started: {len(media["paths"])} configured streams; awaiting video.', flush=True)
        previous = None
        next_health = 0.0
        while not stopping.is_set():
            exited = [(i, p.returncode) for i, p in enumerate(children) if p.poll() is not None]
            if exited:
                print('Bridge process index/exit code:', exited, '; stopping for container restart.', flush=True)
                return 1
            now = time.monotonic()
            if now >= next_health:
                ready = healthy(required)
                if ready != previous:
                    print('All streams ready.' if ready else 'Waiting for one or more streams.', flush=True)
                    previous = ready
                next_health = now + (READY_HEALTH_SECONDS if ready else POLL_SECONDS)
            # Unlike time.sleep, this returns as soon as a stop signal arrives.
            stopping.wait(POLL_SECONDS)
    finally:
        shutdown(children)
    return 0


if __name__ == '__main__':
    sys.exit(main())
