"""O sistema de design da interface (docs/gui-plan.md, seção 12).

* :mod:`.tokens` -- as cores, os tamanhos e os espaços dos dois temas, definidos uma vez (sem Qt);
* :mod:`.cores` -- as contas que conferem as cores: contraste WCAG e separação em OKLab com daltonismo simulado
  (sem Qt; ``tests/test_tema.py`` as roda sobre os tokens);
* :mod:`.aplicar` -- a ``QPalette`` e a folha QSS geradas dos tokens, e a troca de tema sem reiniciar;
* :mod:`.icones` -- os ícones (traço de 24 px, recoloridos pelo tema);
* :mod:`.fontes` -- as fontes da interface (Inter e JetBrains Mono, embutidas quando estiverem em ``recursos``).
"""
