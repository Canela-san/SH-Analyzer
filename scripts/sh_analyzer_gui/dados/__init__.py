"""A camada de dados da interface: o que transforma uma captura de gigabytes em ~1 600 colunas por quadro.

Nada aqui importa o Qt (``tests/test_arquitetura.py`` confere): roda e se testa sem interface gráfica, e pode ser
usado por qualquer outra frente (um script, um notebook, a CLI).

* :mod:`.piramide` -- os mínimos e máximos de blocos cada vez maiores de um sinal (docs/gui-plan.md, seção 6.4);
* :mod:`.cache` -- o arquivo da pirâmide no disco e o cache que evita refazê-la ao reabrir a captura.
"""
