"""Events, diagnostics and a few settings of recorders with management enabled, mirrored to MQTT.

Each recorder gets one long-lived HTTP request to its event stream through the P2P tunnel. The current
state is kept for the ingress page and, when Home Assistant has an MQTT broker, published through MQTT
discovery: binary sensors for events, diagnostic sensors for the recorder and controls for motion
detection. Nothing here touches the video path.
"""
import http.client
import json
import os
import queue
import re
import threading
import time
import urllib.error
import urllib.request

SUPERVISOR_MQTT = 'http://supervisor/services/mqtt'
PREFIX = 'intelbras_p2p'
DISCOVERY_PREFIX = 'homeassistant'
# Recorder event code -> (topic key, sensor name, Home Assistant device class).
CODES = {
    'VideoMotion': ('motion', 'movimento', 'motion'),
    'VideoLoss': ('video_loss', 'sem vídeo', 'problem'),
    'VideoBlind': ('tamper', 'câmera tampada', 'tamper'),
    'SmartMotionHuman': ('person', 'pessoa', 'occupancy'),
    'SmartMotionVehicle': ('vehicle', 'veículo', 'occupancy'),
    'CrossLineDetection': ('line', 'linha virtual', 'motion'),
    'CrossRegionDetection': ('region', 'cerca virtual', 'motion'),
    'FaceDetection': ('face', 'face', 'occupancy'),
}
# Every configured channel gets these; the others appear when the recorder has the function enabled on the
# channel or the first time the event arrives, so recorders without them do not get dozens of dead entities.
BASE_CODES = ('VideoMotion', 'VideoLoss', 'VideoBlind')
# Settings that can be changed from Home Assistant: key -> (entity type, name).
CONTROLS = {'motion_detection': ('switch', 'detecção de movimento'),
            'motion_sensitivity': ('number', 'sensibilidade de movimento')}
EVENT_RE = re.compile(r'Code=(\w+);action=(Start|Stop|Pulse);index=(\d+)')
INDEX_RE = re.compile(r'channels\[\d+\]=(\d+)')
COMMAND_RE = re.compile(re.escape(PREFIX) + r'/([a-z0-9_-]+)/ch(\d{1,2})/(' + '|'.join(CONTROLS) + ')/set')
HEARTBEAT_SECONDS = 10
READ_TIMEOUT = 35  # a few missed heartbeats mean the tunnel or the recorder went away
FIRST_RETRY_SECONDS = 5
MAX_RETRY_SECONDS = 60
# Housekeeping events every recorder sends; not worth a sensor nor a log line.
ROUTINE_CODES = frozenset({'RecordDelete', 'NewFile', 'TimeChange', 'NTPAdjustTime', 'SystemState'})
PULSE_SECONDS = 10  # how long a sensor stays on for an event that has no end
REFRESH_SECONDS = 1800


def parse_event(line):
    """(code, action, channel) for an event line of the stream, else None. Channels count from 1."""
    match = EVENT_RE.search(line)
    return (match[1], match[2], int(match[3]) + 1) if match else None


def parse_indexes(body):
    """Channels, counted from 1, listed by eventManager getEventIndexes."""
    return {int(index) + 1 for index in INDEX_RE.findall(body)}


def truthy(text):
    """Recorders write booleans as true/false or 1/0 depending on the firmware."""
    return str(text).strip().lower() in ('true', '1')


def parse_motion(body, channel):
    """(enabled, sensitivity) of one channel from configManager getConfig MotionDetect[channel - 1]."""
    prefix = re.escape(f'MotionDetect[{channel - 1}].')
    enable = re.search(prefix + r'Enable=(\S+)', body)
    sensitive = re.search(prefix + r'MotionDetectWindow\[0\]\.Sensitive=(\d+)', body)
    if not enable or not sensitive:
        raise ValueError('MotionDetect')
    return truthy(enable[1]), int(sensitive[1])


def enabled_functions(rules, smart, channels):
    """{(channel, code)} of AI functions switched on in VideoAnalyseRule and SmartMotionDetect."""
    found = set()
    kinds = dict(((int(c) + 1, int(r)), kind) for c, r, kind in re.findall(r'VideoAnalyseRule\[(\d+)\]\[(\d+)\]\.Type=(\S+)', rules))
    for channel, rule, value in re.findall(r'VideoAnalyseRule\[(\d+)\]\[(\d+)\]\.Enable=(\S+)', rules):
        code = kinds.get((int(channel) + 1, int(rule)))
        if truthy(value) and code in CODES:
            found.add((int(channel) + 1, code))
    for channel, value in re.findall(r'SmartMotionDetect\[(\d+)\]\.Enable=(\S+)', smart):
        if truthy(value):
            found.update({(int(channel) + 1, 'SmartMotionHuman'), (int(channel) + 1, 'SmartMotionVehicle')})
    return {item for item in found if item[0] in channels}


def parse_command(topic, payload, channels):
    """(device, channel, control, value) for a valid command message, else None.

    Only fixed topics of configured channels with strict payloads get through; nothing from the message is
    ever used as a recorder setting name."""
    match = COMMAND_RE.fullmatch(topic)
    if not match or int(match[2]) not in channels.get(match[1], ()):
        return None
    text = payload.decode('ascii', errors='replace').strip() if isinstance(payload, bytes) else str(payload).strip()
    if match[3] == 'motion_detection':
        if text not in ('ON', 'OFF'):
            return None
        value = text == 'ON'
    else:
        if not re.fullmatch(r'\d{1,3}(\.0+)?', text) or not 0 <= int(float(text)) <= 100:
            return None
        value = int(float(text))
    return match[1], int(match[2]), match[3], value


def device_block(device):
    return {'identifiers': [f'{PREFIX}_{device}'], 'name': f'Intelbras {device}', 'manufacturer': 'Intelbras'}


def availability(device):
    return {'availability': [{'topic': f'{PREFIX}/status'}, {'topic': f'{PREFIX}/{device}/status'}], 'availability_mode': 'all'}


def state_topic(device, channel, key):
    return f'{PREFIX}/{device}/ch{channel}/{key}'


def discovery(device, channel, code):
    """Topic and payload announcing one event binary sensor to Home Assistant."""
    key, label, device_class = CODES[code]
    return f'{DISCOVERY_PREFIX}/binary_sensor/{PREFIX}_{device}/ch{channel}_{key}/config', {
        'name': f'Canal {channel} {label}', 'unique_id': f'{PREFIX}_{device}_ch{channel}_{key}',
        'device_class': device_class, 'state_topic': state_topic(device, channel, key),
        **availability(device), 'device': device_block(device)}


def control_discovery(device, channel, control):
    """Topic and payload announcing one setting (switch or number) of a channel."""
    kind, label = CONTROLS[control]
    topic = state_topic(device, channel, control)
    payload = {'name': f'Canal {channel} {label}', 'unique_id': f'{PREFIX}_{device}_ch{channel}_{control}',
               'state_topic': topic, 'command_topic': topic + '/set', 'entity_category': 'config',
               **availability(device), 'device': device_block(device)}
    if kind == 'number':
        payload.update(min=0, max=100, step=1, mode='box')
    return f'{DISCOVERY_PREFIX}/{kind}/{PREFIX}_{device}/ch{channel}_{control}/config', payload


def diagnostics_discovery(device):
    """Recorder-level diagnostic entities: firmware, disk size and disk problem."""
    def entity(kind, key, name, **extra):
        return f'{DISCOVERY_PREFIX}/{kind}/{PREFIX}_{device}/{key}/config', {
            'name': name, 'unique_id': f'{PREFIX}_{device}_{key}', 'state_topic': f'{PREFIX}/{device}/{key}',
            'entity_category': 'diagnostic', **extra, **availability(device), 'device': device_block(device)}
    return [entity('sensor', 'firmware', 'Firmware'), entity('sensor', 'model', 'Modelo'),
            entity('sensor', 'disk_size', 'Capacidade dos discos', unit_of_measurement='GB', device_class='data_size'),
            entity('binary_sensor', 'disk_problem', 'Problema nos discos', device_class='problem')]


class Hub:
    """Current state of every recorder; forwards each change to `publish(topic, text)`."""

    def __init__(self, channels, publish=None):
        self.channels = channels  # recorder name -> configured channels
        self.publish = publish or (lambda topic, text: None)
        self.lock = threading.Lock()
        self.online = {name: False for name in channels}
        self.sensors = {name: {(channel, code) for channel in numbers for code in BASE_CODES}
                        for name, numbers in channels.items()}
        self.active = {name: set() for name in channels}  # (channel, code) currently on
        self.values = {}  # state topic -> text, for controls and diagnostics
        self.timers = {}

    def set_online(self, device, online):
        with self.lock:
            changed = self.online[device] != online
            self.online[device] = online
        self.publish(f'{PREFIX}/{device}/status', 'online' if online else 'offline')
        return changed

    def add_sensor(self, device, channel, code):
        """Announce an event sensor that is not part of the base set. Returns whether it was new."""
        if channel not in self.channels[device] or code not in CODES:
            return False
        with self.lock:
            new = (channel, code) not in self.sensors[device]
            self.sensors[device].add((channel, code))
        if new:
            topic, payload = discovery(device, channel, code)
            self.publish(topic, json.dumps(payload))
            self.publish(state_topic(device, channel, CODES[code][0]), 'OFF')
        return new

    def codes(self, device):
        with self.lock:
            return sorted({code for _, code in self.sensors[device]})

    def replace(self, device, code, channels):
        """Set which channels have the event active, as read when the stream connects."""
        with self.lock:
            mine = sorted(channel for channel, known in self.sensors[device] if known == code)
            self.active[device] = {item for item in self.active[device] if item[1] != code} | {
                (channel, code) for channel in mine if channel in channels}
        for channel in mine:
            self.publish(state_topic(device, channel, CODES[code][0]), 'ON' if channel in channels else 'OFF')

    def change(self, device, code, action, channel):
        """Apply one event. Returns False for an event of a configured channel that has no sensor type."""
        if channel not in self.channels[device]:  # the recorder reports every channel, configured or not
            return True
        if code not in CODES:
            return False
        self.add_sensor(device, channel, code)
        started = action != 'Stop'
        with self.lock:
            (self.active[device].add if started else self.active[device].discard)((channel, code))
            timer = self.timers.pop((device, channel, code), None)
        if timer:
            timer.cancel()
        self.publish(state_topic(device, channel, CODES[code][0]), 'ON' if started else 'OFF')
        if action == 'Pulse':  # no Stop will follow
            timer = threading.Timer(PULSE_SECONDS, self.change, (device, code, 'Stop', channel))
            timer.daemon = True
            with self.lock:
                self.timers[device, channel, code] = timer
            timer.start()
        return True

    def set_value(self, topic, text):
        """Publish and remember a control or diagnostic value."""
        with self.lock:
            self.values[topic] = text
        self.publish(topic, text)

    def summary(self, device):
        """(connected, {code: sorted channels}) for the page."""
        with self.lock:
            active = {code: sorted(channel for channel, known in self.active[device] if known == code) for code in CODES}
            return self.online[device], active

    def publish_all(self):
        """Everything a broker needs after a (re)connection."""
        self.publish(f'{PREFIX}/status', 'online')
        with self.lock:
            online, values = dict(self.online), dict(self.values)
            sensors = {name: sorted(items) for name, items in self.sensors.items()}
            active = {name: set(items) for name, items in self.active.items()}
        for device, channels in self.channels.items():
            configs = [discovery(device, channel, code) for channel, code in sensors[device]]
            configs += [control_discovery(device, channel, control) for channel in channels for control in CONTROLS]
            configs += diagnostics_discovery(device)
            for topic, payload in configs:
                self.publish(topic, json.dumps(payload))
        for device in self.channels:
            self.publish(f'{PREFIX}/{device}/status', 'online' if online[device] else 'offline')
            for channel, code in sensors[device]:
                self.publish(state_topic(device, channel, CODES[code][0]), 'ON' if (channel, code) in active[device] else 'OFF')
        for topic, text in values.items():
            self.publish(topic, text)


class Manager(threading.Thread):
    """Reads recorder settings into the hub and applies commands, one at a time, away from the MQTT thread."""

    def __init__(self, recorder, hub):
        super().__init__(daemon=True)
        self.recorder, self.hub, self.device = recorder, hub, recorder.device['name']
        self.tasks = queue.Queue(maxsize=50)

    def ask(self, task):
        try:
            self.tasks.put_nowait(task)
        except queue.Full:
            pass

    def read_motion(self, channel):
        enabled, sensitivity = parse_motion(self.recorder.config(f'MotionDetect[{channel - 1}]'), channel)
        self.hub.set_value(state_topic(self.device, channel, 'motion_detection'), 'ON' if enabled else 'OFF')
        self.hub.set_value(state_topic(self.device, channel, 'motion_sensitivity'), str(sensitivity))

    def refresh(self):
        status = self.recorder.guarded(self.recorder.status)
        found = status['disks']
        self.hub.set_value(f'{PREFIX}/{self.device}/firmware', status['firmware'])
        self.hub.set_value(f'{PREFIX}/{self.device}/model', status['model'])
        self.hub.set_value(f'{PREFIX}/{self.device}/disk_size', str(sum(disk['gb'] for disk in found)))
        self.hub.set_value(f'{PREFIX}/{self.device}/disk_problem', 'ON' if not found or any(d['error'] for d in found) else 'OFF')
        for channel in self.recorder.channels:
            self.read_motion(channel)
        functions = enabled_functions(self.recorder.config('VideoAnalyseRule'), self.recorder.config('SmartMotionDetect'),
                                      self.recorder.channels)
        for channel, code in sorted(functions):
            self.hub.add_sensor(self.device, channel, code)

    def apply(self, channel, control, value):
        index = channel - 1
        if control == 'motion_detection':
            self.recorder.set_config(f'MotionDetect[{index}].Enable', 'true' if value else 'false')
        else:
            self.recorder.set_config(f'MotionDetect[{index}].MotionDetectWindow[0].Sensitive', str(value))
        self.read_motion(channel)  # the entity shows what the recorder stored, never what was asked

    def run(self):
        while True:
            try:
                task = self.tasks.get(timeout=REFRESH_SECONDS)
            except queue.Empty:
                task = ('refresh',)
            try:
                if task[0] == 'refresh':
                    self.refresh()
                else:
                    self.apply(*task[1:])
            except (OSError, ValueError, KeyError, http.client.HTTPException):
                pass  # the next refresh, on reconnection or on the timer, brings the values back


class Listener(threading.Thread):
    """Follows the event stream of one recorder, reconnecting for as long as the add-on runs."""

    def __init__(self, device, hub, manager=None):
        super().__init__(daemon=True)
        self.name_, self.hub, self.manager = device['name'], hub, manager
        self.unknown = set()
        self.base = 'http://127.0.0.1:' + str(device['management_local_port']) + '/cgi-bin/eventManager.cgi?action='
        # An opener of its own: the digest handler keeps retry state, and panel requests must not wait for this one.
        passwords = urllib.request.HTTPPasswordMgrWithDefaultRealm()
        passwords.add_password(None, self.base, device['username'], device['password'])
        self.http = urllib.request.build_opener(urllib.request.ProxyHandler({}),
                                                urllib.request.HTTPDigestAuthHandler(passwords),
                                                urllib.request.HTTPBasicAuthHandler(passwords))

    def seed(self):
        for code in self.hub.codes(self.name_):
            try:
                with self.http.open(self.base + 'getEventIndexes&code=' + code, timeout=10) as response:
                    body = response.read(65536).decode('utf-8', errors='replace')
            except urllib.error.HTTPError:
                body = ''  # recorders answer with an error when no channel has the event active
            self.hub.replace(self.name_, code, parse_indexes(body))

    def handle(self, line):
        event = parse_event(line)
        if not event or event[0] in ROUTINE_CODES:
            return
        if not self.hub.change(self.name_, *event) and event[0] not in self.unknown:
            # Shown once per kind, so an AI event this add-on does not know yet is visible instead of lost.
            self.unknown.add(event[0])
            print(f'Gravador {self.name_}: evento sem sensor correspondente: {event[0]} (canal {event[2]}).', flush=True)

    def follow(self):
        with self.http.open(self.base + 'attach&codes=[All]&heartbeat=' + str(HEARTBEAT_SECONDS), timeout=READ_TIMEOUT) as response:
            self.seed()
            if self.hub.set_online(self.name_, True):
                print(f'Gravador {self.name_}: eventos conectados.', flush=True)
            if self.manager:
                self.manager.ask(('refresh',))
            for raw in response:
                self.handle(raw.decode('utf-8', errors='replace'))

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


def command(hub, managers, topic, payload, retained):
    """Route one MQTT message to the manager of its recorder. Returns whether it was accepted."""
    if retained:  # a stored command would be replayed to the recorder on every reconnection
        return False
    parsed = parse_command(topic, payload, hub.channels)
    if not parsed or parsed[0] not in managers:
        return False
    managers[parsed[0]].ask(('set',) + parsed[1:])
    return True


def connect(settings, hub, managers):
    """Start the MQTT client in the background: every change of `hub` goes out retained, commands come in."""
    import paho.mqtt.client as mqtt  # only present in the add-on image
    client = mqtt.Client(client_id=PREFIX)
    if settings.get('username'):
        client.username_pw_set(settings['username'], settings.get('password') or None)
    if settings.get('ssl'):
        client.tls_set()
    client.will_set(f'{PREFIX}/status', 'offline', retain=True)
    hub.publish = lambda topic, text: client.publish(topic, text, retain=True)

    def connected(*_):  # also runs after every reconnection, so a broker restart gets everything back
        client.subscribe(f'{PREFIX}/+/+/+/set')
        hub.publish_all()

    client.on_connect = connected
    client.on_message = lambda _client, _data, message: command(hub, managers, message.topic, message.payload, message.retain)
    client.connect_async(settings['host'], int(settings.get('port') or 1883), keepalive=60)
    client.loop_start()
    return client


HUB = None  # set by start(); read by the page


def start(config, recorders=None):
    """Start the listeners of recorders with management enabled. Returns the hub, or None without any.

    `recorders` maps names to dvr_controls.Recorder objects; with them, settings and diagnostics are
    mirrored too."""
    global HUB
    devices = [device for device in config['devices'] if 'management_local_port' in device]
    if not devices:
        return None
    channels = {device['name']: sorted({int(stream['name'].rsplit('_ch', 1)[1].split('_')[0])
                                        for stream in device['streams']}) for device in devices}
    HUB = hub = Hub(channels)
    managers = {name: Manager(recorder, hub) for name, recorder in (recorders or {}).items() if name in channels}
    settings = broker_settings()
    try:
        if settings is None:
            raise OSError()
        connect(settings, hub, managers)
        print('Eventos dos gravadores: publicados como sensores no MQTT do Home Assistant.', flush=True)
    except (ImportError, OSError, ValueError, KeyError, TypeError):
        print('Eventos dos gravadores: sem MQTT no Home Assistant; visíveis apenas na interface web.', flush=True)
    for manager in managers.values():
        manager.start()
    for device in devices:
        Listener(device, hub, managers.get(device['name'])).start()
    return hub
