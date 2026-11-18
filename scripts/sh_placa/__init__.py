"""A BeagleBone vista do computador (docs/gui-plan.md, seção 11), sem Qt: o cliente do agente da placa
(``firmware/agente/shan_agente.py``), o estado e o diagnóstico dela, e o simulador.

* :mod:`.agente` -- roda o agente por um transporte (o SSH, ou o local do simulador) e confere a resposta;
* :mod:`.conexao` -- a conexão SSH com a placa (o asyncssh), com o salto, a chave do host fixada e o registro;
* :mod:`.destino` -- onde está uma placa (o host, a porta, o usuário e o salto), sem o asyncssh;
* :mod:`.descoberta` -- as placas ao alcance (o USB, o mDNS, as conhecidas e o simulador), uma vez cada;
* :mod:`.conhecidas` -- as placas em que o usuário já conectou, pelo nº de série, com a chave de host e os endereços;
* :mod:`.chaves` -- a chave do aplicativo, as chaves de host conhecidas e o cofre das senhas;
* :mod:`.registro` -- o registro de atividade: cada comando rodado na placa;
* :mod:`.estado` -- as respostas do agente lidas: o estado e a saúde (o diagnóstico: o que está errado e como
  corrigir), o relógio, as capturas e os logs;
* :mod:`.captura` -- a captura contínua: o ``ler_adc -o -`` pelo SSH, com o sudo, gravada aqui enquanto chega, o
  Parar e a queda (o fechamento é o do motor, ``supraharmonicos.saida_continua``);
* :mod:`.pedido` -- o pedido de uma captura (o formulário da Aquisição): os argumentos do ``ler_adc``, a validação
  por campo com as regras dele e a linha de comando lida como o C a lê (sem o asyncssh);
* :mod:`.conferencia` -- o "Conferir antes": uma captura curta do pedido, medida no motor
  (``supraharmonicos.conferencia``);
* :mod:`.laco` -- o laço ``asyncio`` numa thread só dele, onde toda a rede da placa roda (a interface chega a ele
  pela ponte ``sh_analyzer_gui/servicos/placa.py``);
* :mod:`.simulador` -- uma BeagleBone neste computador, com cenários (o sistema de arquivos falso em que o agente de
  verdade roda): para desenvolver e demonstrar sem a placa, e para os testes;
* :mod:`.servidor_do_simulador` -- a placa simulada servida por SSH, como a interface a usa (precisa do asyncssh);
* :mod:`.capturas_simuladas` -- as capturas da placa simulada: ``.bin`` como o ``ler_adc`` grava, com a rede de 60 Hz
  e os supraharmônicos;
* :mod:`.ler_adc_simulado` -- o ``ler_adc`` da placa simulada: a linha de comando dele e as capturas, no cartão ou
  pela saída contínua (``-o -``, ``--progresso-json``), no ritmo da taxa, com o Ctrl+C e os cenários.

A interface (``sh_analyzer_gui``) usa este pacote; ele não sabe do Qt (``tests/test_arquitetura.py`` confere)."""
