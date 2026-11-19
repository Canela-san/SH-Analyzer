"""O resgate pela serial (a F6.8), no estado sem placa da Manutenção: quando a rede pelo USB não sobe (a placa liga,
mas o SSH não responde), a BeagleBone ainda é uma porta serial pelo mesmo cabo, com o login da imagem. A página acha
a porta (a da placa primeiro), diz o que fazer quando este usuário não pode abri-la (o grupo ``dialout``, uma vez,
num terminal: o aplicativo não mexe nos grupos do sistema) e abre o console no terminal do aplicativo, com os atalhos
do resgate (o Enter é de quem lê).
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QComboBox, QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget
from sh_placa import console_serial

from ....componentes.basicos import Botao
from ....tema.fontes import fonte_mono
from ..pecas import fonte
from ..textos import frase, traduzir
from .comuns import texto

ATALHOS = (("As redes", "ip -br addr", "As interfaces e os endereços: o usb0 e o usb1 têm de ter o 192.168.7.2 e o "
                                         "192.168.6.2."),
           ("O SSH e o DHCP do USB", "systemctl --no-pager status ssh dnsmasq",
            "Se o SSH e o dnsmasq (o endereço do computador pelo USB) estão rodando."),
           ("Ligar o SSH e o DHCP", "sudo systemctl restart ssh dnsmasq", "Sobe os dois de novo."),
           ("As cópias do uEnv.txt", "ls -l /boot/uEnv.txt*",
            "As cópias que o assistente fez antes de cada gravação."),
           ("Restaurar o uEnv.txt", "sudo cp /boot/uEnv.txt.sh-analyzer-", "Complete com a data da cópia, um espaço e "
                                                                          "/boot/uEnv.txt; depois, sudo reboot."),
           ("Os erros deste boot", "journalctl -b -p err --no-pager | tail -n 30",
            "As últimas mensagens de erro do sistema."))


class LeitorSerial(QThread):
    """Lê a porta numa thread (a leitura espera até 0,1 s): ``chegou(bytes)``; ``caiu(motivo)`` se a porta some (o
    cabo saiu, a placa desligou)."""

    chegou = Signal(bytes)
    caiu = Signal(str)

    def __init__(self, console: console_serial.ConsoleSerial, parent=None):
        super().__init__(parent)
        self.console = console

    def run(self) -> None:
        while not self.isInterruptionRequested():
            try:
                dados = self.console.ler()
            except Exception as e:                # o SerialException do pyserial, o OSError do sistema
                self.caiu.emit(str(e) or type(e).__name__)
                return
            if dados:
                self.chegou.emit(dados)


class PaginaDoResgate(QWidget):
    """O console serial. ``voltar`` volta ao estado sem placa. ``listar_portas`` e ``abrir_console`` são trocados nos
    testes (um pseudoterminal no lugar da porta)."""

    voltar = Signal()

    def __init__(self, listar_portas=console_serial.portas, abrir_console=console_serial.ConsoleSerial,
                 parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("pagina_do_resgate")
        self.listar_portas, self.abrir_console = listar_portas, abrir_console
        self.portas: list[console_serial.PortaSerial] = []
        self.console: console_serial.ConsoleSerial | None = None
        self.leitor: LeitorSerial | None = None
        self.tela = None                          # o terminal: criado ao abrir (o pyte entra só aí)
        titulo = QLabel(traduzir("Resgate pela serial"))
        titulo.setFont(fonte("tela", QFont.Weight.DemiBold))
        self.voltar_ = Botao(traduzir("Voltar"), "fantasma")
        self.voltar_.setObjectName("voltar_do_resgate")
        self.voltar_.clicked.connect(self._voltar)
        cabecalho = QHBoxLayout()
        cabecalho.addWidget(titulo, 1)
        cabecalho.addWidget(self.voltar_, 0, Qt.AlignmentFlag.AlignTop)
        explicacao = texto(traduzir(
            "Quando a placa liga mas o SSH não responde, o mesmo cabo USB também é uma porta serial com o login da "
            "imagem (o usuário debian e a senha dele). Dali dá para ver o que falhou e desfazer: ligar o SSH, "
            "restaurar o uEnv.txt de antes. (O console do u-boot e do kernel é outro: o de três pinos da placa, com "
            "um cabo serial de 3,3 V, que aparece aqui como ttyUSB.)"), "resumo_do_item")

        self.escolha = QComboBox()
        self.escolha.setObjectName("porta_serial")
        self.escolha.currentIndexChanged.connect(lambda _i: self._situacao())
        self.procurar = Botao(traduzir("Procurar de novo"), "secundario", "girar")
        self.procurar.setObjectName("procurar_as_portas")
        self.procurar.clicked.connect(self.atualizar)
        self.abrir = Botao(traduzir("Abrir o console"), "primario", "terminal")
        self.abrir.setObjectName("abrir_o_console_serial")
        self.abrir.clicked.connect(self.abrir_o_console)
        self.fechar = Botao(traduzir("Fechar"), "secundario")
        self.fechar.setObjectName("fechar_o_console_serial")
        self.fechar.clicked.connect(self.fechar_o_console)
        linha = QHBoxLayout()
        linha.addWidget(self.escolha, 1)
        linha.addWidget(self.procurar)
        linha.addWidget(self.abrir)
        linha.addWidget(self.fechar)

        # sem permissão: o porquê e o comando
        self.permissao = QFrame()
        self.permissao.setObjectName("cartao_pendente")
        caixa = QVBoxLayout(self.permissao)
        caixa.setContentsMargins(12, 10, 12, 10)
        self.porque = texto("", "resumo_do_item")
        self.comando = texto("", "valor_do_fato")
        self.comando.setFont(fonte_mono())
        caixa.addWidget(self.porque)
        caixa.addWidget(self.comando)
        self.situacao = texto("", "texto_mudo")
        self.pelo_cartao_sd = texto(traduzir(
            "Se nem a porta serial aparece (o boot parou antes do Linux): ligue a placa pelo cartão microSD com uma "
            "imagem Debian da BeagleBone, segurando o botão S2 (o do lado do cartão) até os LEDs piscarem. Entre pela "
            "serial ou pelo SSH; o eMMC é o /dev/mmcblk1p1: sudo mount /dev/mmcblk1p1 /mnt, e sudo cp "
            "/mnt/boot/uEnv.txt.sh-analyzer-<data> /mnt/boot/uEnv.txt. Tire o cartão e ligue de novo."), "texto_mudo")
        self.pelo_cartao_sd.setObjectName("resgate_pelo_cartao_sd")

        # o console e os atalhos
        self.area_do_console = QWidget()
        self.coluna_do_console = QHBoxLayout(self.area_do_console)
        self.coluna_do_console.setContentsMargins(0, 0, 0, 0)
        atalhos = QVBoxLayout()
        atalhos.setSpacing(6)
        from ..terminal import BotaoDeAtalho

        self.atalhos = []
        for titulo_, comando, descricao in ATALHOS:
            botao = BotaoDeAtalho(titulo_, comando, descricao)
            botao.clicked.connect(lambda _c=False, cmd=comando: self.escrever(cmd))
            botao.setFixedWidth(260)
            atalhos.addWidget(botao)
            self.atalhos.append(botao)
        atalhos.addStretch(1)
        self.coluna_do_console.addLayout(atalhos)
        self.area_do_console.hide()

        coluna = QVBoxLayout(self)
        coluna.setContentsMargins(24, 20, 24, 16)
        coluna.setSpacing(10)
        coluna.addLayout(cabecalho)
        coluna.addWidget(explicacao)
        coluna.addLayout(linha)
        coluna.addWidget(self.permissao)
        coluna.addWidget(self.situacao)
        coluna.addWidget(self.pelo_cartao_sd)
        coluna.addWidget(self.area_do_console, 1)
        coluna.addStretch(0)                      # sem o console, o espaço fica embaixo (com ele, é dele)
        self.atualizar()

    # ------------------------------------------------------------------ as portas

    @property
    def porta(self) -> console_serial.PortaSerial | None:
        i = self.escolha.currentIndex()
        return self.portas[i] if 0 <= i < len(self.portas) else None

    def atualizar(self) -> None:
        anterior = self.porta.caminho if self.porta is not None else None
        try:
            self.portas = self.listar_portas()
        except Exception as e:                    # o pyserial que falta, o sysfs que não se lê
            self.portas = []
            self.situacao.setText(traduzir("Não deu para listar as portas seriais: {}").format(e))
        self.escolha.blockSignals(True)
        self.escolha.clear()
        for p in self.portas:
            self.escolha.addItem(p.titulo + ("" if p.acessivel else traduzir(" — sem permissão")))
        caminhos = [p.caminho for p in self.portas]
        if anterior in caminhos:
            self.escolha.setCurrentIndex(caminhos.index(anterior))
        self.escolha.blockSignals(False)
        self._situacao()

    def _situacao(self) -> None:
        p, aberto = self.porta, self.console is not None
        self.escolha.setEnabled(not aberto)
        self.procurar.setEnabled(not aberto)
        self.abrir.setVisible(not aberto)
        self.fechar.setVisible(aberto)
        self.abrir.setEnabled(p is not None and p.acessivel)
        self.permissao.setVisible(p is not None and not p.acessivel and not aberto)
        self.pelo_cartao_sd.setVisible(not aberto)
        if p is not None and not p.acessivel:
            porque, comandos = console_serial.como_liberar(p)
            self.porque.setText(porque)
            self.comando.setText("\n".join(comandos))
            self.comando.setVisible(bool(comandos))
        if aberto:
            return
        if not self.portas:
            self.situacao.setText(traduzir("Nenhuma porta serial USB. A placa está no cabo? Ela leva uns 30 s depois de "
                                           "ligar para a porta aparecer."))
        elif p is not None and not p.da_placa:
            self.situacao.setText(traduzir("Esta porta não é a do gadget da BeagleBone: um cabo serial (o console do "
                                           "u-boot e do kernel, 115200 8N1), ou outro aparelho."))
        else:
            self.situacao.setText("")

    # ------------------------------------------------------------------ o console

    def abrir_o_console(self) -> bool:
        p = self.porta
        if p is None or self.console is not None:
            return False
        try:
            self.console = self.abrir_console(p.caminho)
        except Exception as e:
            self.situacao.setText(traduzir("Não deu para abrir {}: {}").format(p.caminho, frase(str(e))))
            return False
        if self.tela is None:
            from ....componentes.terminal import TelaDeTerminal

            self.tela = TelaDeTerminal()
            self.tela.setObjectName("console_serial")
            self.tela.digitou.connect(self._digitou)
            self.coluna_do_console.insertWidget(0, self.tela, 1)
        self.tela.alimentar(("\r\n" + traduzir("— {} aberta (115200 8N1). Tecle Enter para o login. —").format(
            p.caminho) + "\r\n").encode())
        self.area_do_console.show()
        self.leitor = LeitorSerial(self.console, self)
        self.leitor.chegou.connect(self.tela.alimentar)
        self.leitor.caiu.connect(self._caiu)
        self.leitor.start()
        self.situacao.setText(traduzir("Console aberto em {}.").format(p.caminho))
        self._situacao()
        self.tela.setFocus()
        return True

    def _digitou(self, dados: bytes) -> None:
        if self.console is not None:
            try:
                self.console.escrever(dados)
            except Exception as e:
                self._caiu(str(e))

    def escrever(self, comando: str) -> None:
        """Um atalho: escreve o comando no console (o Enter é de quem lê)."""
        self._digitou(comando.encode())
        if self.tela is not None:
            self.tela.setFocus()

    def _caiu(self, motivo: str) -> None:
        self.fechar_o_console()
        self.situacao.setText(traduzir("A porta caiu ({}): o cabo saiu, ou a placa reiniciou. Procure de novo.").format(
            motivo))
        self.atualizar()

    def fechar_o_console(self) -> None:
        leitor, self.leitor = self.leitor, None
        if leitor is not None:
            leitor.requestInterruption()
            leitor.wait(2000)
        console, self.console = self.console, None
        if console is not None:
            try:
                console.fechar()
            except Exception:
                pass
        self._situacao()

    def _voltar(self) -> None:
        self.fechar_o_console()
        self.voltar.emit()

    def hideEvent(self, evento) -> None:
        super().hideEvent(evento)
        if not self.isVisibleTo(self.window()):
            self.fechar_o_console()                # a porta não fica aberta com a página fora de vista

    def closeEvent(self, evento) -> None:
        self.fechar_o_console()
        super().closeEvent(evento)
