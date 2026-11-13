import copy
import io
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'intelbras_p2p' / 'bridge'))

import main as bridge  # noqa: E402
import start  # noqa: E402
import urls  # noqa: E402

PROFILE = {'server': 'p2p.example.test', 'server_port': 8800, 'server_key': 'k', 'remote_ip': '127.0.0.1'}


def options(**overrides):
    base = {'usuario_rtsp': 'frigate', 'senha_rtsp': 'out-pass', 'gravadores': [
        {'nome': 'Vila', 'serial': ' ABC123 ', 'usuario': 'admin', 'senha': 'p@ss:/#', 'canais': 2}]}
    base.update(overrides)
    return base


def recorder(**overrides):
    base = copy.deepcopy(options()['gravadores'][0])
    base.update(overrides)
    return base


def test_configure_generates_streams_and_ports():
    config = start.configure(options(gravadores=[recorder(), recorder(nome='casa')]), PROFILE)
    first, second = config['devices']
    assert [s['name'] for s in first['streams']] == ['vila_ch1', 'vila_ch1_sub', 'vila_ch2', 'vila_ch2_sub']
    assert [s['on_demand'] for s in first['streams']] == [False, True, True, True]
    assert first['streams'][1]['path'] == '/cam/realmonitor?channel=1&subtype=1'
    assert first['p2p']['uuid'] == 'ABC123'
    assert (first['p2p']['local_port'], second['p2p']['local_port']) == (15541, 15542)
    assert first['p2p']['remote_port'] == 554
    assert config['output_auth'] == {'username': 'frigate', 'password': 'out-pass'}


@pytest.mark.parametrize('opts', [
    options(senha_rtsp=''),
    options(gravadores=[]),
    options(gravadores=[recorder(nome='câmera')]),
    options(gravadores=[recorder(), recorder(nome=' VILA ')]),
    options(gravadores=[recorder(canais=0)]),
    options(gravadores=[recorder(canais=65)]),
    options(gravadores=[recorder(canais=True)]),
    options(gravadores=[recorder(serial='  ')]),
])
def test_configure_rejects(opts):
    with pytest.raises(ValueError):
        start.configure(opts, PROFILE)


def test_configure_rejects_non_object_profile():
    with pytest.raises(ValueError):
        start.configure(options(), [])


def test_prepare_builds_mediamtx_config():
    media, tunnels = bridge.prepare(start.configure(options(), PROFILE))
    assert media['paths']['vila_ch1'] == {
        'source': 'rtsp://admin:p%40ss%3A%2F%23@127.0.0.1:15541/cam/realmonitor?channel=1&subtype=0',
        'rtspTransport': 'tcp'}
    assert media['paths']['vila_ch2']['sourceOnDemand'] is True
    assert media['rtspAddress'] == ':8554' and media['apiAddress'] == '127.0.0.1:9997'
    assert all(media[server] is False for server in ('rtmp', 'hls', 'webrtc', 'srt', 'moq'))
    assert media['authInternalUsers'][0] == {
        'user': 'frigate', 'pass': 'out-pass', 'permissions': [{'action': 'read'}]}
    assert tunnels == [{'T2U_SERVER': 'p2p.example.test', 'T2U_SERVER_PORT': '8800', 'T2U_SERVER_KEY': 'k',
                        'T2U_REMOTE_IP': '127.0.0.1', 'T2U_UUID': 'ABC123', 'T2U_REMOTE_PORT': '554',
                        'T2U_LOCAL_PORT': '15541'}]
    assert bridge.required_paths(media['paths']) == {'vila_ch1'}


def test_prepare_rtsp_mode_has_no_tunnel():
    media, tunnels = bridge.prepare({
        'output_auth': {'username': 'u', 'password': 'p'},
        'devices': [{'mode': 'rtsp', 'host': 'nvr.lan:554', 'username': 'a', 'password': 'b',
                     'streams': [{'name': 'x', 'path': '/s'}]}]})
    assert tunnels == [] and media['paths']['x']['source'] == 'rtsp://a:b@nvr.lan:554/s'


def mutated(change):
    config = start.configure(options(gravadores=[recorder(), recorder(nome='casa')]), PROFILE)
    change(config)
    return config


@pytest.mark.parametrize('change', [
    lambda c: c['output_auth'].update(username='any'),
    lambda c: c['output_auth'].update(password=''),
    lambda c: c['devices'][0].update(mode='onvif'),
    lambda c: c['devices'][0]['p2p'].update(server='REPLACE_ME'),
    lambda c: c['devices'][0]['p2p'].update(server_port='8800'),
    lambda c: c['devices'][0]['p2p'].update(local_port=8554),
    lambda c: c['devices'][0]['p2p'].update(local_port=9997),
    lambda c: c['devices'][1]['p2p'].update(local_port=15541),
    lambda c: c['devices'][1]['streams'][0].update(name='vila_ch1'),
    lambda c: c['devices'][0]['streams'][0].update(name='bad name'),
    lambda c: c['devices'][0]['streams'][0].update(path='no-slash'),
    lambda c: c['devices'][0]['streams'][0].update(path='/a\r\nb'),
    lambda c: c.update(devices=[]),
])
def test_prepare_rejects(change):
    with pytest.raises(ValueError):
        bridge.prepare(mutated(change))


def test_main_reports_reason_without_secrets(capsys):
    config = mutated(lambda c: c['devices'][0]['p2p'].update(server_key=''))
    assert bridge.main(config) == 2
    out = capsys.readouterr().out
    assert 'server_key' in out and 'ABC123' not in out and 'p@ss' not in out


def api(monkeypatch, pages):
    calls = []

    def urlopen(url, timeout):
        calls.append(url)
        page = int(url.rsplit('=', 1)[1])
        return io.BytesIO(json.dumps({'pageCount': len(pages), 'items': pages[page]}).encode())

    monkeypatch.setattr(bridge.urllib.request, 'urlopen', urlopen)
    return calls


def test_healthy_follows_pages(monkeypatch):
    calls = api(monkeypatch, [[{'name': 'a', 'ready': True}, {'name': 'c', 'ready': False}],
                              [{'name': 'b', 'ready': True}]])
    assert bridge.healthy({'a', 'b'}) is True
    assert len(calls) == 2
    assert bridge.healthy({'a', 'c'}) is False
    assert bridge.healthy({'a'}) is True and len(calls) == 5  # stops once everything is found


def test_healthy_false_when_api_down(monkeypatch):
    def urlopen(url, timeout):
        raise OSError('refused')

    monkeypatch.setattr(bridge.urllib.request, 'urlopen', urlopen)
    assert bridge.healthy({'a'}) is False


def test_load_defaults_and_overrides(tmp_path, monkeypatch):
    monkeypatch.setattr(start, 'PROFILE_FILE', tmp_path / 'profile.json')
    monkeypatch.setattr(start, 'OPTIONS_FILE', tmp_path / 'options.json')
    (tmp_path / 'options.json').write_text(json.dumps(options()))
    p2p = start.load()['devices'][0]['p2p']  # nothing filled in: the SDK defaults apply
    assert (p2p['server_key'], p2p['password']) == (
        start.DEFAULT_PROFILE['server_key'], start.DEFAULT_PROFILE['password'])
    (tmp_path / 'profile.json').write_text('{"server_key": "", "password": ""}')
    with pytest.raises(ValueError, match='chave_p2p, senha_p2p'):
        start.load()
    (tmp_path / 'options.json').write_text(json.dumps(options(chave_p2p=' ui-key ', senha_p2p='ui-pass')))
    p2p = start.load()['devices'][0]['p2p']
    assert (p2p['server_key'], p2p['password']) == ('ui-key', 'ui-pass')
    (tmp_path / 'profile.json').write_text('{"server_key": "file-key", "password": "file-pass"}')
    assert start.load()['devices'][0]['p2p']['server_key'] == 'ui-key'  # the options win over the file
    (tmp_path / 'options.json').write_text(json.dumps(options(chave_p2p='', senha_p2p='')))
    assert start.load()['devices'][0]['p2p']['server_key'] == 'file-key'
    (tmp_path / 'profile.json').write_text('{"server_key": "k", "password": "p", "server_port": 9}')
    config = start.load()
    p2p = config['devices'][0]['p2p']
    assert (p2p['server'], p2p['server_port'], p2p['remote_ip']) == (start.DEFAULT_PROFILE['server'], 9, '127.0.0.1')
    bridge.prepare(config)
    (tmp_path / 'profile.json').write_text('{not json')
    with pytest.raises(ValueError, match='JSON válido'):
        start.load()
    (tmp_path / 'profile.json').write_text('[]')
    with pytest.raises(ValueError, match='objeto JSON'):
        start.load()


def test_wine_prefix_ready(tmp_path, monkeypatch):
    monkeypatch.setenv('WINEPREFIX', str(tmp_path))
    assert bridge.wine_prefix_ready() is False
    (tmp_path / 'system.reg').write_text('')
    assert bridge.wine_prefix_ready() is True


def test_urls_page_lists_streams_without_secrets():
    config = start.configure(options(usuario_rtsp='a</script>', gravadores=[recorder(), recorder(nome='casa')]),
                             PROFILE)
    html = urls.page(config, 18554).decode()
    data = json.loads(html.split('const data = ', 1)[1].split(';\n', 1)[0])
    assert data == {'user': 'a</script>', 'port': 18554, 'recorders': [
        ['vila_ch1', 'vila_ch1_sub', 'vila_ch2', 'vila_ch2_sub'],
        ['casa_ch1', 'casa_ch1_sub', 'casa_ch2', 'casa_ch2_sub']]}
    assert html.count('</script>') == 1
    for secret in ('out-pass', 'p@ss', 'ABC123', 'p2p.example.test'):
        assert secret not in html


def test_urls_external_port(monkeypatch):
    monkeypatch.setenv('SUPERVISOR_TOKEN', 't')
    reply = {'data': {'network': {'8554/tcp': 28554}}}
    monkeypatch.setattr(urls.urllib.request, 'urlopen', lambda request, timeout: io.BytesIO(json.dumps(reply).encode()))
    assert urls.external_port() == 28554
    reply['data']['network']['8554/tcp'] = None  # port disabled in the Network section
    assert urls.external_port() == urls.DEFAULT_EXTERNAL_PORT
    monkeypatch.delenv('SUPERVISOR_TOKEN')
    assert urls.external_port() == urls.DEFAULT_EXTERNAL_PORT


def test_urls_server_only_answers_ingress(monkeypatch):
    config = start.configure(options(), PROFILE)
    monkeypatch.setattr(urls, 'external_port', lambda: 18554)
    server = urls.serve(config, port=0)
    address = f'http://127.0.0.1:{server.server_address[1]}/any/prefix'
    try:
        with bridge.urllib.request.urlopen(address, timeout=3) as response:
            assert response.status == 200 and b'vila_ch1_sub' in response.read()
        monkeypatch.setattr(urls, 'ALLOWED_PEERS', ('172.30.32.2',))
        with pytest.raises(bridge.urllib.error.HTTPError, match='403'):
            bridge.urllib.request.urlopen(address, timeout=3)
    finally:
        server.shutdown()
        server.server_close()
