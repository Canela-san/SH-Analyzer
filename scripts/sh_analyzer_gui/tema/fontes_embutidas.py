"""A lista das fontes embutidas em ``sh_analyzer_gui/recursos/fontes/`` (docs/gui-plan.md, 12.4 e 15): de onde veio
cada uma, a versão, os arquivos, a licença e o papel (``"interface"`` ou ``"mono"``).

``tests/test_tema.py`` confere que os arquivos e as licenças estão na pasta e que nenhum arquivo de fonte sobrou sem
entrada aqui. Para pôr uma fonte nova (para o usuário escolher nas configurações): os arquivos e a licença na pasta,
e uma entrada em :data:`EMBUTIDAS`. Só licenças livres que permitem embutir: OFL, Apache, MIT.

**Por que a Inter variável:** o Google Fonts distribui a Inter estática com o tamanho óptico no nome da família
("Inter 18pt", "Inter 18pt SemiBold"...); a variável se registra como "Inter", com todos os pesos, num arquivo menor
que quatro estáticos.

Sem Qt: roda e se testa sem interface.
"""

from __future__ import annotations

from dataclasses import dataclass

PAPEIS = ("interface", "mono")


@dataclass(frozen=True)
class FonteEmbutida:
    familia: str                  # o nome com que o Qt registra a fonte
    papel: str                    # "interface" ou "mono"
    arquivos: tuple[str, ...]     # em recursos/fontes/
    licenca: str                  # o arquivo da licença, em recursos/fontes/
    tipo_de_licenca: str
    versao: str
    origem: str


EMBUTIDAS = (
    FonteEmbutida("Inter", "interface", ("Inter-VariableFont.ttf",), "Inter-OFL.txt", "OFL-1.1", "4.001",
                  "Google Fonts (fonts.google.com/specimen/Inter): o arquivo Inter-VariableFont_opsz,wght.ttf"),
    FonteEmbutida("JetBrains Mono", "mono",
                  ("JetBrainsMono-Regular.ttf", "JetBrainsMono-Medium.ttf", "JetBrainsMono-Bold.ttf"),
                  "JetBrainsMono-OFL.txt", "OFL-1.1", "2.304",
                  "jetbrains.com/lp/mono: JetBrainsMono-2.304.zip, pasta fonts/ttf"),
)
