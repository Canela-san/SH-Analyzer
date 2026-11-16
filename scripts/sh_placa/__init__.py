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
* :mod:`.laco` -- o laço ``asyncio`` numa thread só dele, onde toda a rede da placa roda (a interface chega a ele
  pela ponte ``sh_analyzer_gui/servicos/placa.py``);
* :mod:`.simulador` -- uma BeagleBone neste computador, servida por SSH, com cenários (o sistema de arquivos falso em
  que o agente de verdade roda): para desenvolver e demonstrar sem a placa, e para os testes;
* :mod:`.capturas_simuladas` -- as capturas da placa simulada: ``.bin`` como o ``ler_adc`` grava, com a rede de 60 Hz
  e os supraharmônicos.

A interface (``sh_analyzer_gui``) usa este pacote; ele não sabe do Qt (``tests/test_arquitetura.py`` confere)."""
