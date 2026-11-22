# Changelog

## 1.6.0

- Interface web: ao clicar em uma câmera de um gravador com gerenciamento, o botão **Configurações de vídeo e áudio** lê e altera codec, resolução, quadros por segundo, controle de bitrate, bitrate, qualidade, intervalo de quadros-chave e áudio do stream principal e do secundário. Testado no stream secundário do MHDX 1116 e do MHDX 3116-C.

## 1.5.0

- Dois controles novos por canal no Home Assistant: área mínima de movimento e tempo de filtragem de movimento, úteis contra falsos positivos de chuva.

## 1.4.0

- Novos sensores por canal no Home Assistant: câmera tampada e, onde o gravador tem a função ligada, pessoa, veículo, linha virtual, cerca virtual e face.
- Controles por canal: interruptor da detecção de movimento e ajuste da sensibilidade, que alteram a configuração do gravador.
- Diagnóstico do gravador: modelo, firmware, capacidade e problema nos discos.
- A interface web mostra os selos TAMPADA e ALERTA IA nas câmeras.

## 1.3.0

- Interface web refeita: mosaico de câmeras com selos de movimento e de sem vídeo ao vivo, estado do gravador no topo e abas para Gravações e para Endereços e Frigate.
- Gravações com linha do tempo do dia: clique em um período gravado para assistir.
- Em gravadores com gerenciamento, as miniaturas vêm do próprio gravador, mais rápidas e sem abrir o stream de vídeo.

## 1.2.0

- Gerenciamento opcional por gravador (`gerenciamento` e `porta_http`), desligado por padrão.
- Painel na interface web: estado do DVR (modelo, firmware, relógio e discos), nome do canal, PTZ, busca de gravações e reprodução de trechos de até 30 segundos.
- Sensores de movimento e de perda de vídeo por canal no Home Assistant, via MQTT, quando há um broker disponível.
- A busca e a reprodução de gravações dependem do firmware: funcionaram no MHDX 1116 e não no MHDX 3116-C.

## 1.0.8

- Uso de CPU muito menor: a biblioteca P2P fazia esperas de 1 ms em dezenas de threads, o que ocupava cerca de um núcleo por gravador. Essas esperas agora têm um mínimo de 30 ms.

## 1.0.7

- Menos uso de CPU: o túnel de cada gravador passa a ser mantido pelo stream secundário do primeiro canal, e não mais pelo principal. O stream principal só abre quando um cliente pede.

## 1.0.6

- O log passa a dizer o estado do túnel de cada gravador: conectando, conectado, gravador offline ou serial incorreto, chave ou senha P2P recusada, servidor P2P sem resposta, e túnel conectado mas sem vídeo.

## 1.0.5

- A página "Abrir interface web" mostra uma miniatura de cada canal, atualizada ao clicar.
- Novo campo `canais_em_uso` por gravador (por exemplo, `1,2,5-8`) para expor apenas os canais com câmera; `canais` passa a ser opcional.
- A página traz a configuração de câmeras pronta para copiar e colar no Frigate.

## 1.0.4

- Nova página "Abrir interface web" com os endereços RTSP de todos os canais, prontos para copiar.
- Documentação sem nomes de exemplo fixos: os endereços usam o nome dado a cada gravador.

## 1.0.3

- A chave e a senha do servidor P2P da Intelbras Cloud já vêm embutidas; `chave_p2p` e `senha_p2p` tornam-se opcionais e servem apenas para sobrescrever os valores padrão.

## 1.0.2

- A chave e a senha do servidor P2P passam a ser informadas na aba Configuração (`chave_p2p` e `senha_p2p`); o `profile.json` torna-se opcional.

## 1.0.1

- Encerramento em menos de 1 s (antes cerca de 7 s): o servidor MoQ do mediamtx, que não é usado e bloqueava a parada, foi desligado; o add-on reage ao sinal de parada imediatamente e usa um prazo único de 3 s para todos os processos.
- Vídeo pronto cerca de 6 s mais cedo após iniciar (de ~19 s para ~13 s com dois gravadores): o prefixo do Wine é criado na construção da imagem e o `wineboot` deixa de rodar a cada partida.
- O `profile.json` passa a exigir apenas `server_key` e `password`; servidor, porta e IP remoto têm valores padrão da Intelbras Cloud e podem ser sobrescritos.
- Mensagens de erro mais claras quando o `profile.json` está incompleto ou inválido e quando a configuração é rejeitada.
- A verificação de prontidão deixa de reler o arquivo de configuração a cada ciclo, consulta a API com menos frequência depois que os canais estão prontos e passa a funcionar com mais de 1000 streams.
- O túnel valida as portas antes de iniciar o SDK.
- Testes automatizados para a geração e a validação da configuração.

## 1.0.0

- Versão inicial.
