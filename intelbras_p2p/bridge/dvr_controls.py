"""Recorder operations available through the authenticated add-on ingress."""
from datetime import date
import http.client
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


ENCODE_STREAMS = {'main': 'MainFormat[0]', 'sub': 'ExtraFormat[0]'}
# Field of the page -> setting under Encode[channel].<stream>. Resolution is apart: it writes Width and Height.
ENCODE_SETTINGS = {
    'compression': 'Video.Compression', 'fps': 'Video.FPS', 'bitrate_control': 'Video.BitRateControl',
    'bitrate': 'Video.BitRate', 'quality': 'Video.Quality', 'gop': 'Video.GOP', 'audio': 'AudioEnable',
    'audio_compression': 'Audio.Compression'}
# Resolution names used by the recorders that mean one size everywhere.
SIZES = {'1080P': '1920x1080', '1080': '1920x1080', '720P': '1280x720', '720': '1280x720', '1080N': '960x1080',
         '720N': '640x720', 'SXGA': '1280x1024', 'UXGA': '1600x1200', '1_3M': '1280x960', '3M': '2048x1536',
         'QFHD': '3840x2160', 'VGA': '640x480', 'QVGA': '320x240', 'NHD': '640x360'}
# Names whose height follows the video standard of the recorder: (PAL, NTSC).
STANDARD_SIZES = {'960H': ('960x576', '960x480'), 'D1': ('704x576', '704x480'), 'HD1': ('352x576', '352x480'),
                  'BCIF': ('704x288', '704x240'), '2CIF': ('704x288', '704x240'), 'CIF': ('352x288', '352x240'),
                  'QCIF': ('176x144', '176x120')}
WHOLE_RE = re.compile(r'(\d{1,6})(\.0+)?')


def encode_values(body, channel, head):
    """{setting: text} of one stream from configManager getConfig Encode[channel - 1]."""
    prefix = re.escape(f'Encode[{channel - 1}].{head}.')
    return {name: value.strip() for name, value in re.findall(prefix + r'([A-Za-z.]+)=([^\r\n]*)', body)}


def encode_caps(body, channel, head):
    """{capability: text} of one stream from encode getConfigCaps.

    Firmwares write the lines as caps.MainFormat[0]... or caps[N].MainFormat[0]...; with several N, the one
    of the channel wins."""
    found = {}
    for index, name, value in re.findall(r'caps(?:\[(\d+)\])?\.' + re.escape(head) + r'\.([A-Za-z.]+)=([^\r\n]*)', body):
        found.setdefault(index, {})[name] = value.strip()
    return found.get(str(channel - 1)) or found.get('') or next(iter(found.values()), {})


def size(token, standard):
    """'1920x1080' for a resolution written as a size or as a name this add-on knows, else None."""
    match = re.fullmatch(r'(\d{3,4}) ?[xX*] ?(\d{3,4})', token)
    if match:
        return match[1] + 'x' + match[2]
    name = token.upper()
    if name in STANDARD_SIZES and standard in ('PAL', 'NTSC'):
        return STANDARD_SIZES[name][standard == 'NTSC']
    return SIZES.get(name)


def encode_form(values, caps, standard=''):
    """Fields of one stream for the page, built only from what the recorder reported.

    A field has `options` (a choice), `min` and `max` (a whole number), a boolean value (a switch) or none of
    those, which means it is shown but cannot be changed: the recorder did not say what it accepts."""
    fields = []

    def add(key, label, value, **extra):
        fields.append({'key': key, 'label': label, 'value': value, **extra})

    def listed(name):
        return [token.strip() for token in caps.get(name, '').split(',') if token.strip()]

    def choice(key, label, value, options):
        if value:
            add(key, label, value, **({'options': options if value in options else [value] + options} if options else {}))

    def number(name):
        match = WHOLE_RE.fullmatch(values.get(name, ''))
        return int(match[1]) if match else None

    choice('compression', 'Codec de vídeo', values.get('Video.Compression'), listed('Video.CompressionTypes'))
    width, height = number('Video.Width'), number('Video.Height')
    if width and height:
        sizes, unknown = [], []
        for token in listed('Video.ResolutionTypes'):
            found = size(token, standard)
            if found is None:
                unknown.append(token)
            elif found not in sizes:
                sizes.append(found)
        choice('resolution', 'Resolução', f'{width}x{height}', sizes)
        fields[-1]['unsupported'] = unknown
    fps = number('Video.FPS')
    if fps:  # below 1 the recorder means seconds per frame; that is left alone
        add('fps', 'Quadros por segundo', fps, min=1, max=max(fps, number_in(caps.get('Video.FPSMax')) or 30))
    choice('bitrate_control', 'Controle de bitrate', values.get('Video.BitRateControl'), ['CBR', 'VBR'])
    bitrate = number('Video.BitRate')
    if bitrate is not None:
        limits = [number_in(text) for text in caps.get('Video.BitRateOptions', '').split(',')]
        ranged = len(limits) == 2 and None not in limits and limits[0] <= limits[1]
        add('bitrate', 'Bitrate', bitrate, unit='kbps',
            **({'min': min(bitrate, limits[0]), 'max': max(bitrate, limits[1])} if ranged else {}))
    quality = number('Video.Quality')
    if quality:
        add('quality', 'Qualidade (só em VBR)', quality, min=1, max=max(quality, number('Video.QualityRange') or 6))
    gop = number('Video.GOP')
    if gop:
        add('gop', 'Intervalo de quadros-chave', gop, min=1, max=max(gop, 150))
    if 'AudioEnable' in values:
        add('audio', 'Áudio', values['AudioEnable'].lower() in ('true', '1'))
    choice('audio_compression', 'Codec de áudio', values.get('Audio.Compression'), listed('Audio.CompressionTypes'))
    return fields


def number_in(text):
    match = WHOLE_RE.fullmatch((text or '').strip())
    return int(match[1]) if match else None


def encode_changes(fields, wanted):
    """{setting: text} to write for the values asked by the page, checked against the fields the recorder gave.

    Setting names always come from this add-on; a value is only accepted when it is one of the options or
    inside the limits shown."""
    known = {field['key']: field for field in fields}
    changes = {}
    for key, value in wanted.items():
        field = known.get(key)
        if field is None:
            raise ValueError('Configuração inválida.')
        if value == field['value'] and type(value) is type(field['value']):
            continue
        if type(field['value']) is bool:
            valid = type(value) is bool
        elif 'options' in field:
            valid = type(value) is str and value in field['options']
        else:
            valid = 'min' in field and type(value) is int and field['min'] <= value <= field['max']
        if not valid:
            raise ValueError('Valor não aceito pelo gravador: ' + field['label'] + '.')
        if key == 'resolution':
            changes['Video.Width'], changes['Video.Height'] = value.split('x')
        else:
            changes[ENCODE_SETTINGS[key]] = str(value).lower() if type(value) is bool else str(value)
    return changes


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

    def optional(self, script, **params):
        """Answer of a request the firmware may not have, or '' without it."""
        try:
            return self.call(script, **params)
        except (OSError, ValueError, http.client.HTTPException):
            return ''

    def encode(self, channel):
        """{'main': fields, 'sub': fields} with the video and audio settings of the channel's streams."""
        body = self.call('configManager', action='getConfig', name=f'Encode[{channel - 1}]')
        caps = self.optional('encode', action='getConfigCaps', channel=channel)
        standard = self.optional('configManager', action='getConfig', name='VideoStandard').partition('=')[2].strip().upper()
        forms = {name: encode_form(encode_values(body, channel, head), encode_caps(caps, channel, head), standard)
                 for name, head in ENCODE_STREAMS.items()}
        forms = {name: fields for name, fields in forms.items() if fields}
        if not forms:
            raise ValueError('Este firmware não informou as configurações de vídeo.')
        return forms

    def encode_set(self, channel, stream, wanted):
        """Write the changed values of one stream in a single request; returns what the recorder stored."""
        if stream not in ENCODE_STREAMS or type(wanted) is not dict:
            raise ValueError('Configuração inválida.')
        changes = encode_changes(self.encode(channel).get(stream, []), wanted)
        if not changes:
            raise ValueError('Nenhum valor foi alterado.')
        prefix = f'Encode[{channel - 1}].{ENCODE_STREAMS[stream]}.'
        self.call('configManager', action='setConfig', **{prefix + setting: text for setting, text in changes.items()})
        return self.encode(channel)  # the recorder may adjust other values, such as the bitrate, on its own

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
            if action == 'encode':
                return self.encode(channel)
            if action == 'encode_set':
                return self.encode_set(channel, data['stream'], data['values'])
            if action == 'recordings':
                return self.recordings(channel, date.fromisoformat(data['day']).isoformat())
            raise ValueError('Operação inválida.')
        finally:
            self.lock.release()
