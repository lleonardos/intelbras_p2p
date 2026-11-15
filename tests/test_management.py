import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'intelbras_p2p' / 'bridge'))

import dvr_controls  # noqa: E402
import events  # noqa: E402
import main as bridge  # noqa: E402
import playback  # noqa: E402
import start  # noqa: E402
import urls  # noqa: E402

PROFILE = {'server': 'p2p.example', 'server_port': 8800, 'server_key': 'key', 'password': 'tunnel',
           'remote_ip': '127.0.0.1'}


def options(**recorder):
    base = {'nome': 'sitio', 'serial': 'ABC123', 'usuario': 'admin', 'senha': 'dvr-pass', 'canais_em_uso': '1,3'}
    return {'usuario_rtsp': 'frigate', 'senha_rtsp': 'out-pass',
            'gravadores': [{**base, **recorder}, {**base, 'nome': 'casa', 'serial': 'DEF456'}]}


def test_management_is_off_by_default():
    config = start.configure(options(), PROFILE)
    assert all('management_local_port' not in device for device in config['devices'])
    assert all('T2U_HTTP_LOCAL' not in tunnel for tunnel in bridge.prepare(config)[1])
    assert events.start(config) is None


def test_management_adds_a_second_tunnel_port():
    config = start.configure(options(gerenciamento=True, porta_http=8080), PROFILE)
    first, second = bridge.prepare(config)[1]
    assert (first['T2U_HTTP_LOCAL'], first['T2U_HTTP_REMOTE']) == ('35541', '8080')
    assert 'T2U_HTTP_LOCAL' not in second
    assert start.configure(options(gerenciamento=True), PROFILE)['devices'][0]['management_remote_port'] == 80


@pytest.mark.parametrize('port', [15542, 8554, 9997, 0, '35541'])
def test_prepare_rejects_bad_management_port(port):
    config = start.configure(options(gerenciamento=True), PROFILE)
    config['devices'][0]['management_local_port'] = port
    with pytest.raises(ValueError):
        bridge.prepare(config)


# Lines captured from the event stream of a real recorder.
STREAM = '''--myboundary
Content-Type: text/plain
Content-Length:9

Heartbeat
--myboundary
Content-Type: text/plain
Content-Length:78

Code=VideoMotion;action=Start;index=4;data={
   "SmartMotionEnable" : false
}
Code=VideoMotion;action=Stop;index=8;data={
Code=VideoLoss;action=Start;index=0;data={
Code=VideoBlind;action=Start;index=0;data={
Code=VideoMotion;action=Pulse;index=1
'''


def test_parse_event_reads_code_action_and_channel():
    parsed = [event for event in map(events.parse_event, STREAM.splitlines()) if event]
    assert parsed == [('VideoMotion', 'Start', 5), ('VideoMotion', 'Stop', 9), ('VideoLoss', 'Start', 1),
                      ('VideoBlind', 'Start', 1), ('VideoMotion', 'Pulse', 2)]


def test_parse_indexes_counts_channels_from_one():
    assert events.parse_indexes('channels[0]=2\r\nchannels[1]=4\r\nchannels[2]=15\r\n') == {3, 5, 16}
    assert events.parse_indexes('Error\r\nBad Request!') == set()


def hub():
    sent = []
    return events.Hub({'sitio': [1, 3]}, lambda topic, text: sent.append((topic, text))), sent


def test_hub_publishes_only_configured_channels():
    state, sent = hub()
    state.replace('sitio', 'VideoMotion', {1, 2, 9})
    assert sent == [('intelbras_p2p/sitio/ch1/motion', 'ON'), ('intelbras_p2p/sitio/ch3/motion', 'OFF')]
    del sent[:]
    assert state.change('sitio', 'VideoMotion', 'Start', 2)   # not configured: ignored, but not "unknown"
    state.change('sitio', 'VideoMotion', 'Start', 3)
    state.change('sitio', 'VideoMotion', 'Stop', 1)
    state.change('sitio', 'VideoLoss', 'Start', 1)
    assert sent == [('intelbras_p2p/sitio/ch3/motion', 'ON'), ('intelbras_p2p/sitio/ch1/motion', 'OFF'),
                    ('intelbras_p2p/sitio/ch1/video_loss', 'ON')]
    online, active = state.summary('sitio')
    assert not online and active['VideoMotion'] == [3] and active['VideoLoss'] == [1] and active['SmartMotionHuman'] == []


def test_hub_creates_ai_sensors_on_first_event_and_reports_unknown_codes():
    state, sent = hub()
    assert state.codes('sitio') == ['VideoBlind', 'VideoLoss', 'VideoMotion']
    assert state.change('sitio', 'SmartMotionHuman', 'Start', 3)
    topics = [topic for topic, _ in sent]
    assert topics == ['homeassistant/binary_sensor/intelbras_p2p_sitio/ch3_person/config', 'intelbras_p2p/sitio/ch3/person',
                      'intelbras_p2p/sitio/ch3/person']
    assert [text for _, text in sent[1:]] == ['OFF', 'ON']
    assert json.loads(sent[0][1])['name'] == 'Canal 3 pessoa'
    assert 'SmartMotionHuman' in state.codes('sitio')
    assert not state.add_sensor('sitio', 3, 'SmartMotionHuman') and not state.add_sensor('sitio', 2, 'FaceDetection')
    assert state.change('sitio', 'RecordDelete', 'Pulse', 1) is False   # known channel, no sensor for this code
    assert state.change('sitio', 'RecordDelete', 'Pulse', 9) is True    # other channels are simply ignored


def test_hub_turns_pulse_events_off_by_itself(monkeypatch):
    started = []

    class Timer:
        def __init__(self, seconds, action, args):
            self.seconds, self.action, self.args, self.daemon = seconds, action, args, False

        def start(self):
            started.append(self)

        def cancel(self):
            started.remove(self)

    monkeypatch.setattr(events.threading, 'Timer', Timer)
    state, sent = hub()
    state.change('sitio', 'CrossLineDetection', 'Pulse', 1)
    assert sent[-1] == ('intelbras_p2p/sitio/ch1/line', 'ON') and started[0].seconds == events.PULSE_SECONDS
    state.change('sitio', 'CrossLineDetection', 'Pulse', 1)  # a second pulse replaces the pending switch-off
    assert len(started) == 1
    started[0].action(*started[0].args)
    assert sent[-1] == ('intelbras_p2p/sitio/ch1/line', 'OFF') and state.summary('sitio')[1]['CrossLineDetection'] == []


def test_hub_reports_connection_changes():
    state, sent = hub()
    assert state.set_online('sitio', True) and not state.set_online('sitio', True)
    assert state.set_online('sitio', False)
    assert sent[0] == ('intelbras_p2p/sitio/status', 'online') and sent[-1] == ('intelbras_p2p/sitio/status', 'offline')


def test_hub_publish_all_announces_entities_then_states():
    state, sent = hub()
    state.set_online('sitio', True)
    state.change('sitio', 'VideoMotion', 'Start', 3)
    state.set_value('intelbras_p2p/sitio/ch1/motion_sensitivity', '80')
    del sent[:]
    state.publish_all()
    topics = [topic for topic, _ in sent]
    assert sent[0] == ('intelbras_p2p/status', 'online')
    configs = {topic: json.loads(text) for topic, text in sent if topic.endswith('/config')}
    # Two channels: three event sensors and four controls each, plus four recorder diagnostics.
    assert len(configs) == 18 and len({config['unique_id'] for config in configs.values()}) == 18
    motion = configs['homeassistant/binary_sensor/intelbras_p2p_sitio/ch3_motion/config']
    assert motion['state_topic'] == 'intelbras_p2p/sitio/ch3/motion' and motion['device_class'] == 'motion'
    assert {entry['topic'] for entry in motion['availability']} == {'intelbras_p2p/status', 'intelbras_p2p/sitio/status'}
    switch = configs['homeassistant/switch/intelbras_p2p_sitio/ch1_motion_detection/config']
    assert switch['command_topic'] == switch['state_topic'] + '/set' == 'intelbras_p2p/sitio/ch1/motion_detection/set'
    number = configs['homeassistant/number/intelbras_p2p_sitio/ch3_motion_sensitivity/config']
    assert (number['min'], number['max'], number['entity_category']) == (0, 100, 'config')
    dejitter = configs['homeassistant/number/intelbras_p2p_sitio/ch1_motion_dejitter/config']
    assert (dejitter['max'], dejitter['unit_of_measurement']) == (600, 's') and 'unit_of_measurement' not in number
    assert 'homeassistant/number/intelbras_p2p_sitio/ch3_motion_threshold/config' in configs
    assert configs['homeassistant/sensor/intelbras_p2p_sitio/firmware/config']['entity_category'] == 'diagnostic'
    assert all(config['device']['identifiers'] == ['intelbras_p2p_sitio'] for config in configs.values())
    assert topics.index('intelbras_p2p/sitio/ch3/motion') > max(i for i, topic in enumerate(topics) if topic.endswith('/config'))
    assert ('intelbras_p2p/sitio/ch3/motion', 'ON') in sent and ('intelbras_p2p/sitio/ch1/motion', 'OFF') in sent
    assert ('intelbras_p2p/sitio/status', 'online') in sent and ('intelbras_p2p/sitio/ch1/motion_sensitivity', '80') in sent
    assert 'ABC123' not in json.dumps(sent) and 'dvr-pass' not in json.dumps(sent)


@pytest.mark.parametrize('topic, payload, expected', [
    ('intelbras_p2p/sitio/ch3/motion_detection/set', b'ON', ('sitio', 3, 'motion_detection', True)),
    ('intelbras_p2p/sitio/ch1/motion_detection/set', 'OFF', ('sitio', 1, 'motion_detection', False)),
    ('intelbras_p2p/sitio/ch1/motion_sensitivity/set', b'65', ('sitio', 1, 'motion_sensitivity', 65)),
    ('intelbras_p2p/sitio/ch1/motion_sensitivity/set', b'65.0', ('sitio', 1, 'motion_sensitivity', 65)),
    ('intelbras_p2p/sitio/ch2/motion_detection/set', b'ON', None),            # channel not configured
    ('intelbras_p2p/outro/ch1/motion_detection/set', b'ON', None),            # unknown recorder
    ('intelbras_p2p/sitio/ch1/motion_detection/set', b'on', None),
    ('intelbras_p2p/sitio/ch1/motion_sensitivity/set', b'101', None),
    ('intelbras_p2p/sitio/ch3/motion_threshold/set', b'30', ('sitio', 3, 'motion_threshold', 30)),
    ('intelbras_p2p/sitio/ch3/motion_threshold/set', b'101', None),
    ('intelbras_p2p/sitio/ch1/motion_dejitter/set', b'600', ('sitio', 1, 'motion_dejitter', 600)),
    ('intelbras_p2p/sitio/ch1/motion_dejitter/set', b'601', None),
    ('intelbras_p2p/sitio/ch1/motion_dejitter/set', b'ON', None),
    ('intelbras_p2p/sitio/ch1/motion_sensitivity/set', b'-1', None),
    ('intelbras_p2p/sitio/ch1/motion_sensitivity/set', b'80&Enable=false', None),
    ('intelbras_p2p/sitio/ch1/Enable/set', b'ON', None),
    ('intelbras_p2p/sitio/ch1/motion_detection', b'ON', None),                # the state topic is not a command
    ('intelbras_p2p/sitio/ch1/motion_detection/set/x', b'ON', None),
])
def test_parse_command_accepts_only_fixed_topics_and_strict_values(topic, payload, expected):
    assert events.parse_command(topic, payload, {'sitio': [1, 3]}) == expected


def test_command_ignores_retained_and_unmanaged_messages():
    state, _ = hub()
    asked = []
    managers = {'sitio': type('Manager', (), {'ask': lambda self, task: asked.append(task)})()}
    topic = 'intelbras_p2p/sitio/ch3/motion_sensitivity/set'
    assert not events.command(state, managers, topic, b'70', retained=True)
    assert not events.command(state, {}, topic, b'70', retained=False)
    assert not events.command(state, managers, topic, b'seventy', retained=False)
    assert events.command(state, managers, topic, b'70', retained=False)
    assert asked == [('set', 3, 'motion_sensitivity', 70)]


def test_parse_motion_and_boolean_styles():
    body = ('table.MotionDetect[2].Enable=true\r\ntable.MotionDetect[2].MotionDetectWindow[0].Sensitive=80\r\n'
            'table.MotionDetect[2].MotionDetectWindow[1].Sensitive=10\r\n')
    assert events.parse_motion(body, 3) == {'motion_detection': True, 'motion_sensitivity': 80}
    assert events.parse_motion(body.replace('=true', '=0'), 3) == {'motion_detection': False, 'motion_sensitivity': 80}
    full = body + 'table.MotionDetect[2].MotionDetectWindow[0].Threshold=5\r\ntable.MotionDetect[2].EventHandler.Dejitter=15\r\n'
    assert events.parse_motion(full, 3) == {'motion_detection': True, 'motion_sensitivity': 80, 'motion_threshold': 5,
                                            'motion_dejitter': 15}
    with pytest.raises(ValueError):
        events.parse_motion(body, 1)
    assert [events.truthy(text) for text in ('true', 'True', '1', 'false', '0', '')] == [True, True, True, False, False, False]


def test_enabled_functions_reads_both_recorder_styles():
    rules = ('table.VideoAnalyseRule[5][0].Type=CrossRegionDetection\ntable.VideoAnalyseRule[5][0].Enable=true\n'
             'table.VideoAnalyseRule[0][0].Type=FaceDetection\ntable.VideoAnalyseRule[0][0].Enable=false\n'
             'table.VideoAnalyseRule[2][1].Type=CrossLineDetection\ntable.VideoAnalyseRule[2][1].Enable=true\n'
             'table.VideoAnalyseRule[2][0].Type=SomethingNew\ntable.VideoAnalyseRule[2][0].Enable=true\n')
    smart = 'table.SmartMotionDetect[0].Enable=1\ntable.SmartMotionDetect[2].Enable=false\ntable.SmartMotionDetect[5].Enable=true\n'
    assert events.enabled_functions(rules, smart, [1, 3]) == {
        (3, 'CrossLineDetection'), (1, 'SmartMotionHuman'), (1, 'SmartMotionVehicle')}


class FakeRecorder:
    channels = [1, 3]
    device = {'name': 'sitio'}

    def __init__(self):
        self.table = {1: [True, 80], 3: [False, 55]}
        self.extra = {}
        self.writes = []

    def guarded(self, action, *args):
        return action(*args)

    def status(self):
        return {'model': 'MHDX 1116', 'firmware': '4.0 (2024-10-24)', 'clock': 'x', 'disks': [{'gb': 500, 'error': False}, {'gb': 500, 'error': True}]}

    def config(self, name):
        if name.startswith('MotionDetect['):
            index = int(name[13:-1])
            enabled, sensitivity = self.table[index + 1]
            return (f'table.MotionDetect[{index}].Enable={str(enabled).lower()}\n'
                    f'table.MotionDetect[{index}].MotionDetectWindow[0].Sensitive={sensitivity}\n'
                    f'table.MotionDetect[{index}].MotionDetectWindow[0].Threshold={self.extra.get(("Threshold", index), 0)}\n'
                    f'table.MotionDetect[{index}].EventHandler.Dejitter={self.extra.get(("Dejitter", index), 5)}\n')
        if name == 'VideoAnalyseRule':
            return 'table.VideoAnalyseRule[2][0].Type=CrossLineDetection\ntable.VideoAnalyseRule[2][0].Enable=true\n'
        return ''

    def set_config(self, key, value):
        self.writes.append((key, value))  # the recorder keeps its own value: 77 becomes 75 here
        index = int(key[13:key.index(']')])
        if key.endswith('.Enable'):
            self.table[index + 1][0] = value == 'true'
        elif key.endswith(('.Threshold', '.Dejitter')):
            self.extra[key.rsplit('.', 1)[1], index] = int(value)
        else:
            self.table[index + 1][1] = int(value) // 5 * 5


def test_manager_mirrors_settings_and_applies_commands():
    state, sent = hub()
    recorder = FakeRecorder()
    manager = events.Manager(recorder, state)
    manager.refresh()
    assert ('intelbras_p2p/sitio/firmware', '4.0 (2024-10-24)') in sent and ('intelbras_p2p/sitio/disk_size', '1000') in sent
    assert ('intelbras_p2p/sitio/disk_problem', 'ON') in sent and ('intelbras_p2p/sitio/model', 'MHDX 1116') in sent
    assert ('intelbras_p2p/sitio/ch1/motion_detection', 'ON') in sent and ('intelbras_p2p/sitio/ch3/motion_sensitivity', '55') in sent
    assert 'CrossLineDetection' in state.codes('sitio')
    del sent[:]
    manager.apply(3, 'motion_sensitivity', 77)
    manager.apply(1, 'motion_detection', False)
    assert recorder.writes == [('MotionDetect[2].MotionDetectWindow[0].Sensitive', '77'), ('MotionDetect[0].Enable', 'false')]
    assert ('intelbras_p2p/sitio/ch3/motion_sensitivity', '75') in sent   # what the recorder stored, not what was asked
    assert ('intelbras_p2p/sitio/ch1/motion_detection', 'OFF') in sent
    manager.apply(3, 'motion_threshold', 30)
    manager.apply(1, 'motion_dejitter', 20)
    assert recorder.writes[2:] == [('MotionDetect[2].MotionDetectWindow[0].Threshold', '30'), ('MotionDetect[0].EventHandler.Dejitter', '20')]
    assert ('intelbras_p2p/sitio/ch3/motion_threshold', '30') in sent and ('intelbras_p2p/sitio/ch1/motion_dejitter', '20') in sent


def test_listener_logs_an_unmapped_event_once(capsys):
    state, _ = hub()
    device = start.configure(options(gerenciamento=True), PROFILE)['devices'][0]
    listener = events.Listener(device, state)
    for line in ('Code=NewAiThing;action=Start;index=0', 'Code=NewAiThing;action=Stop;index=0', 'Code=NewAiThing;action=Start;index=7',
                 'Code=VideoMotion;action=Start;index=0', 'Code=RecordDelete;action=Pulse;index=0', 'Heartbeat'):
        listener.handle(line)
    assert capsys.readouterr().out.splitlines() == ['Gravador sitio: evento sem sensor correspondente: NewAiThing (canal 1).']


def test_broker_settings_none_without_supervisor(monkeypatch):
    monkeypatch.delenv('SUPERVISOR_TOKEN', raising=False)
    assert events.broker_settings() is None


def test_firmware_and_disks_parsers():
    assert dvr_controls.firmware('version=4.000.00IB003.0,build:2024-10-24 11:29:28') == '4.000.00IB003.0 (2024-10-24)'
    assert dvr_controls.firmware('version=1.2') == '1.2'
    body = ('list.info[0].Detail[0].IsError=false\r\nlist.info[0].Detail[0].TotalBytes=250000000000.000000\r\n'
            'list.info[0].Detail[1].IsError=true\r\nlist.info[0].Detail[1].TotalBytes=250000000000.000000\r\n'
            'list.info[0].Name=/dev/sda\r\nlist.info[1].Detail[0].IsError=false\r\n'
            'list.info[1].Detail[0].TotalBytes=1000000000000.000000\r\n')
    assert dvr_controls.disks(body) == [(500e9, True), (1000e9, False)]
    assert dvr_controls.disks('Error') == []


def managed_recorder(monkeypatch, answers):
    config = start.configure(options(gerenciamento=True), PROFILE)
    recorder = dvr_controls.Recorder(config['devices'][0])
    monkeypatch.setattr(recorder, 'call', lambda script, **params: answers[params['action']])
    return config, recorder


def test_status_has_no_serial(monkeypatch):
    answers = {'getDeviceType': 'type=MHDX 1116', 'getSoftwareVersion': 'version=4.0,build:2024-10-24 11:29:28',
               'getCurrentTime': 'result=2026-11-15 17:15:06',
               'getDeviceAllInfo': 'list.info[0].Detail[0].IsError=false\nlist.info[0].Detail[0].TotalBytes=1e12'}
    _, recorder = managed_recorder(monkeypatch, answers)
    assert recorder.run({'action': 'status', 'channel': 1}) == {
        'model': 'MHDX 1116', 'firmware': '4.0 (2024-10-24)', 'clock': '2026-11-15 17:15:06',
        'disks': [{'gb': 1000, 'error': False}]}
    with pytest.raises(ValueError):
        recorder.run({'action': 'status', 'channel': 2})


def test_titles_and_rename(monkeypatch):
    sent = []
    answers = {'getConfig': 'table.ChannelTitle[0].Name=Portão\r\ntable.ChannelTitle[1].Name=Fundos\r\n'
                            'table.ChannelTitle[2].Name=Garagem 2\r\n'}
    _, recorder = managed_recorder(monkeypatch, answers)
    assert recorder.run({'action': 'titles', 'channel': 1}) == {1: 'Portão', 3: 'Garagem 2'}
    monkeypatch.setattr(recorder, 'call', lambda script, **params: sent.append(params) or 'OK')
    assert recorder.run({'action': 'rename', 'channel': 3, 'title': ' Rua '}) == 'Rua'
    assert sent == [{'action': 'setConfig', 'ChannelTitle[2].Name': 'Rua'}]
    for title in ('', 'x' * 33, 'a\nb'):
        with pytest.raises(ValueError):
            recorder.run({'action': 'rename', 'channel': 3, 'title': title})
    with pytest.raises(ValueError):
        recorder.run({'action': 'ptz', 'channel': 1, 'direction': 'Reboot'})


def test_live_state_follows_the_hub(monkeypatch):
    monkeypatch.setattr(events, 'HUB', None)
    assert urls.live_state(['sitio']) == {'sitio': {'online': False, 'motion': [], 'loss': [], 'tamper': [], 'smart': []}}
    state = events.Hub({'sitio': [1, 3]})
    monkeypatch.setattr(events, 'HUB', state)
    state.set_online('sitio', True)
    state.change('sitio', 'VideoMotion', 'Start', 3)
    state.change('sitio', 'VideoLoss', 'Start', 1)
    state.change('sitio', 'VideoBlind', 'Start', 3)
    state.change('sitio', 'SmartMotionHuman', 'Start', 1)
    state.change('sitio', 'CrossLineDetection', 'Start', 3)
    assert urls.live_state(['sitio']) == {'sitio': {'online': True, 'motion': [3], 'loss': [1], 'tamper': [3], 'smart': [1, 3]}}


def test_server_state_and_control_endpoints(monkeypatch):
    config = start.configure(options(gerenciamento=True), PROFILE)
    monkeypatch.setattr(urls, 'external_port', lambda: 18554)
    monkeypatch.setattr(events, 'HUB', None)
    monkeypatch.setattr(dvr_controls.Recorder, 'run', lambda self, data: {'echo': data['action']})
    monkeypatch.setattr(dvr_controls.Recorder, 'snapshot', lambda self, channel: b'\xff\xd8ch%d' % channel)
    server = urls.serve(config, port=0)
    base = f'http://127.0.0.1:{server.server_address[1]}/prefix/'
    allowed = {'X-DVR-Control': '1'}

    def request(body, headers=()):
        return bridge.urllib.request.Request(base + 'control', json.dumps(body).encode(),
                                             {'Content-Type': 'application/json', **dict(headers)})
    try:
        with bridge.urllib.request.urlopen(base + 'state', timeout=3) as response:
            assert json.load(response) == {'sitio': {'online': False, 'motion': [], 'loss': [], 'tamper': [], 'smart': []}}
        with bridge.urllib.request.urlopen(base + 'snapshot/sitio_ch3_sub?fresh=1', timeout=3) as response:
            assert response.read() == b'\xff\xd8ch3'
        with bridge.urllib.request.urlopen(request({'device': 'sitio', 'action': 'status'}, allowed), timeout=3) as response:
            assert json.load(response) == {'echo': 'status'}
        with pytest.raises(bridge.urllib.error.HTTPError, match='403'):  # a cross-site form cannot send the header
            bridge.urllib.request.urlopen(request({'device': 'sitio', 'action': 'status'}), timeout=3)
        with pytest.raises(bridge.urllib.error.HTTPError, match='400') as refused:  # recorder without management
            bridge.urllib.request.urlopen(request({'device': 'casa', 'action': 'status'}, allowed), timeout=3)
        assert 'dvr-pass' not in refused.value.read().decode()
    finally:
        server.shutdown()
        server.server_close()


def test_playback_rejects_bad_requests_before_running_ffmpeg(monkeypatch):
    device = start.configure(options(gerenciamento=True), PROFILE)['devices'][0]
    monkeypatch.setattr(playback, 'convert', lambda args: pytest.fail('ffmpeg must not run'))
    for data in ({'channel': 2, 'start': '2026-11-14 12:00:00', 'seconds': 10},
                 {'channel': 1, 'start': '2026-11-14 12:00:00', 'seconds': 31},
                 {'channel': 1, 'start': '2026-11-14T12:00', 'seconds': 10}):
        with pytest.raises(ValueError):
            playback.clip(device, [1, 3], data)


def test_playback_asks_the_recorder_for_a_longer_range(monkeypatch):
    device = start.configure(options(gerenciamento=True), PROFILE)['devices'][0]
    seen = []
    monkeypatch.setattr(playback, 'convert', lambda args: seen.append(args) or False)
    with pytest.raises(ValueError):
        playback.clip(device, [1, 3], {'channel': 3, 'start': '2026-11-14 23:59:50', 'seconds': 30})
    url = seen[0][seen[0].index('-i') + 1]
    assert url.endswith('@127.0.0.1:15541/cam/playback?channel=3&starttime=2026_11_14_23_59_50&endtime=2026_11_15_00_00_22')
    assert seen[0][seen[0].index('-t') + 1] == '30'


@pytest.mark.skipif(not shutil.which('node'), reason='needs Node.js to parse the page script')
def test_managed_page_script_parses(tmp_path):
    html = urls.page(start.configure(options(gerenciamento=True), PROFILE), 18554).decode()
    assert '"managed": true' in html and 'dvr-pass' not in html and 'ABC123' not in html
    script = tmp_path / 'page.js'
    script.write_text(html.split('<script>', 1)[1].split('</script>', 1)[0], encoding='utf-8')
    assert subprocess.run(['node', '--check', str(script)]).returncode == 0
