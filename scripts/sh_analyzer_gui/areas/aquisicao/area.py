"""A área de Aquisição (o B1; docs/gui-plan.md, 11 e 13.2): a barra lateral (a placa, as seções e a lista de placas) e
a seção escolhida. A placa conectada mora em ``servicos/conexao_da_placa.py``; a área mostra e pergunta.

**A busca** roda enquanto a área está à vista (``procurar_sempre``), e para quando ela sai (outra área, a janela
minimizada): quem não está olhando a lista não sonda a rede.

**O diálogo da conexão** abre sozinho só quando a conexão precisa do usuário (a impressão digital, a senha, o
bloqueio de uma conexão que ele pediu, o resumo da primeira conexão); conectar a uma placa conhecida da lista não abre
nada.
"""

from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QStackedWidget, QWidget

from ...servicos.conexao_da_placa import ESPERANDO_O_USUARIO, ConexaoDaPlaca
from .dialogo_de_conexao import DialogoDeConexao
from .lateral import SECOES, BarraLateral
from .visao_geral import SecaoQueChega, VisaoGeral


class AreaDeAquisicao(QWidget):
    def __init__(self, conexao: ConexaoDaPlaca, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("area_aquisicao")
        self.conexao = conexao
        self._dialogo: DialogoDeConexao | None = None
        self.lateral = BarraLateral(conexao)
        self.secoes = QStackedWidget()
        self.secoes.setObjectName("secoes_aquisicao")
        self.visao_geral = VisaoGeral(conexao)
        self.paginas: dict[str, QWidget] = {"visao_geral": self.visao_geral}
        for nome, _titulo, _icone in SECOES[1:]:
            self.paginas[nome] = SecaoQueChega(nome)
        for pagina in self.paginas.values():
            self.secoes.addWidget(pagina)
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
        conexao.mudou.connect(self._conexao_mudou)
        self.mostrar_secao("visao_geral")

    @property
    def secao(self) -> str:
        return self.lateral.navegacao.secao

    def mostrar_secao(self, nome: str) -> None:
        self.lateral.navegacao.escolher(nome)

    def _secao_escolhida(self, nome: str) -> None:
        self.secoes.setCurrentWidget(self.paginas[nome])

    @property
    def dialogo(self) -> DialogoDeConexao:
        """O diálogo da conexão (um só, criado na primeira vez, filho da janela)."""
        if self._dialogo is None:
            self._dialogo = DialogoDeConexao(self.conexao, self.window())
        return self._dialogo

    def conectar_por_ip(self) -> None:
        self.dialogo.abrir_para_destino()

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
