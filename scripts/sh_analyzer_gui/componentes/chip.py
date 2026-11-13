"""O chip de traço da legenda (docs/gui-plan.md, 9.3): a cor, o nome, o resumo das transformações e, durante uma
materialização, o progresso. Pintado com ``QPainter`` a partir do tema; clicar seleciona."""

from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from ..tema.aplicar import aparencia
from ..tema.tokens import TAMANHOS, cor_do_traco

ALTURA = 24
RAIO = 6
MARGEM = 8
PONTO = 8
VAO = 6


class ChipDeTraco(QWidget):
    """``clicado()`` sai num clique. ``selecionado``, ``visivel`` e ``progresso`` (0 a 1, ou ``None``) mudam o
    desenho.

    ``cor`` é a posição do traço na paleta (0, 1, 2...: a cor segue o tema, o mesmo matiz em outro tom) ou uma cor
    fixa (``"#rrggbb"``)."""

    clicado = Signal()

    def __init__(self, nome: str, cor: int | str | QColor, resumo: str = "", parent: QWidget | None = None):
        super().__init__(parent)
        self.nome, self._cor, self.resumo = nome, cor, resumo
        self.selecionado, self.visivel = False, True
        self.progresso: float | None = None
        fonte = self.font()
        fonte.setPixelSize(TAMANHOS["secundario"])
        self.setFont(fonte)
        self._fonte_resumo = self.font()
        self._fonte_resumo.setPixelSize(TAMANHOS["legenda"])
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setAccessibleName(f"traço {nome}")
        # Um método, não uma lambda: o Qt desfaz a conexão sozinho quando o chip é destruído.
        aparencia().mudou.connect(self._tema_mudou)

    def _tema_mudou(self, _tema) -> None:
        self.update()

    def definir(self, *, selecionado: bool | None = None, visivel: bool | None = None,
                progresso: float | None | type(...) = ..., resumo: str | None = None) -> None:
        if selecionado is not None:
            self.selecionado = selecionado
        if visivel is not None:
            self.visivel = visivel
        if progresso is not ...:
            self.progresso = None if progresso is None else min(1.0, max(0.0, float(progresso)))
        if resumo is not None:
            self.resumo = resumo
            self.updateGeometry()
        self.update()

    @property
    def cor(self) -> QColor:
        """A cor no tema em uso."""
        if isinstance(self._cor, int):
            return QColor(cor_do_traco(self._cor, aparencia().tema)[0])
        return QColor(self._cor)

    def sizeHint(self) -> QSize:
        largura = MARGEM + PONTO + VAO + QFontMetrics(self.font()).horizontalAdvance(self.nome) + MARGEM
        if self.resumo:
            largura += VAO + 1 + VAO + QFontMetrics(self._fonte_resumo).horizontalAdvance(self.resumo)
        return QSize(largura, ALTURA)

    def mousePressEvent(self, evento) -> None:
        if evento.button() == Qt.MouseButton.LeftButton:
            self.clicado.emit()
        super().mousePressEvent(evento)

    def paintEvent(self, evento) -> None:
        t = aparencia().tema
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        caixa = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        fundo = QColor(t.superficie)
        p.setPen(QPen(QColor(t.acento if self.selecionado else t.borda), 1.0))
        p.setBrush(fundo)
        p.drawRoundedRect(caixa, RAIO, RAIO)
        if self.progresso is not None:
            suave = QColor(t.acento)
            suave.setAlphaF(0.16)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(suave)
            p.setClipRect(QRectF(caixa.left(), caixa.top(), caixa.width() * self.progresso, caixa.height()))
            p.drawRoundedRect(caixa, RAIO, RAIO)
            p.setClipping(False)
        x = MARGEM
        ponto = QRectF(x, (ALTURA - PONTO) / 2, PONTO, PONTO)
        if self.visivel:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(self.cor)
        else:
            p.setPen(QPen(QColor(t.borda_forte), 1.5))
            p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(ponto)
        x += PONTO + VAO
        p.setPen(QColor(t.texto if self.visivel else t.mudo))
        p.setFont(self.font())
        largura_nome = QFontMetrics(self.font()).horizontalAdvance(self.nome)
        p.drawText(QRectF(x, 0, largura_nome + 1, ALTURA), Qt.AlignmentFlag.AlignVCenter, self.nome)
        if self.resumo:
            x += largura_nome + VAO
            p.setPen(QColor(t.borda))
            p.drawLine(int(x), 6, int(x), ALTURA - 6)
            x += 1 + VAO
            p.setPen(QColor(t.mudo))
            p.setFont(self._fonte_resumo)
            p.drawText(QRectF(x, 0, self.width() - x - MARGEM + 2, ALTURA), Qt.AlignmentFlag.AlignVCenter, self.resumo)
        p.end()
