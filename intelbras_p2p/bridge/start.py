import json
import os
import re
import sys
from pathlib import Path

import main as bridge
import urls

OPTIONS_FILE = Path('/data/options.json')
PROFILE_FILE = Path('/config/profile.json')
FIRST_LOCAL_PORT = 15541
# Intelbras Cloud relay settings from the vendor SDK, the same for every recorder. The add-on
# options (key and password) or an optional profile.json in the add-on config folder override them.
DEFAULT_PROFILE = {
    'server': 'intelbrasp2p.com.br',
    'server_port': 1250,
    'server_key': 'p2pintelbras2014543',
    'password': 'tesT91534',
    'remote_ip': '127.0.0.1',
}
PROFILE_SECRETS = {'server_key': 'chave_p2p', 'password': 'senha_p2p'}  # profile key -> add-on option
NAME_RE = re.compile(r'[a-z0-9_-]+')
CHANNELS_RE = re.compile(r'[0-9]+(-[0-9]+)?')
MAX_CHANNEL = 64


def channel_list(recorder):
    """Channels to expose: the `canais_em_uso` list (such as "1,2,5-8") or, without it, 1 to `canais`."""
    text = str(recorder.get('canais_em_uso') or '').replace(' ', '')
    if not text:
        count = recorder.get('canais')
        if type(count) is not int or not 1 <= count <= MAX_CHANNEL:
            raise ValueError('Informe os canais em uso (por exemplo, 1,2,5-8) ou de 1 a 64 canais por gravador.')
        return list(range(1, count + 1))
    channels = set()
    for part in text.split(','):
        first, _, last = part.partition('-')
        if not CHANNELS_RE.fullmatch(part) or not 1 <= int(first) <= int(last or first) <= MAX_CHANNEL:
            raise ValueError('Canais em uso: use números de 1 a 64 separados por vírgula, como 1,2,5-8.')
        channels.update(range(int(first), int(last or first) + 1))
    return sorted(channels)


def configure(options, profile):
    devices = []
    names = set()
    if not options.get('senha_rtsp') or not options.get('gravadores'):
        raise ValueError('Preencha a senha RTSP e adicione um gravador na aba Configuração.')
    if not isinstance(profile, dict):
        raise ValueError('O profile.json deve conter um objeto JSON.')
    for index, recorder in enumerate(options['gravadores']):
        name = recorder['nome'].strip().lower()
        if not NAME_RE.fullmatch(name) or name in names:
            raise ValueError('Cada nome deve ser único e usar letras sem acentos, números, hífen ou sublinhado.')
        names.add(name)
        channels = channel_list(recorder)
        if not all(recorder[key].strip() for key in ('serial', 'usuario', 'senha')):
            raise ValueError('Preencha o serial, o usuário e a senha de cada gravador.')
        streams = []
        for channel in channels:
            for subtype, suffix in ((0, ''), (1, '_sub')):
                # The main stream of the first channel stays connected to keep the recorder tunnel alive.
                streams.append({'name': f'{name}_ch{channel}{suffix}',
                                'path': f'/cam/realmonitor?channel={channel}&subtype={subtype}',
                                'on_demand': channel != channels[0] or subtype != 0})
        devices.append({'mode': 'p2p', 'name': name, 'username': recorder['usuario'], 'password': recorder['senha'],
                        'p2p': {**profile, 'uuid': recorder['serial'].strip(), 'remote_port': 554,
                                'local_port': FIRST_LOCAL_PORT + index}, 'streams': streams})
    return {'output_auth': {'username': options['usuario_rtsp'], 'password': options['senha_rtsp']},
            'devices': devices}


def load():
    try:
        override = json.loads(PROFILE_FILE.read_text())
    except FileNotFoundError:
        override = {}
    except ValueError:
        raise ValueError('O profile.json não é um JSON válido.') from None
    if not isinstance(override, dict):
        raise ValueError('O profile.json deve conter um objeto JSON.')
    options = json.loads(OPTIONS_FILE.read_text())
    profile = {**DEFAULT_PROFILE, **override}
    for key, option in PROFILE_SECRETS.items():
        value = options.get(option)
        if isinstance(value, str) and value.strip():
            profile[key] = value.strip()
    missing = [option for key, option in PROFILE_SECRETS.items() if not profile.get(key)]
    if missing:
        raise ValueError('Valor vazio no profile.json; preencha na aba Configuração: ' + ', '.join(missing) + '.')
    return configure(options, profile)


def drop_privileges(user='bridge'):
    import pwd  # POSIX only; imported here so configure() stays importable elsewhere.
    account = pwd.getpwnam(user)
    os.setgroups([])
    os.setgid(account.pw_gid)
    os.setuid(account.pw_uid)
    os.environ['HOME'] = account.pw_dir


if __name__ == '__main__':
    try:
        settings = load()
    except (KeyError, ValueError, TypeError, AttributeError, OSError) as exc:
        # Only our own ValueError messages are shown; other errors could echo option values.
        print('Verifique a configuração do Intelbras P2P.', str(exc) if type(exc) is ValueError else '', flush=True)
        sys.exit(2)
    drop_privileges()
    try:
        urls.serve(settings)
        print('Endereços RTSP: clique em "Abrir interface web" na página do add-on.', flush=True)
    except OSError:
        print('A página de endereços RTSP não pôde ser iniciada; o vídeo não é afetado.', flush=True)
    sys.exit(bridge.main(settings))
