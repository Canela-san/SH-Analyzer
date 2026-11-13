"""A galeria de componentes (docs/gui-plan.md, 12.8): uma janela de desenvolvimento com todos os componentes, nos dois
temas, para ver, comparar com os mockups e testar. Abra com ``python -m sh_analyzer_gui.galeria`` (da raiz do
repositório: ``uv run --extra gui python -m sh_analyzer_gui.galeria``)."""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QHBoxLayout, QLabel, QMainWindow, QScrollArea, QVBoxLayout, QWidget

from .app import criar_aplicacao
from .componentes.basicos import Botao, CampoComUnidade, CartaoDeMedida, Segmentado
from .componentes.chip import ChipDeTraco
from .componentes.toast import Toast
from .tema.aplicar import aparencia
from .tema.tokens import TAMANHOS


class Galeria(QMainWindow):
    """Os componentes em seções; o botão do topo troca o tema."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("SH-Analyzer · galeria de componentes")
        self.resize(980, 760)
        conteudo = QWidget()
        self._coluna = QVBoxLayout(conteudo)
        self._coluna.setContentsMargins(24, 20, 24, 24)
        self._coluna.setSpacing(10)

        topo = QHBoxLayout()
        titulo = QLabel("Galeria de componentes")
        fonte = titulo.font()
        fonte.setPixelSize(TAMANHOS["tela"])
        fonte.setBold(True)
        titulo.setFont(fonte)
        topo.addWidget(titulo)
        topo.addStretch(1)
        self.botao_tema = Botao("Trocar o tema", "secundario", "lua")
        self.botao_tema.clicked.connect(lambda: aparencia().alternar())
        topo.addWidget(self.botao_tema)
        self._coluna.addLayout(topo)

        self.botoes = [Botao("Nova captura", "primario", "play"), Botao("Exportar", "secundario", "baixar"),
                       Botao("Cancelar", "fantasma"), Botao("Apagar da placa", "perigo", "x")]
        self._secao("Botões", self.botoes)

        self.campos = [CampoComUnidade("Hz", 400_000, minimo=1, maximo=500_000),
                       CampoComUnidade("V", 1.2e-3), CampoComUnidade("s", 0.0105, digitos=3)]
        self._secao("Campo numérico com unidade (aceita 2,5k, 2500, 1,2 mV)", self.campos)

        self.segmentados = [Segmentado(["Envoltória", "Densidade"]), Segmentado(["FFT", "Welch", "IEC 200 Hz"], 1)]
        self._secao("Seletor segmentado", self.segmentados)

        self.chips = [ChipDeTraco("V_A · 09h30", 0, "sonda · −DC"), ChipDeTraco("V_A · 14h10", 3, "+4,2 ms"),
                      ChipDeTraco("I_A · 09h30", 1), ChipDeTraco("V_A · supra", 2, "passa-altas 2 kHz")]
        self.chips[0].definir(selecionado=True)
        self.chips[2].definir(visivel=False)
        self.chips[3].definir(progresso=0.62)
        for chip in self.chips:
            chip.clicado.connect(lambda c=chip: [x.definir(selecionado=x is c) for x in self.chips])
        self._secao("Chips de traço (clique para selecionar)", self.chips)

        self.cartoes = [CartaoDeMedida("RMS", 98.7, "V"), CartaoDeMedida("f₁", 59.998, "Hz", digitos=5),
                        CartaoDeMedida("Supra 2–150 kHz", 3.92, "V"), CartaoDeMedida("Potência ativa", 2214, "W")]
        self._secao("Cartões de medida", self.cartoes)

        self.botoes_toast = []
        for nivel, texto in (("info", "Pirâmide pronta"), ("sucesso", "Figura exportada"),
                             ("aviso", "3 capturas não transferidas"), ("erro", "A placa não respondeu")):
            b = Botao(f"Toast: {nivel}", "secundario")
            b.clicked.connect(lambda _=False, n=nivel, x=texto: Toast.mostrar(self.centralWidget(), x, n))
            self.botoes_toast.append(b)
        self._secao("Toasts", self.botoes_toast)
        self._coluna.addStretch(1)

        rolagem = QScrollArea()
        rolagem.setWidgetResizable(True)
        rolagem.setWidget(conteudo)
        rolagem.setFrameShape(QScrollArea.Shape.NoFrame)
        self.setCentralWidget(rolagem)

    def _secao(self, titulo: str, widgets: list[QWidget]) -> None:
        rotulo = QLabel(titulo)
        fonte = rotulo.font()
        fonte.setPixelSize(TAMANHOS["titulo_painel"])
        fonte.setWeight(fonte.Weight.DemiBold)
        rotulo.setFont(fonte)
        rotulo.setContentsMargins(0, 12, 0, 0)
        self._coluna.addWidget(rotulo)
        linha = QHBoxLayout()
        linha.setSpacing(8)
        for w in widgets:
            linha.addWidget(w)
        linha.addStretch(1)
        self._coluna.addLayout(linha)


def main(argv: list[str] | None = None) -> int:
    app = criar_aplicacao(argv)
    galeria = Galeria()
    galeria.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
