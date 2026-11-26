"""Os primeiros passos (F7.11, GE-07; docs/gui-progress.md, 4h): o cartão que leva do nada à primeira medida na
primeira vez que o aplicativo abre (e quando o usuário o pede, pela paleta ou pelo guia).

Os passos: abrir a captura de exemplo (gerada na hora, na pasta do cache, pela placa simulada: a bancada do projeto
com os supraharmônicos de uma casa), plotar a tensão, medir com os cursores, abrir o espectro e, se quiser,
experimentar a aquisição com a placa simulada. Cada passo se marca sozinho quando o estado da janela mostra que foi
feito (com uma captura do usuário no lugar do exemplo também); o botão de cada um faz o passo por ele.

O cartão mora no canto de baixo à direita da janela inteira (acima da barra de status), por cima dos painéis, e não
bloqueia nada; o "Recolher" o deixa só com o título e o progresso ("2 de 4"), no mesmo canto. Fechado (ou concluído),
ele não volta sozinho: a configuração :data:`CHAVE_DOS_PRIMEIROS_PASSOS` guarda que já foi visto.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, Qt, QTimer
from PySide6.QtWidgets import (QFrame, QGridLayout, QHBoxLayout, QLabel, QMainWindow, QPushButton, QVBoxLayout,
                               QWidget)

from ..configuracao import gravar, ler_texto
from ..tema.aplicar import aparencia

CHAVE_DOS_PRIMEIROS_PASSOS = "ajuda/primeiros_passos"
VISTOS = "vistos"
NOME_DO_EXEMPLO = "exemplo-rede-60Hz.bin"
MARGEM = 16
INTERVALO_MS = 400


def ja_vistos() -> bool:
    return ler_texto(CHAVE_DOS_PRIMEIROS_PASSOS, "") == VISTOS


def marcar_vistos() -> None:
    gravar(CHAVE_DOS_PRIMEIROS_PASSOS, VISTOS)


def gerar_exemplo(pasta: Path) -> Path:
    """A captura de exemplo em ``pasta/exemplos`` (gerada uma vez; a janela passa a pasta do cache, que se refaz, e
    não a dos dados do laboratório): 2 blocos da placa simulada, a corrente no canal 0 e a tensão da tomada no
    canal 1."""
    from sh_placa.capturas_simuladas import Sistema, gravar_captura

    caminho = Path(pasta) / "exemplos" / NOME_DO_EXEMPLO
    if not caminho.is_file():
        gravar_captura(caminho, inicio=time.time() - 60, blocos=2, sistema=Sistema("", "", ""),
                       titulo="Exemplo: a bancada do projeto",
                       descricao="A rede de 60 Hz com os supraharmônicos de um inversor (16 kHz), de drivers de LED "
                                 "(~40 kHz) e de uma comunicação pela rede (72 kHz)")
    return caminho


@dataclass
class Passo:
    id: str
    titulo: str
    texto: str
    botao: str
    feito: Callable[[], bool]
    fazer: Callable[[], None]
    opcional: bool = False


class PrimeirosPassos(QFrame):
    """O cartão. ``passos`` dá a lista (a janela monta os passos com as ações dela); ``parent``, a janela (o cartão
    fica no canto de baixo à direita dela, acima da barra de status)."""

    def __init__(self, passos: list[Passo], parent: QWidget):
        super().__init__(parent)
        self.setObjectName("primeiros_passos")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.passos = passos
        self.titulo = QLabel(self.tr("<b>Primeiros passos</b>"))
        self.titulo.setObjectName("titulo_primeiros_passos")
        self.recolher = QPushButton(self.tr("Recolher"))
        self.recolher.setObjectName("recolher_primeiros_passos")
        self.recolher.setFlat(True)
        self.recolher.setToolTip(self.tr("Deixa só o título e o progresso no canto; clique de novo para ver os passos"))
        self.recolher.clicked.connect(lambda: self.definir_recolhido(not self.recolhido))
        fechar = QPushButton(self.tr("Fechar"))
        fechar.setObjectName("fechar_primeiros_passos")
        fechar.setFlat(True)
        fechar.clicked.connect(self.encerrar)
        cabecalho = QHBoxLayout()
        cabecalho.addWidget(self.titulo)
        cabecalho.addStretch(1)
        cabecalho.addWidget(self.recolher)
        cabecalho.addWidget(fechar)
        self.corpo = QWidget()
        grade = QGridLayout(self.corpo)
        grade.setContentsMargins(0, 4, 0, 0)
        grade.setHorizontalSpacing(10)
        grade.setVerticalSpacing(8)
        self.marcas: dict[str, QLabel] = {}
        self.botoes: dict[str, QPushButton] = {}
        for linha, passo in enumerate(passos):
            marca = QLabel("○")
            marca.setObjectName(f"marca_{passo.id}")
            texto = QLabel(f"<b>{passo.titulo}</b>" + (self.tr(" (opcional)") if passo.opcional else "") +
                           f"<br>{passo.texto}")
            texto.setWordWrap(True)
            texto.setMinimumWidth(240)
            botao = QPushButton(passo.botao)
            botao.setObjectName(f"passo_{passo.id}")
            botao.clicked.connect(passo.fazer)
            grade.addWidget(marca, linha, 0, Qt.AlignmentFlag.AlignTop)
            grade.addWidget(texto, linha, 1)
            grade.addWidget(botao, linha, 2, Qt.AlignmentFlag.AlignTop)
            self.marcas[passo.id], self.botoes[passo.id] = marca, botao
        self.concluido = QLabel(self.tr("Pronto: você abriu, plotou, mediu e viu o espectro. O \"?\" de cada painel "
                                        "e de cada vista abre a ajuda dele (F1: a da vista à frente)."))
        self.concluido.setObjectName("primeiros_passos_concluidos")
        self.concluido.setWordWrap(True)
        self.concluido.hide()
        coluna = QVBoxLayout(self)
        coluna.setContentsMargins(14, 10, 14, 12)
        coluna.addLayout(cabecalho)
        coluna.addWidget(self.corpo)
        coluna.addWidget(self.concluido)
        self.setFixedWidth(440)
        self.recolhido = False
        self._relogio = QTimer(self)
        self._relogio.setInterval(INTERVALO_MS)
        self._relogio.timeout.connect(self.conferir)
        parent.installEventFilter(self)
        aparencia().mudou.connect(self._tema_mudou)
        self._tema_mudou(aparencia().tema)

    def _tema_mudou(self, t) -> None:
        """O fundo elevado e a borda do tema (o cartão fica por cima das vistas: sem fundo, o gráfico aparecia
        através dele); o passo feito na cor de ok."""
        self.setStyleSheet(f"#primeiros_passos {{ background: {t.elevada}; border: 1px solid {t.borda_forte}; "
                           f"border-radius: 8px; }} #primeiros_passos QLabel {{ background: transparent; }} "
                           f"#primeiros_passos QLabel[feito=\"true\"] {{ color: {t.ok}; }}")

    # ------------------------------------------------------------------ o estado

    def feitos(self) -> dict[str, bool]:
        estado = {}
        for p in self.passos:
            try:
                estado[p.id] = bool(p.feito())
            except Exception:       # um passo que não sabe responder agora (o projeto trocando) conta como não feito
                estado[p.id] = False
        return estado

    def conferir(self) -> None:
        """Marca os passos feitos e habilita só o próximo; com os obrigatórios feitos, diz que acabou."""
        estado = self.feitos()
        proximo = next((p.id for p in self.passos if not estado[p.id] and not p.opcional), None)
        for p in self.passos:
            marca = self.marcas[p.id]
            marca.setText("✓" if estado[p.id] else "○")
            if marca.property("feito") != estado[p.id]:
                marca.setProperty("feito", estado[p.id])
                marca.style().unpolish(marca)
                marca.style().polish(marca)
            self.botoes[p.id].setEnabled(not estado[p.id] and (p.id == proximo or p.opcional))
        self.concluido.setVisible(proximo is None and not self.recolhido)
        obrigatorios = [p for p in self.passos if not p.opcional]
        feitos = sum(estado[p.id] for p in obrigatorios)
        self.titulo.setText(self.tr("<b>Primeiros passos</b>") + (
            self.tr(" · {0} de {1}").format(feitos, len(obrigatorios)) if self.recolhido else ""))
        self.adjustSize()
        self._posicionar()

    def definir_recolhido(self, recolhido: bool) -> None:
        """Recolhe o cartão (só o título com o progresso) ou o abre de novo, no mesmo canto."""
        self.recolhido = recolhido
        self.corpo.setVisible(not recolhido)
        self.recolher.setText(self.tr("Ver os passos") if recolhido else self.tr("Recolher"))
        self.setFixedWidth(300 if recolhido else 440)
        self.conferir()

    def mostrar(self) -> None:
        self.conferir()
        self.show()
        self.raise_()
        self._relogio.start()

    def encerrar(self) -> None:
        """Fecha o cartão e lembra que foi visto (ele volta pela paleta ou pelo guia)."""
        marcar_vistos()
        self._relogio.stop()
        self.hide()

    # ------------------------------------------------------------------ o lugar

    def _posicionar(self) -> None:
        """No canto de baixo à direita da janela, acima da barra de status (se a janela tiver uma à vista)."""
        pai = self.parentWidget()
        if pai is None:
            return
        baixo = pai.height()
        if isinstance(pai, QMainWindow) and pai.statusBar().isVisible():
            baixo -= pai.statusBar().height()
        self.move(max(MARGEM, pai.width() - self.width() - MARGEM), max(MARGEM, baixo - self.height() - MARGEM))
        self.raise_()

    def eventFilter(self, objeto: QObject, evento: QEvent) -> bool:
        if objeto is self.parentWidget() and evento.type() == QEvent.Type.Resize and self.isVisible():
            self._posicionar()
        return False
