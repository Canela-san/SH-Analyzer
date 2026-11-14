"""O chip de traço da legenda (docs/gui-plan.md, 9.3): a cor, o nome, o resumo das transformações, durante uma
materialização o progresso e, à direita, o cadeado da escala própria (``graficos/escalas.py``: aberto se o traço está
destravado; fechado e discreto se ele está travado numa escala que não é a comum) e o sinal dos avisos do traço
(``dados/avisos.py``: a sonda, a faixa suposta, uma etapa que não serve), na cor do mais grave, com a lista na dica.
Pintado com ``QPainter`` a partir do tema; clicar seleciona."""

from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QSizePolicy, QWidget

from ..dados.avisos import pior_nivel
from ..tema.aplicar import aparencia
from ..tema.icones import icone
from ..tema.tokens import TAMANHOS, cor_do_traco

ALTURA = 24
RAIO = 6
MARGEM = 8
PONTO = 8
VAO = 6
ICONE = 14
NIVEIS_COM_SINAL = ("aviso", "erro")      # pintados na cor do tema de mesmo nome; um "info" fica só na dica


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
        self.avisos: tuple = ()
        self.escala: str | None = None          # "solta", "propria" ou None (ver o começo do arquivo)
        self._sinal: tuple[str, float, QPixmap] | None = None     # o ícone pintado: a cor, a escala e o desenho
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
        self._sinal = None
        self.update()

    def definir(self, *, selecionado: bool | None = None, visivel: bool | None = None,
                progresso: float | None | type(...) = ..., resumo: str | None = None,
                avisos=None, escala: str | None | type(...) = ...) -> None:
        """``avisos``: os ``Aviso`` do traço (a lista inteira, que substitui a anterior). ``escala``: ``"solta"``,
        ``"propria"`` ou None."""
        if selecionado is not None:
            self.selecionado = selecionado
        if visivel is not None:
            self.visivel = visivel
        if progresso is not ...:
            self.progresso = None if progresso is None else min(1.0, max(0.0, float(progresso)))
        if resumo is not None:
            self.resumo = resumo
            self.updateGeometry()
        mudou_a_dica = False
        if avisos is not None and tuple(avisos) != self.avisos:
            self.avisos = tuple(avisos)
            mudou_a_dica = True
        if escala is not ... and escala != self.escala:
            if escala not in (None, "solta", "propria"):
                raise ValueError(f"estado da escala desconhecido: {escala!r}")
            self.escala = escala
            mudou_a_dica = True
        if mudou_a_dica:
            linhas = [f"• {a.texto}" for a in self.avisos]
            if self.escala == "solta":
                linhas.append(self.tr("Escala própria (destravada): o zoom e o pan do Y com ele selecionado são só "
                                      "dele"))
            elif self.escala == "propria":
                linhas.append(self.tr("Numa escala própria (travada): anda com os outros; \"Mesma escala\" a "
                                      "devolve à comum"))
            texto = "\n".join(linhas)
            self.setToolTip(texto)
            self.setAccessibleDescription(texto)
            self.updateGeometry()
        self.update()

    @property
    def nivel(self) -> str | None:
        """O nível do sinal pintado (``"aviso"`` ou ``"erro"``), ou None sem sinal."""
        nivel = pior_nivel(self.avisos)
        return nivel if nivel in NIVEIS_COM_SINAL else None

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
        if self.nivel is not None:
            largura += VAO + ICONE
        if self.escala is not None:
            largura += VAO + ICONE
        return QSize(largura, ALTURA)

    def _pixmap_do_sinal(self, cor: str) -> QPixmap:
        escala = self.devicePixelRatioF()
        if self._sinal is None or self._sinal[:2] != (cor, escala):
            self._sinal = (cor, escala, icone("alerta", cor, ICONE).pixmap(QSize(ICONE, ICONE), escala))
        return self._sinal[2]

    def _pixmap_do_cadeado(self, t) -> QPixmap:
        nome, cor = ("cadeado_aberto", t.acento) if self.escala == "solta" else ("cadeado", t.mudo)
        return icone(nome, cor, ICONE).pixmap(QSize(ICONE, ICONE), self.devicePixelRatioF())

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
        direita = self.width() - MARGEM
        nivel = self.nivel
        if nivel is not None:
            direita -= ICONE
            p.drawPixmap(int(direita), (ALTURA - ICONE) // 2, self._pixmap_do_sinal(getattr(t, nivel)))
            direita -= VAO
        if self.escala is not None:
            direita -= ICONE
            p.drawPixmap(int(direita), (ALTURA - ICONE) // 2, self._pixmap_do_cadeado(t))
            direita -= VAO
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
            p.drawText(QRectF(x, 0, direita - x + 2, ALTURA), Qt.AlignmentFlag.AlignVCenter, self.resumo)
        p.end()
