# Intelbras P2P

Add-on do Home Assistant que conecta gravadores (DVRs) Intelbras Cloud por P2P e entrega cada canal como um endereço RTSP, pronto para o Frigate ou qualquer outro cliente. Funciona sem IP fixo e sem abrir portas no roteador do local onde o gravador está: basta o serial Intelbras Cloud.

Projeto independente, sem vínculo com a Intelbras.

## Requisitos

- Home Assistant com Supervisor (Home Assistant OS ou Supervised).
- Processador Intel ou AMD de 64 bits (amd64). Não funciona em Raspberry Pi.
- Gravador com o Intelbras Cloud ativado e com acesso à internet.
- O serial Intelbras Cloud, o usuário e a senha de cada gravador.

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
  - nome: loja
    serial: SERIAL_DO_OUTRO_GRAVADOR
    usuario: admin
    senha: senha-do-outro-gravador
    canais: 4
```

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

## Como funciona

O add-on abre um túnel até cada gravador pelos servidores do Intelbras Cloud, usando a biblioteca P2P do fabricante, e republica o RTSP do gravador com o [mediamtx](https://github.com/bluenviron/mediamtx). O vídeo pode passar pelos servidores de retransmissão da Intelbras, então a qualidade depende da internet dos dois lados.

O stream principal do primeiro canal de cada gravador fica sempre aberto para manter o túnel ativo. Os demais só abrem quando um cliente pede vídeo, de modo que canais sem uso não consomem processamento nem banda.

## Avançado

Um arquivo `profile.json` na pasta deste add-on em `/addon_configs/` pode sobrescrever `server`, `server_port`, `remote_ip`, `server_key` e `password`. Os campos da aba **Configuração**, quando preenchidos, têm prioridade sobre o arquivo.
