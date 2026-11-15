"""Recorder operations available through the authenticated add-on ingress."""
from datetime import date
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

PTZ_CODES = ('Up', 'Down', 'Left', 'Right', 'ZoomTele', 'ZoomWide')
SNAPSHOT_BYTES = 2 * 1024 * 1024


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args):
        return None


def firmware(body):
    """'4.000.00IB003.0 (2024-10-24)' from 'version=4.000.00IB003.0,build:2024-10-24 11:29:28'."""
    version, _, build = body.partition('=')[2].partition(',build:')
    return version.strip() + (f' ({build.split()[0]})' if build.strip() else '')


def disks(body):
    """[(total bytes, has error)] per disk from storageDevice getDeviceAllInfo, adding up its partitions."""
    found = {}
    for index, field, value in re.findall(r'list\.info\[(\d+)\]\.Detail\[\d+\]\.(TotalBytes|IsError)=(\S+)', body):
        disk = found.setdefault(int(index), [0.0, False])
        if field == 'TotalBytes':
            disk[0] += float(value)
        elif value.lower() == 'true':
            disk[1] = True
    return [tuple(found[index]) for index in sorted(found)]


def titles(body, channels):
    """{channel: name} for the configured channels, from configManager getConfig ChannelTitle."""
    names = {int(index) + 1: name.strip() for index, name in re.findall(r'ChannelTitle\[(\d+)\]\.Name=([^\r\n]*)', body)}
    return {channel: names[channel] for channel in channels if channel in names}


def recorders(config):
    """{name: Recorder} for the devices with management enabled."""
    return {device['name']: Recorder(device) for device in config['devices'] if 'management_local_port' in device}


class Recorder:
    def __init__(self, device):
        self.device = device
        self.channels = sorted({int(s['name'].rsplit('_ch', 1)[1].split('_')[0]) for s in device['streams']})
        self.base = 'http://127.0.0.1:' + str(device['management_local_port']) + '/cgi-bin/'
        # Separate openers: the digest handler keeps retry state, so panel actions and thumbnails must not share one.
        self.http, self.images = self.opener(), self.opener()
        self.lock, self.image_lock = threading.Lock(), threading.Lock()

    def opener(self):
        passwords = urllib.request.HTTPPasswordMgrWithDefaultRealm()
        passwords.add_password(None, self.base, self.device['username'], self.device['password'])
        return urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect(),
                                           urllib.request.HTTPDigestAuthHandler(passwords),
                                           urllib.request.HTTPBasicAuthHandler(passwords))

    def call(self, script, **params):
        with self.http.open(self.base + script + '.cgi?' + urllib.parse.urlencode(params, quote_via=urllib.parse.quote, safe='[]:'), timeout=8) as response:
            body = response.read(512 * 1024).decode('utf-8', errors='replace').strip()
        if body.startswith('Error') or body.startswith('<'):
            raise ValueError('Operação recusada pelo gravador.')
        return body

    def guarded(self, action, *args, wait=20):
        """Run `action` holding the recorder lock, waiting for a panel request in progress to finish."""
        if not self.lock.acquire(timeout=wait):
            raise ValueError('Gravador ocupado.')
        try:
            return action(*args)
        finally:
            self.lock.release()

    def config(self, name):
        """Text of one configuration table. `name` always comes from this add-on, never from a request."""
        return self.guarded(lambda: self.call('configManager', action='getConfig', name=name))

    def set_config(self, key, value):
        return self.guarded(lambda: self.call('configManager', action='setConfig', **{key: value}))

    def snapshot(self, channel):
        """A JPEG of the channel taken by the recorder itself, or None. Much lighter than opening the RTSP stream."""
        if channel not in self.channels:
            return None
        try:
            with self.image_lock, self.images.open(f'{self.base}snapshot.cgi?channel={channel}', timeout=8) as response:
                image = response.read(SNAPSHOT_BYTES)
        except OSError:
            return None
        return image if image.startswith(b'\xff\xd8') else None

    def status(self):
        """Model, firmware, clock and disks. Never includes the serial number."""
        return {'model': self.call('magicBox', action='getDeviceType').partition('=')[2],
                'firmware': firmware(self.call('magicBox', action='getSoftwareVersion')),
                'clock': self.call('global', action='getCurrentTime').partition('=')[2],
                'disks': [{'gb': round(size / 1e9), 'error': error}
                          for size, error in disks(self.call('storageDevice', action='getDeviceAllInfo'))]}

    def recordings(self, channel, day):
        result = self.call('mediaFileFind', action='factory.create')
        match = re.fullmatch(r'result=(\d+)', result)
        if not match:
            raise ValueError('Busca indisponível neste firmware.')
        obj = match[1]
        try:
            conditions = {
                'condition.Channel': channel, 'condition.StartTime': day + ' 00:00:00',
                'condition.EndTime': day + ' 23:59:59', 'condition.Types[0]': 'dav'}
            try:
                self.call('mediaFileFind', action='findFile', object=obj, **conditions)
            except urllib.error.HTTPError as exc:
                if exc.code != 400 or not 2**31 <= int(obj) < 2**32:
                    raise
                signed = str(int(obj) - 2**32)
                self.call('mediaFileFind', action='findFile', object=signed, **conditions)
                obj = signed
            entries = []
            for _ in range(20):
                batch = self.call('mediaFileFind', action='findNextFile', object=obj, count=50)
                fields = re.findall(r'items\[(\d+)\]\.(StartTime|EndTime)=([^\r\n]+)', batch)
                times = {}
                for index, field, value in fields:
                    times.setdefault(index, {})[field] = value
                entries.extend([t['StartTime'], t['EndTime']] for t in times.values() if len(t) == 2)
                if len(times) < 50:
                    break
            return entries
        finally:
            try:
                self.call('mediaFileFind', action='close', object=obj)
            finally:
                self.call('mediaFileFind', action='destroy', object=obj)

    def run(self, data):
        action = data['action']
        channel = int(data['channel'])
        if channel not in self.channels:
            raise ValueError('Canal inválido.')
        if not self.lock.acquire(blocking=False):
            raise ValueError('Gravador ocupado.')
        try:
            key = f'ChannelTitle[{channel - 1}].Name'
            if action == 'status':
                return self.status()
            if action == 'titles':
                return titles(self.call('configManager', action='getConfig', name='ChannelTitle'), self.channels)
            if action == 'rename':
                title = data['title'].strip()
                if not title or len(title) > 32 or not title.isprintable():
                    raise ValueError('Informe um nome de até 32 caracteres.')
                self.call('configManager', action='setConfig', **{key: title})
                return title
            if action == 'ptz':
                code = data['direction']
                if code not in PTZ_CODES:
                    raise ValueError('Direção inválida.')
                params = dict(channel=channel, code=code, arg1=0, arg2=2, arg3=0)
                try:
                    self.call('ptz', action='start', **params)
                    time.sleep(0.3)
                finally:
                    self.call('ptz', action='stop', **params)
                return True
            if action == 'recordings':
                return self.recordings(channel, date.fromisoformat(data['day']).isoformat())
            raise ValueError('Operação inválida.')
        finally:
            self.lock.release()
