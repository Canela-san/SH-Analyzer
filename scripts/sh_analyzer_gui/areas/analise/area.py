"""As ligações da área de Análise na janela: o painel do projeto, o inspetor, os avisos de cada captura, a barra de
status da captura ativa, as abas das vistas, a seleção e o plotar um canal. A janela monta as regiões (os docks, as
abas); esta classe as faz conversar com o projeto aberto, e troca de projeto junto com a janela.

Cada ligação com o projeto é desfeita ao trocar de projeto (:meth:`AreaDeAnalise.acompanhar`): o projeto antigo não
mexe mais na tela.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import supraharmonicos.api as api
from PySide6.QtCore import QCoreApplication, QObject, QSize, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QDialog, QLabel, QTabBar, QTabWidget, QToolButton, QWidget
from shiboken6 import isValid

from ... import preferencias
from ...componentes.avisos import ListaDeAvisos
from ...componentes.grade_de_vistas import CELULAS
from ...componentes.numeros import formatar_bytes, formatar_si
from ...componentes.primeiros_passos import e_o_exemplo
from ...componentes.toast import Toast
from ...dados import alinhamento as al
from ...dados import exportar_dados as ed
from ...dados.avisos import do_exemplo
from ...dados.espectros import OPCOES_DO_TIPO
from ...dados.proveniencia import dos_dados
from ...dados.receita import ReceitaDoTraco
from ...modelo.comandos import AdicionarTraco, AdicionarVista, MudarTracos, RemoverFonte, RemoverTracos, RemoverVista
from ...modelo.objetos import FonteDoProjeto, Projeto, Traco, Vista
from ...modelo.persistencia import fontes_da_proveniencia
from ...servicos.medidas import PedidoDeMedida, ServicoDeMedidas, valores_no_trecho
from ...tema.aplicar import aparencia
from ...tema.icones import IconeDoTema, icone
from .alinhar import DialogoDeAlinhar
from .arvore import ICONE_DO_TIPO_DE_VISTA, PainelDoProjeto
from .exportar_dados import NOMES_DAS_REGIOES, ColetaDaVista, DialogoDeExportarDados, PedidoDeDados
from .inspetor import TEXTOS_DA_INTEGRIDADE, Inspetor
from .ligacao_dos_eixos import LigacaoDosEixos
from .medidas import TabelaDeMedidas
from .vista_espectro import VistaDeEspectro
from .vista_instrumento import VistaDeInstrumento
from .vista_sonda import VistaDePerfis
from .vista_tempo import VistaDeTempo
from .vistas_de_analise import (
    VistaDeEventos,
    VistaDeHistograma,
    VistaDeQualidade,
    VistaDeTransferencia,
    VistaDeXY,
)
from .vistas_de_bancada import DialogoDeAliasing, VistaDeMetricas
from .vistas_de_mapa import VistaDeBandas, VistaDeEspectrograma, VistaDeHarmonicos

NOME_DA_PRIMEIRA_VISTA = "Tempo"
TAMANHO_DO_BOTAO_DE_FECHAR = 20
TAMANHO_DO_X = 14


def nome_do_traco(fonte: FonteDoProjeto, numero: int) -> str:
    """O nome de um traço novo: o canal e a captura ("canal 1 · A1_60Hz_20k")."""
    return f"canal {numero} · {fonte.caminho.stem}"


class AreaDeAnalise(QObject):
    exibicaoMudou = Signal(object)        # a vista: a janela que ela mostra ou o espectro dela (a figura acompanha)
    dadosExportados = Signal(object)      # o caminho do arquivo (a F5.5)

    def __init__(self, janela, painel: PainelDoProjeto, inspetor: Inspetor, avisos: ListaDeAvisos,
                 status_fonte: QLabel, status_integridade: QLabel, abas: QTabWidget, medidas: TabelaDeMedidas):
        super().__init__(janela)
        self.tabela_de_medidas = medidas
        self.servico_de_medidas = ServicoDeMedidas(janela.tarefas, self, materializacoes=janela.materializacoes)
        self.servico_de_medidas.prontas.connect(medidas.mostrar)
        abas.currentChanged.connect(self._aba_mudou)
        self.ligacao = LigacaoDosEixos(abas, self)
        self.janela, self.painel, self.inspetor, self.avisos = janela, painel, inspetor, avisos
        self.status_fonte, self.status_integridade, self.abas = status_fonte, status_integridade, abas
        self.projeto: Projeto | None = None
        self.dialogo_de_dados: DialogoDeExportarDados | None = None
        self._pedido_de_dados: PedidoDeDados | None = None       # o último: o diálogo abre com ele
        self._pasta_dos_dados: Path | None = None
        self.fonte_ativa: FonteDoProjeto | None = None
        painel.canalAtivado.connect(self.plotar_canal)
        painel.vistaAtivada.connect(self.ativar_vista)
        painel.selecaoMudou.connect(self._selecao_mudou)
        painel.fecharFontePedido.connect(self.fechar_fonte)
        painel.localizarFontePedido.connect(lambda f: self.janela.controle.localizar_fonte(f))
        painel.notaAtivada.connect(self.abrir_no_editor)
        inspetor.do_caderno.abrirPedido.connect(self.abrir_no_editor)
        inspetor.do_traco.alinharPedido.connect(self.alinhar)
        self.dialogo_de_alinhar: DialogoDeAlinhar | None = None
        self.abrir_url = QDesktopServices.openUrl            # os testes trocam por um que não abre nada
        aparencia().mudou.connect(self._estado_da_ativa)      # a taxa e a duração, com o separador de agora

    # ------------------------------------------------------------------ o projeto

    def acompanhar(self, projeto: Projeto) -> None:
        if self.projeto is not None:
            for sinal, alvo in self._ligacoes(self.projeto):
                sinal.disconnect(alvo)
            for fonte in self.projeto.fontes:
                self.avisos.remover_origem(fonte.id)
        self._ativar(None)
        self.projeto = projeto
        # A árvore primeiro: ligada antes, ela já tem a linha da captura nova quando a área a seleciona.
        self.painel.mostrar(projeto)
        for sinal, alvo in self._ligacoes(projeto):
            sinal.connect(alvo)
        self.janela.selecao.mudou.connect(self._tracos_selecionados)
        self.abas.definir_disposicao("uma")           # um projeto começa com uma vista; o salvo traz a grade dele
        self._refazer_abas()
        self.inspetor.mostrar("", None)
        for fonte in projeto.fontes:
            self._avisos_da_fonte(fonte)
        if projeto.fontes:
            self._ativar(projeto.fontes[-1])

    def _ligacoes(self, projeto: Projeto):
        return ((projeto.fonteEntrou, self._fonte_entrou), (projeto.fonteSaiu, self._fonte_saiu),
                (projeto.vistaEntrou, self._vista_entrou), (projeto.vistaSaiu, self._vista_saiu),
                (projeto.vistaMudou, self._vista_mudou))

    # ------------------------------------------------------------------ as abas das vistas

    def _refazer_abas(self) -> None:
        while self.abas.count():
            widget = self.abas.widget(0)
            self.abas.removeTab(0)
            widget.soltar()
            widget.deleteLater()
        for i, vista in enumerate(self.projeto.vistas):
            self._vista_entrou(vista, i)

    # ------------------------------------------------------------------ alinhar (TR-07)

    def alinhar(self, traco: Traco | None = None) -> DialogoDeAlinhar | None:
        """O "Alinhar…": o diálogo que mede o atraso de ``traco`` (sem ele, o selecionado na vista aberta) em relação
        a outro traço da vista de tempo dele, e o "Aplicar" muda o deslocamento (um passo de desfazer)."""
        if traco is None:
            selecionados = self.janela.selecao.tracos if self.janela.selecao is not None else ()
            traco = selecionados[-1] if len(selecionados) == 1 else None
        vista = next((v for v in self.projeto.vistas if traco is not None and traco in v.tracos), None)
        widget = self.widget_da_vista(vista) if vista is not None else None
        if not isinstance(widget, VistaDeTempo):
            return None
        presentes = [t for t in vista.tracos
                     if t is not traco and t.receita.visivel and self._fonte_presente(t.receita.fonte)]
        if self.dialogo_de_alinhar is not None and isValid(self.dialogo_de_alinhar):
            self.dialogo_de_alinhar.close()
        dialogo = DialogoDeAlinhar(traco, presentes, lambda: widget.regiao() if isValid(widget) else None,
                                   lambda *a: self._medir_o_atraso(widget, traco, *a), self.janela)
        widget.regiaoMudou.connect(dialogo.pedir)
        dialogo.finished.connect(lambda _r: isValid(widget) and widget.regiaoMudou.disconnect(dialogo.pedir))
        dialogo.accepted.connect(lambda: self._aplicar_o_alinhamento(dialogo))
        self.dialogo_de_alinhar = dialogo
        dialogo.open()
        return dialogo

    def _fonte_presente(self, fonte_id: str) -> bool:
        try:
            return not self.projeto.fonte(fonte_id).esta_ausente
        except KeyError:
            return False

    def _medir_o_atraso(self, widget: VistaDeTempo, traco: Traco, metodo: str, referencia: Traco, busca: float,
                        ao_terminar):
        """A tarefa que lê os dois trechos (o da referência; o do traço, com a busca dos dois lados) e mede o atraso.
        O resultado é um ``Alinhamento`` ou o motivo (texto) de não haver um."""
        trecho = widget.regiao()
        problema = None
        if trecho is None:
            problema = self.tr("a vista ainda não tem um trecho desenhado")
        elif widget.tem_tempo_proprio(traco) or widget.tem_tempo_proprio(referencia):
            problema = self.tr("um dos traços tem o tempo próprio (a escala do tempo destravada): trave a escala do "
                               "tempo para alinhar")
        planos, encolhida = [], ""
        if problema is None:
            a, b, _ = trecho
            # A referência só onde o traço tem dados dos dois lados da busca (e onde ela mesma tem): com a captura
            # inteira à vista, ela encolhe a busca de cada lado.
            def tempo_de(t):
                canal = self.projeto.fonte(t.receita.fonte).canal(t.receita.canal)
                return t.receita.deslocamento_s, t.receita.deslocamento_s + len(canal.amostras) / canal.taxa_hz

            (r0, r1), (t0, t1) = tempo_de(referencia), tempo_de(traco)
            a2, b2 = max(a, r0, t0 + busca), min(b, r1, t1 - busca)
            if b2 - a2 <= 0:
                problema = self.tr("o trecho não cabe na busca: os dois traços precisam de dados no trecho, e o traço "
                                   "também {} para cada lado (diminua a busca)").format(formatar_si(busca, "s", 3))
            elif (a2, b2) != (a, b):
                encolhida = self.tr("a referência foi lida de {} a {}, onde o traço tem dados para a busca dos dois "
                                    "lados").format(formatar_si(a2, "s", 6), formatar_si(b2, "s", 6))
            a, b = a2, b2
        if problema is None:
            for t, inicio, fim in ((referencia, a, b), (traco, a - busca, b + busca)):
                fonte = self.projeto.fonte(t.receita.fonte)
                taxa = fonte.canal(t.receita.canal).taxa_hz
                if (fim - inicio) * taxa > al.MAXIMO_DE_AMOSTRAS:
                    problema = self.tr("trecho grande demais ({} amostras): aproxime o zoom, use os cursores ou "
                                       "diminua a busca").format(int((fim - inicio) * taxa))
                    break
                planos.append((fonte, t.receita, inicio, fim, self.servico_de_medidas._contexto(fonte, t.receita)))

        def trabalho(progresso, cancelado):
            if problema is not None:
                return problema
            try:
                trechos = [al.Trecho(*valores_no_trecho(*plano)) for plano in planos]
                feito = al.alinhar(metodo, *trechos)
            except (al.AlinhamentoImpossivel, api.ErroSHAN) as e:
                return str(e)
            if encolhida:
                feito = replace(feito, aviso="; ".join(x for x in (feito.aviso, encolhida) if x))
            return feito

        return self.janela.tarefas.iniciar(self.tr("Alinhar"), trabalho, "alinhar", mostrar=False,
                                           ao_terminar=ao_terminar)

    def _aplicar_o_alinhamento(self, dialogo: DialogoDeAlinhar) -> None:
        novo, referencia = dialogo.novo_deslocamento(), dialogo.referencia_escolhida()
        traco = dialogo.traco
        if novo is None or referencia is None or not any(traco in v.tracos for v in self.projeto.vistas):
            return
        comando = MudarTracos([traco], texto=self.tr("Alinhar {} a {}").format(traco.nome, referencia.nome),
                              deslocamento_s=novo)
        if comando.muda_algo:
            self.projeto.pilha.push(comando)

    # ------------------------------------------------------------------ a grade (AN-09)

    def definir_disposicao(self, disposicao: str) -> None:
        self.abas.definir_disposicao(disposicao)

    def ligar_os_eixos(self, ligar: bool) -> None:
        self.ligacao.ligar(ligar)
        acao = self.janela.acoes.get("ligar_eixos")
        if acao is not None and acao.isChecked() != ligar:
            acao.setChecked(ligar)

    def estado_da_grade(self) -> dict:
        """A disposição, a vista de cada célula (pelo id; ``None``: vazia) e os eixos ligados, para o projeto."""
        return {"disposicao": self.abas.disposicao, "ligar": self.ligacao.ligada,
                "celulas": [getattr(getattr(c.widget, "vista", None), "id", None) for c in self.abas.celulas]}

    def restaurar_grade(self, estado: dict) -> bool:
        """A grade guardada no projeto (:meth:`estado_da_grade`). A grade é só conforto: um estado estragado, ou de
        vistas que não existem mais, deixa o que estiver (``False``)."""
        if not isinstance(estado, dict) or estado.get("disposicao") not in CELULAS:
            return False
        ids = estado.get("celulas", [])
        if not isinstance(ids, list):
            return False
        por_id = {v.id: self.widget_da_vista(v) for v in self.projeto.vistas}
        widgets = [por_id.get(i) if isinstance(i, str) else None for i in ids]
        self.abas.definir_disposicao(estado["disposicao"], widgets)
        if isinstance(estado.get("ligar"), bool):
            self.ligar_os_eixos(estado["ligar"])
        return True

    def widget_da_vista(self, vista: Vista) -> VistaDeTempo | None:
        for i in range(self.abas.count()):
            widget = self.abas.widget(i)
            if getattr(widget, "vista", None) is vista:
                return widget
        return None

    def vista_ativa(self) -> Vista | None:
        widget = self.abas.currentWidget()
        return getattr(widget, "vista", None)

    def ativar_vista(self, vista: Vista) -> bool:
        """Abre a aba de ``vista`` (o clique numa vista do painel do projeto)."""
        widget = self.widget_da_vista(vista)
        if widget is None:
            return False
        if widget is self.abas.currentWidget():
            self._inspetor_da_vista(trocou_de_aba=True)     # já aberta: o inspetor mostra a vista, como na troca
        else:
            self.abas.setCurrentWidget(widget)
        return True

    def _vista_de_tempo_por_id(self, vista_id: str | None) -> VistaDeTempo | None:
        """O widget da vista de tempo de ``vista_id`` (sem ela, o da primeira vista de tempo do projeto)."""
        tempos = [v for v in self.projeto.vistas if v.tipo == "tempo"]
        vista = next((v for v in tempos if v.id == vista_id), tempos[0] if tempos else None)
        return self.widget_da_vista(vista) if vista is not None else None

    def abrir_espectro(self) -> Vista | None:
        return self.abrir_analise("espectro")

    def abrir_analise(self, tipo: str) -> Vista | None:
        """Uma vista de ``tipo`` (espectro, bandas, espectrograma) ligada à vista de tempo aberta (ou à que a vista
        de frequência aberta segue)."""
        ativa = self.janela.vista_ativa()
        if ativa is not None and ativa.tipo != "tempo":
            ativa = next((v for v in self.projeto.vistas if v.id == getattr(ativa.opcoes, "vista_de_tempo", None)), None)
        if ativa is None:
            ativa = next((v for v in self.projeto.vistas if v.tipo == "tempo"), None)
        if ativa is None:
            return None
        nomes = {v.nome for v in self.projeto.vistas}
        # Nomes curtos, pelo tipo (as abas cabem, e a árvore não corta); a vista de tempo entra no nome só quando há
        # mais de uma, para dizer de qual o espectro é.
        rotulos = {"espectro": self.tr("Espectro"), "bandas": self.tr("Bandas IEC"),
                   "espectrograma": self.tr("Espectrograma"), "harmonicos": self.tr("Harmônicos"),
                   "xy": self.tr("XY"), "histograma": self.tr("Histograma"), "eventos": self.tr("Eventos"),
                   "qualidade": self.tr("Qualidade"), "transferencia": self.tr("Transferência"),
                   "metricas": self.tr("Métricas"), "instrumento": self.tr("Instrumento")}
        nome = rotulos[tipo]
        if sum(v.tipo == "tempo" for v in self.projeto.vistas) > 1:
            nome = f"{nome} · {ativa.nome}"
        base, n = nome, 2
        while nome in nomes:
            nome, n = f"{base} {n}", n + 1
        vista = Vista(nome, tipo, opcoes=OPCOES_DO_TIPO[tipo](vista_de_tempo=ativa.id))
        self.projeto.pilha.push(AdicionarVista(self.projeto, vista))
        return vista

    def _vista_entrou(self, vista: Vista, i: int) -> None:
        if vista.tipo != "tempo":
            self._vista_de_frequencia_entrou(vista, i)
            return
        widget = VistaDeTempo(vista, self.projeto, self.janela.selecao, materializacoes=self.janela.materializacoes)
        widget.tracoClicado.connect(self._traco_clicado)
        widget.regiaoMudou.connect(self._regiao_mudou)
        widget.regiaoMudou.connect(lambda *_a, v=vista: self.exibicaoMudou.emit(v))
        widget.semRegiao.connect(self._sem_regiao)
        self.abas.insertTab(i, widget, icone("onda", aparencia().tema.texto2), vista.nome)
        self._por_botao_de_fechar(i, widget)
        self.abas.setCurrentIndex(i)

    def abrir_aliasing(self) -> DialogoDeAliasing:
        """O assistente de aliasing (ES-06), com as fontes abertas; não bloqueia a janela."""
        dialogo = DialogoDeAliasing(self.projeto.fontes, self.janela.tarefas, self.janela)
        dialogo.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        dialogo.show()
        return dialogo

    def abrir_perfis(self) -> Vista:
        """A vista dos perfis de sonda (ES-07): a que o projeto já tem fica aberta; sem uma, uma nova."""
        existente = next((v for v in self.projeto.vistas if v.tipo == "sonda"), None)
        if existente is not None:
            self.ativar_vista(existente)
            return existente
        vista = Vista(self.tr("Perfis de sonda"), "sonda")
        self.projeto.pilha.push(AdicionarVista(self.projeto, vista))
        return vista

    def _perfis_entrou(self, vista: Vista, i: int) -> None:
        dialogos = self.janela.controle.dialogos

        def escolher():
            return dialogos.abrir_arquivo(self.tr("Abrir um perfil de sonda"), self.tr("Perfis de sonda (*.json)"),
                                          str(preferencias.pasta("sondas")))

        widget = VistaDePerfis(vista, self.projeto, self.janela.selecao,
                               pasta_das_sondas=lambda: preferencias.pasta("sondas"), escolher_arquivo=escolher)
        widget.semRegiao.connect(self._sem_regiao)
        self.abas.insertTab(i, widget, icone("sonda", aparencia().tema.texto2), vista.nome)
        self._por_botao_de_fechar(i, widget)
        self.abas.setCurrentIndex(i)

    def _vista_de_frequencia_entrou(self, vista: Vista, i: int) -> None:
        if vista.tipo == "sonda":
            self._perfis_entrou(vista, i)
            return
        classe = {"espectro": VistaDeEspectro, "bandas": VistaDeBandas, "espectrograma": VistaDeEspectrograma,
                  "harmonicos": VistaDeHarmonicos, "xy": VistaDeXY, "histograma": VistaDeHistograma,
                  "eventos": VistaDeEventos, "qualidade": VistaDeQualidade, "transferencia": VistaDeTransferencia,
                  "metricas": VistaDeMetricas, "instrumento": VistaDeInstrumento}[vista.tipo]
        nome_do_icone = ICONE_DO_TIPO_DE_VISTA[vista.tipo]
        widget = classe(vista, self.projeto, self.janela.selecao, tarefas=self.janela.tarefas,
                        materializacoes=self.janela.materializacoes, vista_de_tempo=self._vista_de_tempo_por_id)
        widget.tracoClicado.connect(self._traco_clicado)
        widget.semRegiao.connect(self._sem_regiao)
        widget.medidasMudaram.connect(self._medidas_da_vista)
        if vista.tipo == "espectro":
            widget.calculado.connect(self._espectro_calculado)
            widget.calculado.connect(lambda v=vista: self.exibicaoMudou.emit(v))
            widget.grafico.getViewBox().sigXRangeChanged.connect(lambda *_a, v=vista: self.exibicaoMudou.emit(v))
        self.abas.insertTab(i, widget, icone(nome_do_icone, aparencia().tema.texto2), vista.nome)
        self._por_botao_de_fechar(i, widget)
        self.abas.setCurrentIndex(i)

    def _por_botao_de_fechar(self, i: int, widget: QWidget) -> None:
        """O × da aba: um botão de 20 px com o ícone de 14 px, no meio da altura da aba, à direita do nome (o estilo
        põe o botão do lado direito centrado na vertical). Fecha a aba dele, onde ela estiver."""
        fechar = QToolButton()
        fechar.setObjectName("fechar_aba")
        fechar.setAutoRaise(True)
        fechar.setIconSize(QSize(TAMANHO_DO_X, TAMANHO_DO_X))
        fechar.setFixedSize(QSize(TAMANHO_DO_BOTAO_DE_FECHAR, TAMANHO_DO_BOTAO_DE_FECHAR))
        fechar.setCursor(Qt.CursorShape.PointingHandCursor)
        fechar.setToolTip(self.tr("Fechar a vista (Ctrl+W; desfazível)"))
        IconeDoTema(fechar, "x", "texto2", tamanho=TAMANHO_DO_X)
        fechar.clicked.connect(lambda _=False, w=widget: self._fechar_aba(self.abas.indexOf(w)))
        self.abas.tabBar().setTabButton(i, QTabBar.ButtonPosition.RightSide, fechar)

    def _vista_saiu(self, vista: Vista, _i: int) -> None:
        widget = self.widget_da_vista(vista)
        if widget is not None:
            self.abas.removeTab(self.abas.indexOf(widget))
            widget.soltar()
            widget.deleteLater()

    def _vista_mudou(self, vista: Vista, campos) -> None:
        widget = self.widget_da_vista(vista)
        if widget is not None and "nome" in campos:
            self.abas.setTabText(self.abas.indexOf(widget), vista.nome)
            if vista is self.vista_ativa():
                self._inspetor_da_vista()

    # ------------------------------------------------------------------ o inspetor da vista ativa

    def _inspetor_da_vista(self, trocou_de_aba: bool = False) -> None:
        """A vista da aba ativa vai para o inspetor: numa de espectro, a análise dela aparece com o traço
        selecionado e, sem seleção, sozinha (as propriedades da vista). A captura mostrada no inspetor fica, a não ser
        que o usuário tenha trocado de aba (ele foi olhar a vista)."""
        if not isValid(self.inspetor):
            return
        widget = self.abas.currentWidget()
        vista = getattr(widget, "vista", None)
        espectro = vista if vista is not None and vista.tipo == "espectro" else None
        self.inspetor.definir_vista_ativa(self.projeto, vista, widget.fundamental if espectro else None)
        atual = self.inspetor.currentWidget()
        selecao = self.janela.selecao                     # None enquanto a janela se monta
        if (selecao is not None and selecao.tracos) or (atual is self.inspetor.da_fonte and not trocou_de_aba):
            return
        if vista is not None and vista.tipo not in ("tempo", "sonda"):     # as derivadas: as opções e a ajuda
            self.inspetor.mostrar_vista()
        elif atual is self.inspetor.da_vista:
            self.inspetor.mostrar("", None)

    def _espectro_calculado(self) -> None:
        if self.sender() is self.abas.currentWidget() and isValid(self.inspetor):
            self.inspetor.atualizar_vista()

    # ------------------------------------------------------------------ as medidas

    def _regiao_mudou(self, inicio: float, fim: float, dos_cursores: bool) -> None:
        widget = self.sender()
        if widget is self.abas.currentWidget():          # só a vista aberta é medida
            proprias = widget.regioes_proprias(inicio, fim)       # os traços com o tempo próprio: o trecho deles
            self.servico_de_medidas.medir(self.projeto, PedidoDeMedida(widget.vista, inicio, fim, dos_cursores,
                                                                       proprias))

    def _medidas_da_vista(self, medidas) -> None:
        """As medidas dos cursores de uma vista de frequência (só a aberta vai para a tabela)."""
        if self.sender() is self.abas.currentWidget() and isValid(self.tabela_de_medidas):
            self.tabela_de_medidas.mostrar_da_vista(medidas)

    def _sem_regiao(self) -> None:
        if self.sender() is self.abas.currentWidget() and isValid(self.tabela_de_medidas):
            self.tabela_de_medidas.explicar_o_vazio(getattr(getattr(self.sender(), "vista", None), "tipo", None))
            self.tabela_de_medidas.mostrar(None, [])

    def _aba_mudou(self, _i: int) -> None:
        widget = self.abas.currentWidget()
        self._inspetor_da_vista(trocou_de_aba=True)
        if isValid(self.tabela_de_medidas):
            self.tabela_de_medidas.explicar_o_vazio(getattr(getattr(widget, "vista", None), "tipo", None))
            if widget is None:
                self.tabela_de_medidas.mostrar(None, [])
            else:
                widget.emitir_regiao()

    def fechar_vista_ativa(self) -> bool:
        """Ctrl+W: fecha a vista da aba ativa, como o × dela (desfazível)."""
        i = self.abas.currentIndex()
        if i < 0 or getattr(self.abas.widget(i), "vista", None) is None:
            return False
        self._fechar_aba(i)
        return True

    def _fechar_aba(self, i: int) -> None:
        vista = getattr(self.abas.widget(i), "vista", None)
        if vista is not None:
            self.projeto.pilha.push(RemoverVista(self.projeto, vista, self.janela_da_vista(vista)))

    def restaurar_janelas(self, janelas: dict[str, tuple[float, float]],
                          cursores: dict[str, tuple[float, float]] | None = None) -> None:
        """O x que cada vista mostrava quando o projeto foi salvo e os cursores ligados (pelo id): a de tempo e a de
        espectro mostram a janela assim que tiverem os dados."""
        cursores = cursores or {}
        for vista in self.projeto.vistas:
            widget, janela = self.widget_da_vista(vista), janelas.get(vista.id)
            if isinstance(widget, VistaDeTempo) and vista.id in cursores:
                widget.ligar_cursores(True)
                widget.cursores = list(cursores[vista.id])
            if janela is None:
                continue
            if isinstance(widget, VistaDeTempo):
                widget.mostrar_tempo(*janela)
            elif isinstance(widget, VistaDeEspectro):
                widget.mostrar_frequencias(*janela)

    def cursores_da_vista(self, vista: Vista) -> tuple[float, float] | None:
        """Os cursores ligados da vista de tempo (s), ou ``None``."""
        widget = self.widget_da_vista(vista)
        posicoes = widget.cursores if isinstance(widget, VistaDeTempo) else None
        return tuple(posicoes) if posicoes is not None else None

    def janela_da_vista(self, vista: Vista) -> tuple[float, float] | None:
        """O que a vista mostra no x: o tempo (s) na de tempo, a frequência (Hz) na de espectro; ``None`` nas outras
        ou sem nada desenhado."""
        widget = self.widget_da_vista(vista)
        if isinstance(widget, VistaDeTempo):
            return widget.janela_de_tempo()
        if isinstance(widget, VistaDeEspectro) and widget.resultados:
            x0, x1 = widget.grafico.getViewBox().viewRange()[0]
            return (10.0 ** x0, 10.0 ** x1) if widget.opcoes.frequencia_log else (max(0.0, x0), x1)
        return None

    def nova_vista(self) -> Vista:
        nomes = {v.nome for v in self.projeto.vistas}
        n = 1
        while (nome := NOME_DA_PRIMEIRA_VISTA if n == 1 else f"{NOME_DA_PRIMEIRA_VISTA} {n}") in nomes:
            n += 1
        vista = Vista(nome)
        self.projeto.pilha.push(AdicionarVista(self.projeto, vista))
        return vista

    # ------------------------------------------------------------------ a exportação dos dados (F5.5)

    def exportar_dados(self, vista: Vista | None = None, pedido: PedidoDeDados | None = None,
                       caminho: Path | None = None):
        """FG-07: os dados da vista de tempo (a ativa, sem ``vista``). Sem ``pedido``, abre o diálogo (sem bloquear),
        e o "Exportar…" dele pergunta onde gravar; com ``pedido``, exporta direto (pergunta onde, sem ``caminho``).
        Devolve o diálogo, a tarefa ou ``None`` (com o aviso do porquê)."""
        vista = vista or self.vista_ativa()
        widget = self.widget_da_vista(vista) if vista is not None else None
        if not isinstance(widget, VistaDeTempo):
            Toast.mostrar(self.janela, self.tr("Os dados saem de uma vista de tempo: abra uma"), "aviso")
            return None
        if not any(t.receita.visivel for t in vista.tracos):
            Toast.mostrar(self.janela, self.tr("A vista não tem nenhum traço visível"), "aviso")
            return None
        coleta = ColetaDaVista(vista, widget, self.projeto, self.janela.materializacoes, self)
        if pedido is not None:
            return self._exportar_dados(coleta, pedido, caminho)
        dialogo = DialogoDeExportarDados(coleta, self._pedido_de_dados, self.janela)

        def fechou(resultado: int) -> None:
            if self.dialogo_de_dados is dialogo:
                self.dialogo_de_dados = None
            pedido_escolhido = dialogo.pedido() if resultado == QDialog.DialogCode.Accepted else None
            dialogo.deleteLater()
            if pedido_escolhido is not None:
                self._exportar_dados(coleta, pedido_escolhido, None)
            else:
                self._largar_coleta(coleta)

        dialogo.finished.connect(fechou)
        self.dialogo_de_dados = dialogo
        dialogo.open()
        return dialogo

    def _exportar_dados(self, coleta: ColetaDaVista, pedido: PedidoDeDados, caminho: Path | None):
        try:
            trecho = coleta.trecho(pedido)
        except ed.DadosInvalidos as erro:
            self._largar_coleta(coleta)
            Toast.mostrar(self.janela, self.tr("Os dados não foram exportados: {}").format(erro), "erro")
            return None
        self._pedido_de_dados = pedido
        formato = ed.FORMATOS[pedido.opcoes.formato]
        regiao = NOMES_DAS_REGIOES[pedido.regiao]
        if caminho is None:
            pasta = self._pasta_dos_dados or (self.projeto.caminho.parent if self.projeto.caminho else Path.home())
            caminho = self.janela.controle.dialogos.salvar_arquivo(
                self.tr("Exportar os dados da vista"), f"{formato.nome} (*{formato.extensao})",
                str(pasta / ed.nome_do_arquivo(coleta.vista.nome, regiao, pedido.opcoes)))
            if caminho is None:
                self._largar_coleta(coleta)
                return None
        caminho = Path(caminho)
        if caminho.suffix.lower() != formato.extensao:
            caminho = caminho.with_name(caminho.name + formato.extensao)
        self._pasta_dos_dados = caminho.parent
        fontes = coleta.fontes_usadas(trecho)
        proveniencia = dos_dados(trecho, pedido.opcoes, fontes_da_proveniencia(self.projeto),
                                 aplicativo=QCoreApplication.applicationVersion() or "dev", regiao=regiao)
        # O cabeçalho da captura vai no HDF5 quando os traços vêm de uma só (o grupo /captura).
        captura = fontes[0].fonte.captura if len(fontes) == 1 and formato.id == "hdf5" else None

        def trabalho(progresso, cancelado):
            ed.exportar(trecho, caminho, pedido.opcoes, proveniencia=proveniencia,
                        captura=api.cabecalho_para_hdf5(captura) if captura is not None else None,
                        progresso=progresso, cancelado=cancelado)
            return caminho

        return self.janela.tarefas.iniciar(
            self.tr("Exportar os dados de {} ({})").format(coleta.vista.nome, formato.nome), trabalho, "dados",
            pesada=True, ao_terminar=lambda tarefa: self._dados_exportados(tarefa, coleta))

    def _largar_coleta(self, coleta: ColetaDaVista) -> None:
        if isValid(coleta):
            coleta.soltar()
            coleta.deleteLater()

    def _dados_exportados(self, tarefa, coleta: ColetaDaVista) -> None:
        self._largar_coleta(coleta)
        if not isValid(self):
            return
        if tarefa.estado == "concluida":
            caminho = tarefa.resultado
            Toast.mostrar(self.janela, self.tr("Dados exportados: {} ({}), com a proveniência ao lado").format(
                caminho.name, formatar_bytes(caminho.stat().st_size)), "sucesso")
            self.dadosExportados.emit(caminho)
        elif tarefa.estado == "falhou":
            Toast.mostrar(self.janela, self.tr("Os dados não foram exportados: {}").format(tarefa.erro), "erro")

    # ------------------------------------------------------------------ a seleção

    def _traco_clicado(self, traco: Traco | None, modificadores) -> None:
        selecao = self.janela.selecao
        somar = bool(modificadores & Qt.KeyboardModifier.ControlModifier)
        if traco is None:
            if not somar:
                selecao.limpar()
        elif somar:
            selecao.alternar(traco)
        else:
            selecao.definir([traco])

    def _tracos_selecionados(self, tracos) -> None:
        """A seleção de traços vai para o inspetor; sem traço selecionado, ele volta ao vazio (se mostrava traços)."""
        if tracos:
            self.inspetor.mostrar_tracos(self.projeto, tracos)
        elif self.inspetor.currentWidget() is self.inspetor.do_traco:
            self.inspetor.mostrar("", None)
            self._inspetor_da_vista()

    def remover_selecionados(self) -> bool:
        """``Del``: tira da vista ativa os traços selecionados nela (desfazível)."""
        vista = self.vista_ativa()
        if vista is None:
            return False
        tracos = [t for t in self.janela.selecao.tracos if t in vista.tracos]
        if not tracos:
            return False
        self.projeto.pilha.push(RemoverTracos(vista, tracos))
        return True

    def _fonte_entrou(self, fonte: FonteDoProjeto, _i: int) -> None:
        self._avisos_da_fonte(fonte)
        self._ativar(fonte)
        self.painel.selecionar_fonte(fonte)

    def _fonte_saiu(self, fonte: FonteDoProjeto, _i: int) -> None:
        self.avisos.remover_origem(fonte.id)
        if self.fonte_ativa is fonte:
            restantes = self.projeto.fontes
            self._ativar(restantes[-1] if restantes else None)
        if self.inspetor.da_fonte.fonte is fonte:
            self.inspetor.mostrar("", None)

    def _avisos_da_fonte(self, fonte: FonteDoProjeto) -> None:
        if not fonte.esta_ausente:
            avisos = fonte.fonte.captura.avisos
            if e_o_exemplo(fonte.caminho):
                avisos = do_exemplo(avisos)
            self.avisos.adicionar(avisos, fonte.id, fonte.nome)

    # ------------------------------------------------------------------ as notas (os cadernos de bancada)

    def abrir_no_editor(self, arquivo) -> None:
        if arquivo is not None:
            self.abrir_url(QUrl.fromLocalFile(str(arquivo)))

    def cadernos_mudaram(self) -> None:
        """Um caderno mudou (o da sessão, pela Aquisição ou pelo editor): a seção Notas e o inspetor dele."""
        if self.painel.modelo is not None:
            self.painel.modelo.atualizar_as_notas()
        if self.inspetor.currentWidget() is self.inspetor.do_caderno:
            self.inspetor.do_caderno.recarregar()

    # ------------------------------------------------------------------ a captura ativa (a barra de status)

    def _selecao_mudou(self, tipo: str, objeto) -> None:
        if tipo == "vista":
            return                   # o clique abre a aba dela (ativar_vista), e o inspetor segue a aba
        self.inspetor.mostrar(tipo, objeto)
        if tipo == "fonte":
            self._ativar(objeto)
        elif tipo == "canal" and objeto is not None:
            fonte, numero = objeto
            self._ativar(fonte)
            # Um canal da árvore seleciona os traços dele na vista aberta.
            vista = self.vista_ativa()
            if vista is not None:
                dele = [t for t in vista.tracos if t.receita.fonte == fonte.id and t.receita.canal == numero]
                if dele:
                    self.janela.selecao.definir(dele)

    def _ativar(self, fonte: FonteDoProjeto | None) -> None:
        if fonte is self.fonte_ativa:
            self._estado_da_ativa()
            return
        if self.fonte_ativa is not None and isValid(self.fonte_ativa):
            self.fonte_ativa.estadoMudou.disconnect(self._estado_da_ativa)
        self.fonte_ativa = fonte
        if fonte is not None:
            fonte.estadoMudou.connect(self._estado_da_ativa)
        self._estado_da_ativa()

    def _estado_da_ativa(self, *_) -> None:
        if not isValid(self.status_fonte):
            return
        fonte = self.fonte_ativa
        if fonte is None:
            self.status_fonte.setText(self.tr("Nenhuma captura aberta"))
            self.status_integridade.setText("")
            return
        if fonte.esta_ausente:
            self.status_fonte.setText(self.tr("{}: ausente").format(fonte.nome))
            self.status_integridade.setText("")
            return
        canais = fonte.canais
        captura = fonte.fonte.captura
        partes = [fonte.nome, formatar_si(canais[0].taxa_hz * len(canais), "S/s", 3),
                  f"{len(canais)} {'canal' if len(canais) == 1 else 'canais'}"]
        if captura.tipo != "bin":
            partes.append({"csv": "CSV", "h5": "HDF5"}[captura.tipo])
        partes.append(self.tr("cabeçalho v{}").format(captura.cabecalho.versao_cabecalho)
                      if captura.cabecalho is not None else self.tr("sem cabeçalho (taxa informada)"))
        if fonte.progresso_da_piramide is not None:
            partes.append(self.tr("pirâmide {:.0%}").format(fonte.progresso_da_piramide))
        elif fonte.piramides:
            partes.append(self.tr("pirâmide pronta · {} níveis").format(len(fonte.piramides[0].niveis)))
        self.status_fonte.setText(" · ".join(partes))
        self.status_integridade.setText({"confere": self.tr("✓ integridade"),
                                         "nao_confere": self.tr("✗ CRC não confere"),
                                         "conferindo": self.tr("conferindo o CRC…")}.get(fonte.integridade, ""))
        self.status_integridade.setToolTip(TEXTOS_DA_INTEGRIDADE[fonte.integridade][2])
        self.status_integridade.setProperty("nivel", {"confere": "ok", "nao_confere": "erro"}.get(fonte.integridade,
                                                                                                   ""))
        self.status_integridade.style().unpolish(self.status_integridade)
        self.status_integridade.style().polish(self.status_integridade)

    # ------------------------------------------------------------------ ações

    def plotar_canal(self, fonte: FonteDoProjeto, numero: int, vista: Vista | None = None) -> Traco:
        """Põe o canal na vista (a ativa; sem nenhuma, cria a primeira), com a próxima cor livre. Um passo só de
        desfazer, mesmo quando cria a vista."""
        projeto = self.projeto
        vista = vista or self.janela.vista_ativa()
        if vista is not None and vista.tipo != "tempo":       # o espectro segue uma vista de tempo: o traço vai nela
            tempos = [v for v in projeto.vistas if v.tipo == "tempo"]
            vista = next((v for v in tempos if v.id == getattr(vista.opcoes, "vista_de_tempo", None)),
                         tempos[0] if tempos else None)
        nome = nome_do_traco(fonte, numero)
        projeto.pilha.beginMacro(self.tr("Plotar {}").format(nome))
        try:
            if vista is None:
                vista = Vista(NOME_DA_PRIMEIRA_VISTA)
                projeto.pilha.push(AdicionarVista(projeto, vista))
            traco = Traco(ReceitaDoTraco(fonte.id, numero, nome, vista.proxima_cor(),
                                         faixa=self._faixa_para(vista, fonte.canal(numero).unidade)))
            projeto.pilha.push(AdicionarTraco(vista, traco))
        finally:
            projeto.pilha.endMacro()
        return traco

    def _faixa_para(self, vista: Vista, unidade: str) -> int:
        """A faixa de um traço novo: a dos traços com a mesma unidade na vista (a de cada um: a dele ou a do
        canal); sem nenhum, uma faixa nova."""
        ocupadas = {}
        for t in vista.tracos:
            try:
                f = self.projeto.fonte(t.receita.fonte)
            except KeyError:
                continue
            if not f.esta_ausente:
                ocupadas.setdefault(t.receita.unidade_de(f.canal(t.receita.canal).unidade), t.receita.faixa)
        if unidade in ocupadas:
            return ocupadas[unidade]
        usadas = {t.receita.faixa for t in vista.tracos}
        return max(usadas) + 1 if usadas else 0

    def fechar_fonte(self, fonte: FonteDoProjeto) -> None:
        self.projeto.pilha.push(RemoverFonte(self.projeto, fonte))
