"""A placa na barra de status da janela, com a Aquisição à vista (o B1): o estado da conexão e o caminho, como ela se
autenticou e o enlace."""

from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget

from ...servicos.conexao_da_placa import ConexaoDaPlaca
from .textos import resumo, texto_do_enlace, traduzir

NIVEIS = {"conectada": "ok", "atencao": "aviso", "erro": "erro"}


class StatusDaPlaca(QWidget):
    def __init__(self, conexao: ConexaoDaPlaca, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("status_da_placa")
        self.conexao = conexao
        self.estado = QLabel()
        self.estado.setObjectName("status_da_conexao")
        self.autenticacao = QLabel()
        self.autenticacao.setObjectName("status_da_autenticacao")
        self.enlace = QLabel()
        self.enlace.setObjectName("status_do_enlace")
        linha = QHBoxLayout(self)
        linha.setContentsMargins(0, 0, 0, 0)
        linha.setSpacing(0)
        for rotulo in (self.estado, self.autenticacao, self.enlace):
            linha.addWidget(rotulo)
        linha.addStretch(1)
        conexao.mudou.connect(self.atualizar)
        self.atualizar()

    def atualizar(self) -> None:
        c = self.conexao
        r = resumo(c)
        if c.estado == "conectada":
            texto = traduzir("conectada · {}").format(c.detalhe_do_caminho or (c.destino.host if c.destino else ""))
        else:
            texto = r.titulo[0].lower() + r.titulo[1:]
        self.estado.setText(texto)
        self.estado.setToolTip(r.detalhe)
        self.estado.setProperty("nivel", NIVEIS.get(r.nivel, ""))
        self.estado.style().unpolish(self.estado)
        self.estado.style().polish(self.estado)
        conectada = c.estado in ("conectada", "reconectando") and not c.simulada
        self.autenticacao.setText(("SSH · " + (traduzir("chave do aplicativo") if c.autenticada_com == "chave"
                                               else traduzir("senha"))) if conectada else "")
        self.enlace.setText(texto_do_enlace(c) if conectada else "")
        for rotulo in (self.autenticacao, self.enlace):
            rotulo.setVisible(bool(rotulo.text()))
