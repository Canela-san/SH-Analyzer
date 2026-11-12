"""A interface gráfica do SH-Analyzer (``sh-analyzer-gui``), em PySide6.

O plano está em ``docs/gui-plan.md``. A regra de dependência: esta interface chama o motor (o pacote
``supraharmonicos``, o mesmo da linha de comando), e o motor nunca importa o Qt (``tests/test_arquitetura.py``
confere). Um número na tela é o número da CLI.

Para abrir: ``uv run --extra gui sh-analyzer-gui`` ou ``python -m sh_analyzer_gui``.
"""
