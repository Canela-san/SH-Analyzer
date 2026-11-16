"""A seção Terminal da Aquisição (docs/gui-plan.md, 11.8; a F3.8): um shell na placa, em abas, ao lado dos atalhos
dos comandos de sempre.

* **As abas:** cada uma é um shell num PTY da placa (``sh_placa/terminal.py``), na conexão de agora, pintado pela
  :class:`~sh_analyzer_gui.componentes.terminal.TelaDeTerminal`. A primeira abre sozinha quando a seção aparece com a
  placa conectada. Ctrl+Shift+T abre outra, Ctrl+Shift+W fecha, Ctrl+PgUp/PgDn troca.
* **A gravação:** a saída de cada aba é acrescentada a um arquivo da pasta da sessão do dia, como o ``lab ssh`` faz
  (``$DIA/terminal_bbb.txt``; a segunda aba, ``terminal_bbb_2.txt``, para as saídas não se misturarem).
* **A queda do cabo:** o shell morre com a conexão; quando ela volta, a aba reabre sozinha, com uma linha separando o
  que era do que vem. O shell que saiu (o ``exit``) espera o "Reabrir".
* **Fechar uma aba com uma captura rodando** pergunta antes: o ``ler_adc`` que ela começou morreria com ela.
* **Os atalhos** escrevem o comando na aba; o Enter é de quem lê.
* **"Abrir no terminal do sistema":** o ``ssh`` com a chave e o ``known_hosts`` do aplicativo, no terminal da área de
  trabalho (o COSMIC, o GNOME, o KDE...; o Windows Terminal; o Terminal do macOS). Sem nenhum conhecido, o comando vai
  para a área de transferência.

**O pyte** entra com a primeira aba: a seção existe desde a abertura da janela, sem ele.
"""

from __future__ import annotations

import os
import shlex
import shutil
import sys
import time
from collections.abc import Callable
from functools import partial
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QUrl, Signal
from PySide6.QtGui import QAction, QDesktopServices, QFont, QGuiApplication, QKeySequence
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QTabBar,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)
from shiboken6 import isValid

from ... import preferencias
from ...componentes.basicos import Botao
from ...componentes.painel import EstadoVazio
from ...componentes.toast import Toast
from ...servicos.conexao_da_placa import ConexaoDaPlaca
from ...tema.icones import IconeDoTema
from .pecas import Painel, fonte
from .textos import frase, traduzir

ATALHOS = (
    ("Conferir a placa", "cd ~/firmware && ./coletar.sh conferir",
     "~10 s: o firmware, os pinos e o ADC respondendo; o nível, o offset e o ruído do sinal."),
    ("Os modos de coleta", "cd ~/firmware && ./coletar.sh --help",
     "A ajuda do coletar.sh: conferir, calibrar, sonda, aliasing, ruído, teto e bancada."),
    ("Captura rodando?", "pgrep -a ler_adc || echo 'nenhuma captura rodando'",
     "O ler_adc em execução, com os argumentos."),
    ("Estado da PRU0", "cat /sys/class/remoteproc/remoteproc1/{state,firmware}",
     "O remoteproc da PRU0 (4a334000.pru): rodando ou parada, e o firmware carregado."),
    ("Pinos da PRU", "for p in P9_28 P9_29 P9_30 P9_31; do config-pin -q $p; done",
     "O modo de cada pino (pruout e pruin)."),
    ("Mensagens do kernel", "dmesg | tail -n 30", "As 30 últimas mensagens: a PRU, o USB, os erros."),
    ("Capturas e espaço", "ls -lh ~/firmware/*.bin; df -h ~", "Os .bin na pasta do firmware e o espaço no cartão."),
    ("Memória e carga", "free -h; uptime", "A memória livre, a carga e o tempo ligada."),
)
"""(título, comando, o que ele mostra). Os comandos do dia a dia no laboratório (os do ``lab`` e do ``setup.sh``)."""

EMULADORES = {
    "cosmic-term": ["--"], "gnome-terminal": ["--"], "ptyxis": ["--"], "kgx": ["--"], "konsole": ["-e"],
    "xfce4-terminal": ["-x"], "terminator": ["-x"], "kitty": [], "alacritty": ["-e"], "wezterm": ["start", "--"],
    "foot": [], "xterm": ["-e"],
}
"""Os terminais do Linux e o que vem antes do comando em cada um, na ordem de procura."""

DA_AREA_DE_TRABALHO = {"COSMIC": "cosmic-term", "GNOME": "gnome-terminal", "UBUNTU": "gnome-terminal",
                       "KDE": "konsole", "XFCE": "xfce4-terminal"}


def terminal_do_sistema(ssh: list[str], plataforma: str = sys.platform, procurar=shutil.which,
                        ambiente=os.environ) -> list[str] | None:
    """O programa e os argumentos que abrem ``ssh`` num terminal da área de trabalho; ``None`` sem nenhum conhecido.
    No Linux: o da área de trabalho (``XDG_CURRENT_DESKTOP``), o ``x-terminal-emulator`` do Debian (pelo programa que
    ele é: cada terminal recebe o comando de um jeito) e os outros de :data:`EMULADORES`."""
    if plataforma == "win32":
        if (wt := procurar("wt")) is not None:
            return [wt, "new-tab", "--title", "BeagleBone", *ssh]
        return [ambiente.get("COMSPEC", "cmd.exe"), "/c", "start", "", *ssh]
    if plataforma == "darwin":
        comando = shlex.join(ssh).replace("\\", "\\\\").replace('"', '\\"')
        return ["osascript", "-e", f'tell application "Terminal" to do script "{comando}"',
                "-e", 'tell application "Terminal" to activate']
    preferidos = [DA_AREA_DE_TRABALHO[n.upper()] for n in ambiente.get("XDG_CURRENT_DESKTOP", "").split(":")
                  if n.upper() in DA_AREA_DE_TRABALHO]
    if (alternativa := procurar("x-terminal-emulator")) is not None:
        nome = Path(os.path.realpath(alternativa)).name.removesuffix(".wrapper")
        if nome in EMULADORES:
            preferidos.append(nome)
    for nome in [*preferidos, *EMULADORES]:
        if (caminho := procurar(nome)) is not None:
            return [caminho, *EMULADORES[nome], *ssh]
    return None


def iniciar_destacado(argumentos: list[str]) -> bool:
    """Roda o programa fora do aplicativo (ele segue aberto depois de o aplicativo fechar)."""
    from PySide6.QtCore import QProcess

    resultado = QProcess.startDetached(argumentos[0], argumentos[1:])
    return bool(resultado[0] if isinstance(resultado, tuple) else resultado)


# Uma aba ------------------------------------------------------------------------------------------------------------

class BarraDeBusca(QFrame):
    """A busca na rolagem da aba: a cada tecla (a mesma achada, enquanto ela ainda serve), o Enter procura a anterior,
    o Shift+Enter a próxima, o Esc fecha e devolve o foco ao terminal."""

    def __init__(self, tela, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("busca_do_terminal")
        self.tela = tela
        self.campo = QLineEdit()
        self.campo.setObjectName("campo_da_busca")
        self.campo.setPlaceholderText(traduzir("Buscar na rolagem"))
        self.campo.setClearButtonEnabled(True)
        self.campo.textEdited.connect(lambda texto: self.buscar(de_novo=False))
        self.campo.returnPressed.connect(lambda: self.buscar())
        self.situacao = QLabel()
        self.situacao.setObjectName("texto_mudo")
        self.situacao.setFont(fonte("secundario"))
        self.anterior = Botao("", "fantasma", "cima")
        self.anterior.setToolTip(traduzir("A anterior (Enter)"))
        self.anterior.clicked.connect(lambda: self.buscar(para_tras=True))
        self.proxima = Botao("", "fantasma", "baixo")
        self.proxima.setToolTip(traduzir("A próxima (Shift+Enter)"))
        self.proxima.clicked.connect(lambda: self.buscar(para_tras=False))
        fechar = Botao("", "fantasma", "x")
        fechar.setToolTip(traduzir("Fechar a busca (Esc)"))
        fechar.clicked.connect(self.fechar)
        linha = QHBoxLayout(self)
        linha.setContentsMargins(8, 4, 8, 4)
        linha.setSpacing(4)
        linha.addWidget(self.campo, 1)
        linha.addWidget(self.situacao)
        for botao in (self.anterior, self.proxima, fechar):
            linha.addWidget(botao)
        self.hide()

    def abrir(self) -> None:
        self.show()
        selecionado = self.tela.selecionado()
        if selecionado and "\n" not in selecionado:
            self.campo.setText(selecionado)
        self.campo.selectAll()
        self.campo.setFocus(Qt.FocusReason.ShortcutFocusReason)

    def fechar(self) -> None:
        self.hide()
        self.tela.setFocus(Qt.FocusReason.OtherFocusReason)

    def buscar(self, para_tras: bool | None = None, de_novo: bool = True) -> bool:
        if para_tras is None:
            para_tras = not (QGuiApplication.keyboardModifiers() & Qt.KeyboardModifier.ShiftModifier)
        achou = self.tela.buscar(self.campo.text(), para_tras=para_tras, de_novo=de_novo)
        self.situacao.setText("" if achou or not self.campo.text() else traduzir("nada encontrado"))
        return achou

    def keyPressEvent(self, evento) -> None:
        if evento.key() == Qt.Key.Key_Escape:
            self.fechar()
        else:
            super().keyPressEvent(evento)


class AbaDeTerminal(QWidget):
    """Um shell na placa: a tela, a busca e o aviso do fim (o shell que saiu, a conexão que caiu, a que não abriu).
    ``estado``: ``novo``, ``aberto``, ``terminou`` (saiu, com o ``codigo``), ``caiu`` (a conexão acabou antes) ou
    ``falhou`` (não abriu, com o ``erro``)."""

    mudou = Signal(object)                   # a própria aba: o estado ou o título mudou
    _chegou = Signal(object)                 # os bytes da placa, do laço para a thread da interface

    def __init__(self, conexao: ConexaoDaPlaca, numero: int, parent: QWidget | None = None):
        super().__init__(parent)
        from ...componentes.terminal import TelaDeTerminal

        self.setObjectName("aba_do_terminal")
        self.conexao, self.numero = conexao, numero
        self.estado, self.codigo, self.erro = "novo", None, ""
        self.sessao = self.chamada = None
        self.caiu_em: float | None = None
        self.tela = TelaDeTerminal()
        self.busca = BarraDeBusca(self.tela)
        self.aviso = QFrame()
        self.aviso.setObjectName("aviso_do_terminal")
        self.texto_do_aviso = QLabel()
        self.texto_do_aviso.setWordWrap(True)
        self.reabrir = Botao(traduzir("Reabrir"), "primario", "terminal")
        self.reabrir.setObjectName("reabrir_terminal")
        self.reabrir.clicked.connect(self.abrir)
        linha = QHBoxLayout(self.aviso)
        linha.setContentsMargins(12, 8, 8, 8)
        linha.addWidget(self.texto_do_aviso, 1)
        linha.addWidget(self.reabrir)
        self.aviso.hide()
        coluna = QVBoxLayout(self)
        coluna.setContentsMargins(0, 0, 0, 0)
        coluna.setSpacing(0)
        coluna.addWidget(self.tela, 1)
        coluna.addWidget(self.busca)
        coluna.addWidget(self.aviso)
        self._chegou.connect(self.tela.alimentar)
        self.tela.digitou.connect(self._digitou)
        self.tela.tamanhoMudou.connect(self._tamanho_mudou)
        self.tela.tituloMudou.connect(self._titulo_mudou)
        self.tela.buscaPedida.connect(self.busca.abrir)
        conexao.mudou.connect(self._atualizar)

    @property
    def gravacao(self) -> Path:
        """O arquivo da gravação desta aba, na pasta da sessão do dia (o de hoje, a cada abertura)."""
        nome = "terminal_bbb.txt" if self.numero == 1 else f"terminal_bbb_{self.numero}.txt"
        return preferencias.pasta_da_sessao() / nome

    @property
    def titulo(self) -> str:
        """O título que o shell deu (o ``debian@beaglebone: ~`` do bash), ou "Terminal 2"."""
        return self.tela.titulo or traduzir("Terminal {}").format(self.numero)

    @property
    def aberta(self) -> bool:
        return self.estado == "aberto"

    def abrir(self) -> bool:
        """Abre o shell na conexão de agora (``False``: sem conexão, ou já aberto)."""
        from sh_placa.terminal import SessaoDeTerminal

        ssh = self.conexao.conexao_ssh
        if ssh is None or self.conexao.estado != "conectada" or self.aberta:
            return False
        if self.estado != "novo":            # a mesma aba de novo: uma linha separa o que era do que vem
            quando = time.strftime("%H:%M:%S")
            self.tela.alimentar(f"\x1b[0m\r\n\x1b[2m── {traduzir('reaberto às {}').format(quando)} ──\x1b[0m\r\n".encode())
        self.sessao = SessaoDeTerminal(ssh, self.tela.colunas, self.tela.linhas, ao_receber=self._receber,
                                       gravacao=self.gravacao)
        self.estado, self.codigo, self.erro, self.caiu_em = "aberto", None, "", None
        self.chamada = self.conexao.servico.chamar(traduzir("terminal da placa"), self.sessao.rodar,
                                                   ao_terminar=self._terminou)
        self._atualizar()
        self.mudou.emit(self)
        return True

    def fechar(self) -> None:
        """Fecha o shell (a aba vai embora: nada mais chega a ela)."""
        sessao, self.sessao = self.sessao, None
        if sessao is not None:
            sessao.ao_receber = lambda _dados: None
            self.conexao.servico.laco.agendar(sessao.fechar)
        self.chamada = None

    def _titulo_mudou(self, _titulo: str) -> None:
        self.mudou.emit(self)

    def _receber(self, dados: bytes) -> None:
        """Na thread do laço: os bytes vão pela fila de eventos (a aba fechada no meio do caminho não recebe)."""
        if isValid(self):
            try:
                self._chegou.emit(dados)
            except RuntimeError:             # apagada entre o isValid e o emit
                pass

    def _digitou(self, dados: bytes) -> None:
        if self.sessao is not None and self.aberta:
            self.conexao.servico.laco.agendar(self.sessao.escrever, dados)

    def _tamanho_mudou(self, colunas: int, linhas: int) -> None:
        if self.sessao is not None and self.aberta:
            self.conexao.servico.laco.agendar(self.sessao.redimensionar, colunas, linhas)

    def _terminou(self, chamada) -> None:
        if chamada is not self.chamada:
            return
        if chamada.estado == "falhou":
            self.estado, self.erro = "falhou", chamada.erro
        elif chamada.estado == "concluida" and chamada.resultado is not None:
            self.estado, self.codigo = "terminou", chamada.resultado
        else:
            self.estado, self.caiu_em = "caiu", time.time()
        sessao = self.sessao
        self._atualizar()
        self.mudou.emit(self)
        if self.estado == "caiu" and sessao is not None and self.conexao.conexao_ssh not in (None, sessao.conexao):
            self.abrir()                     # a placa já voltou, numa conexão nova

    def _atualizar(self) -> None:
        if self.estado in ("novo", "aberto"):
            self.aviso.hide()
            return
        conectada = self.conexao.estado == "conectada" and self.conexao.conexao_ssh is not None
        if self.estado == "terminou":
            texto = traduzir("O shell terminou (código {}). A saída ficou em {}.").format(self.codigo, self.gravacao)
        elif self.estado == "caiu":
            texto = traduzir("A conexão com a placa caiu: o terminal reabre sozinho quando ela voltar.") \
                if not conectada else traduzir("O terminal fechou sem o código de saída.")
        else:
            texto = traduzir("O terminal não abriu: {}").format(frase(self.erro))
        self.texto_do_aviso.setText(texto)
        self.reabrir.setEnabled(conectada)
        self.aviso.setProperty("nivel", "aviso" if self.estado in ("caiu", "falhou") else "")
        self.aviso.style().unpolish(self.aviso)
        self.aviso.style().polish(self.aviso)
        self.aviso.show()


# A seção ------------------------------------------------------------------------------------------------------------

class BotaoDeAtalho(QPushButton):
    """Um atalho: o título e, embaixo, o comando em mono. Clicar escreve o comando na aba."""

    def __init__(self, titulo: str, comando: str, descricao: str, parent: QWidget | None = None):
        super().__init__(parent)
        from ...tema.fontes import fonte_mono

        self.setObjectName("atalho_do_terminal")
        self.comando = comando
        self.setToolTip(f"{traduzir(descricao)}\n\n{comando}\n\n" + traduzir("Escreve o comando na aba; o Enter é seu."))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        nome = QLabel(traduzir(titulo))
        nome.setFont(fonte("corpo", QFont.Weight.DemiBold))
        texto = QLabel(comando)
        texto.setObjectName("comando_do_atalho")
        texto.setFont(fonte_mono())
        for rotulo in (nome, texto):
            rotulo.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        texto.setMinimumWidth(1)              # o comando comprido não alarga o painel: ele é cortado
        coluna = QVBoxLayout(self)
        coluna.setContentsMargins(12, 6, 12, 6)
        coluna.setSpacing(2)
        coluna.addWidget(nome)
        coluna.addWidget(texto)
        self.setMinimumHeight(coluna.sizeHint().height())


class Terminal(QWidget):
    """A seção Terminal. ``executar_programa(argumentos)`` abre o terminal do sistema; ``abrir_url`` mostra a pasta
    da gravação; ``dialogos_de()`` pergunta antes de fechar uma aba com uma captura rodando (os testes passam falsos)."""

    def __init__(self, conexao: ConexaoDaPlaca, *, dialogos_de=None,
                 executar_programa: Callable[[list[str]], bool] = iniciar_destacado,
                 abrir_url: Callable[[QUrl], object] = QDesktopServices.openUrl, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("terminal_da_placa")
        self.conexao, self.dialogos_de = conexao, dialogos_de
        self.executar_programa, self.abrir_url = executar_programa, abrir_url
        self.paginas = QStackedWidget()
        self.vazio = EstadoVazio(traduzir("Nenhuma placa conectada"),
                                 traduzir("Conecte uma placa para abrir um terminal nela. A saída de cada aba fica "
                                          "gravada na pasta da sessão do dia."), icone_nome="terminal",
                                 largura_do_texto=440)
        self.simulador = EstadoVazio(traduzir("O simulador não tem terminal"),
                                     traduzir("Ele roda neste computador, sem SSH: o terminal é o da placa de "
                                              "verdade."), icone_nome="terminal", largura_do_texto=440)
        self.paginas.addWidget(self.vazio)
        self.paginas.addWidget(self.simulador)
        self.paginas.addWidget(self._criar_conectada())
        coluna = QVBoxLayout(self)
        coluna.setContentsMargins(0, 0, 0, 0)
        coluna.addWidget(self.paginas)
        self._criar_acoes()
        self._conectada_antes = False
        conexao.mudou.connect(self.atualizar)
        self.atualizar()

    # ------------------------------------------------------------------ montar

    def _criar_conectada(self) -> QWidget:
        titulo = QLabel(traduzir("Terminal"))
        titulo.setFont(fonte("tela", QFont.Weight.DemiBold))
        self.subtitulo = QLabel()
        self.subtitulo.setObjectName("subtitulo_da_secao")
        self.subtitulo.setWordWrap(True)
        self.subtitulo.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.mostrar_gravacao = Botao(traduzir("Mostrar a gravação"), "fantasma", "pasta")
        self.mostrar_gravacao.setObjectName("mostrar_a_gravacao")
        self.mostrar_gravacao.clicked.connect(lambda: self.abrir_url(
            QUrl.fromLocalFile(str(preferencias.pasta_da_sessao()))))
        self.do_sistema = Botao(traduzir("Abrir no terminal do sistema"), "secundario", "terminal")
        self.do_sistema.setObjectName("abrir_no_terminal_do_sistema")
        self.do_sistema.clicked.connect(self.abrir_no_terminal_do_sistema)
        cabecalho = QHBoxLayout()
        textos = QVBoxLayout()
        textos.setSpacing(2)
        textos.addWidget(titulo)
        textos.addWidget(self.subtitulo)
        cabecalho.addLayout(textos, 1)
        for botao in (self.mostrar_gravacao, self.do_sistema):
            cabecalho.addWidget(botao, 0, Qt.AlignmentFlag.AlignTop)

        self.abas = QTabWidget()
        self.abas.setObjectName("abas_do_terminal")
        self.abas.setDocumentMode(True)
        self.abas.setMovable(True)                  # o × de cada aba é nosso (o mesmo das vistas da Análise)
        self.abas.currentChanged.connect(lambda _i: self._focar())
        self.nova = Botao("", "fantasma", "mais")
        self.nova.setObjectName("nova_aba_do_terminal")
        self.nova.setToolTip(traduzir("Nova aba (Ctrl+Shift+T)"))
        self.nova.clicked.connect(self.nova_aba)
        self.abas.setCornerWidget(self.nova, Qt.Corner.TopRightCorner)

        self.painel_dos_atalhos = Painel(traduzir("Atalhos"))
        self.atalhos: list[BotaoDeAtalho] = []
        for titulo_do_atalho, comando, descricao in ATALHOS:
            botao = BotaoDeAtalho(titulo_do_atalho, comando, descricao)
            botao.clicked.connect(lambda _marcado=False, b=botao: self.escrever_atalho(b.comando))
            self.atalhos.append(botao)
            self.painel_dos_atalhos.corpo.addWidget(botao)
        dica = QLabel(traduzir("Clicar escreve o comando na aba; o Enter é seu."))
        dica.setObjectName("texto_mudo")
        dica.setFont(fonte("secundario"))
        dica.setWordWrap(True)
        dica.setContentsMargins(14, 8, 14, 12)
        self.painel_dos_atalhos.corpo.addWidget(dica)
        self.painel_dos_atalhos.corpo.addStretch(1)
        self.painel_dos_atalhos.setMinimumWidth(240)
        self.painel_dos_atalhos.setMaximumWidth(360)

        self.abrir_um = Botao(traduzir("Abrir um terminal"), "primario", "terminal")
        self.abrir_um.setObjectName("abrir_um_terminal")
        self.abrir_um.clicked.connect(self.nova_aba)
        self.sem_abas = EstadoVazio(traduzir("Nenhum terminal aberto"),
                                    traduzir("Cada aba é um shell na placa, gravado na pasta da sessão do dia."),
                                    icone_nome="terminal", botao=self.abrir_um, largura_do_texto=360)
        self.corpo = QStackedWidget()
        self.corpo.addWidget(self.abas)
        self.corpo.addWidget(self.sem_abas)
        divisor = QSplitter(Qt.Orientation.Horizontal)
        divisor.setChildrenCollapsible(False)
        divisor.addWidget(self.corpo)
        divisor.addWidget(self.painel_dos_atalhos)
        divisor.setStretchFactor(0, 1)
        divisor.setStretchFactor(1, 0)
        pagina = QWidget()
        externa = QVBoxLayout(pagina)
        externa.setContentsMargins(24, 20, 24, 20)
        externa.setSpacing(16)
        externa.addLayout(cabecalho)
        externa.addWidget(divisor, 1)
        return pagina

    def _criar_acoes(self) -> None:
        contexto = Qt.ShortcutContext.WidgetWithChildrenShortcut
        for atalho, funcao in (("Ctrl+Shift+T", self.nova_aba),
                               ("Ctrl+Shift+W", lambda: self.pedir_para_fechar(self.abas.currentWidget())),
                               ("Ctrl+PgDown", lambda: self._trocar(1)), ("Ctrl+PgUp", lambda: self._trocar(-1))):
            acao = QAction(self)
            acao.setShortcut(QKeySequence(atalho))
            acao.setShortcutContext(contexto)
            acao.triggered.connect(funcao)
            self.addAction(acao)

    # ------------------------------------------------------------------ o estado

    @property
    def abas_abertas(self) -> list[AbaDeTerminal]:
        return [self.abas.widget(i) for i in range(self.abas.count())]

    def _pode_abrir(self) -> bool:
        return self.conexao.estado == "conectada" and self.conexao.conexao_ssh is not None

    def atualizar(self) -> None:
        c = self.conexao
        if c.simulada:
            self.paginas.setCurrentWidget(self.simulador)
            return
        if c.estado not in ("conectada", "reconectando") and not self.abas.count():
            self.paginas.setCurrentWidget(self.vazio)
            return
        self.paginas.setCurrentIndex(2)
        conta = c.destino.conta if c.destino is not None else ""
        if c.estado == "conectada":
            situacao = conta
        elif c.estado == "reconectando":
            situacao = traduzir("{}: reconectando…").format(conta)
        else:
            situacao = traduzir("sem conexão")
        self.subtitulo.setText(traduzir("{} · a saída de cada aba fica gravada na pasta da sessão do dia "
                                        "(terminal_bbb.txt)").format(situacao))
        self.subtitulo.setToolTip(str(preferencias.pasta_da_sessao()))
        pode = self._pode_abrir()
        chegou, self._conectada_antes = pode and not self._conectada_antes, pode
        self.nova.setEnabled(pode)
        self.abrir_um.setEnabled(pode)
        self.corpo.setCurrentWidget(self.abas if self.abas.count() else self.sem_abas)
        self.do_sistema.setEnabled(c.conexao_ssh is not None)
        for botao in self.atalhos:
            botao.setEnabled(any(a.aberta for a in self.abas_abertas))
        if chegou:                           # a placa (re)conectou: as abas que caíram voltam
            for aba in self.abas_abertas:
                if aba.estado == "caiu":
                    aba.abrir()
            if not self.abas.count() and self.isVisible():
                self.nova_aba()

    def showEvent(self, evento) -> None:
        super().showEvent(evento)
        if not self.abas.count() and self._pode_abrir():
            self.nova_aba()
        self._focar()

    def _focar(self) -> None:
        aba = self.abas.currentWidget()
        if aba is not None and self.isVisible():
            aba.tela.setFocus(Qt.FocusReason.OtherFocusReason)

    # ------------------------------------------------------------------ as abas

    def nova_aba(self) -> AbaDeTerminal | None:
        if not self._pode_abrir():
            return None
        usados = {a.numero for a in self.abas_abertas}
        numero = next(n for n in range(1, len(usados) + 2) if n not in usados)
        aba = AbaDeTerminal(self.conexao, numero)
        aba.mudou.connect(self._aba_mudou)
        i = self.abas.addTab(aba, aba.titulo)
        fechar = QToolButton()
        fechar.setObjectName("fechar_aba")
        fechar.setAutoRaise(True)
        fechar.setIconSize(QSize(14, 14))
        fechar.setFixedSize(QSize(20, 20))
        fechar.setCursor(Qt.CursorShape.PointingHandCursor)
        fechar.setToolTip(traduzir("Fechar a aba (Ctrl+Shift+W)"))
        IconeDoTema(fechar, "x", "texto2", tamanho=14)
        fechar.clicked.connect(lambda _=False, a=aba: self.pedir_para_fechar(a))
        self.abas.tabBar().setTabButton(i, QTabBar.ButtonPosition.RightSide, fechar)
        self.abas.setCurrentWidget(aba)
        aba.abrir()                          # no tamanho que ela tem agora; o do layout chega logo depois
        self.atualizar()
        self._focar()
        return aba

    def _aba_mudou(self, aba: AbaDeTerminal) -> None:
        i = self.abas.indexOf(aba)
        if i < 0:
            return
        titulo = aba.titulo
        self.abas.setTabText(i, titulo if len(titulo) <= 32 else titulo[:31] + "…")
        self.abas.setTabToolTip(i, f"{titulo}\n{aba.gravacao}")
        self.atualizar()

    def _trocar(self, passo: int) -> None:
        if self.abas.count():
            self.abas.setCurrentIndex((self.abas.currentIndex() + passo) % self.abas.count())

    def pedir_para_fechar(self, aba: AbaDeTerminal | None) -> None:
        """Fecha a aba; com o shell aberto, antes confere se há uma captura rodando na placa (e pergunta)."""
        if aba is None:
            return
        ssh = self.conexao.conexao_ssh
        if not aba.aberta or ssh is None or self.dialogos_de is None:
            self.fechar_aba(aba)
            return
        conferir = partial(ssh.executar, "pgrep -x ler_adc", tempo_limite=10.0,
                           descricao="terminal: há captura rodando antes de fechar a aba?")
        self.conexao.servico.chamar(traduzir("conferir se há captura rodando"), conferir,
                                    ao_terminar=lambda chamada, a=aba: self._fechar_se_puder(a, chamada))

    def _fechar_se_puder(self, aba: AbaDeTerminal, chamada) -> None:
        if not isValid(aba) or self.abas.indexOf(aba) < 0:
            return
        rodando = chamada.estado == "concluida" and chamada.resultado.codigo == 0
        if rodando:
            resposta = self.dialogos_de().perguntar(
                traduzir("Fechar o terminal"),
                traduzir("Uma captura (o ler_adc) está rodando na placa. Se ela começou nesta aba, fechar a aba a "
                         "interrompe."), {"fechar": traduzir("Fechar a aba")}, None)
            if resposta != "fechar":
                return
        self.fechar_aba(aba)

    def fechar_aba(self, aba: AbaDeTerminal) -> None:
        i = self.abas.indexOf(aba)
        if i < 0:
            return
        aba.fechar()
        self.abas.removeTab(i)
        aba.deleteLater()
        self.atualizar()
        self._focar()

    def fechar_todas(self) -> None:
        for aba in self.abas_abertas:
            self.fechar_aba(aba)

    # ------------------------------------------------------------------ os atalhos e o terminal do sistema

    def escrever_atalho(self, comando: str) -> bool:
        """Escreve ``comando`` na aba da frente, sem o Enter."""
        aba = self.abas.currentWidget()
        if aba is None or not aba.aberta:
            return False
        aba.tela.escrever(comando)
        return True

    def argumentos_do_ssh(self) -> list[str] | None:
        """O ``ssh`` para a placa conectada, com a chave e o ``known_hosts`` desta conexão."""
        from sh_placa.terminal import argumentos_do_ssh

        ssh = self.conexao.conexao_ssh
        if ssh is None:
            return None
        return argumentos_do_ssh(ssh.destino, ssh.chave.caminho, ssh.hosts.arquivo)

    def abrir_no_terminal_do_sistema(self) -> bool:
        ssh = self.argumentos_do_ssh()
        if ssh is None:
            return False
        programa = terminal_do_sistema(ssh)
        if programa is not None and self.executar_programa(programa):
            return True
        QGuiApplication.clipboard().setText(shlex.join(ssh))
        Toast.mostrar(self.window(), traduzir("Nenhum terminal do sistema abriu: o comando do ssh foi copiado para a "
                                              "área de transferência."), "aviso")
        return False

