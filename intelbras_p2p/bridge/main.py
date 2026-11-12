import json
import os
import re
import signal
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from urllib.parse import quote


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
            if p['local_port'] in ports or p['local_port'] in (8554, 9997):
                raise ValueError('Duplicate or reserved local port')
            ports.add(p['local_port'])
            env = {('T2U_' + k.upper()): str(v) for k, v in p.items()}
            tunnels.append(env)
            host = '127.0.0.1:' + str(p['local_port'])
        else:
            host = device['host']
            if not re.fullmatch(r'[A-Za-z0-9.-]+:[0-9]+', host):
                raise ValueError('host must be hostname:port')
        user = quote(device['username'], safe='')
        password = quote(device['password'], safe='')
        for stream in device['streams']:
            name, path = stream['name'], stream['path']
            if not re.fullmatch(r'[A-Za-z0-9_-]+', name) or name in paths:
                raise ValueError('Invalid or duplicate stream name')
            if not path.startswith('/') or any(c in path for c in '\r\n#'):
                raise ValueError('Invalid RTSP path')
            paths[name] = {'source': f'rtsp://{user}:{password}@{host}{path}', 'rtspTransport': 'tcp'}
            if stream.get('on_demand', False):
                paths[name].update(sourceOnDemand=True, sourceOnDemandStartTimeout='30s',
                                   sourceOnDemandCloseAfter='10s')
    if not paths:
        raise ValueError('At least one stream is required')
    return {
        'logLevel': 'error', 'rtspAddress': ':8554', 'rtspTransports': ['tcp'],
        'rtmp': False, 'hls': False, 'webrtc': False, 'srt': False,
        'api': True, 'apiAddress': '127.0.0.1:9997',
        'authInternalUsers': [
            {'user': auth['username'], 'pass': auth['password'], 'permissions': [{'action': 'read'}]},
            {'user': 'any', 'ips': ['127.0.0.1', '::1'], 'permissions': [{'action': 'api'}]},
        ], 'paths': paths,
    }, tunnels


def healthy():
    try:
        with urllib.request.urlopen('http://127.0.0.1:9997/v3/paths/list?itemsPerPage=1000', timeout=3) as response:
            items = json.load(response)['items']
        expected = json.loads(Path('/run/bridge/mediamtx.json').read_text())['paths']
        ready = {p['name'] for p in items if p.get('ready')}
        # Dormant on-demand paths are intentionally not connected to the NVR.
        required = {name for name, settings in expected.items() if not settings.get('sourceOnDemand')}
        return required.issubset(ready)
    except (OSError, ValueError, KeyError):
        return False


def main(config=None):
    if '--health' in sys.argv:
        return 0 if healthy() else 1
    try:
        if config is None:
            config = json.loads(Path('/config/config.json').read_text())
        media, tunnels = prepare(config)
        if tunnels and not Path('/vendor/libt2u.dll').is_file():
            raise ValueError('Mount the extracted libt2u.dll in /vendor')
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print('Configuration rejected (' + type(exc).__name__ + '); check required fields.', flush=True)
        return 2
    os.umask(0o077)
    if tunnels:
        # Wine must map DLLs from its Linux filesystem, not a Windows bind mount.
        sdk = Path('/run/bridge/sdk')
        sdk.mkdir(exist_ok=True)
        for library in Path('/vendor').glob('*.dll'):
            shutil.copyfile(library, sdk / library.name)
    Path('/run/bridge/mediamtx.json').write_text(json.dumps(media))
    children = []
    stopping = False

    def stop(*_):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        if tunnels:
            # Initialize the shared Wine prefix once before concurrent DVR workers.
            subprocess.run(['wineboot', '-u'], stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, check=True, timeout=90)
        for env in tunnels:
            # The SDK may log device identifiers; keep its raw output private.
            children.append(subprocess.Popen(['wine', '/opt/bridge/tunnel.exe'], env={**os.environ, **env}, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
        children.append(subprocess.Popen(['mediamtx', '/run/bridge/mediamtx.json'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
        print(f'Bridge started: {len(media["paths"])} configured streams; awaiting video.')
        previous = None
        while not stopping:
            exited = [(i, p.returncode) for i, p in enumerate(children) if p.poll() is not None]
            if exited:
                print('Bridge process index/exit code:', exited, '; stopping for container restart.')
                return 1
            ready = healthy()
            if ready != previous:
                print('All streams ready.' if ready else 'Waiting for one or more streams.')
                previous = ready
            time.sleep(2)
    finally:
        for child in children:
            if child.poll() is None:
                child.terminate()
        for child in children:
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()
    return 0


if __name__ == '__main__':
    sys.exit(main())
