"""A BeagleBone vista do computador (docs/gui-plan.md, seção 11), sem Qt: o cliente do agente da placa
(``firmware/agente/shan_agente.py``), o estado e o diagnóstico dela, e o simulador.

* :mod:`.agente` -- roda o agente por um transporte (hoje, local; o SSH vem na Fase 3) e confere a resposta;
* :mod:`.estado` -- o estado da placa e o diagnóstico (o que está errado e como corrigir);
* :mod:`.laco` -- o laço ``asyncio`` numa thread só dele, onde toda a rede da placa roda (a interface chega a ele
  pela ponte ``sh_analyzer_gui/servicos/placa.py``);
* :mod:`.simulador` -- um sistema de arquivos falso de BeagleBone, com cenários, em que o agente de verdade roda: para
  desenvolver e demonstrar sem a placa, e para os testes.

A interface (``sh_analyzer_gui``) usa este pacote; ele não sabe do Qt (``tests/test_arquitetura.py`` confere)."""
