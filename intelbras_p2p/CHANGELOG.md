# Changelog

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
