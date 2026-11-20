"""A vista dos perfis de sonda (ES-07, docs/gui-plan.md, 9.5): a lista dos perfis, o Bode dos marcados e qual perfil
cada canal do projeto usa e por quê.

* **A lista:** os perfis que os canais do projeto usam (o registrado na captura, ou o escolhido na correção de um
  traço), os da pasta das sondas (Configurações → Pastas) e os abertos aqui ("Abrir um perfil…"). Marcar um perfil o
  põe no Bode, cada um na sua cor; os marcados ficam nas opções da vista (o projeto os guarda, e o desfazer volta).
  Sem nenhuma escolha ainda, vêm marcados os que o projeto usa.
* **O Bode** (``dados/perfis_de_sonda.py``): a magnitude em dB e a fase em graus, contra a frequência em escala log,
  os pontos de calibração com as barras de erro do arquivo e a curva que a correção divide (a do motor: sólida na
  faixa válida, tracejada fora, onde o ganho fica constante), a faixa válida sombreada. A correção só usa o ganho: a
  fase aparece quando o perfil a traz, e não muda o sinal corrigido. O mouse perto de um ponto mostra os valores dele.
* **Os canais:** cada canal de cada captura aberta, a sonda que a captura registra, o perfil que vale e o porquê (a
  regra da CLI: o registrado, achado na pasta das sondas; ou o problema que impediu de usá-lo), e os traços que
  corrigem o canal, com o perfil de cada um. Clicar numa linha marca o perfil dela.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from pathlib import Path

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QIcon, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from shiboken6 import isValid

from ...ajuda import botao_de_ajuda
from ...componentes.basicos import Botao
from ...componentes.numeros import decimal, formatar_si
from ...dados import perfis_de_sonda as ps
from ...dados.cadeia import CorrecaoSonda
from ...graficos.faixa import EixoDoTema, GradeDoTema
from ...modelo.comandos import MudarOpcoesDaVista
from ...modelo.objetos import Projeto, Vista
from ...tema.aplicar import aparencia
from ...tema.tokens import Tema, cor_do_traco

PERTO_PX = 12                       # o mouse a até isto de um ponto mostra os valores dele
ESPERA_MS = 0                       # as mudanças do projeto (um gesto pode trazer várias) refazem a vista uma vez
COLUNAS = ("Captura", "Canal", "Sonda registrada", "Perfil", "Por quê", "Correção nos traços")


class VistaDePerfis(QWidget):
    tracoClicado = Signal(object, object)            # a interface das outras vistas (esta não tem traços)
    regiaoMudou = Signal(float, float, bool)
    semRegiao = Signal()
    medidasMudaram = Signal(object)

    def __init__(self, vista: Vista, projeto: Projeto, selecao=None, parent: QWidget | None = None, *,
                 pasta_das_sondas: Callable[[], Path] | None = None,
                 escolher_arquivo: Callable[[], Path | None] | None = None, **_outros):
        super().__init__(parent)
        self.setObjectName("vista_sonda")
        self.vista, self.projeto = vista, projeto
        self.pasta_das_sondas = pasta_das_sondas or (lambda: ps.api.SONDAS_DIR_PADRAO)
        self.escolher_arquivo = escolher_arquivo or (lambda: None)
        self.perfis: dict[str, ps.PerfilParaVer | str] = {}     # o caminho: o perfil, ou o motivo de não abrir
        self.ordem: list[str] = []
        self._itens_do_bode: list = []
        self._pontos: list[tuple[str, int, float, float, float | None]] = []   # (caminho, i, log f, dB, graus)

        barra = QWidget()
        barra.setObjectName("barra_da_vista")
        linha = QHBoxLayout(barra)
        linha.setContentsMargins(10, 6, 10, 6)
        self.abrir = Botao(self.tr("Abrir um perfil…"), "secundario", "pasta")
        self.abrir.setObjectName("abrir_perfil")
        self.abrir.clicked.connect(self._abrir_um_perfil)
        self.info = QLabel()
        self.info.setObjectName("info_sonda")
        self.info.setWordWrap(True)
        linha.addWidget(self.abrir)
        linha.addWidget(self.info, 1)
        linha.addWidget(botao_de_ajuda("perfis"))

        self.lista = QListWidget()
        self.lista.setObjectName("lista_de_perfis")
        self.lista.setIconSize(QSize(10, 10))
        self.lista.itemChanged.connect(self._marcado)
        self.lista.currentItemChanged.connect(lambda *_: self._detalhar())
        self.detalhe = QLabel()
        self.detalhe.setObjectName("detalhe_do_perfil")
        self.detalhe.setWordWrap(True)
        self.detalhe.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.detalhe.setAlignment(Qt.AlignmentFlag.AlignTop)
        esquerda = QWidget()
        coluna = QVBoxLayout(esquerda)
        coluna.setContentsMargins(8, 0, 4, 8)
        coluna.addWidget(self.lista, 3)
        coluna.addWidget(self.detalhe, 2)

        self.grafico = pg.GraphicsLayoutWidget()
        self.grafico.setObjectName("bode")
        self.eixos = {nome: (EixoDoTema("bottom"), EixoDoTema("left")) for nome in ("magnitude", "fase")}
        self.magnitude = self.grafico.addPlot(row=0, col=0, axisItems={"bottom": self.eixos["magnitude"][0],
                                                                      "left": self.eixos["magnitude"][1]})
        self.fase = self.grafico.addPlot(row=1, col=0, axisItems={"bottom": self.eixos["fase"][0],
                                                                 "left": self.eixos["fase"][1]})
        self.grades = []
        for plot, nome in ((self.magnitude, "magnitude"), (self.fase, "fase")):
            plot.setMenuEnabled(False)
            plot.hideButtons()
            plot.setLogMode(x=True, y=False)
            grade = GradeDoTema(*self.eixos[nome])
            plot.getViewBox().addItem(grade, ignoreBounds=True)
            self.grades.append(grade)
        self.fase.setXLink(self.magnitude)
        self.eixos["magnitude"][1].definir_rotulo(self.tr("ganho (dB)"))
        self.eixos["fase"][1].definir_rotulo(self.tr("fase (°)"))
        self.eixos["magnitude"][0].setStyle(showValues=False)
        self.eixos["fase"][0].definir_rotulo(self.tr("frequência"), "Hz")
        self.valor_no_mouse = pg.TextItem(anchor=(0, 1))
        self.valor_no_mouse.setZValue(30)
        self.valor_no_mouse.hide()
        self.magnitude.addItem(self.valor_no_mouse, ignoreBounds=True)
        self.grafico.scene().sigMouseMoved.connect(self._mouse_moveu)

        self.canais = QTableWidget(0, len(COLUNAS))
        self.canais.setObjectName("canais_e_perfis")
        self.canais.setHorizontalHeaderLabels([self.tr(c) for c in COLUNAS])
        self.canais.verticalHeader().hide()
        self.canais.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.canais.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.canais.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.canais.setWordWrap(True)
        cabecalho = self.canais.horizontalHeader()
        cabecalho.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        cabecalho.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        cabecalho.setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        self.canais.cellClicked.connect(self._canal_clicado)

        direita = QSplitter(Qt.Orientation.Vertical)
        direita.addWidget(self.grafico)
        direita.addWidget(self.canais)
        direita.setStretchFactor(0, 3)
        direita.setStretchFactor(1, 1)
        divisao = QSplitter(Qt.Orientation.Horizontal)
        divisao.addWidget(esquerda)
        divisao.addWidget(direita)
        divisao.setStretchFactor(0, 1)
        divisao.setStretchFactor(1, 4)
        coluna = QVBoxLayout(self)
        coluna.setContentsMargins(0, 0, 0, 0)
        coluna.setSpacing(0)
        coluna.addWidget(barra)
        coluna.addWidget(divisao, 1)

        self._espera = QTimer(self)
        self._espera.setSingleShot(True)
        self._espera.setInterval(ESPERA_MS)
        self._espera.timeout.connect(self.refazer)
        self._ligacoes = ((projeto.fonteEntrou, self._pedir), (projeto.fonteSaiu, self._pedir),
                          (projeto.tracoEntrou, self._pedir), (projeto.tracoSaiu, self._pedir),
                          (projeto.tracoMudou, self._traco_mudou), (vista.mudou, self._vista_mudou))
        for sinal, alvo in self._ligacoes:
            sinal.connect(alvo)
        aparencia().mudou.connect(self._tema_mudou)
        self._tema_mudou(aparencia().tema)
        self.refazer()

    # ------------------------------------------------------------------ a interface das vistas

    def soltar(self) -> None:
        for sinal, alvo in self._ligacoes:
            try:
                sinal.disconnect(alvo)
            except (RuntimeError, TypeError):
                pass

    def emitir_regiao(self) -> None:
        self.semRegiao.emit()                 # nada a medir: a tabela de medidas fica vazia

    # ------------------------------------------------------------------ o que mostrar

    def _pedir(self, *_args) -> None:
        self._espera.start()

    def _traco_mudou(self, _traco, campos) -> None:
        if "cadeia" in campos or "canal" in campos or "fonte" in campos:
            self._pedir()

    def _vista_mudou(self, _vista, campos) -> None:
        if "opcoes" in campos:
            self._pedir()

    def usados(self) -> dict[str, list[str]]:
        """Os perfis que o projeto usa, pelo caminho, e quem usa cada um ("captura · canal 1", "traço X")."""
        usados: dict[str, list[str]] = {}
        for fonte in self.projeto.fontes:
            for canal in fonte.canais:
                if canal.perfil is not None:
                    usados.setdefault(str(Path(canal.perfil.caminho)), []).append(
                        f"{fonte.nome} · canal {canal.numero}")
        for vista in self.projeto.vistas:
            for traco in vista.tracos:
                for etapa in traco.receita.cadeia.ligadas:
                    if isinstance(etapa, CorrecaoSonda) and etapa.perfil is not None:
                        usados.setdefault(str(Path(etapa.perfil)), []).append(traco.nome)
        return usados

    def marcados(self) -> list[str]:
        """Os perfis no Bode: os das opções; sem escolha ainda, os que o projeto usa (sem nenhum, o primeiro)."""
        escolhidos = self.vista.opcoes.perfis
        if escolhidos is not None:
            return [c for c in escolhidos if c in self.perfis]
        usados = [c for c in self.usados() if c in self.perfis]
        return usados or self.ordem[:1]

    def refazer(self) -> None:
        if not isValid(self):
            return
        usados = self.usados()
        caminhos = list(usados)
        for c in [*map(str, ps.perfis_da_pasta(self.pasta_das_sondas())), *(self.vista.opcoes.perfis or ())]:
            if c not in caminhos:
                caminhos.append(c)
        for c in caminhos:
            if c not in self.perfis:
                try:
                    self.perfis[c] = ps.ler(Path(c))
                except ps.PerfilIlegivel as e:
                    self.perfis[c] = str(e)
        self.ordem = caminhos
        self._refazer_a_lista(usados)
        self._refazer_o_bode()
        self._refazer_os_canais()
        self._detalhar()

    def _cor(self, caminho: str) -> str:
        return cor_do_traco(self.ordem.index(caminho), aparencia().tema)[0]

    def _refazer_a_lista(self, usados: dict[str, list[str]]) -> None:
        marcados = set(self.marcados())
        atual = self.lista.currentItem().data(Qt.ItemDataRole.UserRole) if self.lista.currentItem() else None
        self.lista.blockSignals(True)
        self.lista.clear()
        for c in self.ordem:
            perfil = self.perfis[c]
            nome = perfil.id if isinstance(perfil, ps.PerfilParaVer) else Path(c).stem
            item = QListWidgetItem(nome if c not in usados else self.tr("{} (em uso)").format(nome))
            item.setData(Qt.ItemDataRole.UserRole, c)
            item.setToolTip(c if isinstance(perfil, ps.PerfilParaVer) else self.tr("{}: não abre ({})").format(
                c, perfil))
            if isinstance(perfil, ps.PerfilParaVer):
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(Qt.CheckState.Checked if c in marcados else Qt.CheckState.Unchecked)
                amostra = QPixmap(10, 10)
                amostra.fill(QColor(self._cor(c)))
                item.setIcon(QIcon(amostra))
            else:
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsUserCheckable)
                item.setForeground(QColor(aparencia().tema.mudo))
            self.lista.addItem(item)
            if c == atual:
                self.lista.setCurrentItem(item)
        self.lista.blockSignals(False)

    def _marcado(self, item: QListWidgetItem) -> None:
        caminho = item.data(Qt.ItemDataRole.UserRole)
        marcados = self.marcados()
        if item.checkState() == Qt.CheckState.Checked and caminho not in marcados:
            marcados.append(caminho)
        elif item.checkState() != Qt.CheckState.Checked and caminho in marcados:
            marcados.remove(caminho)
        self.marcar(marcados)

    def marcar(self, caminhos: list[str]) -> None:
        """Os perfis no Bode (pelas opções da vista: um passo de desfazer)."""
        nova = self.vista.opcoes.com(perfis=tuple(caminhos))
        if nova != self.vista.opcoes:
            self.projeto.pilha.push(MudarOpcoesDaVista(self.vista, nova))

    def _abrir_um_perfil(self) -> None:
        caminho = self.escolher_arquivo()
        if caminho is None:
            return
        caminho = str(Path(caminho))
        self.perfis.pop(caminho, None)                # lido de novo: o arquivo pode ter mudado
        marcados = self.marcados()
        if caminho not in marcados:
            marcados.append(caminho)
        extras = tuple(dict.fromkeys([*(self.vista.opcoes.perfis or ()), caminho]))
        nova = self.vista.opcoes.com(perfis=tuple(c for c in extras if c in marcados or c == caminho))
        if nova != self.vista.opcoes:
            self.projeto.pilha.push(MudarOpcoesDaVista(self.vista, nova))
        self._espera.stop()
        self.refazer()                                # já, para escolher o perfil na lista
        for i in range(self.lista.count()):
            if self.lista.item(i).data(Qt.ItemDataRole.UserRole) == caminho:
                self.lista.setCurrentRow(i)

    # ------------------------------------------------------------------ o Bode

    def _refazer_o_bode(self) -> None:
        for plot, item in self._itens_do_bode:
            plot.removeItem(item)
        self._itens_do_bode, self._pontos = [], []
        marcados = [c for c in self.marcados() if isinstance(self.perfis.get(c), ps.PerfilParaVer)]
        tem_fase = False
        for c in marcados:
            p = self.perfis[c]
            cor = QColor(self._cor(c))
            self._desenhar_magnitude(c, p, cor)
            tem_fase = self._desenhar_fase(c, p, cor) or tem_fase
        self.fase.setVisible(tem_fase)
        self.eixos["magnitude"][0].setStyle(showValues=not tem_fase)
        if tem_fase:
            self.eixos["magnitude"][0].setLabel("")
        else:
            self.eixos["magnitude"][0].definir_rotulo(self.tr("frequência"), "Hz")
        self.magnitude.autoRange()
        if tem_fase:
            self.fase.enableAutoRange(axis="y")
        if not marcados:
            self.info.setText(self.tr("Marque um perfil na lista para ver o Bode dele."))
        else:
            self.info.setText(self.tr("A curva é a que a correção divide (sólida na faixa válida; fora dela, o ganho "
                                      "fica constante). A correção usa só o ganho: a fase não muda o sinal "
                                      "corrigido."))

    def _por(self, plot, item, limites: bool = True) -> None:
        plot.addItem(item, ignoreBounds=not limites)
        self._itens_do_bode.append((plot, item))

    def _faixa(self, plot, p: ps.PerfilParaVer, cor: QColor) -> None:
        if p.faixa_valida is None:
            return
        fundo = QColor(cor)
        fundo.setAlphaF(0.07)
        regiao = pg.LinearRegionItem(values=tuple(math.log10(f) for f in p.faixa_valida), movable=False,
                                     brush=pg.mkBrush(fundo), pen=pg.mkPen(None))
        regiao.setZValue(-5)
        self._por(plot, regiao, limites=False)

    def _desenhar_magnitude(self, c: str, p: ps.PerfilParaVer, cor: QColor) -> None:
        self._faixa(self.magnitude, p, cor)
        f, db = p.curva()
        dentro = np.ones(len(f), bool) if p.faixa_valida is None else (f >= p.faixa_valida[0]) & (
            f <= p.faixa_valida[1])
        self._por(self.magnitude, pg.PlotDataItem(f, np.where(dentro, db, np.nan), pen=pg.mkPen(cor, width=1.6),
                                                  connect="finite"))
        self._por(self.magnitude, pg.PlotDataItem(f, np.where(dentro, np.nan, db), connect="finite",
                                                  pen=pg.mkPen(cor, width=1.2, style=Qt.PenStyle.DashLine)),
                  limites=False)
        if p.tipo != "resposta_frequencia":
            return
        abaixo, acima = p.barras_db()
        tem = np.isfinite(abaixo) & np.isfinite(acima)
        if tem.any():
            self._por(self.magnitude, pg.ErrorBarItem(x=np.log10(p.freq_hz[tem]), y=p.ganho_db[tem],
                                                      top=acima[tem], bottom=abaixo[tem], beam=0.02,
                                                      pen=pg.mkPen(cor, width=1)))
        self._por(self.magnitude, pg.PlotDataItem(p.freq_hz, p.ganho_db, pen=None, symbol="o", symbolSize=6,
                                                  symbolBrush=pg.mkBrush(cor), symbolPen=pg.mkPen(cor)))
        fases = p.fase_graus()
        for i, (f_i, g_i) in enumerate(zip(p.freq_hz, p.ganho_db)):
            self._pontos.append((c, i, math.log10(f_i), float(g_i), None if fases is None else float(fases[i])))

    def _desenhar_fase(self, c: str, p: ps.PerfilParaVer, cor: QColor) -> bool:
        curva = p.curva_da_fase()
        if curva is None:
            return False
        self._faixa(self.fase, p, cor)
        self._por(self.fase, pg.PlotDataItem(*curva, pen=pg.mkPen(cor, width=1.2, style=Qt.PenStyle.DashLine)),
                  limites=False)
        graus, sigma = p.fase_graus(), np.degrees(p.sigma_fase_rad)
        tem = np.isfinite(sigma)
        if tem.any():
            self._por(self.fase, pg.ErrorBarItem(x=np.log10(p.freq_hz[tem]), y=graus[tem], height=2 * sigma[tem],
                                                 beam=0.02, pen=pg.mkPen(cor, width=1)))
        self._por(self.fase, pg.PlotDataItem(p.freq_hz, graus, pen=None, symbol="o", symbolSize=6,
                                             symbolBrush=pg.mkBrush(cor), symbolPen=pg.mkPen(cor)))
        return True

    def ponto_perto(self, posicao_na_cena) -> tuple | None:
        """O ponto de calibração mais perto do mouse (na magnitude), a até :data:`PERTO_PX`."""
        caixa = self.magnitude.getViewBox()
        melhor, distancia = None, PERTO_PX
        for ponto in self._pontos:
            na_cena = caixa.mapViewToScene(pg.Point(ponto[2], ponto[3]))
            d = math.hypot(na_cena.x() - posicao_na_cena.x(), na_cena.y() - posicao_na_cena.y())
            if d <= distancia:
                melhor, distancia = ponto, d
        return melhor

    def texto_do_ponto(self, ponto) -> str:
        c, i, _lf, db, graus = ponto
        p = self.perfis[c]

        def numero(x: float, formato: str) -> str:
            return decimal(format(x, formato)).replace("-", "−")

        partes = [f"{p.id}: {formatar_si(float(p.freq_hz[i]), 'Hz', 5)}",
                  self.tr("ganho {} ({} dB)").format(numero(float(p.ganho[i]), ".6f"), numero(db, ".4f"))]
        if math.isfinite(p.desvio_pct[i]):
            partes.append(self.tr("desvio {} %").format(numero(float(p.desvio_pct[i]), ".3g")))
        if graus is not None:
            texto = self.tr("fase {}°").format(numero(graus, ".4f"))
            if math.isfinite(p.sigma_fase_rad[i]):
                texto += " ± " + numero(math.degrees(float(p.sigma_fase_rad[i])), ".3g") + "°"
            partes.append(texto)
        return "\n".join(partes)

    def _mouse_moveu(self, posicao) -> None:
        ponto = self.ponto_perto(posicao) if self.magnitude.sceneBoundingRect().contains(posicao) else None
        if ponto is None:
            self.valor_no_mouse.hide()
            return
        self.valor_no_mouse.setText(self.texto_do_ponto(ponto))
        self.valor_no_mouse.setPos(ponto[2], ponto[3])
        self.valor_no_mouse.show()

    # ------------------------------------------------------------------ os canais

    def linhas_dos_canais(self) -> list[tuple[str, ...]]:
        """Uma linha por canal de cada captura aberta: a captura, o canal, a sonda registrada, o perfil, por quê e a
        correção nos traços (e o caminho do perfil, para marcar)."""
        linhas = []
        for fonte in self.projeto.fontes:
            if fonte.esta_ausente:
                continue
            for canal in fonte.canais:
                corrigem = []
                for vista in self.projeto.vistas:
                    for traco in vista.tracos:
                        r = traco.receita
                        if r.fonte != fonte.id or r.canal != canal.numero:
                            continue
                        etapa = next((e for e in r.cadeia.ligadas if isinstance(e, CorrecaoSonda)), None)
                        if etapa is not None:
                            corrigem.append(f"{traco.nome} ({Path(etapa.perfil).stem})" if etapa.perfil
                                            else self.tr("{} (o da captura)").format(traco.nome))
                if canal.perfil is not None:
                    perfil, caminho = canal.perfil.id, str(Path(canal.perfil.caminho))
                    porque = self.tr("a captura registra a sonda {}, e o perfil dela está em {}").format(
                        canal.sonda_id, Path(caminho).parent)
                elif canal.problema_sonda:
                    perfil, caminho, porque = "—", "", canal.problema_sonda
                elif canal.sonda_id:
                    perfil, caminho = "—", ""
                    porque = self.tr("a sonda {} está registrada, mas o perfil não abriu").format(canal.sonda_id)
                else:
                    perfil, caminho, porque = "—", "", self.tr("a captura não registra uma sonda para este canal")
                correcao = ", ".join(corrigem) if corrigem else self.tr("nenhum traço corrige")
                linhas.append((fonte.nome, str(canal.numero), canal.sonda_id or "—", perfil, porque, correcao,
                               caminho))
        return linhas

    def _refazer_os_canais(self) -> None:
        linhas = self.linhas_dos_canais()
        self.canais.setRowCount(len(linhas))
        for i, linha in enumerate(linhas):
            for j, texto in enumerate(linha[:len(COLUNAS)]):
                item = QTableWidgetItem(texto)
                item.setData(Qt.ItemDataRole.UserRole, linha[-1])
                item.setToolTip(texto)
                self.canais.setItem(i, j, item)
        self.canais.resizeRowsToContents()

    def _canal_clicado(self, linha: int, _coluna: int) -> None:
        item = self.canais.item(linha, 0)
        caminho = item.data(Qt.ItemDataRole.UserRole) if item is not None else ""
        if not caminho:
            return
        marcados = self.marcados()
        if caminho not in marcados:
            self.marcar([*marcados, caminho])
        for i in range(self.lista.count()):
            if self.lista.item(i).data(Qt.ItemDataRole.UserRole) == caminho:
                self.lista.setCurrentRow(i)

    def _detalhar(self) -> None:
        item = self.lista.currentItem()
        if item is None:
            self.detalhe.setText(self.tr("Escolha um perfil na lista para ver os detalhes."))
            return
        c = item.data(Qt.ItemDataRole.UserRole)
        p = self.perfis.get(c)
        if not isinstance(p, ps.PerfilParaVer):
            self.detalhe.setText(self.tr("{}\nNão abre: {}").format(c, p))
            return
        linhas = [p.id, p.resumo()]
        if p.calibrado_com:
            linhas.append(self.tr("Calibrado com: {}").format(p.calibrado_com))
        quem = self.usados().get(c)
        if quem:
            linhas.append(self.tr("Em uso: {}").format(", ".join(quem)))
        linhas.append(c)
        self.detalhe.setText("\n".join(linhas))

    # ------------------------------------------------------------------ tema

    def _tema_mudou(self, t: Tema) -> None:
        if not isValid(self):
            return
        self.grafico.setBackground(QColor(t.afundada))
        for eixo_x, eixo_y in self.eixos.values():
            eixo_x.aplicar_tema(t)
            eixo_y.aplicar_tema(t)
        for grade in self.grades:
            grade.aplicar_tema(t)
        self.valor_no_mouse.setColor(QColor(t.texto))
        self.valor_no_mouse.fill = pg.mkBrush(QColor(t.elevada))
        if self.ordem:
            self._refazer_a_lista(self.usados())
            self._refazer_o_bode()
