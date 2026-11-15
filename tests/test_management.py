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


def test_parse_event_keeps_known_start_and_stop_lines():
    parsed = [event for event in map(events.parse_event, STREAM.splitlines()) if event]
    assert parsed == [('VideoMotion', True, 5), ('VideoMotion', False, 9), ('VideoLoss', True, 1)]


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
    state.change('sitio', 'VideoMotion', True, 2)   # not configured: ignored
    state.change('sitio', 'VideoMotion', True, 3)
    state.change('sitio', 'VideoMotion', False, 1)
    state.change('sitio', 'VideoLoss', True, 1)
    assert sent == [('intelbras_p2p/sitio/ch3/motion', 'ON'), ('intelbras_p2p/sitio/ch1/motion', 'OFF'),
                    ('intelbras_p2p/sitio/ch1/video_loss', 'ON')]
    assert state.summary('sitio') == (False, {'VideoMotion': [3], 'VideoLoss': [1]})


def test_hub_reports_connection_changes():
    state, sent = hub()
    assert state.set_online('sitio', True) and not state.set_online('sitio', True)
    assert state.set_online('sitio', False)
    assert sent[0] == ('intelbras_p2p/sitio/status', 'online') and sent[-1] == ('intelbras_p2p/sitio/status', 'offline')


def test_hub_publish_all_announces_sensors_then_states():
    state, sent = hub()
    state.set_online('sitio', True)
    state.change('sitio', 'VideoMotion', True, 3)
    del sent[:]
    state.publish_all()
    topics = [topic for topic, _ in sent]
    assert sent[0] == ('intelbras_p2p/status', 'online')
    configs = [json.loads(text) for topic, text in sent if topic.endswith('/config')]
    assert len(configs) == 4 and len({config['unique_id'] for config in configs}) == 4
    motion = next(config for config in configs if config['unique_id'] == 'intelbras_p2p_sitio_ch3_motion')
    assert motion['state_topic'] == 'intelbras_p2p/sitio/ch3/motion' and motion['device_class'] == 'motion'
    assert {entry['topic'] for entry in motion['availability']} == {'intelbras_p2p/status', 'intelbras_p2p/sitio/status'}
    assert topics.index('intelbras_p2p/sitio/ch3/motion') > max(i for i, topic in enumerate(topics) if topic.endswith('/config'))
    assert ('intelbras_p2p/sitio/ch3/motion', 'ON') in sent and ('intelbras_p2p/sitio/ch1/motion', 'OFF') in sent
    assert ('intelbras_p2p/sitio/status', 'online') in sent
    assert 'ABC123' not in json.dumps(sent) and 'dvr-pass' not in json.dumps(sent)


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


def test_status_text_has_no_serial(monkeypatch):
    config = start.configure(options(gerenciamento=True), PROFILE)
    recorder = dvr_controls.Recorder(config['devices'][0])
    answers = {'getDeviceType': 'type=MHDX 1116', 'getSoftwareVersion': 'version=4.0,build:2024-10-24 11:29:28',
               'getCurrentTime': 'result=2026-11-15 17:15:06',
               'getDeviceAllInfo': 'list.info[0].Detail[0].IsError=false\nlist.info[0].Detail[0].TotalBytes=1e12'}
    monkeypatch.setattr(recorder, 'call', lambda script, **params: answers[params['action']])
    state = events.Hub({'sitio': [1, 3]})
    monkeypatch.setattr(events, 'HUB', state)
    text = recorder.run({'action': 'status', 'channel': 1})
    assert text.splitlines() == ['Modelo: MHDX 1116', 'Firmware: 4.0 (2024-10-24)', 'Relógio do DVR: 2026-11-15 17:15:06',
                                 'Disco 1: 1000 GB, sem erro', 'Eventos: sem conexão com o gravador']
    state.set_online('sitio', True)
    state.change('sitio', 'VideoMotion', True, 3)
    assert recorder.run({'action': 'status', 'channel': 1}).splitlines()[-2:] == [
        'Canais com movimento agora: 3', 'Canais sem vídeo agora: nenhum']
    with pytest.raises(ValueError):
        recorder.run({'action': 'status', 'channel': 2})


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


@pytest.mark.skipif(not shutil.which('node'), reason='needs Node.js to parse the panel script')
def test_panel_script_parses(tmp_path):
    config = start.configure(options(gerenciamento=True), PROFILE)
    html = dvr_controls.panel({'sitio': dvr_controls.Recorder(config['devices'][0])})
    assert 'data-op="status"' in html and 'dvr-pass' not in html and 'ABC123' not in html
    script = tmp_path / 'panel.js'
    script.write_text(html.split('<script>', 1)[1].split('</script>', 1)[0], encoding='utf-8')
    assert subprocess.run(['node', '--check', str(script)]).returncode == 0
    assert dvr_controls.panel({}) == ''
