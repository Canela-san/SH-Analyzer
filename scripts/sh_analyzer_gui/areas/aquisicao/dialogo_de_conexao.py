"""O diálogo da conexão (docs/gui-plan.md, 11.3; a F3.5): o endereço digitado ("Conectar por IP…") e cada passo que
precisa do usuário numa conexão. Ele segue o estado da placa conectada (``servicos/conexao_da_placa.py``): cada estado
tem a sua página, e o diálogo só abre quando há o que perguntar ou mostrar (conectar a uma placa conhecida da lista
não abre nada).

As páginas:

* **o endereço:** o host (aceita ``debian@192.168.6.2:22``), a porta, o usuário e, se precisar, o salto;
* **conectando:** o que está acontecendo, e "Cancelar";
* **a impressão digital** (a primeira conexão com o endereço): a impressão, como conferi-la na placa, e "Confiar e
  conectar" ou "Não confiar";
* **a senha** (a placa ou o salto pediu): a senha, "Instalar a chave do aplicativo" (marcado: as próximas conexões não
  pedem a senha) e "Guardar no cofre do sistema" (desmarcado);
* **o bloqueio** (a chave de host mudou): as duas impressões, o que pode ter acontecido e, só depois de o usuário
  dizer que conferiu na placa, "Esquecer a chave antiga";
* **a falha:** o motivo e "Tentar de novo";
* **pronta** (a primeira conexão deu certo): o que foi feito (a impressão guardada, a chave instalada), a sugestão de
  trocar a senha padrão da imagem e a pergunta do relógio.

Fechar o diálogo (Esc) é a resposta segura de cada página: não confiar, cancelar a conexão, deixar a pergunta do
relógio para a próxima vez.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QFont, QGuiApplication
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)
from sh_placa.destino import SENHA_PADRAO_DA_IMAGEM, Destino

from ...componentes.basicos import Botao, RotuloDeIcone
from ...componentes.toast import Toast
from ...servicos.conexao_da_placa import ConexaoDaPlaca
from ...tema.fontes import fonte_mono
from ...tema.icones import IconeDoTema
from ...tema.tokens import TAMANHOS
from .textos import frase, nome_da_placa, traduzir

LARGURA = 520
COMANDO_DA_IMPRESSAO = "ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub"
PAGINAS = ("destino", "conectando", "falhou", "impressao", "senha", "bloqueada", "pronta")


def _titulo(texto: str = "") -> QLabel:
    rotulo = QLabel(texto)
    rotulo.setObjectName("titulo_do_dialogo")
    fonte = QFont()
    fonte.setPixelSize(TAMANHOS["secao"])
    fonte.setWeight(QFont.Weight.DemiBold)
    rotulo.setFont(fonte)
    rotulo.setWordWrap(True)
    return rotulo


def _texto(texto: str = "", nome: str = "texto_do_dialogo") -> QLabel:
    rotulo = QLabel(texto)
    rotulo.setObjectName(nome)
    rotulo.setWordWrap(True)
    rotulo.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return rotulo


class _Mono(QFrame):
    """Um texto para conferir ou copiar (a impressão digital, um comando), na fonte mono, com o botão de copiar."""

    def __init__(self, texto: str = "", parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("bloco_mono")
        self.rotulo = QLabel(texto)
        self.rotulo.setObjectName("texto_mono")
        self.rotulo.setFont(fonte_mono(TAMANHOS["corpo"]))
        self.rotulo.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.rotulo.setWordWrap(True)
        self.copiar = QToolButton()
        self.copiar.setObjectName("copiar")
        self.copiar.setProperty("variante", "fantasma")
        self.copiar.setAutoRaise(True)
        self.copiar.setToolTip(traduzir("Copiar"))
        IconeDoTema(self.copiar, "copiar", "texto2", tamanho=14)
        self.copiar.clicked.connect(self._copiar)
        linha = QHBoxLayout(self)
        linha.setContentsMargins(10, 6, 6, 6)
        linha.addWidget(self.rotulo, 1)
        linha.addWidget(self.copiar, 0, Qt.AlignmentFlag.AlignTop)

    def definir(self, texto: str) -> None:
        self.rotulo.setText(texto)

    def _copiar(self) -> None:
        QGuiApplication.clipboard().setText(self.rotulo.text())
        Toast.mostrar(self.window(), traduzir("Copiado."), "sucesso", 2000)


def _opcao(texto: str, descricao: str, nome: str) -> tuple[QWidget, QCheckBox]:
    """Uma caixa de marcar com o rótulo curto e, embaixo, a explicação em letra discreta, que quebra as linhas (o texto
    de uma ``QCheckBox`` não quebra, e um longo seria cortado no diálogo de largura fixa)."""
    caixa = QCheckBox(texto)
    caixa.setObjectName(nome)
    explicacao = _texto(descricao, "texto_mudo")
    explicacao.setContentsMargins(caixa.style().pixelMetric(caixa.style().PixelMetric.PM_IndicatorWidth) + 8, 0, 0, 0)
    bloco = QWidget()
    coluna = QVBoxLayout(bloco)
    coluna.setContentsMargins(0, 0, 0, 0)
    coluna.setSpacing(0)
    coluna.addWidget(caixa)
    coluna.addWidget(explicacao)
    return bloco, caixa


class _Item(QWidget):
    """Uma linha do resumo da primeira conexão: o ícone (feito ou atenção) e a frase."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.icone = RotuloDeIcone("ok", "ok", 16)
        self.texto = _texto()
        linha = QHBoxLayout(self)
        linha.setContentsMargins(0, 0, 0, 0)
        linha.setSpacing(10)
        linha.addWidget(self.icone, 0, Qt.AlignmentFlag.AlignTop)
        linha.addWidget(self.texto, 1)

    def definir(self, texto: str, atencao: bool = False) -> None:
        self.icone.trocar("alerta" if atencao else "ok", "aviso" if atencao else "ok")
        self.texto.setText(texto)


class DialogoDeConexao(QDialog):
    """Use :meth:`abrir_para_destino` ("Conectar por IP…") ou :meth:`acompanhar` (a conexão precisa do usuário)."""

    def __init__(self, conexao: ConexaoDaPlaca, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("dialogo_de_conexao")
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.conexao = conexao
        # As páginas numa coluna, só a da vez visível (e não numa QStackedWidget, que pede a altura da mais alta: o
        # diálogo fica do tamanho da página de agora, com as linhas quebradas).
        self._paginas: dict[str, QWidget] = {}
        self._padrao: dict[str, QPushButton] = {}
        self._atual = PAGINAS[0]
        coluna = QVBoxLayout(self)
        coluna.setContentsMargins(24, 20, 24, 18)
        coluna.setSizeConstraint(QVBoxLayout.SizeConstraint.SetFixedSize)
        for nome in PAGINAS:
            self._criando = nome
            pagina = getattr(self, f"_criar_{nome}")()
            pagina.setObjectName(f"pagina_{nome}")
            pagina.setFixedWidth(LARGURA - 48)
            pagina.setVisible(nome == self._atual)
            self._paginas[nome] = pagina
            coluna.addWidget(pagina)
        conexao.mudou.connect(self._sincronizar)

    # ------------------------------------------------------------------ abrir e seguir o estado

    @property
    def pagina(self) -> str:
        return self._atual

    def abrir_para_destino(self) -> None:
        """O endereço digitado: o formulário, com o último endereço digitado (se houver)."""
        destino = self.conexao.destino if self.conexao.placa is None else None
        if destino is not None:
            self.campo_host.setText(destino.host)
            self.campo_porta.setValue(destino.porta)
            self.campo_usuario.setText(destino.usuario)
            self.usar_salto.setChecked(destino.salto is not None)
            if destino.salto is not None:
                self.campo_host_do_salto.setText(destino.salto.host)
                self.campo_porta_do_salto.setValue(destino.salto.porta)
                self.campo_usuario_do_salto.setText(destino.salto.usuario)
        self._ir("destino")
        self._mostrar()

    def acompanhar(self) -> None:
        """A página do estado de agora (a placa pede uma resposta, ou a primeira conexão deu certo)."""
        self._mostrar()
        self._sincronizar()

    def _mostrar(self) -> None:
        if not self.isVisible():
            self.open()
        self.raise_()
        self.activateWindow()

    def _sincronizar(self) -> None:
        if not self.isVisible():
            return
        estado = self.conexao.estado
        if estado == "conectando":
            self._ir("conectando")
        elif estado == "confirmar_host":
            self._ir("impressao")
        elif estado == "pedir_senha":
            self._ir("senha")
        elif estado == "bloqueada":
            self._ir("bloqueada")
        elif estado == "falhou":
            self._ir("falhou")
        elif estado == "conectada" and self.conexao.primeira_conexao is not None:
            self._ir("pronta")
        elif estado == "conectada":
            self.accept()
        elif estado == "reconectando" or self.pagina != "destino":
            super().reject()                         # desconectada (sem estar digitando um endereço), ou caiu

    def reject(self) -> None:
        """Fechar é a resposta segura da página: não confiar, cancelar, deixar o relógio para a próxima vez."""
        pagina = self.pagina
        if pagina == "impressao":
            self.conexao.confirmar_host(False)
        elif pagina in ("conectando", "senha"):
            self.conexao.cancelar()
        elif pagina == "pronta":
            self.conexao.dispensar_primeira_conexao()
        super().reject()

    def _ir(self, nome: str) -> None:
        getattr(self, f"_preencher_{nome}", lambda: None)()
        self._atual = nome
        for pagina, widget in self._paginas.items():
            widget.setVisible(pagina == nome)
        for pagina, botao in self._padrao.items():
            botao.setDefault(pagina == nome)
        self.setWindowTitle({"destino": traduzir("Conectar por IP"), "impressao": traduzir("Confira a placa"),
                             "senha": traduzir("A senha"), "bloqueada": traduzir("Conexão bloqueada"),
                             "pronta": traduzir("Conectada")}.get(nome, traduzir("Conectar à placa")))
        foco = {"destino": self.campo_host, "senha": self.campo_senha}.get(nome)
        if foco is not None:
            foco.setFocus()
        elif nome in self._padrao:
            self._padrao[nome].setFocus()

    def _pagina(self, *conteudo, botoes: list[QPushButton], padrao: QPushButton | None = None) -> QWidget:
        pagina = QWidget()
        coluna = QVBoxLayout(pagina)
        coluna.setContentsMargins(0, 0, 0, 0)
        coluna.setSpacing(12)
        for item in conteudo:
            if isinstance(item, QWidget):
                coluna.addWidget(item)
            else:
                coluna.addLayout(item)
        coluna.addStretch(1)
        linha = QHBoxLayout()
        linha.setContentsMargins(0, 8, 0, 0)
        linha.addStretch(1)
        for botao in botoes:
            botao.setAutoDefault(False)
            linha.addWidget(botao)
        coluna.addLayout(linha)
        if padrao is not None:
            self._padrao[self._criando] = padrao
        return pagina

    # ------------------------------------------------------------------ o endereço

    def _criar_destino(self) -> QWidget:
        self.campo_host = QLineEdit()
        self.campo_host.setObjectName("campo_host")
        self.campo_host.setPlaceholderText(traduzir("192.168.6.2, beaglebone.local ou debian@host:porta"))
        self.campo_porta = self._porta()
        self.campo_usuario = QLineEdit("debian")
        self.campo_usuario.setObjectName("campo_usuario")
        formulario = QFormLayout()
        formulario.setHorizontalSpacing(16)
        formulario.addRow(traduzir("Endereço"), self.campo_host)
        formulario.addRow(traduzir("Porta"), self.campo_porta)
        formulario.addRow(traduzir("Usuário"), self.campo_usuario)
        salto, self.usar_salto = _opcao(traduzir("Passar por um salto (ProxyJump)"),
                                        traduzir("Quando a placa só é alcançada através de outra máquina (o servidor do "
                                                 "laboratório, por exemplo)."), "usar_salto")
        self.campo_host_do_salto = QLineEdit()
        self.campo_host_do_salto.setObjectName("campo_host_do_salto")
        self.campo_host_do_salto.setPlaceholderText(traduzir("gateway.do.laboratorio ou usuario@host:porta"))
        self.campo_porta_do_salto = self._porta()
        self.campo_usuario_do_salto = QLineEdit()
        self.campo_usuario_do_salto.setObjectName("campo_usuario_do_salto")
        self.campo_usuario_do_salto.setPlaceholderText(traduzir("o seu usuário no salto"))
        self.caixa_do_salto = QWidget()
        do_salto = QFormLayout(self.caixa_do_salto)
        do_salto.setContentsMargins(24, 0, 0, 0)
        do_salto.setHorizontalSpacing(16)
        do_salto.addRow(traduzir("Salto"), self.campo_host_do_salto)
        do_salto.addRow(traduzir("Porta"), self.campo_porta_do_salto)
        do_salto.addRow(traduzir("Usuário"), self.campo_usuario_do_salto)
        self.caixa_do_salto.setVisible(False)
        self.usar_salto.toggled.connect(self.caixa_do_salto.setVisible)
        self.erro_do_destino = _texto("", "erro_do_dialogo")
        self.erro_do_destino.hide()
        for campo in (self.campo_host, self.campo_usuario, self.campo_host_do_salto, self.campo_usuario_do_salto):
            campo.textEdited.connect(lambda _t: self.erro_do_destino.hide())
        cancelar = Botao(traduzir("Cancelar"), "secundario")
        cancelar.clicked.connect(self.reject)
        conectar = Botao(traduzir("Conectar"), "primario")
        conectar.setObjectName("conectar_ao_destino")
        conectar.clicked.connect(self._conectar_ao_destino)
        return self._pagina(
            _titulo(traduzir("Conectar por IP")),
            _texto(traduzir("Para uma placa que a busca não acha sozinha: em outra rede (por uma VPN, por exemplo) ou "
                            "atrás de outra máquina.")),
            formulario, salto, self.caixa_do_salto, self.erro_do_destino,
            botoes=[cancelar, conectar], padrao=conectar)

    @staticmethod
    def _porta() -> QSpinBox:
        porta = QSpinBox()
        porta.setRange(1, 65535)
        porta.setValue(22)
        porta.setFixedWidth(90)
        return porta

    def destino_digitado(self) -> Destino:
        """O destino do formulário (``ValueError`` com a mensagem, se não der)."""
        salto = None
        if self.usar_salto.isChecked():
            try:
                salto = Destino.de_texto(self.campo_host_do_salto.text(), self.campo_porta_do_salto.value(),
                                         self.campo_usuario_do_salto.text() or "debian")
            except ValueError as e:
                raise ValueError(traduzir("Salto: {}").format(frase(str(e)))) from None
        return Destino.de_texto(self.campo_host.text(), self.campo_porta.value(),
                                self.campo_usuario.text().strip() or "debian", salto)

    def _conectar_ao_destino(self) -> None:
        try:
            destino = self.destino_digitado()
        except ValueError as e:
            self.erro_do_destino.setText(frase(str(e)))
            self.erro_do_destino.show()
            return
        self.conexao.conectar(destino=destino)
        self._sincronizar()

    # ------------------------------------------------------------------ conectando e a falha

    def _criar_conectando(self) -> QWidget:
        self.titulo_conectando = _titulo()
        self.texto_conectando = _texto()
        barra = QProgressBar()
        barra.setRange(0, 0)
        barra.setTextVisible(False)
        barra.setFixedHeight(6)
        cancelar = Botao(traduzir("Cancelar"), "secundario")
        cancelar.setObjectName("cancelar_conexao")
        cancelar.clicked.connect(self.reject)
        return self._pagina(self.titulo_conectando, self.texto_conectando, barra, botoes=[cancelar])

    def _preencher_conectando(self) -> None:
        destino = self.conexao.destino
        self.titulo_conectando.setText(traduzir("Conectando a {}…").format(destino.conta) if destino is not None
                                       else traduzir("Conectando ao simulador…"))
        self.texto_conectando.setText(traduzir("Pelo salto {}.").format(destino.salto) if destino is not None
                                      and destino.salto is not None else "")
        self.texto_conectando.setVisible(bool(self.texto_conectando.text()))

    def _criar_falhou(self) -> QWidget:
        self.texto_da_falha = _texto()
        self.mudar_endereco = Botao(traduzir("Mudar o endereço"), "secundario")
        self.mudar_endereco.clicked.connect(lambda: self._ir("destino"))
        fechar = Botao(traduzir("Fechar"), "secundario")
        fechar.clicked.connect(self.reject)
        tentar = Botao(traduzir("Tentar de novo"), "primario")
        tentar.setObjectName("tentar_de_novo")
        tentar.clicked.connect(self.conexao.tentar_de_novo)
        return self._pagina(_titulo(traduzir("Não deu para conectar")), self.texto_da_falha,
                            botoes=[self.mudar_endereco, fechar, tentar], padrao=tentar)

    def _preencher_falhou(self) -> None:
        self.texto_da_falha.setText(frase(self.conexao.motivo))
        self.mudar_endereco.setVisible(self.conexao.placa is None and self.conexao.destino is not None)

    # ------------------------------------------------------------------ a impressão digital

    def _criar_impressao(self) -> QWidget:
        self.texto_da_impressao = _texto()
        self.impressao = _Mono()
        self.impressao.setObjectName("impressao_digital")
        como = _texto(traduzir("Para conferir, rode na placa (pelo console serial, ou por uma conexão em que você já "
                               "confia) e compare:"))
        comando = _Mono(COMANDO_DA_IMPRESSAO)
        cabo = _texto(traduzir("Num cabo USB ligado direto entre este computador e a placa, ninguém fica no meio: dá "
                               "para confiar sem conferir."), "texto_mudo")
        nao = Botao(traduzir("Não confiar"), "secundario")
        nao.setObjectName("nao_confiar")
        nao.clicked.connect(self.reject)
        sim = Botao(traduzir("Confiar e conectar"), "primario")
        sim.setObjectName("confiar")
        sim.clicked.connect(lambda: self.conexao.confirmar_host(True))
        return self._pagina(_titulo(traduzir("Confira a placa")), self.texto_da_impressao, self.impressao, como,
                            comando, cabo, botoes=[nao, sim], padrao=sim)

    def _preencher_impressao(self) -> None:
        c = self.conexao
        pedido = c.destino_pedido or c.destino
        salto = c.destino is not None and c.destino.salto is not None and pedido == c.destino.salto
        modelo = traduzir("É a primeira conexão com {} (o salto). Ele se identificou com esta impressão digital da "
                          "chave de host:") if salto else \
            traduzir("É a primeira conexão com {}. A placa se identificou com esta impressão digital da chave de host:")
        self.texto_da_impressao.setText(modelo.format(pedido.conta if pedido is not None else ""))
        self.impressao.definir(c.impressao_pedida or "")

    # ------------------------------------------------------------------ a senha

    def _criar_senha(self) -> QWidget:
        self.titulo_da_senha = _titulo()
        self.motivo_da_senha = _texto("", "erro_do_dialogo")
        self.campo_senha = QLineEdit()
        self.campo_senha.setObjectName("campo_senha")
        self.campo_senha.setEchoMode(QLineEdit.EchoMode.Password)
        self.mostrar_senha = QAction(self.campo_senha)
        self.mostrar_senha.setCheckable(True)
        self.mostrar_senha.setToolTip(traduzir("Mostrar a senha"))
        IconeDoTema(self.mostrar_senha, "olho", "texto2", papel_ligado="acento")
        self.mostrar_senha.toggled.connect(lambda ligado: self.campo_senha.setEchoMode(
            QLineEdit.EchoMode.Normal if ligado else QLineEdit.EchoMode.Password))
        self.campo_senha.addAction(self.mostrar_senha, QLineEdit.ActionPosition.TrailingPosition)
        self.dica_da_senha = _texto("", "texto_mudo")
        self.opcao_da_chave, self.instalar_chave = _opcao(
            traduzir("Instalar a chave do aplicativo na placa"),
            traduzir("As próximas conexões entram com a chave, sem pedir a senha."), "instalar_chave")
        self.instalar_chave.setChecked(True)
        opcao_do_cofre, self.guardar_senha = _opcao(
            traduzir("Guardar a senha no cofre do sistema"),
            traduzir("O sudo da placa (no diagnóstico) a usa, e ela vale se a chave sumir da placa."), "guardar_senha")
        cancelar = Botao(traduzir("Cancelar"), "secundario")
        cancelar.clicked.connect(self.reject)
        self.conectar_com_senha = Botao(traduzir("Conectar"), "primario")
        self.conectar_com_senha.setObjectName("conectar_com_senha")
        self.conectar_com_senha.clicked.connect(self._informar_senha)
        self.campo_senha.textChanged.connect(lambda t: self.conectar_com_senha.setEnabled(bool(t)))
        self.campo_senha.returnPressed.connect(self._informar_senha)
        return self._pagina(self.titulo_da_senha, self.motivo_da_senha, self.campo_senha, self.dica_da_senha,
                            self.opcao_da_chave, opcao_do_cofre, botoes=[cancelar, self.conectar_com_senha],
                            padrao=self.conectar_com_senha)

    def _preencher_senha(self) -> None:
        c = self.conexao
        pedido = c.destino_pedido or c.destino
        salto = c.destino is not None and c.destino.salto is not None and pedido == c.destino.salto
        self.titulo_da_senha.setText(traduzir("A senha de {}").format(pedido.conta))
        self.motivo_da_senha.setText(c.motivo)
        self.motivo_da_senha.setVisible(bool(c.motivo))
        self.campo_senha.clear()
        self.mostrar_senha.setChecked(False)
        self.conectar_com_senha.setEnabled(False)
        self.dica_da_senha.setText(
            traduzir("A placa não aceitou a chave do aplicativo (ainda não está nela). Numa placa nova, a senha do "
                     "usuário debian é a da imagem: {}.").format(SENHA_PADRAO_DA_IMAGEM) if not salto else
            traduzir("A senha do seu usuário no salto ({}).").format(pedido.host))
        self.opcao_da_chave.setVisible(not salto)

    def _informar_senha(self) -> None:
        senha = self.campo_senha.text()
        if not senha:
            return
        self.campo_senha.clear()                     # a senha não fica no campo (nem na memória do widget)
        self.conexao.informar_senha(senha, guardar=self.guardar_senha.isChecked(),
                                    instalar_chave=self.instalar_chave.isChecked())

    # ------------------------------------------------------------------ o bloqueio

    def _criar_bloqueada(self) -> QWidget:
        self.texto_do_bloqueio = _texto()
        self.conhecida = _Mono()
        self.apresentada = _Mono()
        impressoes = QVBoxLayout()
        impressoes.setSpacing(4)
        impressoes.addWidget(_texto(traduzir("A impressão conhecida:"), "texto_mudo"))
        impressoes.addWidget(self.conhecida)
        impressoes.addSpacing(4)
        impressoes.addWidget(_texto(traduzir("A de agora:"), "texto_mudo"))
        impressoes.addWidget(self.apresentada)
        explicacao = _texto(traduzir(
            "Se a placa foi regravada (a imagem reinstalada, outro cartão SD), a chave nova é esperada: confira a "
            "impressão nova na própria placa, pelo console ({}). Se ela não foi regravada, alguém pode estar no meio "
            "da conexão: não continue.").format(COMANDO_DA_IMPRESSAO))
        conferi, self.conferi = _opcao(traduzir("Conferi na própria placa"),
                                       traduzir("Ela foi regravada, e a impressão de agora é a que o comando mostra "
                                                "nela."), "conferi_na_placa")
        fechar = Botao(traduzir("Fechar"), "secundario")
        fechar.clicked.connect(self.reject)
        self.esquecer = Botao(traduzir("Esquecer a chave antiga e conectar"), "perigo")
        self.esquecer.setObjectName("esquecer_chave_antiga")
        self.esquecer.setEnabled(False)
        self.conferi.toggled.connect(self.esquecer.setEnabled)
        self.esquecer.clicked.connect(self._esquecer_a_chave)
        topo = QHBoxLayout()
        topo.setSpacing(10)
        topo.addWidget(RotuloDeIcone("alerta", "erro", 20))
        topo.addWidget(_titulo(traduzir("Conexão bloqueada")), 1)
        return self._pagina(topo, self.texto_do_bloqueio, impressoes, explicacao, conferi,
                            botoes=[fechar, self.esquecer], padrao=fechar)

    def _preencher_bloqueada(self) -> None:
        bloqueio = self.conexao.bloqueio
        conta = bloqueio.destino.conta if bloqueio is not None else ""
        self.texto_do_bloqueio.setText(traduzir(
            "A placa em {} apresentou uma chave de host diferente da que este computador conhece. Nada foi enviado: "
            "nem a senha, nem a chave do aplicativo.").format(conta))
        self.conhecida.definir(bloqueio.conhecida if bloqueio is not None else "")
        self.apresentada.definir((bloqueio.apresentada if bloqueio is not None else None)
                                 or traduzir("não deu para ler"))
        self.conferi.setChecked(False)

    def _esquecer_a_chave(self) -> None:
        if self.conferi.isChecked():
            self.conexao.esquecer_chave_do_host()

    # ------------------------------------------------------------------ pronta (a primeira conexão)

    def _criar_pronta(self) -> QWidget:
        self.titulo_pronta = _titulo()
        self.itens = [_Item() for _ in range(5)]
        lista = QVBoxLayout()
        lista.setSpacing(8)
        for item in self.itens:
            lista.addWidget(item)
        self.pergunta = QFrame()
        self.pergunta.setObjectName("pergunta_do_relogio")
        titulo = QLabel(traduzir("Acertar o relógio da placa a cada conexão?"))
        fonte = titulo.font()
        fonte.setWeight(QFont.Weight.DemiBold)
        titulo.setFont(fonte)
        texto = _texto(traduzir(
            "A BeagleBone não tem bateria no relógio: desligada, ela volta com a hora errada, e essa hora vai no "
            "cabeçalho de cada captura. Acertar usa a hora deste computador e o sudo da placa."))
        caixa = QVBoxLayout(self.pergunta)
        caixa.setContentsMargins(14, 12, 14, 12)
        caixa.setSpacing(4)
        caixa.addWidget(titulo)
        caixa.addWidget(texto)
        self.nao_acertar = Botao(traduzir("Não acertar"), "secundario")
        self.nao_acertar.setObjectName("nao_acertar_relogio")
        self.nao_acertar.clicked.connect(lambda: self.conexao.responder_relogio(False))
        self.acertar = Botao(traduzir("Acertar a cada conexão"), "primario")
        self.acertar.setObjectName("acertar_relogio")
        self.acertar.clicked.connect(lambda: self.conexao.responder_relogio(True))
        self.concluir = Botao(traduzir("Concluir"), "primario")
        self.concluir.setObjectName("concluir_primeira_conexao")
        self.concluir.clicked.connect(self.reject)
        return self._pagina(self.titulo_pronta, lista, self.pergunta,
                            botoes=[self.nao_acertar, self.acertar, self.concluir])

    def _preencher_pronta(self) -> None:
        c = self.conexao
        primeira = c.primeira_conexao
        self.titulo_pronta.setText(traduzir("Conectada a {}").format(nome_da_placa(c)))
        frases: list[tuple[str, bool]] = []
        if primeira is not None:
            if primeira.host_confirmado:
                frases.append((traduzir("A impressão digital da placa ficou guardada: se ela mudar, a conexão é "
                                        "bloqueada."), False))
            if primeira.chave_instalada is True:
                frases.append((traduzir("A chave do aplicativo foi instalada na placa: as próximas conexões não pedem "
                                        "a senha."), False))
            elif primeira.chave_instalada is False:
                frases.append((traduzir("A chave do aplicativo já estava na placa."), False))
            elif primeira.sem_a_chave:
                frases.append((traduzir("A chave do aplicativo não foi instalada: cada conexão vai pedir a senha."),
                               True))
            if primeira.senha_padrao:
                frases.append((traduzir(
                    "A placa usa a senha padrão da imagem ({}), que todo mundo conhece: qualquer um na mesma rede entra "
                    "nela. Troque-a no terminal da placa, com o comando passwd (a chave do aplicativo continua "
                    "valendo).").format(SENHA_PADRAO_DA_IMAGEM), True))
            if primeira.aviso_do_cofre:
                frases.append((frase(primeira.aviso_do_cofre), True))
        for item, par in zip(self.itens, (*frases, *([None] * len(self.itens))), strict=False):
            item.setVisible(par is not None)
            if par is not None:
                item.definir(*par)
        perguntar = primeira is not None and primeira.perguntar_relogio
        self.pergunta.setVisible(perguntar)
        self.nao_acertar.setVisible(perguntar)
        self.acertar.setVisible(perguntar)
        self.concluir.setVisible(not perguntar)
        padrao = self.acertar if perguntar else self.concluir
        for botao in (self.acertar, self.concluir):
            botao.setDefault(botao is padrao)
        padrao.setFocus()
