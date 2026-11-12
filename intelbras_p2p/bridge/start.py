import json
import os
import pwd
import re
import sys
from pathlib import Path

import main as bridge


def configure(options, profile):
    devices = []
    names = set()
    if not options.get('senha_rtsp') or not options.get('gravadores'):
        raise ValueError('Preencha a senha RTSP e adicione um gravador na aba Configuração.')
    for index, recorder in enumerate(options['gravadores']):
        name = recorder['nome'].strip().lower()
        if not re.fullmatch(r'[a-z0-9_-]+', name) or name in names:
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
                                'local_port': 15541 + index}, 'streams': streams})
    return {'output_auth': {'username': options['usuario_rtsp'], 'password': options['senha_rtsp']},
            'devices': devices}


if __name__ == '__main__':
    try:
        settings = configure(json.loads(Path('/data/options.json').read_text()),
                             json.loads(Path('/config/profile.json').read_text()))
    except (KeyError, ValueError, OSError) as exc:
        print('Verifique a configuração do Intelbras P2P.', str(exc) if type(exc) is ValueError else '', flush=True)
        sys.exit(2)
    account = pwd.getpwnam('bridge')
    os.setgroups([])
    os.setgid(account.pw_gid)
    os.setuid(account.pw_uid)
    os.environ['HOME'] = account.pw_dir
    sys.exit(bridge.main(settings))
