"""As vistas das bandas IEC e do espectrograma (docs/gui-plan.md, 9.5; ES-03 e ES-04): um traço da vista de tempo
ligada, no tempo.

* **O traço** é um dos traços da vista de tempo ligada (o seletor da barra), com a sua cadeia; **o trecho**, a captura
  inteira (o padrão), a janela visível ou a região dos cursores de lá.
* **O tempo ligado:** o eixo do tempo destas vistas é o mesmo da vista de tempo (``setXLink``): o zoom de uma leva a
  outra, e um afundamento visto na forma de onda está no mesmo lugar do mapa.
* **As bandas** (``VistaDeBandas``): o mapa de calor banda × tempo (o nível RMS de cada banda em cada janela de 200 ms,
  em dB re 1 unidade) e a tabela das estatísticas de cada banda (RMS, P95, máximo, mínimo), em ordem da estatística
  escolhida (a do ``adc_tool --bandas-iec`` é o P95). As janelas fixas de 200 ms ou as sincronizadas à fundamental.
* **O espectrograma** (``VistaDeEspectrograma``): o espectro ao longo do tempo, com o mapa de cores perceptual
  (viridis) e a faixa dinâmica escolhida abaixo do máximo.
* **Os harmônicos** (``VistaDeHarmonicos``, ES-05): as barras e a tabela das ordens da IEC 61000-4-7 (a componente, o
  grupo e o subgrupo, em % da fundamental ou em valor RMS), com o THD, o THDG e o THDS, da janela retangular
  sincronizada pelos cruzamentos por zero (o ``adc_tool --fft --harmonicos``). O trecho padrão é a janela visível.
* **As contas** são as da ``api`` (``dados/espectros.py``), em segundo plano, com o progresso no painel de tarefas numa
  captura longa; cada pedido cancela o anterior.
* **Os cursores C1 e C2** (o botão da barra, ou C): os mesmos da vista de tempo (``graficos/cursores.py``), com as
  setas andando um passo (uma janela, uma coluna, uma ordem); as medidas (os instantes, Δt e 1/Δt; nos harmônicos, as
  ordens e o valor das barras) vão para a tabela de Medidas do painel de baixo.
"""

from __future__ import annotations

import math
from collections.abc import Callable

import numpy as np
import pyqtgraph as pg
import supraharmonicos.api as api
from PySide6.QtCore import QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QHeaderView,
    QLabel,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)
from shiboken6 import isValid

from ...componentes.basicos import CampoComUnidade, Segmentado
from ...componentes.fluxo import LayoutDeFluxo
from ...componentes.numeros import formatar_si
from ...dados import espectros as esp
from ...graficos.cursores import CursoresDaVista
from ...graficos.faixa import EixoDoTema
from ...modelo.comandos import MudarOpcoesDaVista
from ...modelo.objetos import Projeto, Traco, Vista
from ...modelo.selecao import Selecao
from ...tema.aplicar import aparencia
from ...tema.tokens import Tema, cor_do_traco
from .medidas import LinhaDaTabela, MedidasDaVista, numero_para_planilha

ESPERA_MS = 40
TRECHOS = ("captura", "janela", "cursores")
AMOSTRAS_PARA_MOSTRAR_A_TAREFA = 20_000_000
MAPA_DE_CORES = "viridis"


class VistaLigada(QWidget):
    """A base: a vista de tempo ligada, o traço, o trecho e a conta em segundo plano. As subclasses montam o
    conteúdo (``_montar_conteudo``), fazem a conta de um trecho (``_conta``) e desenham o resultado (``_desenhar``)."""

    tracoClicado = Signal(object, object)
    regiaoMudou = Signal(float, float, bool)
    semRegiao = Signal()
    calculado = Signal()
    medidasMudaram = Signal(object)          # MedidasDaVista dos cursores (ou None): a tabela de Medidas

    nome_da_conta = "Conta"
    unidade_x = "s"                 # a unidade do eixo x (o tempo; nos harmônicos, a ordem)

    def __init__(self, vista: Vista, projeto: Projeto, selecao: Selecao, *, tarefas, materializacoes,
                 vista_de_tempo: Callable[[str | None], object], parent: QWidget | None = None):
        super().__init__(parent)
        self.vista, self.projeto, self.selecao = vista, projeto, selecao
        self.tarefas, self.materializacoes, self._achar_vista_de_tempo = tarefas, materializacoes, vista_de_tempo
        self.resultado = None
        self.opcoes_calculadas = None          # as opções que deram o resultado mostrado
        self._chave_calculada = None           # o traço, o trecho e as opções do resultado (para não refazer)
        self.traco: Traco | None = None
        self.trecho_atual: esp.TrechoDoTraco | None = None
        self.erro = ""
        self.aguardando = False
        self._tempo = None
        self._tarefa = None
        self._caixa_ligada = None
        coluna = QVBoxLayout(self)
        coluna.setContentsMargins(0, 0, 0, 0)
        coluna.setSpacing(0)
        barra = QWidget()
        barra.setObjectName("barra_vista")
        politica = QSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        politica.setHeightForWidth(True)
        barra.setSizePolicy(politica)
        self._linha = LayoutDeFluxo(barra, espaco=8)          # quebra em linhas: nada espremido até cortar o texto
        self._linha.setContentsMargins(8, 4, 8, 4)
        self.seletor = QComboBox()
        self.seletor.setObjectName("traco_da_vista")
        self.seletor.setToolTip(self.tr("O traço da vista de tempo"))
        self.seletor.activated.connect(lambda i: self._mudar(traco=int(self.seletor.itemData(i))))
        self.trecho = Segmentado([self.tr("Captura"), self.tr("Janela"), self.tr("Cursores")])
        self.trecho.setToolTip(self.tr("O trecho: a captura inteira, a janela visível da vista de tempo ou a região "
                                       "dos cursores dela"))
        self.trecho.escolhaMudou.connect(lambda i: self._mudar(trecho=TRECHOS[i]))
        self._linha.addWidget(self.seletor)
        self._linha.addWidget(self.trecho)
        coluna.addWidget(barra)
        self._montar_conteudo(coluna)
        self.acao_cursores = QAction(self.tr("Cursores"), self)
        self.acao_cursores.setCheckable(True)
        self.acao_cursores.setShortcut(QKeySequence("C"))
        self.acao_cursores.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self.acao_cursores.setToolTip(self.tr("Os cursores A e B, com a distância entre eles (C)"))
        self.addAction(self.acao_cursores)
        botao = QToolButton()
        botao.setObjectName("botao_cursores")
        botao.setDefaultAction(self.acao_cursores)
        botao.setAutoRaise(True)
        self._linha.addWidget(botao)
        self.cursores = CursoresDaVista(parent=self)
        self.cursores.por_nas([self.grafico.getViewBox()])
        self.cursores.mudou.connect(self.emitir_regiao)
        self.acao_cursores.toggled.connect(self._ligar_cursores)
        for tecla, passos in (("Left", -1), ("Right", 1), ("Shift+Left", -10), ("Shift+Right", 10)):
            andar = QAction(self)
            andar.setShortcut(QKeySequence(tecla))
            andar.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            andar.triggered.connect(lambda _=False, n=passos: self.cursores.andar(n, self._passo_do_cursor()))
            self.addAction(andar)
        self.info = QLabel()
        self.info.setObjectName("info_vista")
        self.info.setWordWrap(True)
        self.info.setContentsMargins(10, 2, 10, 4)
        coluna.addWidget(self.info)
        self._espera = QTimer(self)
        self._espera.setSingleShot(True)
        self._espera.setInterval(ESPERA_MS)
        self._espera.timeout.connect(self._calcular)
        vista.mudou.connect(self._vista_mudou)
        projeto.vistaEntrou.connect(self._vistas_do_projeto)
        projeto.vistaSaiu.connect(self._vistas_do_projeto)
        materializacoes.mudou.connect(self._materializacao_mudou)
        aparencia().mudou.connect(self._tema_mudou)
        self._tema_mudou(aparencia().tema)
        self._mostrar_opcoes()
        self._pedir()

    # ------------------------------------------------------------------ para as subclasses

    def _montar_conteudo(self, coluna: QVBoxLayout) -> None:
        raise NotImplementedError

    def _conta(self, trecho: esp.TrechoDoTraco, progresso, cancelado):
        raise NotImplementedError

    def _desenhar(self) -> None:
        raise NotImplementedError

    def _mostrar_opcoes_proprias(self) -> None:
        pass

    def _novo_grafico(self) -> pg.PlotWidget:
        grafico = pg.PlotWidget(axisItems={"bottom": EixoDoTema("bottom"), "left": EixoDoTema("left")})
        grafico.setMenuEnabled(False)
        grafico.hideButtons()
        grafico.setLabel("bottom", self.tr("tempo"), units="s")
        return grafico

    # ------------------------------------------------------------------ as opções

    @property
    def opcoes(self):
        return self.vista.opcoes

    def _mudar(self, **mudancas) -> bool:
        try:
            nova = self.opcoes.com(**mudancas)
        except esp.OpcoesInvalidas as e:
            self.info.setText(str(e))
            self._mostrar_opcoes()
            return False
        if nova == self.opcoes:
            return False
        self.projeto.pilha.push(MudarOpcoesDaVista(self.vista, nova, juntar=bool(set(mudancas) & {
            "resolucao_hz", "faixa_dinamica_db", "freq_min", "freq_max"})))
        return True

    def _mostrar_opcoes(self) -> None:
        self.trecho.blockSignals(True)
        self.trecho.escolher(TRECHOS.index(self.opcoes.trecho))
        self.trecho.blockSignals(False)
        self._mostrar_opcoes_proprias()

    def _vista_mudou(self, _vista, campos) -> None:
        if "opcoes" in campos and isValid(self):
            self._mostrar_opcoes()
            self._pedir()

    # ------------------------------------------------------------------ a vista de tempo ligada

    def vista_de_tempo(self):
        widget = self._achar_vista_de_tempo(self.opcoes.vista_de_tempo)
        if widget is not self._tempo:
            if self._tempo is not None and isValid(self._tempo):
                for sinal, slot in self._ligacoes():
                    try:
                        sinal.disconnect(slot)
                    except (RuntimeError, TypeError):
                        pass
            self._tempo = widget
            if widget is not None:
                for sinal, slot in self._ligacoes():
                    sinal.connect(slot)
        return widget

    def _ligacoes(self):
        t = self._tempo
        return ((t.regiaoMudou, self._regiao_de_la), (t.vista.tracoEntrou, self._tracos_de_la),
                (t.vista.tracoSaiu, self._tracos_de_la), (t.vista.tracoMudou, self._traco_de_la))

    def _ligar_o_tempo(self, caixa: pg.ViewBox) -> None:
        """O eixo do tempo desta vista segue o da faixa principal da vista de tempo, e o contrário: o mesmo intervalo
        de tempo nas duas (o ``setXLink`` do PyQtGraph alinha pela posição na tela, e as caixas têm larguras
        diferentes)."""
        tempo = self._tempo
        principal = tempo._faixa_principal() if tempo is not None and isValid(tempo) else None
        alvo = principal.getViewBox() if principal is not None else None
        if alvo is self._caixa_ligada:
            return
        if self._caixa_ligada is not None and isValid(self._caixa_ligada):
            try:
                self._caixa_ligada.sigXRangeChanged.disconnect(self._tempo_mudou_la)
            except (RuntimeError, TypeError):
                pass
        if self._caixa_ligada is None:
            caixa.sigXRangeChanged.connect(self._tempo_mudou_aqui)
        self._caixa_ligada, self._caixa_daqui = alvo, caixa
        if alvo is not None:
            alvo.sigXRangeChanged.connect(self._tempo_mudou_la)
            self._tempo_mudou_la(alvo, alvo.viewRange()[0])

    def _copiar_tempo(self, destino: pg.ViewBox, intervalo) -> None:
        if getattr(self, "_copiando", False) or destino is None or not isValid(destino):
            return
        self._copiando = True
        try:
            destino.setXRange(float(intervalo[0]), float(intervalo[1]), padding=0)
        finally:
            self._copiando = False

    def _tempo_mudou_la(self, _caixa, intervalo) -> None:
        if isValid(self):
            self._copiar_tempo(getattr(self, "_caixa_daqui", None), intervalo)

    def _tempo_mudou_aqui(self, _caixa, intervalo) -> None:
        if isValid(self):
            self._copiar_tempo(self._caixa_ligada, intervalo)

    def _vistas_do_projeto(self, *_):
        if isValid(self):
            QTimer.singleShot(0, self._pedir)

    def _regiao_de_la(self, *_):
        if isValid(self) and self.opcoes.trecho != "captura":
            self._pedir()

    def _tracos_de_la(self, *_):
        self._pedir()

    def _traco_de_la(self, traco, campos):
        if campos & {"cadeia", "ganho", "visivel", "nome", "deslocamento_s"}:
            self._pedir()

    def _materializacao_mudou(self, estado) -> None:
        if isValid(self) and self.aguardando and estado.pronta is not None:
            self._pedir()

    # ------------------------------------------------------------------ a conta

    def _pedir(self, *_) -> None:
        if isValid(self):
            self._espera.start()

    def _refazer_seletor(self, tracos) -> int:
        """O seletor com os traços da vista de tempo; devolve a posição do escolhido (ou do primeiro visível)."""
        self.seletor.blockSignals(True)
        self.seletor.clear()
        for i, t in enumerate(tracos):
            self.seletor.addItem(t.nome, i)
        escolhido = self.opcoes.traco if self.opcoes.traco < len(tracos) else 0
        self.seletor.setCurrentIndex(escolhido)
        self.seletor.blockSignals(False)
        return escolhido

    def _calcular(self) -> None:
        if not isValid(self):
            return
        if self._tarefa is not None and self._tarefa.ativa:
            self._tarefa.cancelar()
        tempo = self.vista_de_tempo()
        self.erro, self.aguardando, nota = "", False, ""
        tracos = tempo.vista.tracos if tempo is not None else ()
        if not tracos:
            self.resultado, self.traco, self.trecho_atual = None, None, None
            self.info.setText(self.tr("Nenhum traço na vista de tempo ligada: plote um canal."))
            self._desenhar()
            return
        traco = tracos[self._refazer_seletor(tracos)]
        r = traco.receita
        try:
            fonte = self.projeto.fonte(r.fonte)
        except KeyError:
            return
        if fonte.esta_ausente:
            self.info.setText(self.tr("A captura de {} está ausente.").format(traco.nome))
            return
        canal = fonte.canal(r.canal)
        n = len(canal.amostras)
        a, b = 0, n
        if self.opcoes.trecho != "captura":
            regiao = tempo.janela_de_tempo()
            if self.opcoes.trecho == "cursores":
                if tempo.cursores is None:
                    nota = self.tr("Sem os cursores na vista de tempo (C): a janela visível.")
                else:
                    regiao = tuple(sorted(tempo.cursores))
            if regiao is not None:
                a = int(min(max(round((regiao[0] - r.deslocamento_s) * canal.taxa_hz), 0), n))
                b = int(min(max(round((regiao[1] - r.deslocamento_s) * canal.taxa_hz), 0), n))
        estado = self.materializacoes.estado_de(traco)
        pronta = estado.pronta.amostras if estado is not None and estado.pronta is not None else None
        trecho = esp.TrechoDoTraco(fonte.fonte.captura, r.canal, r.cadeia, self.materializacoes.contexto(fonte, r.canal),
                                   a, b, r.ganho, pronta)
        self._nota = nota
        opcoes = self.opcoes
        chave = (id(traco), r.fonte, r.canal, r.cadeia, r.ganho, a, b, opcoes, pronta is not None)
        if chave == self._chave_calculada and not self.aguardando:
            self._mostrar_info()               # o mesmo trecho com as mesmas opções: nada a refazer
            return

        def calcular(progresso, cancelado):
            try:
                return self._conta(trecho, progresso, cancelado), ""
            except esp.AguardandoMaterializacao:
                return None, "aguardando"
            except api.ErroSHAN as e:
                return None, str(e)

        def terminou(tarefa) -> None:
            if tarefa is not self._tarefa or not isValid(self):
                return
            self._tarefa = None
            if tarefa.estado != "concluida":
                if tarefa.estado == "falhou":
                    self.info.setText(tarefa.erro)
                return
            resultado, erro = tarefa.resultado
            self.traco, self.trecho_atual, self.opcoes_calculadas = traco, trecho, opcoes
            self._chave_calculada = chave
            self.resultado = resultado
            self.aguardando = erro == "aguardando"
            self.erro = "" if self.aguardando else erro
            self._desenhar()
            self._mostrar_info()
            if self.cursores.ligados:
                self.emitir_regiao()          # os valores nos cursores mudaram com o resultado
            self.calculado.emit()

        grande = trecho.n_amostras > AMOSTRAS_PARA_MOSTRAR_A_TAREFA
        self._tarefa = self.tarefas.iniciar(self.tr("{} de {}").format(self.nome_da_conta, traco.nome), calcular,
                                            f"{self.vista.tipo}-{self.vista.id}", mostrar=grande,
                                            ao_terminar=terminou)

    def _mostrar_info(self) -> None:
        partes = [self._nota] if getattr(self, "_nota", "") else []
        if self.aguardando:
            partes.append(self.tr("aguardando a transformação da captura inteira de {}").format(self.traco.nome))
        if self.erro:
            partes.append(self.erro)
        partes += self._descricao()
        self.info.setText(" · ".join(partes))

    def _descricao(self) -> list[str]:
        return []

    def _tempo_do_trecho(self) -> float:
        """O tempo (na vista de tempo) da primeira amostra do trecho."""
        t = self.trecho_atual
        return self.traco.receita.deslocamento_s + t.inicio / t.captura.canal(t.numero).taxa_hz

    def _ligar_cursores(self, ligar: bool) -> None:
        if ligar:
            self.cursores.ligar(tuple(self.grafico.getViewBox().viewRange()[0]))
        else:
            self.cursores.desligar()

    def _passo_do_cursor(self) -> float:
        """Quanto as setas andam: no tempo, uma janela das bandas ou uma coluna do espectrograma."""
        return 0.0

    def _texto_x(self, valor: float) -> str:
        if self.unidade_x:
            return formatar_si(valor, self.unidade_x, 7)
        return f"{valor:.2f}".replace(".", ",").replace("-", "−")

    def medidas(self) -> MedidasDaVista | None:
        """As medidas dos cursores (para a tabela de Medidas): no tempo, os instantes, Δt e 1/Δt."""
        if self.cursores.posicoes is None:
            return None
        c1, c2 = self.cursores.posicoes
        dt = c2 - c1
        inverso = formatar_si(1.0 / abs(dt), "Hz", 5) if dt else "—"
        resumo = self.tr("Cursores: {} → {} · Δt {} · 1/Δt {}").format(self._texto_x(c1), self._texto_x(c2),
                                                                         self._texto_x(dt), inverso)
        planilha = "\t".join(["C1 (s)", "C2 (s)", "Δt (s)"]) + "\n" + "\t".join(
            numero_para_planilha(v) for v in (c1, c2, dt)) + "\n"
        return MedidasDaVista(resumo, planilha=planilha)

    def emitir_regiao(self) -> None:
        if isValid(self):
            self.medidasMudaram.emit(self.medidas())

    def soltar(self) -> None:
        if self._tarefa is not None and self._tarefa.ativa:
            self._tarefa.cancelar()
        self._espera.stop()

    def _tema_mudou(self, t: Tema) -> None:
        if isValid(self) and hasattr(self, "grafico"):
            self.grafico.setBackground(QColor(t.afundada))


def _imagem_com_barra(grafico: pg.PlotWidget, rotulo: str) -> tuple[pg.ImageItem, pg.ColorBarItem]:
    imagem = pg.ImageItem(axisOrder="col-major")
    imagem.setAutoDownsample(True)        # o mapa de 1 h de bandas tem 18 000 janelas × 490 bandas: reduzido à tela
    grafico.addItem(imagem)
    barra = pg.ColorBarItem(colorMap=pg.colormap.get(MAPA_DE_CORES), interactive=False, label=rotulo, width=14)
    barra.setImageItem(imagem, insert_in=grafico.getPlotItem())
    return imagem, barra


class VistaDeBandas(VistaLigada):
    nome_da_conta = "Bandas IEC"

    def _montar_conteudo(self, coluna: QVBoxLayout) -> None:
        self.setObjectName("vista_bandas")
        self.estatistica = Segmentado(["P95", "RMS", self.tr("Máximo"), self.tr("Mínimo")])
        self.estatistica.setToolTip(self.tr("A ordem da tabela: as bandas de maior P95 primeiro (como no adc_tool), ou "
                                            "da estatística escolhida"))
        self.estatistica.escolhaMudou.connect(lambda i: self._mudar(estatistica=("p95", "rms", "maximo", "minimo")[i]))
        self.sincronizar = QCheckBox(self.tr("Sincronizar"))
        self.sincronizar.setObjectName("sincronizar_bandas")
        self.sincronizar.setToolTip(self.tr("Janelas de 10 ciclos (50 Hz) ou 12 (60 Hz) da fundamental medida, em vez "
                                            "de 200 ms fixos (IEC 61000-4-30)"))
        self.sincronizar.clicked.connect(lambda marcado: self._mudar(sincronizar=bool(marcado)))
        self._linha.addWidget(self.estatistica)
        self._linha.addWidget(self.sincronizar)
        self.grafico = self._novo_grafico()
        self.grafico.setObjectName("mapa_bandas")
        self.grafico.setLabel("left", self.tr("banda"), units="Hz")
        self.imagem, self.barra = _imagem_com_barra(self.grafico, self.tr("nível RMS da banda (dB)"))
        self.tabela = QTableWidget(0, 5)
        self.tabela.setObjectName("tabela_bandas")
        self.tabela.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tabela.verticalHeader().hide()
        self.tabela.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        divisor = QSplitter(Qt.Orientation.Vertical)
        divisor.addWidget(self.grafico)
        divisor.addWidget(self.tabela)
        divisor.setSizes([400, 220])
        coluna.addWidget(divisor, 1)

    def _mostrar_opcoes_proprias(self) -> None:
        self.estatistica.blockSignals(True)
        self.estatistica.escolher(("p95", "rms", "maximo", "minimo").index(self.opcoes.estatistica))
        self.estatistica.blockSignals(False)
        self.sincronizar.setChecked(self.opcoes.sincronizar)
        if self.resultado is not None:
            self._preencher_tabela()

    def _conta(self, trecho, progresso, cancelado):
        return esp.bandas_do_trecho(trecho, self.opcoes.parametros, progresso=progresso, cancelado=cancelado)

    def _passo_do_cursor(self) -> float:
        return self.resultado.bandas.duracao_janela_s if self.resultado is not None else 0.0

    def linhas(self) -> list[tuple[float, dict[str, float]]]:
        """As bandas na ordem da tabela: (centro, estatísticas), da maior para a menor na estatística escolhida."""
        b = self.resultado.bandas
        est = b.estatisticas()
        ordem = np.argsort(est[self.opcoes.estatistica])[::-1]
        return [(float(b.centros_hz[i]), {k: float(v[i]) for k, v in est.items()}) for i in ordem]

    def _preencher_tabela(self) -> None:
        unidade = self.traco_unidade()
        self.tabela.setHorizontalHeaderLabels([self.tr("banda"), "P95", "RMS", self.tr("máximo"), self.tr("mínimo")])
        linhas = self.linhas()
        self.tabela.setRowCount(len(linhas))
        for k, (centro, est) in enumerate(linhas):
            valores = [formatar_si(centro, "Hz", 5)] + [formatar_si(est[nome], unidade, 4)
                                                        for nome in ("p95", "rms", "maximo", "minimo")]
            for c, texto in enumerate(valores):
                self.tabela.setItem(k, c, QTableWidgetItem(texto))

    def traco_unidade(self) -> str:
        t = self.trecho_atual
        return t.captura.canal(t.numero).unidade if t is not None else ""

    def _desenhar(self) -> None:
        if self.resultado is None:
            self.imagem.clear()
            self.tabela.setRowCount(0)
            return
        b = self.resultado.bandas
        niveis_db = 20.0 * np.log10(np.maximum(b.niveis, 1e-12))
        self.imagem.setImage(niveis_db, autoLevels=False)
        finitos = niveis_db[np.isfinite(niveis_db)]
        topo = float(np.max(finitos)) if len(finitos) else 0.0
        self.barra.setLevels((max(float(np.min(finitos)), topo - 80.0) if len(finitos) else -1.0, topo))
        t0 = self._tempo_do_trecho()
        largura = (b.tempos_s[-1] + b.duracao_janela_s) if len(b.tempos_s) else b.duracao_janela_s
        f0 = float(b.centros_hz[0] - b.largura_hz / 2)
        self.imagem.setRect(QRectF(t0, f0, float(largura), float(len(b.centros_hz) * b.largura_hz)))
        self._preencher_tabela()
        self._ligar_o_tempo(self.grafico.getViewBox())

    def _descricao(self) -> list[str]:
        if self.resultado is None:
            return []
        b = self.resultado.bandas
        partes = [self.tr("{} bandas de {} ({} a {}), {}").format(
            len(b.centros_hz), formatar_si(b.largura_hz, "Hz", 3), formatar_si(b.centros_hz[0], "Hz", 4),
            formatar_si(b.centros_hz[-1], "Hz", 4), b.descricao_janelas())]
        partes += [a.texto for a in self.resultado.avisos]
        return partes


class VistaDeEspectrograma(VistaLigada):
    nome_da_conta = "Espectrograma"

    def _montar_conteudo(self, coluna: QVBoxLayout) -> None:
        self.setObjectName("vista_espectrograma")
        self.resolucao = CampoComUnidade("Hz", 200.0, minimo=1e-3, digitos=4)
        self.resolucao.setObjectName("resolucao_espectrograma")
        self.resolucao.setToolTip(self.tr("A resolução em frequência de cada segmento"))
        self.resolucao.setMaximumWidth(90)
        self.resolucao.valorMudou.connect(lambda v: self._mudar(resolucao_hz=v))
        self.faixa = CampoComUnidade("dB", 80.0, minimo=1.0, digitos=3)
        self.faixa.setObjectName("faixa_dinamica")
        self.faixa.setToolTip(self.tr("A faixa dinâmica do mapa de cores, abaixo do nível mais alto"))
        self.faixa.setMaximumWidth(80)
        self.faixa.valorMudou.connect(lambda v: self._mudar(faixa_dinamica_db=v))
        self._linha.addWidget(QLabel(self.tr("Resolução")))
        self._linha.addWidget(self.resolucao)
        self._linha.addWidget(QLabel(self.tr("Faixa")))
        self._linha.addWidget(self.faixa)
        self.grafico = self._novo_grafico()
        self.grafico.setObjectName("mapa_espectrograma")
        self.grafico.setLabel("left", self.tr("frequência"), units="Hz")
        self.imagem, self.barra = _imagem_com_barra(self.grafico, "dB")
        coluna.addWidget(self.grafico, 1)

    def _mostrar_opcoes_proprias(self) -> None:
        self.resolucao.definir_valor(self.opcoes.resolucao_hz)
        self.faixa.definir_valor(self.opcoes.faixa_dinamica_db)
        if self.resultado is not None:
            self._desenhar()

    def _conta(self, trecho, progresso, cancelado):
        return esp.espectrograma_do_trecho(trecho, self.opcoes.parametros, progresso=progresso, cancelado=cancelado)

    def _passo_do_cursor(self) -> float:
        e = self.resultado
        return float(e.tempos_s[1] - e.tempos_s[0]) if e is not None and len(e.tempos_s) > 1 else 0.0

    def _desenhar(self) -> None:
        e = self.resultado
        if e is None:
            self.imagem.clear()
            return
        self.imagem.setImage(e.db, autoLevels=False)
        topo = float(np.max(e.db))
        self.barra.setLevels((topo - float(self.opcoes.faixa_dinamica_db), topo))
        passo = float(e.tempos_s[1] - e.tempos_s[0]) if len(e.tempos_s) > 1 else 1.0 / e.taxa_hz
        resolucao = float(e.freqs_hz[1] - e.freqs_hz[0]) if len(e.freqs_hz) > 1 else 1.0
        t0 = self._tempo_do_trecho() + float(e.tempos_s[0]) - passo / 2
        self.imagem.setRect(QRectF(t0, -resolucao / 2, passo * len(e.tempos_s), resolucao * len(e.freqs_hz)))
        self._ligar_o_tempo(self.grafico.getViewBox())

    def _descricao(self) -> list[str]:
        e = self.resultado
        if e is None:
            return []
        passo = e.tempos_s[1] - e.tempos_s[0] if len(e.tempos_s) > 1 else math.nan
        return [self.tr("{} colunas de {} × {} frequências (resolução {}, janela {})").format(
            len(e.tempos_s), formatar_si(passo, "s", 3), len(e.freqs_hz),
            formatar_si(e.freqs_hz[1] - e.freqs_hz[0], "Hz", 3), e.rotulo_janela)]



class VistaDeHarmonicos(VistaLigada):
    nome_da_conta = "Harmônicos"
    unidade_x = ""                  # a ordem harmônica
    GRANDEZAS = ("subgrupo", "grupo", "componente")

    def _montar_conteudo(self, coluna: QVBoxLayout) -> None:
        self.setObjectName("vista_harmonicos")
        self.grandeza = Segmentado([self.tr("Subgrupo"), self.tr("Grupo"), self.tr("Componente")])
        self.grandeza.setToolTip(self.tr("Subgrupo: o harmônico e os bins a até 5 Hz dele (a IEC 61000-4-30 classe A). "
                                         "Grupo: também o conteúdo entre harmônicos. Componente: só o bin"))
        self.grandeza.escolhaMudou.connect(lambda i: self._mudar(grandeza=self.GRANDEZAS[i]))
        self.escala = Segmentado(["% h1", "RMS"])
        self.escala.escolhaMudou.connect(lambda i: self._mudar(escala=("pct", "rms")[i]))
        self.ordem = QSpinBox()
        self.ordem.setObjectName("ordem_maxima")
        self.ordem.setRange(2, 200)
        self.ordem.setKeyboardTracking(False)
        self.ordem.setToolTip(self.tr("A última ordem calculada (a IEC 61000-4-7 define o THD até a 40ª)"))
        self.ordem.valueChanged.connect(lambda v: self._mudar(ordem_maxima=int(v)))
        for w in (self.grandeza, self.escala, QLabel(self.tr("Até a ordem")), self.ordem):
            self._linha.addWidget(w)
        self.grafico = self._novo_grafico()
        self.grafico.setObjectName("barras_harmonicos")
        self.grafico.setLabel("bottom", self.tr("ordem"))
        self.grafico.showGrid(x=False, y=True, alpha=0.15)
        self.barras = pg.BarGraphItem(x=[], height=[], width=0.7)
        self._rotulo_desenhado: str | None = None     # o do eixo Y no último desenho (outro: a vista se ajusta)
        self.grafico.addItem(self.barras)
        self.tabela = QTableWidget(0, 7)
        self.tabela.setObjectName("tabela_harmonicos")
        self.tabela.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tabela.verticalHeader().hide()
        self.tabela.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        divisor = QSplitter(Qt.Orientation.Vertical)
        divisor.addWidget(self.grafico)
        divisor.addWidget(self.tabela)
        divisor.setSizes([360, 260])
        coluna.addWidget(divisor, 1)

    def _mostrar_opcoes_proprias(self) -> None:
        o = self.opcoes
        for seg, indice in ((self.grandeza, self.GRANDEZAS.index(o.grandeza)), (self.escala, ("pct", "rms").index(o.escala))):
            seg.blockSignals(True)
            seg.escolher(indice)
            seg.blockSignals(False)
        self.ordem.blockSignals(True)
        self.ordem.setValue(o.ordem_maxima)
        self.ordem.blockSignals(False)
        if self.resultado is not None:
            self._desenhar()

    def _conta(self, trecho, progresso, cancelado):
        return esp.harmonicos_do_trecho(trecho, self.opcoes.parametros)

    def _passo_do_cursor(self) -> float:
        return 1.0                                 # uma ordem

    def medidas(self) -> MedidasDaVista | None:
        """As ordens de C1 e de C2 (a barra mais perto de cada um) e o valor das barras, na grandeza e na escala da
        vista."""
        if self.cursores.posicoes is None or self.resultado is None:
            return None
        ordens, alturas = self.valores()
        if not len(ordens):
            return None
        indices = [int(np.argmin(np.abs(ordens - c))) for c in self.cursores.posicoes]
        h1, h2 = (int(ordens[i]) for i in indices)
        v1, v2 = (float(alturas[i]) for i in indices)
        unidade = "%" if self.opcoes.escala == "pct" else self.traco_unidade()

        def texto(v):
            return f"{v:.4f} %".replace(".", ",") if unidade == "%" else formatar_si(v, unidade, 5)

        resumo = self.tr("Cursores: ordem {} → ordem {} · Δ {} ordens").format(h1, h2, h2 - h1)
        colunas = (self.tr("Ordem {}").format(h1), self.tr("Ordem {}").format(h2), self.tr("Δ"))
        linha = LinhaDaTabela(self.traco, (texto(v1), texto(v2), texto(v2 - v1)))
        planilha = "\t".join(["Traço", "Unidade", "Ordem C1", "Ordem C2", "Valor C1", "Valor C2", "Δ"]) + "\n" + \
            "\t".join([self.traco.nome, unidade, str(h1), str(h2), numero_para_planilha(v1), numero_para_planilha(v2),
                       numero_para_planilha(v2 - v1)]) + "\n"
        return MedidasDaVista(resumo, colunas, (linha,), planilha)

    def valores(self) -> tuple[np.ndarray, np.ndarray]:
        """As ordens 2 em diante e a altura das barras, na grandeza e na escala escolhidas."""
        tab = self.resultado.tabela
        campo = {"subgrupo": "rms_subgrupo", "grupo": "rms_grupo", "componente": "rms"}[self.opcoes.grandeza]
        base = getattr(tab.harmonicos[0], campo)
        ordens = np.array([h.ordem for h in tab.harmonicos[1:]], dtype=float)
        rms = np.array([getattr(h, campo) for h in tab.harmonicos[1:]])
        return ordens, (100.0 * rms / base if self.opcoes.escala == "pct" else rms)

    def _desenhar(self) -> None:
        if self.resultado is None:
            self.barras.setOpts(x=[], height=[])
            self.tabela.setRowCount(0)
            return
        t = aparencia().tema
        cor = QColor(cor_do_traco(self.traco.receita.cor, t)[0])
        ordens, alturas = self.valores()
        self.barras.setOpts(x=ordens, height=alturas, width=0.7, brush=cor, pen=pg.mkPen(None))
        unidade = self.traco_unidade()
        rotulo = self.tr("% da fundamental") if self.opcoes.escala == "pct" else self.tr("valor RMS ({})").format(unidade)
        # A vista fica onde o usuário a pôs (outra grandeza, outra ordem máxima, outro trecho); ela se ajusta só no
        # primeiro desenho e quando o eixo Y passa a medir outra coisa (% ou o valor RMS).
        ajustar = rotulo != self._rotulo_desenhado
        self._rotulo_desenhado = rotulo
        self.grafico.setLabel("left", rotulo)
        tab = self.resultado.tabela
        self.tabela.setHorizontalHeaderLabels(["h", "f", "RMS", self.tr("subgrupo"), self.tr("grupo"), "% h1",
                                               self.tr("fase (°)")])
        self.tabela.setRowCount(len(tab.harmonicos))
        for k, h in enumerate(tab.harmonicos):
            textos = [str(h.ordem), formatar_si(h.frequencia_hz, "Hz", 6), formatar_si(h.rms, unidade, 5),
                      formatar_si(h.rms_subgrupo, unidade, 5), formatar_si(h.rms_grupo, unidade, 5),
                      f"{h.pct_fundamental:.4f}".replace(".", ","), f"{h.fase_graus:.2f}".replace(".", ",").replace("-", "−")]
            for c, texto in enumerate(textos):
                self.tabela.setItem(k, c, QTableWidgetItem(texto))
        if ajustar:
            self.grafico.getViewBox().autoRange(padding=0.02)

    def traco_unidade(self) -> str:
        t = self.trecho_atual
        return t.captura.canal(t.numero).unidade if t is not None else ""

    def _descricao(self) -> list[str]:
        if self.resultado is None:
            return []
        tab = self.resultado.tabela
        return [self.tr("f₁ = {} · {} ciclos (janela retangular síncrona)").format(formatar_si(tab.f0_hz, "Hz", 7),
                                                                                    tab.n_ciclos),
                self.tr("THDS {} % · THDG {} % · THD {} % (até a ordem {})").format(
                    f"{tab.thds_pct:.4f}".replace(".", ","), f"{tab.thdg_pct:.4f}".replace(".", ","),
                    f"{tab.thd_pct:.4f}".replace(".", ","), tab.harmonicos[-1].ordem)]
