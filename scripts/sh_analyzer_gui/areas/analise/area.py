"""As ligações da área de Análise na janela: o painel do projeto, o inspetor, os avisos de cada captura, a barra de
status da captura ativa e o plotar um canal. A janela monta as regiões (os docks, as abas); esta classe as faz
conversar com o projeto aberto, e troca de projeto junto com a janela.

Cada ligação com o projeto é desfeita ao trocar de projeto (:meth:`AreaDeAnalise.acompanhar`): o projeto antigo não
mexe mais na tela.
"""

from __future__ import annotations

from PySide6.QtCore import QObject
from PySide6.QtWidgets import QLabel
from shiboken6 import isValid

from ...componentes.avisos import ListaDeAvisos
from ...componentes.numeros import formatar_si
from ...dados.receita import ReceitaDoTraco
from ...modelo.comandos import AdicionarTraco, AdicionarVista, RemoverFonte
from ...modelo.objetos import FonteDoProjeto, Projeto, Traco, Vista
from .arvore import PainelDoProjeto
from .inspetor import TEXTOS_DA_INTEGRIDADE, Inspetor

NOME_DA_PRIMEIRA_VISTA = "Tempo"


def nome_do_traco(fonte: FonteDoProjeto, numero: int) -> str:
    """O nome de um traço novo: o canal e a captura ("canal 1 · A1_60Hz_20k")."""
    return f"canal {numero} · {fonte.caminho.stem}"


class AreaDeAnalise(QObject):
    def __init__(self, janela, painel: PainelDoProjeto, inspetor: Inspetor, avisos: ListaDeAvisos,
                 status_fonte: QLabel, status_integridade: QLabel):
        super().__init__(janela)
        self.janela, self.painel, self.inspetor, self.avisos = janela, painel, inspetor, avisos
        self.status_fonte, self.status_integridade = status_fonte, status_integridade
        self.projeto: Projeto | None = None
        self.fonte_ativa: FonteDoProjeto | None = None
        painel.canalAtivado.connect(self.plotar_canal)
        painel.selecaoMudou.connect(self._selecao_mudou)
        painel.fecharFontePedido.connect(self.fechar_fonte)

    # ------------------------------------------------------------------ o projeto

    def acompanhar(self, projeto: Projeto) -> None:
        if self.projeto is not None:
            self.projeto.fonteEntrou.disconnect(self._fonte_entrou)
            self.projeto.fonteSaiu.disconnect(self._fonte_saiu)
            for fonte in self.projeto.fontes:
                self.avisos.remover_origem(fonte.id)
        self._ativar(None)
        self.projeto = projeto
        # A árvore primeiro: ligada antes, ela já tem a linha da captura nova quando a área a seleciona.
        self.painel.mostrar(projeto)
        projeto.fonteEntrou.connect(self._fonte_entrou)
        projeto.fonteSaiu.connect(self._fonte_saiu)
        self.inspetor.mostrar("", None)
        for fonte in projeto.fontes:
            self._avisos_da_fonte(fonte)
        if projeto.fontes:
            self._ativar(projeto.fontes[-1])

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
            self._ativar(objeto[0])

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
        nome = nome_do_traco(fonte, numero)
        projeto.pilha.beginMacro(self.tr("Plotar {}").format(nome))
        try:
            if vista is None:
                vista = Vista(NOME_DA_PRIMEIRA_VISTA)
                projeto.pilha.push(AdicionarVista(projeto, vista))
            traco = Traco(ReceitaDoTraco(fonte.id, numero, nome, vista.proxima_cor()))
            projeto.pilha.push(AdicionarTraco(vista, traco))
        finally:
            projeto.pilha.endMacro()
        return traco

    def fechar_fonte(self, fonte: FonteDoProjeto) -> None:
        self.projeto.pilha.push(RemoverFonte(self.projeto, fonte))
