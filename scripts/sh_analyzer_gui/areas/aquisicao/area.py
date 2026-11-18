"""A área de Aquisição (o B1; docs/gui-plan.md, 11 e 13.2): a barra lateral (a placa, as seções e a lista de placas) e
a seção escolhida. A placa conectada mora em ``servicos/conexao_da_placa.py``, e o que se sabe dela, em
``servicos/saude_da_placa.py``; a área mostra e pergunta.

**A busca** roda enquanto a área está à vista (``procurar_sempre``), e para quando ela sai (outra área, a janela
minimizada): quem não está olhando a lista não sonda a rede.

**O diálogo da conexão** abre sozinho só quando a conexão precisa do usuário (a impressão digital, a senha, o
bloqueio de uma conexão que ele pediu, o resumo da primeira conexão); conectar a uma placa conhecida da lista não abre
nada.

**As correções** (o "Corrigir" da visão geral e do diagnóstico) passam pelo diálogo da correção, que confirma e
mostra o comando; o resultado aparece num toast na janela, inclusive o do relógio acertado sozinho ao conectar.
"""

from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QStackedWidget, QWidget

from ...componentes.toast import Toast
from ...servicos.conexao_da_placa import ESPERANDO_O_USUARIO, ConexaoDaPlaca
from ...servicos.conferencia_da_placa import ConferenciaDaPlaca
from ...servicos.saude_da_placa import SaudeDaPlaca
from ...servicos.transferencias import TransferenciasDaPlaca
from .arquivos import Arquivos
from .capturar import Capturar
from .diagnostico import Diagnostico
from .dialogo_de_conexao import DialogoDeConexao
from .dialogo_de_correcao import DialogoDeCorrecao
from .lateral import SECOES, BarraLateral
from .terminal import Terminal
from .textos import frase, traduzir
from .visao_geral import SecaoQueChega, VisaoGeral


class AreaDeAquisicao(QWidget):
    """``dialogos_de()``: quem pergunta (onde salvar o relatório, apagar da placa, fechar um terminal com uma captura
    rodando); o ``controle.dialogos`` da janela. ``abrir_na_analise(caminhos)``: as cópias das capturas, abertas na
    Análise. ``abrir_url``: o gerenciador de arquivos do sistema, e ``executar_programa``: o terminal do sistema (os
    testes passam uns que não abrem nada)."""

    def __init__(self, conexao: ConexaoDaPlaca, saude: SaudeDaPlaca, dialogos_de=None,
                 transferencias: TransferenciasDaPlaca | None = None, abrir_na_analise=None, abrir_url=None,
                 executar_programa=None, conferencia: ConferenciaDaPlaca | None = None,
                 opcoes_da_captura: dict | None = None, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("area_aquisicao")
        self.conexao, self.saude = conexao, saude
        self._dialogo: DialogoDeConexao | None = None
        self.dialogo_de_correcao: DialogoDeCorrecao | None = None
        self._avisada = None                 # a correção cujo resultado já foi avisado
        self.lateral = BarraLateral(conexao)
        self.secoes = QStackedWidget()
        self.secoes.setObjectName("secoes_aquisicao")
        self.transferencias = transferencias if transferencias is not None else TransferenciasDaPlaca(conexao, saude,
                                                                                                    parent=self)
        self.visao_geral = VisaoGeral(conexao, saude, self.transferencias)
        self.diagnostico = Diagnostico(conexao, saude, dialogos_de)
        extras = {"abrir_url": abrir_url} if abrir_url is not None else {}
        self.arquivos = Arquivos(conexao, saude, self.transferencias, abrir_na_analise=abrir_na_analise,
                                 dialogos_de=dialogos_de, **extras)
        if executar_programa is not None:
            extras["executar_programa"] = executar_programa
        self.terminal = Terminal(conexao, dialogos_de=dialogos_de, **extras)
        self.conferencia = conferencia if conferencia is not None else ConferenciaDaPlaca(conexao, saude, parent=self)
        self.capturar = Capturar(conexao, saude, self.conferencia, **(opcoes_da_captura or {}))
        self.paginas: dict[str, QWidget] = {"visao_geral": self.visao_geral, "diagnostico": self.diagnostico,
                                            "arquivos": self.arquivos, "terminal": self.terminal,
                                            "capturar": self.capturar}
        for nome, _titulo, _icone in SECOES:
            if nome not in self.paginas:
                self.paginas[nome] = SecaoQueChega(nome)
            self.secoes.addWidget(self.paginas[nome])
        linha = QHBoxLayout(self)
        linha.setContentsMargins(0, 0, 0, 0)
        linha.setSpacing(0)
        linha.addWidget(self.lateral)
        linha.addWidget(self.secoes, 1)

        self.lateral.navegacao.secaoEscolhida.connect(self._secao_escolhida)
        self.lateral.conectarPorIp.connect(self.conectar_por_ip)
        self.lateral.cartao.responder.connect(lambda: self.dialogo.acompanhar())
        self.lateral.lista.conectadaClicada.connect(lambda: self.mostrar_secao("visao_geral"))
        self.visao_geral.conectarPorIp.connect(self.conectar_por_ip)
        self.visao_geral.verBloqueio.connect(lambda: self.dialogo.acompanhar())
        self.visao_geral.corrigir.connect(self.corrigir)
        self.diagnostico.corrigir.connect(self.corrigir)
        conexao.mudou.connect(self._conexao_mudou)
        saude.correcaoMudou.connect(self._correcao_mudou)
        self.mostrar_secao("visao_geral")

    @property
    def secao(self) -> str:
        return self.lateral.navegacao.secao

    def mostrar_secao(self, nome: str) -> None:
        self.lateral.navegacao.escolher(nome)

    def acompanhar(self, projeto) -> None:
        """O projeto da janela: os modelos de captura são dele."""
        self.capturar.acompanhar(projeto)

    def _secao_escolhida(self, nome: str) -> None:
        if nome == "capturar":
            self.capturar.ler_os_perfis()
            self.capturar.validar()
        self.secoes.setCurrentWidget(self.paginas[nome])

    @property
    def dialogo(self) -> DialogoDeConexao:
        """O diálogo da conexão (um só, criado na primeira vez, filho da janela)."""
        if self._dialogo is None:
            self._dialogo = DialogoDeConexao(self.conexao, self.window())
        return self._dialogo

    def conectar_por_ip(self) -> None:
        self.dialogo.abrir_para_destino()

    def corrigir(self, nome: str) -> DialogoDeCorrecao:
        """A confirmação da correção ``nome`` (nada roda antes dela)."""
        if self.dialogo_de_correcao is not None:
            self.dialogo_de_correcao.deleteLater()
        self.dialogo_de_correcao = DialogoDeCorrecao(self.saude, nome, self.window())
        self.dialogo_de_correcao.open()
        return self.dialogo_de_correcao

    def _correcao_mudou(self) -> None:
        """O resultado de uma correção, num toast: a feita (pedida ou a do relógio a cada conexão) e a automática que
        falhou (a pedida que falhou fica no diálogo dela)."""
        correcao = self.saude.correcao
        if correcao is None or correcao is self._avisada:
            return
        if correcao.estado == "feita":
            self._avisada = correcao
            Toast.mostrar(self.window(), correcao.mensagem, "sucesso")
        elif correcao.estado == "falhou" and correcao.automatica:
            self._avisada = correcao
            Toast.mostrar(self.window(), traduzir("O relógio não foi acertado: {}").format(frase(correcao.mensagem)),
                          "aviso")

    def _conexao_mudou(self) -> None:
        c = self.conexao
        precisa = c.estado in ESPERANDO_O_USUARIO or (c.estado == "bloqueada" and c.pedida_pelo_usuario) or \
            (c.estado == "conectada" and c.primeira_conexao is not None)
        if precisa and not self.dialogo.isVisible():
            self.dialogo.acompanhar()

    def showEvent(self, evento) -> None:
        super().showEvent(evento)
        self.conexao.procurar_sempre(True)

    def hideEvent(self, evento) -> None:
        super().hideEvent(evento)
        self.conexao.procurar_sempre(False)
