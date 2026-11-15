"""Motion and video-loss events of recorders with management enabled.

Each recorder gets one long-lived HTTP request to its event stream through the P2P tunnel. The current
state is kept for the ingress panel and, when Home Assistant has an MQTT broker, published as binary
sensors through MQTT discovery. Nothing here touches the video path.
"""
import http.client
import json
import os
import re
import threading
import time
import urllib.error
import urllib.request

SUPERVISOR_MQTT = 'http://supervisor/services/mqtt'
PREFIX = 'intelbras_p2p'
DISCOVERY_PREFIX = 'homeassistant'
# Recorder event code -> (topic key, sensor name, Home Assistant device class).
CODES = {'VideoMotion': ('motion', 'movimento', 'motion'), 'VideoLoss': ('video_loss', 'sem vídeo', 'problem')}
EVENT_RE = re.compile(r'Code=(\w+);action=(Start|Stop);index=(\d+)')
INDEX_RE = re.compile(r'channels\[\d+\]=(\d+)')
HEARTBEAT_SECONDS = 10
READ_TIMEOUT = 35  # a few missed heartbeats mean the tunnel or the recorder went away
FIRST_RETRY_SECONDS = 5
MAX_RETRY_SECONDS = 60


def parse_event(line):
    """(code, started, channel) for a known event line of the stream, else None. Channels count from 1."""
    match = EVENT_RE.search(line)
    if not match or match[1] not in CODES:
        return None
    return match[1], match[2] == 'Start', int(match[3]) + 1


def parse_indexes(body):
    """Channels, counted from 1, listed by eventManager getEventIndexes."""
    return {int(index) + 1 for index in INDEX_RE.findall(body)}


def state_topic(device, channel, code):
    return f'{PREFIX}/{device}/ch{channel}/{CODES[code][0]}'


def discovery(device, channel, code):
    """Topic and payload announcing one binary sensor to Home Assistant."""
    key, label, device_class = CODES[code]
    identity = f'{PREFIX}_{device}_ch{channel}_{key}'
    return f'{DISCOVERY_PREFIX}/binary_sensor/{PREFIX}_{device}/ch{channel}_{key}/config', {
        'name': f'Canal {channel} {label}', 'unique_id': identity,
        'device_class': device_class, 'state_topic': state_topic(device, channel, code),
        'availability': [{'topic': f'{PREFIX}/status'}, {'topic': f'{PREFIX}/{device}/status'}],
        'availability_mode': 'all',
        'device': {'identifiers': [f'{PREFIX}_{device}'], 'name': f'Intelbras {device}', 'manufacturer': 'Intelbras'}}


class Hub:
    """Current event state of every recorder; forwards each change to `publish(topic, text)`."""

    def __init__(self, channels, publish=None):
        self.channels = channels  # recorder name -> configured channels
        self.publish = publish or (lambda topic, text: None)
        self.lock = threading.Lock()
        self.online = {name: False for name in channels}
        self.active = {(name, code): set() for name in channels for code in CODES}

    def set_online(self, device, online):
        with self.lock:
            changed = self.online[device] != online
            self.online[device] = online
        self.publish(f'{PREFIX}/{device}/status', 'online' if online else 'offline')
        return changed

    def replace(self, device, code, channels):
        """Set which channels have the event active, as read when the stream connects."""
        channels = set(channels) & set(self.channels[device])
        with self.lock:
            self.active[device, code] = channels
        for channel in self.channels[device]:
            self.publish(state_topic(device, channel, code), 'ON' if channel in channels else 'OFF')

    def change(self, device, code, started, channel):
        if channel not in self.channels[device]:  # the recorder reports every channel, configured or not
            return
        with self.lock:
            (self.active[device, code].add if started else self.active[device, code].discard)(channel)
        self.publish(state_topic(device, channel, code), 'ON' if started else 'OFF')

    def summary(self, device):
        """(connected, {code: sorted channels}) for the panel."""
        with self.lock:
            return self.online[device], {code: sorted(self.active[device, code]) for code in CODES}

    def publish_all(self):
        """Everything a broker needs after a (re)connection."""
        self.publish(f'{PREFIX}/status', 'online')
        for device, channels in self.channels.items():
            for channel in channels:
                for code in CODES:
                    topic, payload = discovery(device, channel, code)
                    self.publish(topic, json.dumps(payload))
        with self.lock:
            online, active = dict(self.online), {key: set(value) for key, value in self.active.items()}
        for device, channels in self.channels.items():
            self.publish(f'{PREFIX}/{device}/status', 'online' if online[device] else 'offline')
            for code in CODES:
                for channel in channels:
                    self.publish(state_topic(device, channel, code), 'ON' if channel in active[device, code] else 'OFF')


class Listener(threading.Thread):
    """Follows the event stream of one recorder, reconnecting for as long as the add-on runs."""

    def __init__(self, device, hub):
        super().__init__(daemon=True)
        self.name_, self.hub = device['name'], hub
        self.base = 'http://127.0.0.1:' + str(device['management_local_port']) + '/cgi-bin/eventManager.cgi?action='
        # An opener of its own: the digest handler keeps retry state, and panel requests must not wait for this one.
        passwords = urllib.request.HTTPPasswordMgrWithDefaultRealm()
        passwords.add_password(None, self.base, device['username'], device['password'])
        self.http = urllib.request.build_opener(urllib.request.ProxyHandler({}),
                                                urllib.request.HTTPDigestAuthHandler(passwords),
                                                urllib.request.HTTPBasicAuthHandler(passwords))

    def seed(self):
        for code in CODES:
            try:
                with self.http.open(self.base + 'getEventIndexes&code=' + code, timeout=10) as response:
                    body = response.read(65536).decode('utf-8', errors='replace')
            except urllib.error.HTTPError:
                body = ''  # recorders answer with an error when no channel has the event active
            self.hub.replace(self.name_, code, parse_indexes(body))

    def follow(self):
        url = self.base + 'attach&codes=[' + ','.join(CODES) + ']&heartbeat=' + str(HEARTBEAT_SECONDS)
        with self.http.open(url, timeout=READ_TIMEOUT) as response:
            self.seed()
            if self.hub.set_online(self.name_, True):
                print(f'Gravador {self.name_}: eventos conectados.', flush=True)
            for raw in response:
                event = parse_event(raw.decode('utf-8', errors='replace'))
                if event:
                    self.hub.change(self.name_, *event)

    def run(self):
        delay = FIRST_RETRY_SECONDS
        failures = 0
        while True:
            began = time.monotonic()
            try:
                self.follow()
            except (OSError, ValueError, http.client.HTTPException):
                pass
            if self.hub.set_online(self.name_, False):
                failures = 0
                print(f'Gravador {self.name_}: eventos desconectados; tentando de novo.', flush=True)
            failures += 1
            if failures == 5:  # about two minutes without ever reaching the recorder's HTTP interface
                print(f'Gravador {self.name_}: sem acesso ao gerenciamento; confira porta_http e as permissões '
                      'do usuário.', flush=True)
            # A stream that lasted a while was a real connection: start over with the short wait.
            delay = FIRST_RETRY_SECONDS if time.monotonic() - began > MAX_RETRY_SECONDS else min(delay * 2, MAX_RETRY_SECONDS)
            time.sleep(delay)


def broker_settings():
    """MQTT broker offered by Home Assistant to this add-on, or None when there is none."""
    try:
        request = urllib.request.Request(
            SUPERVISOR_MQTT, headers={'Authorization': 'Bearer ' + os.environ['SUPERVISOR_TOKEN']})
        with urllib.request.urlopen(request, timeout=5) as response:
            data = json.load(response)['data']
        return data if data.get('host') else None
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return None


def connect(settings, hub):
    """Start the MQTT client in the background and send every change of `hub` to it, retained."""
    import paho.mqtt.client as mqtt  # only present in the add-on image
    client = mqtt.Client(client_id=PREFIX)
    if settings.get('username'):
        client.username_pw_set(settings['username'], settings.get('password') or None)
    if settings.get('ssl'):
        client.tls_set()
    client.will_set(f'{PREFIX}/status', 'offline', retain=True)
    hub.publish = lambda topic, text: client.publish(topic, text, retain=True)
    # Also runs after every reconnection, so a broker restart gets the sensors back.
    client.on_connect = lambda *_: hub.publish_all()
    client.connect_async(settings['host'], int(settings.get('port') or 1883), keepalive=60)
    client.loop_start()
    return client


HUB = None  # set by start(); read by the panel


def start(config):
    """Start one listener per recorder with management enabled. Returns the hub, or None without any."""
    global HUB
    devices = [device for device in config['devices'] if 'management_local_port' in device]
    if not devices:
        return None
    channels = {device['name']: sorted({int(stream['name'].rsplit('_ch', 1)[1].split('_')[0])
                                        for stream in device['streams']}) for device in devices}
    HUB = hub = Hub(channels)
    settings = broker_settings()
    try:
        if settings is None:
            raise OSError()
        connect(settings, hub)
        print('Eventos dos gravadores: publicados como sensores no MQTT do Home Assistant.', flush=True)
    except (ImportError, OSError, ValueError, KeyError, TypeError):
        print('Eventos dos gravadores: sem MQTT no Home Assistant; visíveis apenas na interface web.', flush=True)
    for device in devices:
        Listener(device, hub).start()
    return hub
