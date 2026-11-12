# Changelog

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
