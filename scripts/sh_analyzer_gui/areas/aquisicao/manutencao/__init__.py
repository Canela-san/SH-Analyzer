"""A seção Manutenção (a Fase 6): ``secao.py`` junta as páginas (``firmware.py``, ``inicializacao.py``,
``sistema.py``); ``comuns.py`` tem as peças delas."""

from .secao import PAGINAS, Manutencao

__all__ = ["PAGINAS", "Manutencao"]
