# Intelbras P2P

Na aba **Configuração**, escolha o usuário e a senha RTSP que o Frigate usará para ler as câmeras. Os campos `chave_p2p` e `senha_p2p` são opcionais: deixe-os vazios para usar a chave e a senha padrão do servidor Intelbras Cloud, e preencha apenas se a Intelbras alterar esses valores (eles não são a senha do DVR). Em **Gravadores**, adicione uma entrada por DVR. Informe um nome curto e único (por exemplo, `casa`), o serial Intelbras Cloud, o usuário e a senha do DVR e a quantidade de canais. Salve e inicie o add-on. Após editar ou remover gravadores, salve e reinicie.

Com o add-on iniciado, clique em **Abrir interface web** para ver os endereços RTSP de todos os canais e copiá-los. Cada endereço usa o nome que você deu ao gravador: o canal principal é `rtsp://USUARIO:SENHA@IP_DO_HOME_ASSISTANT:18554/NOME_ch1` e o secundário termina em `/NOME_ch1_sub`, em que `NOME` é o nome do gravador e o número é o canal. Use as credenciais RTSP configuradas na primeira etapa; a página já codifica caracteres especiais da senha. A porta externa pode ser alterada na seção Rede se 18554 já estiver em uso, inclusive pelo Frigate.

O canal principal 1 mantém a conexão de cada gravador ativa. Os demais abrem quando um cliente pede vídeo. A implementação usa o RTSP do gravador na porta 554 e foi testada com os modelos MHDX 3116-C e MHDX 1116. Requer Home Assistant com Supervisor em Intel ou AMD de 64 bits.

Opcionalmente, um profile.json na pasta deste add-on em /addon_configs/ pode sobrescrever `server`, `server_port`, `remote_ip`, `server_key` e `password`, que por padrão usam os valores da Intelbras Cloud. Os campos da aba Configuração, quando preenchidos, têm prioridade sobre o arquivo.
