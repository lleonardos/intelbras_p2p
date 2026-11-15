"""Recorder operations available through the authenticated add-on ingress."""
from datetime import date
import json
import re
import threading
import time
import urllib.parse
import urllib.error
import urllib.request

import events


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


class Recorder:
    def __init__(self, device):
        self.device = device
        self.channels = sorted({int(s['name'].rsplit('_ch', 1)[1].split('_')[0]) for s in device['streams']})
        self.base = 'http://127.0.0.1:' + str(device['management_local_port']) + '/cgi-bin/'
        passwords = urllib.request.HTTPPasswordMgrWithDefaultRealm()
        passwords.add_password(None, self.base, device['username'], device['password'])
        self.http = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect(),
                                                urllib.request.HTTPDigestAuthHandler(passwords),
                                                urllib.request.HTTPBasicAuthHandler(passwords))
        self.lock = threading.Lock()

    def call(self, script, **params):
        with self.http.open(self.base + script + '.cgi?' + urllib.parse.urlencode(params, quote_via=urllib.parse.quote, safe='[]:'), timeout=8) as response:
            body = response.read(512 * 1024).decode('utf-8', errors='replace').strip()
        if body.startswith('Error') or body.startswith('<'):
            raise ValueError('Operação recusada pelo gravador.')
        return body

    def status(self):
        """Model, firmware, clock, disks and current events as text. Never includes the serial number."""
        lines = ['Modelo: ' + self.call('magicBox', action='getDeviceType').partition('=')[2],
                 'Firmware: ' + firmware(self.call('magicBox', action='getSoftwareVersion')),
                 'Relógio do DVR: ' + self.call('global', action='getCurrentTime').partition('=')[2]]
        found = disks(self.call('storageDevice', action='getDeviceAllInfo'))
        lines += [f'Disco {number}: {size / 1e9:.0f} GB, ' + ('com erro' if error else 'sem erro')
                  for number, (size, error) in enumerate(found, 1)] or ['Disco: nenhum encontrado']
        if events.HUB:
            online, active = events.HUB.summary(self.device['name'])
            if online:
                lines += [f'Canais {label} agora: ' + (', '.join(map(str, active[code])) or 'nenhum')
                          for code, label in (('VideoMotion', 'com movimento'), ('VideoLoss', 'sem vídeo'))]
            else:
                lines.append('Eventos: sem conexão com o gravador')
        return '\n'.join(lines)

    def run(self, data):
        action = data['action']
        channel = int(data['channel'])
        if channel not in self.channels:
            raise ValueError('Canal inválido.')
        if not self.lock.acquire(blocking=False):
            raise ValueError('Gravador ocupado.')
        try:
            if action == 'status':
                return self.status()
            key = f'ChannelTitle[{channel - 1}].Name'
            if action == 'title':
                values = self.call('configManager', action='getConfig', name='ChannelTitle')
                for line in values.splitlines():
                    if line.startswith('table.' + key + '='):
                        return line.partition('=')[2]
                raise ValueError('Nome do canal indisponível.')
            if action == 'rename':
                title = data['title'].strip()
                if not title or len(title) > 32 or not title.isprintable():
                    raise ValueError('Informe um nome de até 32 caracteres.')
                return self.call('configManager', action='setConfig', **{key: title})
            if action == 'ptz':
                code = data['direction']
                if code not in ('Up', 'Down', 'Left', 'Right', 'ZoomTele', 'ZoomWide'):
                    raise ValueError('Direção inválida.')
                params = dict(channel=channel, code=code, arg1=0, arg2=2, arg3=0)
                try:
                    self.call('ptz', action='start', **params)
                    time.sleep(0.3)
                finally:
                    self.call('ptz', action='stop', **params)
                return 'Comando enviado.'
            if action == 'recordings':
                day = date.fromisoformat(data['day']).isoformat()
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
                        entries.extend(t.get('StartTime', '?') + ' — ' + t.get('EndTime', '?') for t in times.values())
                        if len(times) < 50:
                            break
                    return '\n'.join(entries) or 'Nenhuma gravação encontrada.'
                finally:
                    try:
                        self.call('mediaFileFind', action='close', object=obj)
                    finally:
                        self.call('mediaFileFind', action='destroy', object=obj)
            raise ValueError('Operação inválida.')
        finally:
            self.lock.release()


def panel(recorders):
    devices = json.dumps({name: rec.channels for name, rec in recorders.items()}).replace('<', '\\u003c')
    if not recorders:
        return ''
    return '''<section><h2>Gerenciar gravador</h2><select id="dvr"></select> Canal <select id="dch"></select>
    <p><button data-op="status">Estado do DVR</button> <button data-op="title">Consultar nome</button> <input id="dtitle" maxlength="32" placeholder="Nome do canal">
    <button data-op="rename">Salvar nome no DVR</button></p>
    <p>PTZ <button data-dir="Up">↑</button><button data-dir="Down">↓</button><button data-dir="Left">←</button>
    <button data-dir="Right">→</button><button data-dir="ZoomTele">Zoom +</button><button data-dir="ZoomWide">Zoom −</button></p>
    <input type="date" id="dday"><button data-op="recordings">Buscar gravações</button><pre id="dresult" role="status"></pre><div id="intervals"></div>
    <p><label>Horário no DVR <input type="time" id="dtime" step="1" value="12:00:00"></label>
    <button id="watch">Reproduzir trecho</button><button id="next" disabled>Próximos 30 s</button></p>
    <video id="archive" controls playsinline style="width:100%;max-width:960px"></video></section>
    <script>(()=>{const devices=DEVICES, el=id=>document.getElementById(id), d=el('dvr'), ch=el('dch');
    for(const name of Object.keys(devices)) d.add(new Option(name,name));
    function refresh(){ch.replaceChildren();for(const n of devices[d.value])ch.add(new Option(n,n));}
    d.onchange=refresh;refresh();el('dday').valueAsDate=new Date();
    let currentUrl, generation=0, until=null;
    function reset(){generation++;el('archive').pause();el('archive').removeAttribute('src');el('archive').load();
      if(currentUrl)URL.revokeObjectURL(currentUrl);currentUrl=null;until=null;el('next').disabled=true;
      el('intervals').replaceChildren();el('dresult').textContent='';}
    for(const input of [d,ch,el('dday')])input.addEventListener('change',reset);
    el('dtime').onchange=()=>{until=null;el('next').disabled=true;};
    function instant(s){return Date.parse(s.replace(' ','T')+'Z');}
    async function watch(){
      const id=++generation, time=el('dtime').value, start=el('dday').value+' '+(time.length===5?time+':00':time);
      const ms=instant(start);if(!Number.isFinite(ms))return;
      const seconds=until===null?30:Math.min(30,Math.floor((until-ms)/1000));if(seconds<1)return;
      const data={action:'playback',device:d.value,channel:ch.value,start,seconds};
      el('next').disabled=true;el('dresult').textContent='Carregando trecho…';
      try{const r=await fetch('control',{method:'POST',headers:{'Content-Type':'application/json','X-DVR-Control':'1'},body:JSON.stringify(data)});
        if(!r.ok)throw Error();const blob=await r.blob();if(id!==generation)return;
        if(currentUrl)URL.revokeObjectURL(currentUrl);currentUrl=URL.createObjectURL(blob);
        el('archive').src=currentUrl;el('archive').play().catch(()=>{});
        el('dresult').textContent=start;const next=ms+seconds*1000;
        el('next').disabled=until!==null&&next>=until;
        el('next').onclick=()=>{const iso=new Date(next).toISOString();el('dday').value=iso.slice(0,10);el('dtime').value=iso.slice(11,19);watch();};
      }catch{if(id===generation)el('dresult').textContent='Trecho indisponível neste horário ou gravador ocupado.';}}
    el('watch').onclick=watch;
    for(const b of document.querySelectorAll('[data-op],[data-dir]')) b.onclick=async()=>{
    const action=b.dataset.op||'ptz';if(action==='rename'&&!confirm('Alterar o nome deste canal no gravador?'))return;
    const data={device:d.value,channel:ch.value,action,direction:b.dataset.dir,title:el('dtitle').value,day:el('dday').value};
    try{const r=await fetch('control',{method:'POST',headers:{'Content-Type':'application/json','X-DVR-Control':'1'},body:JSON.stringify(data)});
    const msg=await r.json();
    if(data.device!==d.value||data.channel!==ch.value||data.day!==el('dday').value)return;
    if(action==='recordings'){const list=el('intervals');list.replaceChildren();
      if(r.ok)for(const line of msg.split('\\n')){const parts=line.split(' — ');if(parts.length!==2)continue;
        const item=document.createElement('button');item.textContent=line;item.onclick=()=>{el('dday').value=parts[0].slice(0,10);el('dtime').value=parts[0].slice(11,19);until=instant(parts[1]);watch();};list.append(item);}
      el('dresult').textContent=list.children.length?'Selecione uma gravação.':(r.ok?msg:'Lista indisponível. Você pode tentar reproduzir pelo horário.');return;}
    el('dresult').textContent=msg;if(action==='title'&&r.ok)el('dtitle').value=msg;}
    catch{el('dresult').textContent='Falha ao comunicar com o add-on.'}}})();</script>'''.replace('DEVICES', devices)
