"""A confirmação de uma correção (docs/gui-plan.md, 11.1 e 11.9; a F3.6): nada roda na placa sem ela. O diálogo diz o
que vai acontecer, mostra o comando exato ("Ver o comando") e o botão diz a ação ("Acertar o relógio", "Pôr P9_28 e
P9_31 no modo da PRU"). No relógio, a senha do sudo só é pedida se a sessão e o cofre não a têm, ou se a placa a
recusou; e a permissão de acertar a cada conexão fica aqui também.

Ele segue a correção da saúde (``servicos/saude_da_placa.py``): rodando, os botões esperam; feita, o diálogo fecha (a
área avisa o resultado num toast); com uma falha, o motivo fica à vista para tentar de novo.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QFont
from PySide6.QtWidgets import QCheckBox, QDialog, QHBoxLayout, QLabel, QLineEdit, QProgressBar, QVBoxLayout, QWidget

from ...componentes.basicos import Botao
from ...servicos.saude_da_placa import SaudeDaPlaca
from ...tema.icones import IconeDoTema
from ...tema.tokens import TAMANHOS
from .itens import comando_da_correcao
from .pecas import BlocoDeComando, repolir
from .textos import frase, traduzir
from .visao_geral import texto_da_diferenca

LARGURA = 520


def _texto(texto: str = "", nome: str = "texto_do_dialogo") -> QLabel:
    rotulo = QLabel(texto)
    rotulo.setObjectName(nome)
    rotulo.setWordWrap(True)
    return rotulo


def _lista(pinos: list[str]) -> str:
    return pinos[0] if len(pinos) == 1 else ", ".join(pinos[:-1]) + traduzir(" e ") + pinos[-1]


class DialogoDeCorrecao(QDialog):
    """A confirmação da correção ``nome`` (``"pinos"``, ``"relogio"`` ou ``"pru"``)."""

    def __init__(self, saude: SaudeDaPlaca, nome: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("dialogo_de_correcao")
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.saude, self.nome = saude, nome
        self.titulo = _texto(nome="titulo_do_dialogo")
        fonte = QFont()
        fonte.setPixelSize(TAMANHOS["secao"])
        fonte.setWeight(QFont.Weight.DemiBold)
        self.titulo.setFont(fonte)
        self.explicacao = _texto()
        self.comando = BlocoDeComando(comando_da_correcao(nome, saude))
        self.comando.hide()
        self.ver = Botao(traduzir("Ver o comando"), "fantasma")
        self.ver.setObjectName("ver_o_comando")
        self.ver.setCheckable(True)
        self.ver.toggled.connect(self.comando.setVisible)
        self.ver.toggled.connect(lambda _l: self.adjustSize())
        self.campo_senha = QLineEdit()
        self.campo_senha.setObjectName("senha_do_sudo")
        self.campo_senha.setEchoMode(QLineEdit.EchoMode.Password)
        self.campo_senha.setPlaceholderText(traduzir("a senha do sudo na placa"))
        mostrar = QAction(self.campo_senha)
        mostrar.setCheckable(True)
        mostrar.setToolTip(traduzir("Mostrar a senha"))
        IconeDoTema(mostrar, "olho", "texto2", papel_ligado="acento")
        mostrar.toggled.connect(lambda ligado: self.campo_senha.setEchoMode(
            QLineEdit.EchoMode.Normal if ligado else QLineEdit.EchoMode.Password))
        self.campo_senha.addAction(mostrar, QLineEdit.ActionPosition.TrailingPosition)
        self.guardar = QCheckBox(traduzir("Guardar a senha no cofre do sistema"))
        self.guardar.setObjectName("guardar_senha_do_sudo")
        self.caixa_da_senha = QWidget()
        senha = QVBoxLayout(self.caixa_da_senha)
        senha.setContentsMargins(0, 0, 0, 0)
        senha.setSpacing(6)
        senha.addWidget(self.campo_senha)
        senha.addWidget(self.guardar)
        self.caixa_da_senha.hide()
        self.a_cada_conexao = QCheckBox(traduzir("Acertar sozinho a cada conexão com esta placa"))
        self.a_cada_conexao.setObjectName("acertar_a_cada_conexao")
        self.a_cada_conexao.setChecked(bool(saude.lembrar_acertar()))
        self.a_cada_conexao.setVisible(nome == "relogio")
        self.mensagem = _texto("", "erro_do_dialogo")
        self.mensagem.hide()
        self.barra = QProgressBar()
        self.barra.setRange(0, 0)
        self.barra.setTextVisible(False)
        self.barra.setFixedHeight(6)
        self.barra.hide()
        self.cancelar = Botao(traduzir("Cancelar"), "secundario")
        self.cancelar.clicked.connect(self.reject)
        self.confirmar = Botao("", "primario")
        self.confirmar.setObjectName("confirmar_correcao")
        self.confirmar.setDefault(True)
        self.confirmar.clicked.connect(self._confirmar)
        self.campo_senha.returnPressed.connect(self._confirmar)
        botoes = QHBoxLayout()
        botoes.setContentsMargins(0, 8, 0, 0)
        botoes.addWidget(self.ver)
        botoes.addStretch(1)
        botoes.addWidget(self.cancelar)
        botoes.addWidget(self.confirmar)
        coluna = QVBoxLayout(self)
        coluna.setContentsMargins(24, 20, 24, 18)
        coluna.setSpacing(12)
        coluna.setSizeConstraint(QVBoxLayout.SizeConstraint.SetFixedSize)
        for widget in (self.titulo, self.explicacao, self.comando, self.caixa_da_senha, self.a_cada_conexao,
                       self.mensagem, self.barra):
            widget.setFixedWidth(LARGURA - 48)
            coluna.addWidget(widget)
        coluna.addLayout(botoes)
        self._preencher()
        saude.correcaoMudou.connect(self._correcao_mudou)

    def _preencher(self) -> None:
        e = self.saude.saude
        if self.nome == "pinos":
            errados = e.pinos_errados if e is not None else []
            self.setWindowTitle(traduzir("Os pinos da PRU"))
            self.titulo.setText(traduzir("Pôr os pinos no modo da PRU"))
            self.explicacao.setText(traduzir(
                "Roda o config-pin em {}, como o setup.sh faz. Não pede senha e não reinicia nada (o ler_adc também "
                "tenta isso ao capturar).").format(_lista(errados)))
            self.confirmar.setText(traduzir("Pôr {} no modo da PRU").format(_lista(errados)))
            return
        if self.nome == "pru":
            self.setWindowTitle(traduzir("O firmware da PRU"))
            self.titulo.setText(traduzir("Recarregar o firmware da PRU"))
            self.explicacao.setText(traduzir(
                "Instala o fw_pru.out compilado na pasta do firmware como o da PRU0 (/lib/firmware/am335x-pru0-fw), põe "
                "os pinos no modo dela e a liga de novo, como o setup.sh faz, sem compilar. Roda como root, pelo sudo; "
                "a senha vai só pelo stdin, para um arquivo na RAM da placa que some em seguida."))
            self.confirmar.setText(traduzir("Recarregar a PRU"))
            return
        self.setWindowTitle(traduzir("O relógio da placa"))
        self.titulo.setText(traduzir("Acertar o relógio da placa"))
        relogio = e.relogio if e is not None else None
        agora = traduzir(" Agora, ela está {} do computador.").format(texto_da_diferenca(relogio.diferenca_s())) \
            if relogio is not None else ""
        self.explicacao.setText(traduzir(
            "A hora da placa passa a ser a deste computador, com a precisão do enlace (cerca de 1 ms no USB).{} Roda "
            "como root, pelo sudo; a senha vai só pelo stdin, para um arquivo na RAM da placa que some em seguida.").format(
            agora))
        self.confirmar.setText(traduzir("Acertar o relógio"))

    def _confirmar(self) -> None:
        if self.nome == "pinos":
            self.saude.corrigir_pinos()
            return
        senha = self.campo_senha.text() if self.caixa_da_senha.isVisible() else None
        if self.nome == "pru":
            if self.caixa_da_senha.isVisible() and not senha:
                self.campo_senha.setFocus()
                return
            self.campo_senha.clear()
            self.saude.recarregar_pru(senha, guardar=self.guardar.isChecked())
            return
        if self.a_cada_conexao.isChecked() != bool(self.saude.lembrar_acertar()):
            self.saude.permitir_acertar_a_cada_conexao(self.a_cada_conexao.isChecked())
        senha = self.campo_senha.text() if self.caixa_da_senha.isVisible() else None
        if self.caixa_da_senha.isVisible() and not senha:
            self.campo_senha.setFocus()
            return
        self.campo_senha.clear()                         # a senha não fica no campo
        self.saude.acertar_relogio(senha, guardar=self.guardar.isChecked())

    def _correcao_mudou(self) -> None:
        correcao = self.saude.correcao
        if correcao is None or correcao.nome != self.nome or correcao.automatica:
            return
        rodando = correcao.estado == "rodando"
        self.barra.setVisible(rodando)
        self.confirmar.setEnabled(not rodando)
        self.cancelar.setEnabled(not rodando)
        if correcao.estado == "feita":
            self.accept()
            return
        if correcao.estado in ("precisa_da_senha", "senha_recusada"):
            self.caixa_da_senha.show()
            self.campo_senha.setFocus()
        if correcao.estado in ("senha_recusada", "falhou"):
            self.mensagem.setText(frase(correcao.mensagem))
        elif correcao.estado == "precisa_da_senha":
            self.mensagem.setText(traduzir("A placa pede a senha do sudo (a do usuário dela): esta sessão e o cofre do "
                                           "sistema não a têm."))
        self.mensagem.setVisible(correcao.estado in ("senha_recusada", "falhou", "precisa_da_senha"))
        self.mensagem.setObjectName("texto_mudo" if correcao.estado == "precisa_da_senha" else "erro_do_dialogo")
        repolir(self.mensagem)
