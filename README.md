# Intelbras P2P

Add-on do Home Assistant que conecta gravadores (DVRs) Intelbras Cloud por P2P e entrega cada canal como um endereço RTSP, pronto para o Frigate ou qualquer outro cliente. Funciona sem IP fixo e sem abrir portas no roteador do local onde o gravador está: basta o serial Intelbras Cloud.

Opcionalmente, o add-on também cria sensores de movimento e de perda de vídeo no Home Assistant e oferece um painel para consultar o estado do gravador e rever gravações.

Projeto independente, sem vínculo com a Intelbras.

## Requisitos

- Home Assistant com Supervisor (Home Assistant OS ou Supervised).
- Processador Intel ou AMD de 64 bits (amd64). Não funciona em Raspberry Pi.
- Gravador com o Intelbras Cloud ativado e com acesso à internet.
- O serial Intelbras Cloud, o usuário e a senha de cada gravador.
- Opcional, apenas para os sensores de eventos: um broker MQTT no Home Assistant, como o add-on Mosquitto, com a integração MQTT configurada.

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
7. Clique em **Abrir interface web** para ver e copiar os endereços RTSP.

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
| `gerenciamento` | Não | Liga o painel de gerenciamento e os sensores de eventos deste gravador. Desligado por padrão. Veja [Gerenciamento do gravador](#gerenciamento-do-gravador). |
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

A página **Abrir interface web** lista todos os endereços com botão de copiar e uma miniatura de cada canal. Digite a senha RTSP na própria página para que os endereços saiam completos; caracteres especiais da senha já são codificados.

Se a porta 18554 estiver em uso, troque-a na aba **Configuração**, seção **Rede**.

## Uso com o Frigate

A mesma página traz o bloco **Configuração para o Frigate**, com uma câmera por canal: o stream secundário para detecção e o principal para gravação. Copie e cole dentro do `config.yaml` do Frigate, depois ajuste resolução, zonas e o que mais precisar.

## Gerenciamento do gravador

Opcional e desligado por padrão. Com `gerenciamento` ligado em um gravador, o add-on abre uma segunda conexão P2P, para a interface HTTP dele. O vídeo ao vivo não muda.

### Como ativar

1. Na aba **Configuração**, ligue `gerenciamento` no gravador desejado. Se a porta HTTP do gravador não for a 80, informe-a em `porta_http`.
2. Salve e reinicie o add-on.
3. Confira a aba **Log**: deve aparecer `Gravador NOME: eventos conectados.`
4. Clique em **Abrir interface web**. O painel **Gerenciar gravador** fica no fim da página.

### Sensores no Home Assistant

Cada canal configurado ganha dois sensores, criados automaticamente por MQTT:

| Sensor | Fica ligado quando |
|---|---|
| Canal N movimento | O gravador detecta movimento no canal. |
| Canal N sem vídeo | O canal está sem sinal de câmera. |

Eles aparecem no dispositivo **Intelbras NOME**, em **Configurações → Dispositivos e serviços → MQTT**, e ficam indisponíveis enquanto o add-on ou a conexão com o gravador estiver fora do ar.

- O movimento é o detectado pelo próprio gravador, então a detecção de movimento precisa estar habilitada nele.
- Sem broker MQTT, os sensores não são criados e os eventos aparecem apenas em **Estado do DVR**, no painel. O log informa qual dos dois casos vale.
- Para usar um sensor como gatilho no Frigate ou em outra ferramenta, crie uma automação no Home Assistant.

### Painel na interface web

Escolha o gravador e o canal e use os botões:

| Função | O que faz |
|---|---|
| **Estado do DVR** | Mostra modelo, firmware, relógio, discos e os canais com movimento ou sem vídeo naquele momento. |
| **Consultar nome** | Lê o nome do canal gravado no DVR. |
| **Salvar nome no DVR** | Altera o nome do canal no gravador. Pede confirmação. |
| **PTZ** | Envia pulsos de direção e zoom para câmeras com PTZ. |
| **Buscar gravações** | Lista os intervalos gravados no dia escolhido, no horário do DVR. |
| **Reproduzir trecho** | Mostra até 30 segundos de gravação, sem áudio, a partir do horário informado. **Próximos 30 s** continua de onde parou. |

A reprodução converte o vídeo dentro do add-on, o que usa processador enquanto alguém assiste.

### Compatibilidade

O que cada função alcança depende do modelo, do firmware e das permissões do usuário do gravador.

| Função | MHDX 1116 | MHDX 3116-C |
|---|---|---|
| Sensores de eventos | Funciona | Funciona |
| Estado do DVR e nome do canal | Funciona | Funciona |
| Busca e reprodução de gravações | Funciona | Não funciona |
| Salvar nome e PTZ | Não testado | Não testado |

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
