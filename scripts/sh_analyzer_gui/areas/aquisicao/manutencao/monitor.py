"""O monitor da placa, na página Sistema (a F6.6): o processador, a memória em uso, a temperatura e a carga ao vivo,
cada um no seu gráfico (uma medida por gráfico, a linha fina na cor do acento, a grade discreta; passar o mouse mostra
o valor e quando), os processos que mais pesam e o ``ler_adc`` que roda sem esta janela, com "Parar…".
"""

from __future__ import annotations

import time

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ....componentes.basicos import Botao
from ....componentes.numeros import formatar_bytes
from ....servicos.monitor_da_placa import AMOSTRAS_GUARDADAS, INTERVALO_DO_MONITOR_S, MonitorDaPlaca
from ....tema.aplicar import aparencia
from ..pecas import fonte
from ..textos import frase, traduzir
from .comuns import texto

JANELA_S = AMOSTRAS_GUARDADAS * INTERVALO_DO_MONITOR_S


def _numero(valor: float, casas: int) -> str:
    return f"{valor:.{casas}f}".replace(".", ",")


class GraficoDoMonitor(QWidget):
    """Uma medida dos últimos :data:`JANELA_S` segundos: o título e o valor de agora no alto, a linha de 2 px na cor do
    acento, três linhas de grade com a escala à direita; passar o mouse marca o ponto mais perto, com o valor e há
    quanto tempo."""

    def __init__(self, titulo: str, unidade: str, minimo: float, maximo: float | None, casas: int = 0,
                 maximo_minimo: float = 1.0, parent: QWidget | None = None):
        super().__init__(parent)
        self.titulo, self.unidade, self.casas = titulo, unidade, casas
        self.minimo, self.maximo, self.maximo_minimo = minimo, maximo, maximo_minimo
        self.pontos: list[tuple[float, float]] = []          # (a hora monotônica de chegada, o valor)
        self.aviso = ""                                       # sem pontos: o porquê (a placa não informa)
        self.agora = time.monotonic()
        self._mouse: float | None = None
        self.setMouseTracking(True)
        self.setMinimumHeight(120)
        aparencia().mudou.connect(self._tema_mudou)

    def _tema_mudou(self, _tema) -> None:
        self.update()

    def definir(self, pontos: list[tuple[float, float]], agora: float | None = None) -> None:
        self.pontos = [(t, v) for t, v in pontos if v is not None]
        self.agora = time.monotonic() if agora is None else agora
        self.update()

    def texto_do_valor(self, valor: float | None) -> str:
        if valor is None:
            return "—"
        return f"{_numero(valor, self.casas)}{(' ' + self.unidade) if self.unidade and self.unidade != '%' else self.unidade}"

    @property
    def valor_atual(self) -> float | None:
        return self.pontos[-1][1] if self.pontos else None

    def _escala(self) -> tuple[float, float]:
        if self.maximo is not None:
            return self.minimo, self.maximo
        maior = max((v for _t, v in self.pontos), default=self.minimo)
        return self.minimo, max(self.maximo_minimo, maior * 1.2)

    def _area(self) -> QRectF:
        return QRectF(4, 26, max(10, self.width() - 52), max(10, self.height() - 34))

    def paintEvent(self, _evento) -> None:
        tema = aparencia().tema
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        area = self._area()
        baixo, alto = self._escala()

        def y_de(valor: float) -> float:
            return area.bottom() - (min(max(valor, baixo), alto) - baixo) / ((alto - baixo) or 1) * area.height()

        def x_de(t: float) -> float:
            return area.right() - (self.agora - t) / JANELA_S * area.width()

        # o título (texto secundário) e o valor de agora (texto, em destaque)
        p.setFont(fonte("secundario"))
        p.setPen(QColor(tema.texto2))
        p.drawText(QRectF(4, 0, self.width() - 8, 20), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   self.titulo)
        p.setFont(fonte("corpo", QFont.Weight.DemiBold))
        p.setPen(QColor(tema.texto))
        p.drawText(QRectF(4, 0, self.width() - 8, 20), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                   self.texto_do_valor(self.valor_atual))

        # a grade e a escala, discretas
        p.setFont(fonte("legenda"))
        for fracao in (0.0, 0.5, 1.0):
            valor = baixo + fracao * (alto - baixo)
            y = y_de(valor)
            p.setPen(QPen(QColor(tema.grade), 1))
            p.drawLine(QPointF(area.left(), y), QPointF(area.right(), y))
            p.setPen(QColor(tema.mudo))
            p.drawText(QRectF(area.right() + 6, y - 8, 44, 16), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                       _numero(valor, 0 if alto - baixo >= 10 else 1))

        # a linha (ou, sem pontos, o porquê)
        visiveis = [(t, v) for t, v in self.pontos if self.agora - t <= JANELA_S]
        if not visiveis and self.aviso:
            p.setFont(fonte("secundario"))
            p.setPen(QColor(tema.mudo))
            p.drawText(area, Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, self.aviso)
        if len(visiveis) >= 2:
            caminho = QPainterPath(QPointF(x_de(visiveis[0][0]), y_de(visiveis[0][1])))
            for t, v in visiveis[1:]:
                caminho.lineTo(QPointF(x_de(t), y_de(v)))
            caneta = QPen(QColor(tema.acento), 2)
            caneta.setCapStyle(Qt.PenCapStyle.RoundCap)
            caneta.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            p.setPen(caneta)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(caminho)

        # o ponto sob o mouse: a linha vertical, o ponto com o anel da superfície e o valor com a hora
        if self._mouse is not None and visiveis:
            t, v = min(visiveis, key=lambda tv: abs(x_de(tv[0]) - self._mouse))
            x, y = x_de(t), y_de(v)
            p.setPen(QPen(QColor(tema.borda_forte), 1))
            p.drawLine(QPointF(x, area.top()), QPointF(x, area.bottom()))
            p.setPen(QPen(QColor(tema.superficie), 2))
            p.setBrush(QColor(tema.acento))
            p.drawEllipse(QPointF(x, y), 4.5, 4.5)
            rotulo = traduzir("{} · há {} s").format(self.texto_do_valor(v), int(round(self.agora - t)))
            p.setFont(fonte("secundario"))
            largura = p.fontMetrics().horizontalAdvance(rotulo) + 16
            caixa = QRectF(min(max(x - largura / 2, area.left()), area.right() - largura), area.top() + 2, largura, 22)
            p.setPen(QPen(QColor(tema.borda), 1))
            p.setBrush(QColor(tema.elevada))
            p.drawRoundedRect(caixa, 6, 6)
            p.setPen(QColor(tema.texto))
            p.drawText(caixa, Qt.AlignmentFlag.AlignCenter, rotulo)
        p.end()

    def mouseMoveEvent(self, evento) -> None:
        self._mouse = evento.position().x()
        self.update()

    def leaveEvent(self, _evento) -> None:
        self._mouse = None
        self.update()


class CartaoDoMonitor(QFrame):
    """O monitor na página Sistema: os quatro gráficos, os processos que mais pesam e o ``ler_adc`` esquecido.
    ``pararCaptura`` pede à seção o diálogo do "Parar…"."""

    pararCaptura = Signal()

    def __init__(self, monitor: MonitorDaPlaca, captura_rodando=None, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("item_do_diagnostico")
        self.monitor = monitor
        self.captura_rodando = captura_rodando or (lambda: False)
        titulo = QLabel(traduzir("Monitor"))
        titulo.setFont(fonte("corpo", QFont.Weight.DemiBold))
        self.situacao = texto("", "texto_mudo")
        self.situacao.setFont(fonte("secundario"))
        self.ao_vivo = Botao(traduzir("Ao vivo"), "fantasma")
        self.ao_vivo.setObjectName("monitor_ao_vivo")
        self.ao_vivo.setCheckable(True)
        self.ao_vivo.setChecked(True)
        self.ao_vivo.setToolTip(traduzir("Desligue durante uma captura delicada: cada amostra custa um pouco do núcleo "
                                         "único da placa."))
        self.ao_vivo.toggled.connect(self._ligar)
        topo = QHBoxLayout()
        topo.addWidget(titulo)
        topo.addWidget(self.situacao, 1)
        topo.addWidget(self.ao_vivo)
        self.graficos = {
            "cpu": GraficoDoMonitor(traduzir("Processador"), "%", 0, 100),
            "memoria": GraficoDoMonitor(traduzir("Memória em uso"), "%", 0, 100),
            "temperatura": GraficoDoMonitor(traduzir("Temperatura"), "°C", 20, None, 1, maximo_minimo=80),
            "carga": GraficoDoMonitor(traduzir("Carga (1 min)"), "", 0, None, 2, maximo_minimo=2),
        }
        grade = QGridLayout()
        grade.setHorizontalSpacing(16)
        grade.setVerticalSpacing(10)
        for i, grafico in enumerate(self.graficos.values()):
            grade.addWidget(grafico, i // 2, i % 2)

        # o ler_adc que roda sem esta janela
        self.captura, corpo_da_captura = QFrame(), QHBoxLayout()
        self.captura.setObjectName("cartao_pendente")
        self.captura.setLayout(corpo_da_captura)
        corpo_da_captura.setContentsMargins(12, 8, 12, 8)
        self.texto_da_captura = texto("", "resumo_do_item")
        self.parar = Botao(traduzir("Parar…"), "perigo")
        self.parar.setObjectName("parar_o_ler_adc")
        self.parar.clicked.connect(self.pararCaptura.emit)
        corpo_da_captura.addWidget(self.texto_da_captura, 1)
        corpo_da_captura.addWidget(self.parar, 0, Qt.AlignmentFlag.AlignVCenter)
        self.captura.hide()

        rotulo_dos_processos = QLabel(traduzir("Os processos que mais pesam"))
        rotulo_dos_processos.setFont(fonte("secundario", QFont.Weight.DemiBold))
        self.processos = QTableWidget(0, 5)
        self.processos.setObjectName("processos_da_placa")
        self.processos.setHorizontalHeaderLabels([traduzir("PID"), traduzir("Dono"), traduzir("Processador"),
                                                  traduzir("Memória"), traduzir("Comando")])
        self.processos.verticalHeader().hide()
        self.processos.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.processos.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.processos.setShowGrid(False)
        cabecalho = self.processos.horizontalHeader()
        for coluna in range(4):
            cabecalho.setSectionResizeMode(coluna, QHeaderView.ResizeMode.ResizeToContents)
        cabecalho.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.processos.setFixedHeight(8 * 26 + 30)

        coluna = QVBoxLayout(self)
        coluna.setContentsMargins(14, 12, 14, 12)
        coluna.setSpacing(10)
        coluna.addLayout(topo)
        coluna.addLayout(grade)
        coluna.addWidget(self.captura)
        coluna.addWidget(rotulo_dos_processos)
        coluna.addWidget(self.processos)
        monitor.amostraNova.connect(self._amostra)
        monitor.monitorMudou.connect(self._estado)
        monitor.processosMudaram.connect(self._processos)
        self._estado()
        self._processos()

    def ligar(self, visivel: bool) -> None:
        """A página apareceu (ou sumiu): o monitor roda só à vista, e só com o "Ao vivo"."""
        self.monitor.ligar_monitor(visivel and self.ao_vivo.isChecked())

    def _ligar(self, ligado: bool) -> None:
        if self.isVisible():
            self.monitor.ligar_monitor(ligado)
        self._estado()

    def _estado(self) -> None:
        m = self.monitor
        if m.erro_do_monitor:
            self.situacao.setText(frase(m.erro_do_monitor))
        elif m.monitorando:
            self.situacao.setText(traduzir("a cada {} s, os últimos {} min").format(
                _numero(INTERVALO_DO_MONITOR_S, 0), int(JANELA_S // 60)))
        else:
            self.situacao.setText(traduzir("parado"))
        self._amostra()

    def _amostra(self, _amostra=None) -> None:
        amostras = list(self.monitor.amostras)
        agora = time.monotonic()

        def serie(funcao):
            pontos = []
            for a in amostras:
                try:
                    pontos.append((a["recebida"], funcao(a)))
                except (KeyError, TypeError, ZeroDivisionError):
                    continue
            return pontos

        self.graficos["cpu"].definir(serie(lambda a: a["cpu"]), agora)
        self.graficos["memoria"].definir(
            serie(lambda a: 100.0 * (a["memoria_kib"] - a["disponivel_kib"]) / a["memoria_kib"]), agora)
        temperatura = self.graficos["temperatura"]
        temperatura.definir(serie(lambda a: a["temperatura_c"]), agora)
        temperatura.aviso = traduzir("esta placa não informa a temperatura (o kernel não tem o sensor do AM335x)") \
            if len(amostras) >= 3 and not temperatura.pontos else ""
        self.graficos["carga"].definir(serie(lambda a: a["carga"]), agora)

    def _processos(self) -> None:
        p = self.monitor.processos or {}
        lista = p.get("processos") or []
        self.processos.setRowCount(len(lista))
        for i, processo in enumerate(lista):
            valores = [str(processo.get("pid", "")), processo.get("dono") or str(processo.get("uid") or ""),
                       f"{_numero(processo.get('cpu') or 0.0, 1)} %",
                       formatar_bytes((processo.get("memoria_kib") or 0) * 1024),
                       processo.get("linha") or processo.get("nome") or ""]
            for j, valor in enumerate(valores):
                item = QTableWidgetItem(valor)
                if j in (0, 2, 3):
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.processos.setItem(i, j, item)
        capturas = self.monitor.capturas
        alheia = bool(capturas) and not self.captura_rodando()
        self.captura.setVisible(alheia)
        if alheia:
            descricao = "; ".join(f"PID {c.pid}: {c.linha[:80]}" for c in capturas[:3])
            self.texto_da_captura.setText(traduzir(
                "Um ler_adc roda na placa sem esta janela ({}). Ele segura a PRU: outra captura não começa enquanto "
                "ele roda.").format(descricao))
