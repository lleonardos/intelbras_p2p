# Intelbras P2P

Add-on do Home Assistant que conecta gravadores (DVRs) Intelbras Cloud por P2P e entrega cada canal como um endereço RTSP, pronto para o Frigate ou qualquer outro cliente. Funciona sem IP fixo e sem abrir portas no roteador do local onde o gravador está: basta o serial Intelbras Cloud.

Opcionalmente, o add-on também cria no Home Assistant sensores de movimento, de perda de vídeo e dos alertas inteligentes do gravador, controles da detecção de movimento, e oferece um painel para consultar o estado do gravador e rever gravações.

Projeto independente, sem vínculo com a Intelbras.

## Requisitos

- Home Assistant com Supervisor (Home Assistant OS ou Supervised).
- Processador Intel ou AMD de 64 bits (amd64). Não funciona em Raspberry Pi.
- Gravador com o Intelbras Cloud ativado e com acesso à internet.
- O serial Intelbras Cloud, o usuário e a senha de cada gravador.
- Opcional, apenas para os sensores e controles no Home Assistant: um broker MQTT no Home Assistant, como o add-on Mosquitto, com a integração MQTT configurada.

Testado com os modelos MHDX 3116-C e MHDX 1116.

## Instalação

1. No Home Assistant, abra **Configurações → Add-ons → Loja de add-ons**.
2. Clique em **⋮ → Repositórios**, cole o endereço abaixo e clique em **Adicionar**.

   ```
   https://github.com/lleonardos/intelbras_p2p
   ```

3. Feche a janela, procure **Intelbras P2P** na loja e clique em **Instalar**. A imagem é montada no próprio Home Assistant, então a instalação leva vários minutos.
4. Abra a aba **Configuração** e preencha os campos descritos na próxima seção.
5. Clique em **Salvar** e, na aba **Informações**, em **Iniciar**.
6. Confira a aba **Log**. Em cerca de 15 segundos deve aparecer `Gravador NOME: túnel conectado.` para cada gravador.
7. Clique em **Abrir interface web** para ver as câmeras e copiar os endereços RTSP.

Depois de alterar, adicionar ou remover gravadores, salve e reinicie o add-on.

## Campos da configuração

### Gerais

| Campo | Obrigatório | O que é |
|---|---|---|
| `usuario_rtsp` | Sim | Usuário que o Frigate (ou outro cliente) usará para ler os vídeos deste add-on. Você escolhe; o padrão é `frigate`. Não é o usuário do gravador. |
| `senha_rtsp` | Sim | Senha desse usuário. Você escolhe. Não é a senha do gravador. |
| `chave_p2p` | Não | Chave do servidor Intelbras Cloud. Deixe vazio: o add-on já usa a chave padrão. Preencha só se a Intelbras mudar esse valor. |
| `senha_p2p` | Não | Senha P2P do servidor Intelbras Cloud. Deixe vazio pelo mesmo motivo. Não é a senha do gravador. |

### Gravadores

Adicione uma entrada para cada gravador.

| Campo | Obrigatório | O que é |
|---|---|---|
| `nome` | Sim | Apelido curto e único, que entra no endereço de cada canal. Use letras sem acento, números, hífen ou sublinhado, sem espaços. Exemplo: `casa`. |
| `serial` | Sim | Número de série Intelbras Cloud do gravador. Está na etiqueta do aparelho e no menu do gravador, na tela do Intelbras Cloud. |
| `usuario` | Sim | Usuário de acesso do gravador, o mesmo usado no aplicativo da Intelbras. Normalmente `admin`. |
| `senha` | Sim | Senha desse usuário do gravador. |
| `canais_em_uso` | Um dos dois | Lista dos canais que têm câmera, separados por vírgula, com intervalos se quiser. Exemplo: `1,2,5-8`. |
| `canais` | Um dos dois | Quantidade total de canais, de 1 a 64. Expõe do canal 1 até esse número. Usado apenas quando `canais_em_uso` está vazio. |
| `gerenciamento` | Não | Liga o painel de gerenciamento, os sensores e os controles deste gravador. Desligado por padrão. Veja [Gerenciamento do gravador](#gerenciamento-do-gravador). |
| `porta_http` | Não | Porta HTTP do gravador, usada pelo gerenciamento. Padrão: 80. |

Prefira `canais_em_uso`: a página de endereços e o YAML do Frigate ficam só com as câmeras que existem.

### Exemplo

Na aba **Configuração**, em **⋮ → Editar em YAML**:

```yaml
usuario_rtsp: frigate
senha_rtsp: escolha-uma-senha
gravadores:
  - nome: casa
    serial: SERIAL_DO_GRAVADOR
    usuario: admin
    senha: senha-do-gravador
    canais_em_uso: "1,2,5-8"
    gerenciamento: true
  - nome: loja
    serial: SERIAL_DO_OUTRO_GRAVADOR
    usuario: admin
    senha: senha-do-outro-gravador
    canais: 4
```

Neste exemplo, só o gravador `casa` tem o gerenciamento ligado.

## Endereços RTSP

Cada canal tem dois endereços, formados com o nome do gravador em minúsculas e o número do canal:

| Stream | Endereço |
|---|---|
| Principal (alta resolução) | `rtsp://USUARIO:SENHA@IP_DO_HOME_ASSISTANT:18554/NOME_ch1` |
| Secundário (baixa resolução) | `rtsp://USUARIO:SENHA@IP_DO_HOME_ASSISTANT:18554/NOME_ch1_sub` |

`USUARIO` e `SENHA` são o `usuario_rtsp` e a `senha_rtsp`. Para o gravador `casa`, o canal 5 fica em `/casa_ch5` e `/casa_ch5_sub`.

A página **Abrir interface web** tem três abas:

- **Câmeras:** um mosaico com a imagem de cada canal. Clique em uma câmera para ver e copiar os dois endereços dela.
- **Gravações:** aparece quando algum gravador tem o gerenciamento ligado.
- **Endereços e Frigate:** todos os endereços de uma vez e a configuração pronta para o Frigate.

Na aba **Endereços e Frigate**, digite a senha RTSP para que os endereços saiam completos; caracteres especiais da senha já são codificados.

Se a porta 18554 estiver em uso, troque-a na aba **Configuração**, seção **Rede**.

## Uso com o Frigate

A aba **Endereços e Frigate** traz o bloco **Configuração para o Frigate**, com uma câmera por canal: o stream secundário para detecção e o principal para gravação. Copie e cole dentro do `config.yaml` do Frigate, depois ajuste resolução, zonas e o que mais precisar.

## Gerenciamento do gravador

Opcional e desligado por padrão. Com `gerenciamento` ligado em um gravador, o add-on abre uma segunda conexão P2P, para a interface HTTP dele. O vídeo ao vivo não muda.

### Como ativar

1. Na aba **Configuração**, ligue `gerenciamento` no gravador desejado. Se a porta HTTP do gravador não for a 80, informe-a em `porta_http`.
2. Salve e reinicie o add-on.
3. Confira a aba **Log**: deve aparecer `Gravador NOME: eventos conectados.`
4. Clique em **Abrir interface web**. O gravador passa a mostrar o selo **eventos ao vivo**, e a aba **Gravações** aparece.

### Sensores e controles no Home Assistant

Tudo é criado automaticamente por MQTT e aparece no dispositivo **Intelbras NOME**, em **Configurações → Dispositivos e serviços → MQTT**.

**Sensores por canal**

| Sensor | Fica ligado quando | Criado |
|---|---|---|
| Canal N movimento | O gravador detecta movimento no canal. | Sempre |
| Canal N sem vídeo | O canal está sem sinal de câmera. | Sempre |
| Canal N câmera tampada | A imagem do canal está obstruída. | Sempre |
| Canal N pessoa / veículo | A detecção inteligente do gravador identifica uma pessoa ou um veículo. | Quando a função está ligada no canal |
| Canal N linha virtual / cerca virtual | Uma regra de linha ou de área do gravador dispara. | Quando há regra ativa no canal |
| Canal N face | A detecção de face dispara. | Quando há regra ativa no canal |

Os sensores da coluna "quando" também são criados na primeira vez que o evento chega. As funções inteligentes são ligadas e configuradas no próprio gravador; depois de ligá-las, reinicie o add-on. Um evento que o add-on ainda não conhece aparece uma vez no log, com o nome do evento e o canal.

**Controles por canal**

| Controle | O que altera no gravador |
|---|---|
| Canal N detecção de movimento | Liga ou desliga a detecção de movimento do canal. |
| Canal N sensibilidade de movimento | Sensibilidade da detecção, de 0 a 100. Valores menores reagem a menos mudanças na imagem. |
| Canal N área mínima de movimento | Quanto da área monitorada precisa mudar para disparar, de 0 a 100. Em 0, qualquer mudança dispara. |
| Canal N tempo de filtragem de movimento | Tempo, em segundos (0 a 600), que o gravador mantém um evento antes de encerrá-lo. Valores maiores juntam disparos seguidos em um só. |

Contra falsos positivos de chuva, insetos ou folhas, reduza a sensibilidade e aumente a área mínima aos poucos, conferindo o resultado.

O valor mostrado é sempre o que o gravador confirmou depois da alteração. Desligar a detecção de movimento de um canal também afeta a gravação por movimento do próprio gravador. Qualquer cliente com acesso ao broker MQTT pode enviar esses comandos.

**Diagnóstico do gravador**

Modelo, firmware, capacidade dos discos e um sensor de problema nos discos, atualizados a cada 30 minutos.

Todas as entidades ficam indisponíveis enquanto o add-on ou a conexão com o gravador estiver fora do ar.

- O movimento é o detectado pelo próprio gravador, então a detecção de movimento precisa estar habilitada nele.
- Sem broker MQTT, nada disso é criado e os eventos aparecem apenas no mosaico da interface web. O log informa qual dos dois casos vale.
- Para usar um sensor como gatilho no Frigate ou em outra ferramenta, crie uma automação no Home Assistant.

### Na interface web

**Aba Câmeras**

- O topo de cada gravador mostra modelo, firmware, relógio e discos.
- Cada câmera ganha os selos **MOVIMENTO**, **SEM VÍDEO**, **TAMPADA** e **ALERTA IA** (pessoa, veículo, linha, cerca ou face) enquanto o evento dura, atualizados a cada poucos segundos.
- As miniaturas passam a vir do próprio gravador, o que é mais rápido e não abre o stream de vídeo.
- Ao clicar em uma câmera, além dos endereços aparecem:

| Controle | O que faz |
|---|---|
| **Nome do canal no gravador** e **Salvar nome** | Mostra o nome gravado no DVR e permite alterá-lo. Pede confirmação. |
| Setas e **Aproximar** / **Afastar** | Enviam pulsos de direção e zoom para câmeras com PTZ. |
| **Ver gravações deste canal** | Abre a aba Gravações já no canal escolhido. |
| **Configurações de vídeo e áudio** | Lê do gravador e permite alterar, no stream principal e no secundário: codec de vídeo, resolução, quadros por segundo, controle de bitrate (CBR ou VBR), bitrate, qualidade, intervalo de quadros-chave, áudio ligado ou desligado e codec de áudio. |

Sobre as configurações de vídeo e áudio:

- Codecs, resoluções e limites de bitrate são os que o gravador informa para aquele canal; os demais campos usam as faixas usuais desses gravadores. Um campo acinzentado é um valor que o gravador mostrou sem dizer o que aceita, e por isso não pode ser alterado por aqui.
- Resoluções que o gravador lista por um nome que o add-on não conhece aparecem em uma nota abaixo do campo, e continuam ajustáveis apenas no próprio gravador.
- **Salvar** pede confirmação, grava de uma vez só as alterações daquele stream e mostra de volta o que o gravador confirmou; ele pode ajustar outros valores por conta própria, como o intervalo de quadros-chave ao baixar os quadros por segundo. Se o gravador responder que salvou mas guardar outro valor, a página avisa quais campos ele não aplicou.
- Ao salvar, o vídeo do canal pode reiniciar. Se mudar o codec ou a resolução, confira a configuração do Frigate (por exemplo, a resolução de `detect`). O stream secundário do primeiro canal é o que mantém a conexão com o gravador ativa.

**Aba Gravações**

1. Escolha o gravador, o canal e o dia, e clique em **Buscar gravações**.
2. A linha do tempo mostra em verde os períodos gravados, no horário do gravador. Clique em uma faixa para assistir desde o início dela.
3. Para outro horário, clique em qualquer ponto da linha do tempo, ou digite o horário, e use **Reproduzir 30 s**. **Próximos 30 s** continua de onde parou.

Cada trecho tem até 30 segundos, sem áudio. A reprodução converte o vídeo dentro do add-on, o que usa processador enquanto alguém assiste.

### Compatibilidade

O que cada função alcança depende do modelo, do firmware e das permissões do usuário do gravador.

| Função | MHDX 1116 | MHDX 3116-C |
|---|---|---|
| Sensores de movimento e sem vídeo | Funciona | Funciona |
| Controles de movimento (detecção, sensibilidade, área mínima e filtragem) | Funciona | Funciona |
| Diagnóstico do gravador | Funciona | Funciona |
| Sensores de linha e cerca virtual | Criados; disparo não observado | Não tem a função |
| Sensores de pessoa, veículo, face e câmera tampada | Disparo não observado | Disparo não observado |
| Estado do DVR e nome do canal | Funciona | Funciona |
| Busca e reprodução de gravações | Funciona | Não funciona |
| Salvar nome e PTZ | Não testado | Não testado |
| Configurações de vídeo e áudio: leitura dos dois streams | Funciona | Funciona |
| Configurações de vídeo e áudio: alterar resolução, quadros por segundo, bitrate e quadros-chave do stream secundário | Funciona | Funciona |
| Configurações de vídeo e áudio: alterar o stream principal, o codec e o áudio | Não testado | Não testado |

## Mensagens do log

| Mensagem | O que fazer |
|---|---|
| `conectando` | Aguarde; a conexão leva cerca de 10 segundos. |
| `túnel conectado` | Tudo certo. |
| `túnel conectado, mas sem vídeo` | O gravador foi alcançado, mas recusou o acesso. Confira `usuario`, `senha` e os canais. |
| `gravador offline ou serial incorreto` | Confira o `serial` e se o gravador está ligado, com internet e com o Intelbras Cloud ativado. |
| `chave do servidor P2P recusada` | Apague o campo `chave_p2p` para voltar ao valor padrão. |
| `senha P2P recusada` | Apague o campo `senha_p2p` para voltar ao valor padrão. |
| `servidor P2P sem resposta` | Confira a internet do Home Assistant. |
| `eventos conectados` | O gerenciamento do gravador está funcionando. |
| `eventos desconectados; tentando de novo` | A conexão de eventos caiu. O add-on reconecta sozinho; o vídeo não é afetado. |
| `sem acesso ao gerenciamento` | Confira `porta_http` e se o usuário do gravador tem permissão de acesso pela web. |
| `Eventos dos gravadores: sem MQTT no Home Assistant` | Instale um broker MQTT e configure a integração MQTT para ter os sensores. |

## Como funciona

O add-on abre um túnel até cada gravador pelos servidores do Intelbras Cloud, usando a biblioteca P2P do fabricante, e republica o RTSP do gravador com o [mediamtx](https://github.com/bluenviron/mediamtx). O vídeo pode passar pelos servidores de retransmissão da Intelbras, então a qualidade depende da internet dos dois lados.

O stream secundário do primeiro canal de cada gravador fica sempre aberto para manter o túnel ativo. Os demais só abrem quando um cliente pede vídeo, de modo que canais sem uso não consomem processamento nem banda.

Com o gerenciamento ligado, o mesmo túnel leva uma segunda porta até a interface HTTP do gravador. Por ela o add-on acompanha o fluxo de eventos e atende o painel.

## Avançado

Um arquivo `profile.json` na pasta deste add-on em `/addon_configs/` pode sobrescrever `server`, `server_port`, `remote_ip`, `server_key` e `password`. Os campos da aba **Configuração**, quando preenchidos, têm prioridade sobre o arquivo.
