# Intelbras P2P

Na aba **Configuração**, escolha o usuário e a senha RTSP que o Frigate usará para ler as câmeras. Em **Gravadores**, adicione uma entrada por DVR. Informe um nome curto e único (por exemplo, `vila`), o serial Intelbras Cloud, o usuário e a senha do DVR e a quantidade de canais. Salve e inicie o add-on. Após editar ou remover gravadores, salve e reinicie.

Abra o canal principal pelo endereço `rtsp://USUARIO:SENHA@IP_DO_HOME_ASSISTANT:18554/vila_ch1`. O secundário termina em `/vila_ch1_sub`. Troque o número para selecionar outro canal. Use as credenciais RTSP configuradas na primeira etapa e codifique caracteres especiais na URL. A porta externa pode ser alterada na seção Rede se 18554 já estiver em uso, inclusive pelo Frigate.

O canal principal 1 mantém a conexão de cada gravador ativa. Os demais abrem quando um cliente pede vídeo. A implementação usa o RTSP do gravador na porta 554 e foi testada com os modelos MHDX 3116-C e MHDX 1116. Requer Home Assistant com Supervisor em Intel ou AMD de 64 bits.

Antes de iniciar, crie um profile.json na pasta deste add-on em /addon_configs/ no Home Assistant com os campos `server_key` e `password` do SDK. Dentro do container o arquivo será lido em /config/profile.json. Os campos `server`, `server_port` e `remote_ip` são opcionais e, quando ausentes, usam os valores padrão da Intelbras Cloud. Depois, cadastre seus DVRs na aba Configuração.
