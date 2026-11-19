"""A seção Manutenção da Aquisição (docs/gui-plan.md, 11.10; a Fase 6): as páginas no alto (:data:`PAGINAS`), cada
uma numa coluna no meio, como o diagnóstico; sem placa, o estado vazio. As confirmações (o diálogo da atualização, o
das ações do sistema) abrem daqui, sobre a janela."""

from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QStackedWidget, QVBoxLayout, QWidget

from ....componentes.basicos import Segmentado
from ....componentes.painel import EstadoVazio
from ....servicos.conexao_da_placa import ConexaoDaPlaca
from ....servicos.manutencao_da_placa import ManutencaoDaPlaca
from ..textos import traduzir
from .firmware import DialogoDaAtualizacao, PaginaDoFirmware

PAGINAS = (("firmware", "Firmware", "chave"),)


class Manutencao(QWidget):
    """A seção Manutenção: as páginas (:data:`PAGINAS`) no alto e a escolhida embaixo; sem placa, o estado vazio."""

    def __init__(self, conexao: ConexaoDaPlaca, manutencao: ManutencaoDaPlaca, dialogos_de=None,
                 captura_rodando=None, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("secao_manutencao")
        self.conexao, self.manutencao, self.dialogos_de = conexao, manutencao, dialogos_de
        self.dialogo: DialogoDaAtualizacao | None = None
        self.firmware = PaginaDoFirmware(manutencao, dialogos_de, captura_rodando)
        self.firmware.confirmar.connect(self.confirmar_atualizacao)
        self.paginas: dict[str, QWidget] = {"firmware": self.firmware}
        self.escolha = Segmentado([traduzir(t) for _n, t, _i in PAGINAS], icones=[i for _n, _t, i in PAGINAS])
        self.escolha.setObjectName("paginas_da_manutencao")
        self.pilha = QStackedWidget()
        for nome, _t, _i in PAGINAS:
            self.pilha.addWidget(self.paginas[nome])
        self.escolha.escolhaMudou.connect(lambda i: self.pilha.setCurrentIndex(i))
        conectada = QWidget()
        coluna = QVBoxLayout(conectada)
        coluna.setContentsMargins(0, 12, 0, 0)
        coluna.setSpacing(0)
        topo = QHBoxLayout()
        topo.addStretch(1)
        topo.addWidget(self.escolha)
        topo.addStretch(1)
        coluna.addLayout(topo)
        coluna.addWidget(self.pilha, 1)
        self.vazio = EstadoVazio(traduzir("Nenhuma placa conectada"),
                                 traduzir("A manutenção cuida do firmware da placa conectada: atualizar com a volta "
                                          "sozinha, voltar a uma versão anterior, compilar e carregar de novo."),
                                 icone_nome="chave", largura_do_texto=440)
        self.estados = QStackedWidget()
        self.estados.addWidget(self.vazio)
        self.estados.addWidget(conectada)
        fora = QVBoxLayout(self)
        fora.setContentsMargins(0, 0, 0, 0)
        fora.addWidget(self.estados)
        conexao.mudou.connect(self._conexao_mudou)
        self._conexao_mudou()

    def _conexao_mudou(self) -> None:
        self.estados.setCurrentIndex(1 if self.conexao.estado in ("conectada", "reconectando") else 0)
        if self.isVisible():
            self.manutencao.ler_se_preciso()

    def showEvent(self, evento) -> None:
        super().showEvent(evento)
        self.manutencao.ler_se_preciso()           # o firmware é lido quando a seção aparece (o git, o plano)

    def mostrar_pagina(self, nome: str) -> None:
        indice = [n for n, _t, _i in PAGINAS].index(nome)
        self.escolha.escolher(indice)
        self.pilha.setCurrentIndex(indice)

    @property
    def pagina(self) -> str:
        return PAGINAS[self.pilha.currentIndex()][0]

    def confirmar_atualizacao(self, origem) -> DialogoDaAtualizacao:
        if self.dialogo is not None:
            self.dialogo.deleteLater()
        self.dialogo = DialogoDaAtualizacao(self.manutencao, origem, self.window())
        self.dialogo.open()
        return self.dialogo
