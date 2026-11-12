import json
import os
import re
import sys
from pathlib import Path

import main as bridge

OPTIONS_FILE = Path('/data/options.json')
PROFILE_FILE = Path('/config/profile.json')
FIRST_LOCAL_PORT = 15541
# Intelbras Cloud relay settings, the same for every recorder. A profile.json in the add-on config
# folder overrides any of them and must supply the two SDK secrets that are not shipped here.
DEFAULT_PROFILE = {
    'server': 'intelbrasp2p.com.br',
    'server_port': 1250,
    'remote_ip': '127.0.0.1',
}
PROFILE_SECRETS = ('server_key', 'password')
NAME_RE = re.compile(r'[a-z0-9_-]+')


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
        count = recorder['canais']
        if type(count) is not int or not 1 <= count <= 64:
            raise ValueError('Informe de 1 a 64 canais por gravador.')
        if not all(recorder[key].strip() for key in ('serial', 'usuario', 'senha')):
            raise ValueError('Preencha o serial, o usuário e a senha de cada gravador.')
        streams = []
        for channel in range(1, count + 1):
            for subtype, suffix in ((0, ''), (1, '_sub')):
                streams.append({'name': f'{name}_ch{channel}{suffix}',
                                'path': f'/cam/realmonitor?channel={channel}&subtype={subtype}',
                                'on_demand': channel != 1 or subtype != 0})
        devices.append({'mode': 'p2p', 'username': recorder['usuario'], 'password': recorder['senha'],
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
    profile = {**DEFAULT_PROFILE, **override}
    missing = [key for key in PROFILE_SECRETS if not profile.get(key)]
    if missing:
        raise ValueError('Faltam no profile.json (pasta deste add-on em /addon_configs/): '
                         + ', '.join(missing) + '.')
    return configure(json.loads(OPTIONS_FILE.read_text()), profile)


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
    sys.exit(bridge.main(settings))
