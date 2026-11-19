"""A página Sistema da Manutenção (a F6.5, a F6.6 e a F6.7): o Linux da placa (o nome, o sistema, o kernel, há quanto
tempo está ligada, o fuso, a memória), o monitor ao vivo (``monitor.py``: os gráficos, os processos, o ``ler_adc``
esquecido), o cartão e a limpeza, os serviços da imagem, a rede, a senha (``cartoes_do_sistema.py``) e a energia:
"Reiniciar…" e "Desligar…", seguros (o sistema para antes; desligar da tomada com ele ligado pode corromper o
cartão). O diálogo
confirma, pede o sudo e, com uma captura rodando, pergunta se pode cortá-la; o cartão da ação conta os segundos até a
placa voltar (ou sumir: aí já pode tirar da tomada).
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from ....componentes.basicos import Botao
from ....componentes.numeros import formatar_bytes
from ....servicos.monitor_da_placa import MonitorDaPlaca
from ....servicos.sistema_da_placa import SistemaDaPlaca
from ..pecas import fonte
from ..textos import frase, traduzir
from .cartoes_do_sistema import CartaoDaRede, CartaoDaSenha, CartaoDoCartao, CartaoDosServicos
from .comuns import CartaoDaAcao, cartao, coluna_central, fato, ha_quanto_tempo, texto
from .monitor import CartaoDoMonitor

ACOES_DA_PAGINA = ("reiniciar", "desligar", "parar_ler_adc", "servico", "limpar", "expandir", "trocar_senha")


class PaginaDoSistema(QWidget):
    """A página Sistema. ``confirmar(tipo, argumento)`` pede à seção o diálogo de uma das :data:`ACOES_DA_PAGINA`."""

    confirmar = Signal(str, object)

    def __init__(self, sistema: SistemaDaPlaca, monitor: MonitorDaPlaca, captura_rodando=None, senha_padrao=None,
                 parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("pagina_do_sistema")
        self.sistema = sistema
        self.titulo = QLabel(traduzir("Sistema"))
        self.titulo.setFont(fonte("tela", QFont.Weight.DemiBold))
        self.subtitulo = texto("", "subtitulo_da_secao")
        self.ler_de_novo = Botao(traduzir("Ler de novo"), "secundario", "girar")
        self.ler_de_novo.setObjectName("ler_o_sistema_de_novo")
        self.ler_de_novo.clicked.connect(sistema.ler)
        cabecalho = QHBoxLayout()
        textos = QVBoxLayout()
        textos.setSpacing(2)
        textos.addWidget(self.titulo)
        textos.addWidget(self.subtitulo)
        cabecalho.addLayout(textos, 1)
        cabecalho.addWidget(self.ler_de_novo, 0, Qt.AlignmentFlag.AlignTop)

        self.cartao_da_acao = CartaoDaAcao(sistema, ACOES_DA_PAGINA)
        self.monitor = CartaoDoMonitor(monitor, captura_rodando)
        self.monitor.pararCaptura.connect(lambda: self.confirmar.emit("parar_ler_adc", None))

        self.cartao_da_placa, self.corpo_da_placa = cartao(traduzir("A placa"))
        self.fatos: list[QWidget] = []

        self.cartao_da_energia, energia = cartao(traduzir("Energia"))
        energia.addWidget(texto(traduzir(
            "Desligar da tomada com o sistema ligado pode corromper o cartão. Desligue por aqui e espere o aviso de "
            "que a placa sumiu; reiniciar faz o mesmo e volta sozinha, com a conexão (cerca de 1 min)."), "resumo_do_item"))
        self.reiniciar = Botao(traduzir("Reiniciar…"), "secundario", "girar")
        self.reiniciar.setObjectName("reiniciar_a_placa")
        self.reiniciar.clicked.connect(lambda: self.confirmar.emit("reiniciar", None))
        self.desligar = Botao(traduzir("Desligar…"), "perigo", "energia")
        self.desligar.setObjectName("desligar_a_placa")
        self.desligar.clicked.connect(lambda: self.confirmar.emit("desligar", None))
        botoes = QHBoxLayout()
        botoes.setContentsMargins(0, 6, 0, 0)
        botoes.addWidget(self.reiniciar)
        botoes.addWidget(self.desligar)
        botoes.addStretch(1)
        energia.addLayout(botoes)

        conteudo = QWidget()
        self.coluna = QVBoxLayout(conteudo)
        self.coluna.setContentsMargins(24, 20, 24, 20)
        self.coluna.setSpacing(14)
        self.coluna.addLayout(cabecalho)
        self.cartao = CartaoDoCartao(sistema)
        self.servicos = CartaoDosServicos(sistema)
        self.rede = CartaoDaRede(sistema)
        self.senha = CartaoDaSenha(sistema, senha_padrao)
        for c in (self.cartao, self.servicos, self.rede, self.senha):
            c.confirmar.connect(self.confirmar.emit)
        for w in (self.cartao_da_acao, self.cartao_da_placa, self.monitor, self.cartao, self.servicos, self.rede,
                  self.senha, self.cartao_da_energia):
            self.coluna.addWidget(w)
        self.coluna.addStretch(1)
        fora = QVBoxLayout(self)
        fora.setContentsMargins(0, 0, 0, 0)
        fora.addWidget(coluna_central(conteudo, "rolagem_do_sistema"))
        sistema.mudou.connect(self.atualizar)
        sistema.acaoMudou.connect(self._acao_mudou)
        self.atualizar()

    def showEvent(self, evento) -> None:
        super().showEvent(evento)
        self.monitor.ligar(True)

    def hideEvent(self, evento) -> None:
        super().hideEvent(evento)
        self.monitor.ligar(False)

    def atualizar(self) -> None:
        s = self.sistema
        d = s.detalhe
        self.ler_de_novo.setEnabled(not s.lendo)
        for w in (self.cartao_da_placa, self.cartao, self.servicos, self.rede, self.senha):
            w.setVisible(d is not None)
        if d is None:
            self.subtitulo.setText(traduzir("Lendo o sistema da placa…") if s.lendo else frase(s.erro))
        else:
            self.subtitulo.setText(traduzir("O Linux da placa: o que roda, o cartão, os serviços, a rede, a senha e "
                                            "a energia."))
            self._fatos(d)
        self._acao_mudou()

    def _fatos(self, d: dict) -> None:
        for w in self.fatos:
            w.hide()
            w.deleteLater()
        memoria = d.get("memoria") or {}
        total, livre = memoria.get("total_kib"), memoria.get("disponivel_kib")
        fatos = [
            (traduzir("Nome"), d.get("nome") or ""),
            (traduzir("Sistema"), d.get("sistema") or ""),
            (traduzir("Kernel"), d.get("kernel") or ""),
            (traduzir("Ligada há"), ha_quanto_tempo(d.get("ligada_s"))),
            (traduzir("Fuso horário"), d.get("fuso") or traduzir("não configurado (UTC)")),
            (traduzir("Memória"), traduzir("{} disponível de {}").format(formatar_bytes(livre * 1024),
                                                                       formatar_bytes(total * 1024))
             if total and livre is not None else ""),
        ]
        self.fatos = [fato(nome, valor) for nome, valor in fatos]
        for w in self.fatos:
            self.corpo_da_placa.addWidget(w)

    def _acao_mudou(self) -> None:
        livre = not self.sistema.ocupado and self.sistema.conexao.estado == "conectada"
        self.reiniciar.setEnabled(livre)
        self.desligar.setEnabled(livre)
        self.monitor.parar.setEnabled(livre)
        a = self.sistema.acao
        if a is not None and a.nome == "parar_ler_adc" and a.estado == "feita":
            self.monitor.monitor.ler_processos()        # o ler_adc parado some da lista
