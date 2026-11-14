"""As ligações da área de Análise na janela: o painel do projeto, o inspetor, os avisos de cada captura, a barra de
status da captura ativa, as abas das vistas, a seleção e o plotar um canal. A janela monta as regiões (os docks, as
abas); esta classe as faz conversar com o projeto aberto, e troca de projeto junto com a janela.

Cada ligação com o projeto é desfeita ao trocar de projeto (:meth:`AreaDeAnalise.acompanhar`): o projeto antigo não
mexe mais na tela.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, QSize, Qt
from PySide6.QtWidgets import QLabel, QTabBar, QTabWidget, QToolButton, QWidget
from shiboken6 import isValid

from ...componentes.avisos import ListaDeAvisos
from ...componentes.numeros import formatar_si
from ...dados.espectros import OPCOES_DO_TIPO
from ...dados.receita import ReceitaDoTraco
from ...modelo.comandos import AdicionarTraco, AdicionarVista, RemoverFonte, RemoverTracos, RemoverVista
from ...modelo.objetos import FonteDoProjeto, Projeto, Traco, Vista
from ...servicos.medidas import PedidoDeMedida, ServicoDeMedidas
from ...tema.aplicar import aparencia
from ...tema.icones import IconeDoTema, icone
from .arvore import PainelDoProjeto
from .inspetor import TEXTOS_DA_INTEGRIDADE, Inspetor
from .medidas import TabelaDeMedidas
from .vista_espectro import VistaDeEspectro
from .vista_tempo import VistaDeTempo
from .vistas_de_mapa import VistaDeBandas, VistaDeEspectrograma, VistaDeHarmonicos

NOME_DA_PRIMEIRA_VISTA = "Tempo"
TAMANHO_DO_BOTAO_DE_FECHAR = 20
TAMANHO_DO_X = 14


def nome_do_traco(fonte: FonteDoProjeto, numero: int) -> str:
    """O nome de um traço novo: o canal e a captura ("canal 1 · A1_60Hz_20k")."""
    return f"canal {numero} · {fonte.caminho.stem}"


class AreaDeAnalise(QObject):
    def __init__(self, janela, painel: PainelDoProjeto, inspetor: Inspetor, avisos: ListaDeAvisos,
                 status_fonte: QLabel, status_integridade: QLabel, abas: QTabWidget, medidas: TabelaDeMedidas):
        super().__init__(janela)
        self.tabela_de_medidas = medidas
        self.servico_de_medidas = ServicoDeMedidas(janela.tarefas, self, materializacoes=janela.materializacoes)
        self.servico_de_medidas.prontas.connect(medidas.mostrar)
        abas.currentChanged.connect(self._aba_mudou)
        self.janela, self.painel, self.inspetor, self.avisos = janela, painel, inspetor, avisos
        self.status_fonte, self.status_integridade, self.abas = status_fonte, status_integridade, abas
        self.projeto: Projeto | None = None
        self.fonte_ativa: FonteDoProjeto | None = None
        painel.canalAtivado.connect(self.plotar_canal)
        painel.selecaoMudou.connect(self._selecao_mudou)
        painel.fecharFontePedido.connect(self.fechar_fonte)


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

    def widget_da_vista(self, vista: Vista) -> VistaDeTempo | None:
        for i in range(self.abas.count()):
            widget = self.abas.widget(i)
            if getattr(widget, "vista", None) is vista:
                return widget
        return None

    def vista_ativa(self) -> Vista | None:
        widget = self.abas.currentWidget()
        return getattr(widget, "vista", None)

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
            ativa = next((v for v in self.projeto.vistas if v.id == ativa.opcoes.vista_de_tempo), None)
        if ativa is None:
            ativa = next((v for v in self.projeto.vistas if v.tipo == "tempo"), None)
        if ativa is None:
            return None
        nomes = {v.nome for v in self.projeto.vistas}
        rotulos = {"espectro": self.tr("Espectro de {}"), "bandas": self.tr("Bandas de {}"),
                   "espectrograma": self.tr("Espectrograma de {}"), "harmonicos": self.tr("Harmônicos de {}")}
        nome, n = rotulos[tipo].format(ativa.nome), 2
        base = nome
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
        widget.semRegiao.connect(self._sem_regiao)
        self.abas.insertTab(i, widget, icone("onda", aparencia().tema.texto2), vista.nome)
        self._por_botao_de_fechar(i, widget)
        self.abas.setCurrentIndex(i)

    def _vista_de_frequencia_entrou(self, vista: Vista, i: int) -> None:
        classe, nome_do_icone = {"espectro": (VistaDeEspectro, "espectro"), "bandas": (VistaDeBandas, "grade"),
                                 "espectrograma": (VistaDeEspectrograma, "camadas"),
                                 "harmonicos": (VistaDeHarmonicos, "pulso")}[vista.tipo]
        widget = classe(vista, self.projeto, self.janela.selecao, tarefas=self.janela.tarefas,
                        materializacoes=self.janela.materializacoes, vista_de_tempo=self._vista_de_tempo_por_id)
        widget.tracoClicado.connect(self._traco_clicado)
        widget.semRegiao.connect(self._sem_regiao)
        widget.medidasMudaram.connect(self._medidas_da_vista)
        if vista.tipo == "espectro":
            widget.calculado.connect(self._espectro_calculado)
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
        if espectro is not None:
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
            self.servico_de_medidas.medir(self.projeto, PedidoDeMedida(widget.vista, inicio, fim, dos_cursores))

    def _medidas_da_vista(self, medidas) -> None:
        """As medidas dos cursores de uma vista de frequência (só a aberta vai para a tabela)."""
        if self.sender() is self.abas.currentWidget() and isValid(self.tabela_de_medidas):
            self.tabela_de_medidas.mostrar_da_vista(medidas)

    def _sem_regiao(self) -> None:
        if self.sender() is self.abas.currentWidget() and isValid(self.tabela_de_medidas):
            self.tabela_de_medidas.mostrar(None, [])

    def _aba_mudou(self, _i: int) -> None:
        widget = self.abas.currentWidget()
        self._inspetor_da_vista(trocou_de_aba=True)
        if isValid(self.tabela_de_medidas):
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
            self.projeto.pilha.push(RemoverVista(self.projeto, vista))

    def nova_vista(self) -> Vista:
        nomes = {v.nome for v in self.projeto.vistas}
        n = 1
        while (nome := NOME_DA_PRIMEIRA_VISTA if n == 1 else f"{NOME_DA_PRIMEIRA_VISTA} {n}") in nomes:
            n += 1
        vista = Vista(nome)
        self.projeto.pilha.push(AdicionarVista(self.projeto, vista))
        return vista

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
            self.avisos.adicionar(fonte.fonte.captura.avisos, fonte.id, fonte.nome)

    # ------------------------------------------------------------------ a captura ativa (a barra de status)

    def _selecao_mudou(self, tipo: str, objeto) -> None:
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
        cabecalho = fonte.fonte.captura.cabecalho
        partes = [fonte.nome, formatar_si(canais[0].taxa_hz * len(canais), "S/s", 3),
                  f"{len(canais)} {'canal' if len(canais) == 1 else 'canais'}",
                  self.tr("cabeçalho v{}").format(cabecalho.versao_cabecalho)]
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
            vista = next((v for v in tempos if v.id == vista.opcoes.vista_de_tempo), tempos[0] if tempos else None)
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
        """A faixa de um traço novo: a dos traços com a mesma unidade na vista; sem nenhum, uma faixa nova."""
        ocupadas = {}
        for t in vista.tracos:
            try:
                f = self.projeto.fonte(t.receita.fonte)
            except KeyError:
                continue
            if not f.esta_ausente:
                ocupadas.setdefault(f.canal(t.receita.canal).unidade, t.receita.faixa)
        if unidade in ocupadas:
            return ocupadas[unidade]
        usadas = {t.receita.faixa for t in vista.tracos}
        return max(usadas) + 1 if usadas else 0

    def fechar_fonte(self, fonte: FonteDoProjeto) -> None:
        self.projeto.pilha.push(RemoverFonte(self.projeto, fonte))
