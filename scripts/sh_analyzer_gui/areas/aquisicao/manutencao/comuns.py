"""As peças das páginas da Manutenção (docs/gui-plan.md, 11.10; a Fase 6): o texto selecionável, o texto mono
longo (o log, o roteiro) e o diff colorido, o cartão, a linha de um fato e a coluna central, como os do diagnóstico;
e, das ações do sistema da placa (``servicos/sistema_da_placa.py``), o cartão da ação ao vivo e o diálogo que a
confirma (com o sudo)."""

from __future__ import annotations

import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QFont, QSyntaxHighlighter, QTextCharFormat
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QProgressBar,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ....componentes.basicos import Botao
from ....componentes.numeros import formatar_bytes
from ....servicos.sistema_da_placa import AcaoDoSistema, SistemaDaPlaca
from ....tema.aplicar import aparencia
from ....tema.fontes import fonte_mono
from ....tema.tokens import TAMANHOS
from ..pecas import Selo, fonte, repolir
from ..textos import frase, traduzir

LARGURA_MAXIMA = 920
LARGURA_DO_DIALOGO = 600
LARGURA_DO_NOME_DO_FATO = 190


def texto(texto: str = "", nome: str = "texto_do_dialogo", selecionavel: bool = True) -> QLabel:
    rotulo = QLabel(texto)
    rotulo.setObjectName(nome)
    rotulo.setWordWrap(True)
    if selecionavel:
        rotulo.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return rotulo


class TextoMono(QPlainTextEdit):
    """Um texto longo na fonte mono, só de leitura (o log de uma tarefa, um roteiro)."""

    def __init__(self, linhas_visiveis: int = 12, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("texto_mono_longo")
        self.setReadOnly(True)
        self.setFont(fonte_mono(TAMANHOS["secundario"]))
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.setMaximumBlockCount(5000)
        altura = self.fontMetrics().lineSpacing() * linhas_visiveis + 16
        self.setFixedHeight(altura)

    def acrescentar(self, texto: str) -> None:
        barra = self.verticalScrollBar()
        no_fim = barra.value() >= barra.maximum() - 2
        cursor = self.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        cursor.insertText(texto)
        if no_fim:
            barra.setValue(barra.maximum())


def coluna_central(conteudo: QWidget, nome: str) -> QScrollArea:
    """A coluna de no máximo :data:`LARGURA_MAXIMA` no meio, rolando (como o diagnóstico)."""
    conteudo.setMaximumWidth(LARGURA_MAXIMA)
    centro = QWidget()
    centro.setObjectName("conteudo_do_diagnostico")
    linha = QHBoxLayout(centro)
    linha.setContentsMargins(0, 0, 0, 0)
    linha.addStretch(1)
    linha.addWidget(conteudo, 100)
    linha.addStretch(1)
    rolagem = QScrollArea()
    rolagem.setObjectName(nome)
    rolagem.setWidgetResizable(True)
    rolagem.setFrameShape(QFrame.Shape.NoFrame)
    rolagem.setWidget(centro)
    return rolagem


def cartao(titulo: str = "", nome: str = "item_do_diagnostico") -> tuple[QFrame, QVBoxLayout]:
    """Um cartão (o do diagnóstico), com o título em negrito, se houver."""
    quadro = QFrame()
    quadro.setObjectName(nome)
    coluna = QVBoxLayout(quadro)
    coluna.setContentsMargins(14, 12, 14, 12)
    coluna.setSpacing(6)
    if titulo:
        rotulo = QLabel(titulo)
        rotulo.setFont(fonte("corpo", QFont.Weight.DemiBold))
        coluna.addWidget(rotulo)
    return quadro, coluna


def fato(nome: str, valor: str, mono: bool = False) -> QWidget:
    """Uma linha "nome: valor" de um cartão de fatos (o valor selecionável; ``mono`` para linhas de comando)."""
    linha = QWidget()
    caixa = QHBoxLayout(linha)
    caixa.setContentsMargins(0, 0, 0, 0)
    caixa.setSpacing(12)
    rotulo = QLabel(nome)
    rotulo.setObjectName("texto_mudo")
    rotulo.setFixedWidth(LARGURA_DO_NOME_DO_FATO)
    rotulo.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
    valor_ = texto(valor or "—")
    valor_.setObjectName("valor_do_fato")
    if mono:
        valor_.setFont(fonte_mono(TAMANHOS["secundario"]))
    caixa.addWidget(rotulo)
    caixa.addWidget(valor_, 1)
    return linha


def ha_quanto_tempo(segundos: float | None) -> str:
    """"3 h 12 min", "4 dias": quanto a placa está ligada."""
    if segundos is None:
        return ""
    s = int(segundos)
    if s < 60:
        return traduzir("{} s").format(s)
    if s < 3600:
        return traduzir("{} min").format(s // 60)
    if s < 86400:
        return traduzir("{} h {} min").format(s // 3600, s % 3600 // 60)
    return traduzir("{} dia(s) {} h").format(s // 86400, s % 86400 // 3600)


class DestaqueDoDiff(QSyntaxHighlighter):
    """As linhas de um diff unificado: as que entram na cor do ok, as que saem na do erro, os cabeçalhos em mudo."""

    def __init__(self, documento):
        super().__init__(documento)
        aparencia().mudou.connect(self._tema_mudou)

    def _tema_mudou(self, _tema) -> None:
        self.rehighlight()

    def highlightBlock(self, linha: str) -> None:
        tema = aparencia().tema
        if linha.startswith(("+++", "---", "@@")):
            cor = tema.mudo
        elif linha.startswith("+"):
            cor = tema.ok
        elif linha.startswith("-"):
            cor = tema.erro
        else:
            return
        formato = QTextCharFormat()
        formato.setForeground(QColor(cor))
        self.setFormat(0, len(linha), formato)


class Diff(TextoMono):
    """Um diff unificado colorido (o ``uEnv.txt`` de agora e o novo)."""

    def __init__(self, linhas_visiveis: int = 10, parent: QWidget | None = None):
        super().__init__(linhas_visiveis, parent)
        self.setObjectName("diff")
        self.destaque = DestaqueDoDiff(self.document())

    def linhas(self) -> list[tuple[str, str]]:
        """As linhas que mudam, como ``("+", linha)`` e ``("-", linha)`` (para os testes e o caderno)."""
        return [(x[0], x[1:]) for x in self.toPlainText().splitlines()
                if x[:1] in "+-" and not x.startswith(("+++", "---"))]


# ------------------------------------------------------------------ as ações do sistema

def descrever_acao(acao: AcaoDoSistema, agora: float | None = None) -> tuple[str, str, str]:
    """``(nível, selo, texto)`` da ação, para o cartão dela."""
    agora = time.monotonic() if agora is None else agora
    d = acao.detalhes
    copia = d.get("copia")
    sobre_a_copia = traduzir(" A cópia de antes ficou em {}.").format(copia) if copia else ""
    if acao.estado == "rodando" and acao.nome == "parar_ler_adc":
        return "info", traduzir("parando"), traduzir("Parando o ler_adc como o Ctrl+C (o INT: ele fecha o arquivo e "
                                                     "para a PRU)…")
    if acao.estado == "rodando":
        if acao.energia is not None and (d.get("gravado") or d.get("feito") or acao.nome in ("reiniciar", "desligar")):
            return "info", traduzir("pedindo"), (traduzir("Pedindo o reinício à placa…") if acao.energia == "reiniciar"
                                                 else traduzir("Pedindo o desligamento à placa…"))
        if acao.nome in ("gravar_uenv", "restaurar_uenv"):
            return "info", traduzir("gravando"), traduzir("Gravando o /boot/uEnv.txt, com a cópia de segurança…")
        textos = {"servico": (traduzir("Ligando o {}…") if d.get("ligar") else traduzir("Desligando o {}…")).format(
                      d.get("unidade", "")),
                  "limpar": traduzir("Limpando…"), "expandir": traduzir("Mudando a tabela de partições…"),
                  "trocar_senha": traduzir("Trocando a senha (o chpasswd)…")}
        return "info", traduzir("rodando"), textos.get(acao.nome, traduzir("Rodando…"))
    if acao.estado == "esperando_a_placa":
        segundos = int(agora - acao.pediu_em) if acao.pediu_em is not None else 0
        if acao.energia == "reiniciar":
            return "info", traduzir("reiniciando"), traduzir(
                "A placa está reiniciando ({} s): ela volta sozinha, e a conexão também (a de verdade leva cerca de "
                "1 min).").format(segundos) + sobre_a_copia
        return "info", traduzir("desligando"), traduzir(
            "Esperando a placa desligar ({} s): ainda não a tire da tomada.").format(segundos)
    if acao.estado == "feita":
        voltou = d.get("voltou_em_s")
        em = traduzir(" em {} s").format(int(voltou)) if voltou is not None else ""
        if acao.nome in ("gravar_uenv", "restaurar_uenv"):
            if acao.energia == "reiniciar":
                texto_ = traduzir("Gravado, e a placa voltou{} com o uEnv.txt novo.").format(em)
            else:
                texto_ = traduzir("Gravado: o uEnv.txt novo vale no próximo boot (Sistema, Reiniciar).")
            texto_ += sobre_a_copia
        elif acao.nome == "reiniciar":
            texto_ = traduzir("A placa reiniciou e voltou{}.").format(em)
        elif acao.nome == "servico":
            texto_ = (traduzir("O {} está ligado: roda agora e sobe nos próximos boots.") if d.get("ligar") else
                      traduzir("O {} está desligado: parou e não sobe mais no boot.")).format(d.get("unidade", ""))
        elif acao.nome == "limpar":
            if d.get("qual") == "tarefas":
                texto_ = traduzir("{} tarefa(s) terminada(s) apagada(s).").format(d.get("resultado") or 0)
            else:
                texto_ = traduzir("Limpo (ocupava {}).").format(formatar_bytes(d.get("antes") or 0))
        elif acao.nome == "expandir":
            texto_ = (traduzir("A partição vai até o fim do cartão, e a placa voltou{}: o sistema de arquivos "
                               "cresceu.").format(em) if acao.energia == "reiniciar" else
                      traduzir("A tabela de partições mudou: o sistema de arquivos cresce no próximo boot (Sistema, "
                               "Reiniciar)."))
        elif acao.nome == "trocar_senha":
            texto_ = traduzir("Senha trocada: vale para o SSH e para o sudo da placa, daí em diante.") + " " + (
                traduzir("O cofre do sistema guarda a nova.") if d.get("no_cofre") else
                traduzir("O cofre do sistema não guarda senha desta placa."))
        elif acao.nome == "parar_ler_adc":
            dito = d.get("dito", "")
            texto_ = (traduzir("O ler_adc parou (PID {}).").format(dito.split(":", 1)[1].strip())
                      if dito.startswith("parado:") else traduzir("Nenhum ler_adc rodava mais na placa."))
        else:
            texto_ = traduzir("A placa desligou: já pode tirar da tomada.")
        if acao.energia == "reiniciar":
            texto_ += " " + traduzir("Os pinos da PRU voltam ao padrão a cada boot: a próxima captura os configura "
                                     "(como o setup.sh).")
        if acao.mensagem:
            texto_ += " " + frase(acao.mensagem)
        selo = {"gravar_uenv": "gravado", "restaurar_uenv": "restaurado", "reiniciar": "reiniciada",
                "desligar": "desligada", "parar_ler_adc": "parado", "servico": "feito", "limpar": "limpo",
                "expandir": "expandida", "trocar_senha": "trocada"}.get(acao.nome, "feita")
        return "ok", traduzir(selo), texto_
    if acao.estado == "falhou":
        texto_ = frase(acao.mensagem) or traduzir("A ação falhou.")
        if d.get("gravado") and acao.energia == "reiniciar":
            texto_ += " " + traduzir(
                "O uEnv.txt novo já está gravado.{} Se a placa não voltar, a serial mostra o boot dela; para "
                "desfazer, restaure a cópia (na placa: sudo cp {} /boot/uEnv.txt && sudo reboot).").format(
                sobre_a_copia, copia or "/boot/uEnv.txt.sh-analyzer-…")
        return "erro", traduzir("falhou"), texto_
    return "aviso", traduzir("esperando você"), frase(acao.mensagem)


class CartaoDaAcao(QFrame):
    """O cartão da ação de agora (ou da última) numa página que pede as ações ``nomes``: o título, o selo, o que
    aconteceu, a espera da placa contando os segundos e, no fim, "Fechar"."""

    def __init__(self, sistema: SistemaDaPlaca, nomes: tuple[str, ...], parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("item_do_diagnostico")
        self.sistema, self.nomes = sistema, nomes
        self.titulo = QLabel()
        self.titulo.setFont(fonte("corpo", QFont.Weight.DemiBold))
        self.selo = Selo("info")
        self.dispensar = Botao(traduzir("Fechar"), "fantasma")
        self.dispensar.setObjectName("dispensar_a_acao")
        self.dispensar.clicked.connect(sistema.dispensar)
        topo = QHBoxLayout()
        topo.addWidget(self.titulo)
        topo.addWidget(self.selo)
        topo.addStretch(1)
        topo.addWidget(self.dispensar)
        self.texto = texto("", "resumo_do_item")
        self.diff = Diff(8)
        self.diff.hide()
        coluna = QVBoxLayout(self)
        coluna.setContentsMargins(14, 12, 14, 12)
        coluna.setSpacing(6)
        coluna.addLayout(topo)
        coluna.addWidget(self.texto)
        coluna.addWidget(self.diff)
        self._relogio = QTimer(self)
        self._relogio.setInterval(1000)
        self._relogio.timeout.connect(self.atualizar)
        sistema.acaoMudou.connect(self.atualizar)
        self.hide()

    def atualizar(self) -> None:
        a = self.sistema.acao
        visivel = a is not None and a.nome in self.nomes and not a.esperando_o_usuario
        self.setVisible(visivel)
        if not visivel:
            self._relogio.stop()
            return
        nivel, selo, texto_ = descrever_acao(a)
        self.titulo.setText(traduzir(a.titulo) + (traduzir(" e reiniciar") if a.energia == "reiniciar"
                                                  and a.nome.endswith("uenv") else ""))
        self.selo.definir(nivel, selo)
        self.texto.setText(texto_)
        diff = a.detalhes.get("diff", "")
        if diff != self.diff.toPlainText():
            self.diff.setPlainText(diff)
        self.diff.setVisible(bool(diff))
        self.dispensar.setVisible(not a.rodando)
        if a.estado == "esperando_a_placa":
            if not self._relogio.isActive():
                self._relogio.start()
        else:
            self._relogio.stop()


class DialogoDaAcao(QDialog):
    """A confirmação de uma ação do sistema da placa (gravar o ``uEnv.txt``, restaurar uma cópia, reiniciar,
    desligar): o que vai acontecer, o diff (quando muda um arquivo), o comando exato ("Ver o comando"), a escolha de
    reiniciar logo depois, o corte da captura que roda e, se a sessão e o cofre não a têm, a senha do sudo. Fica
    aberto enquanto a ação começa (a senha recusada e a captura rodando perguntam de novo, aqui) e fecha quando ela
    segue sozinha: o cartão da página mostra o resto.

    ``comecar(senha, guardar, reiniciar_depois, mesmo_capturando) -> bool`` começa a ação."""

    def __init__(self, sistema: SistemaDaPlaca, *, janela: str, titulo: str, explicacao: str, confirmar: str,
                 comecar, diff: str = "", comando: str = "", reiniciar_depois: bool | None = None,
                 captura_rodando: bool = False, perigo: bool = False, rotulo_do_reinicio: str = "",
                 parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("dialogo_da_acao")
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.setWindowTitle(janela)
        self.sistema, self.comecar, self._texto_de_confirmar = sistema, comecar, confirmar
        self._comecou = False
        self.titulo = texto(titulo, "titulo_do_dialogo", selecionavel=False)
        fonte_do_titulo = QFont()
        fonte_do_titulo.setPixelSize(TAMANHOS["secao"])
        fonte_do_titulo.setWeight(QFont.Weight.DemiBold)
        self.titulo.setFont(fonte_do_titulo)
        self.explicacao = texto(explicacao)
        self.diff = Diff(10)
        self.diff.setPlainText(diff)
        self.diff.setVisible(bool(diff))
        self.reiniciar_depois = QCheckBox(rotulo_do_reinicio or traduzir(
            "Reiniciar a placa logo depois (o uEnv.txt só vale no próximo boot)"))
        self.reiniciar_depois.setObjectName("reiniciar_depois")
        self.reiniciar_depois.setChecked(bool(reiniciar_depois))
        self.reiniciar_depois.setVisible(reiniciar_depois is not None)
        self.reiniciar_depois.toggled.connect(self._rotular)
        self.cortar = QCheckBox(traduzir("Cortar a captura que está rodando (o que ela gravou até ali fica)"))
        self.cortar.setObjectName("cortar_a_captura")
        self.cortar.setVisible(captura_rodando)
        self.comando = TextoMono(10)
        self.comando.setPlainText(comando)
        self.comando.hide()
        self.ver = Botao(traduzir("Ver o comando"), "fantasma")
        self.ver.setObjectName("ver_o_comando")
        self.ver.setCheckable(True)
        self.ver.setVisible(bool(comando))
        self.ver.toggled.connect(self.comando.setVisible)
        self.ver.toggled.connect(lambda _l: self.adjustSize())
        self.campo_senha = QLineEdit()
        self.campo_senha.setObjectName("senha_do_sudo")
        self.campo_senha.setEchoMode(QLineEdit.EchoMode.Password)
        self.campo_senha.setPlaceholderText(traduzir("a senha do sudo na placa"))
        self.guardar = QCheckBox(traduzir("Guardar a senha no cofre do sistema"))
        self.guardar.setObjectName("guardar_senha_do_sudo")
        self.caixa_da_senha = QWidget()
        senha = QVBoxLayout(self.caixa_da_senha)
        senha.setContentsMargins(0, 0, 0, 0)
        senha.setSpacing(6)
        senha.addWidget(self.campo_senha)
        senha.addWidget(self.guardar)
        self.caixa_da_senha.hide()
        self.mensagem = texto("", "erro_do_dialogo")
        self.mensagem.hide()
        self.barra = QProgressBar()
        self.barra.setRange(0, 0)
        self.barra.setTextVisible(False)
        self.barra.setFixedHeight(6)
        self.barra.hide()
        self.cancelar = Botao(traduzir("Cancelar"), "secundario")
        self.cancelar.clicked.connect(self.reject)
        self.confirmar = Botao(confirmar, "perigo" if perigo else "primario")
        self.confirmar.setObjectName("confirmar_acao")
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
        for widget in (self.titulo, self.explicacao, self.diff, self.reiniciar_depois, self.cortar, self.comando,
                       self.caixa_da_senha, self.mensagem, self.barra):
            widget.setFixedWidth(LARGURA_DO_DIALOGO - 48)
            coluna.addWidget(widget)
        coluna.addLayout(botoes)
        self._rotular()
        sistema.acaoMudou.connect(self._mudou)

    def _rotular(self) -> None:
        if not self.reiniciar_depois.isHidden():
            self.confirmar.setText(self._texto_de_confirmar + (traduzir(" e reiniciar")
                                                               if self.reiniciar_depois.isChecked() else ""))

    def _confirmar(self) -> None:
        senha = self.campo_senha.text() if self.caixa_da_senha.isVisible() else None
        if self.caixa_da_senha.isVisible() and not senha:
            self.campo_senha.setFocus()
            return
        self.campo_senha.clear()
        self.mensagem.hide()
        mesmo = self.cortar.isVisible() and self.cortar.isChecked()
        a = self.sistema.acao
        if self._comecou and a is not None and a.esperando_o_usuario:
            self.sistema.repetir(senha, self.guardar.isChecked(), mesmo)
            return
        reiniciar = self.reiniciar_depois.isChecked() if not self.reiniciar_depois.isHidden() else None
        if not self.comecar(senha, self.guardar.isChecked(), reiniciar, mesmo):
            self.mensagem.setText(traduzir("A placa está ocupada com outra ação, ou a conexão caiu."))
            self.mensagem.show()
            return
        self._comecou = True
        self._mudou()

    def _mudou(self) -> None:
        a = self.sistema.acao
        if not self._comecou or a is None:
            return
        rodando = a.estado == "rodando"
        self.barra.setVisible(rodando)
        self.confirmar.setEnabled(not rodando)
        self.cancelar.setEnabled(not rodando)
        if rodando:
            return
        if not a.esperando_o_usuario:
            self.accept()                        # segue sozinha (ou terminou): o cartão da página mostra
            return
        if a.estado in ("precisa_da_senha", "senha_recusada"):
            self.caixa_da_senha.show()
            self.campo_senha.setFocus()
        if a.estado == "captura_rodando":
            self.cortar.show()
        self.mensagem.setText(frase(a.mensagem))
        self.mensagem.setObjectName("texto_mudo" if a.estado == "precisa_da_senha" else "erro_do_dialogo")
        repolir(self.mensagem)
        self.mensagem.show()

    def reject(self) -> None:
        a = self.sistema.acao
        if a is not None and a.estado == "rodando" and self._comecou:
            return                               # começou: espera a placa responder
        if self._comecou and a is not None and a.esperando_o_usuario:
            self.sistema.dispensar()
        super().reject()


class DialogoDaSenhaNova(DialogoDaAcao):
    """Trocar a senha do usuário da placa: a nova duas vezes (conferidas aqui: iguais, sem quebra de linha, com 6
    caracteres ou mais) e "Guardar a nova no cofre do sistema"; a de agora (a do sudo) só se a sessão e o cofre não a
    têm. A nova nunca vai numa linha de comando: pelo stdin, até o ``chpasswd``."""

    def __init__(self, sistema: SistemaDaPlaca, *, comando: str = "", parent: QWidget | None = None):
        super().__init__(sistema, janela=traduzir("Trocar a senha"), titulo=traduzir("Trocar a senha da placa"),
                         explicacao=traduzir("A senha nova vale para o SSH e para o sudo da placa, daí em diante. O "
                                             "aplicativo continua entrando pela chave dele."),
                         confirmar=traduzir("Trocar a senha"), comando=comando, comecar=self._trocar, parent=parent)
        self.setObjectName("dialogo_da_senha_nova")
        self.nova = QLineEdit()
        self.nova.setObjectName("senha_nova")
        self.nova.setEchoMode(QLineEdit.EchoMode.Password)
        self.nova.setPlaceholderText(traduzir("a senha nova"))
        self.de_novo = QLineEdit()
        self.de_novo.setObjectName("senha_nova_de_novo")
        self.de_novo.setEchoMode(QLineEdit.EchoMode.Password)
        self.de_novo.setPlaceholderText(traduzir("a senha nova, de novo"))
        self.guardar_a_nova = QCheckBox(traduzir("Guardar a senha nova no cofre do sistema"))
        self.guardar_a_nova.setObjectName("guardar_a_senha_nova")
        self.campo_senha.setPlaceholderText(traduzir("a senha de agora (a do sudo)"))
        self.guardar.hide()                       # a de agora não vai para o cofre: ela deixa de valer
        coluna = self.layout()
        indice = coluna.indexOf(self.explicacao) + 1
        for i, w in enumerate((self.nova, self.de_novo, self.guardar_a_nova)):
            w.setFixedWidth(LARGURA_DO_DIALOGO - 48)
            coluna.insertWidget(indice + i, w)
        self.de_novo.returnPressed.connect(self._confirmar)

    def _trocar(self, senha, _guardar, _reiniciar, _mesmo) -> bool:
        return self.sistema.trocar_senha(self.nova.text(), senha, self.guardar_a_nova.isChecked())

    def _confirmar(self) -> None:
        from sh_placa.sistema import conferir_a_senha_nova

        if not self._comecou or self.sistema.acao is None or not self.sistema.acao.esperando_o_usuario:
            problema = conferir_a_senha_nova(self.nova.text())
            if problema is None and self.nova.text() != self.de_novo.text():
                problema = "as duas senhas novas não são iguais"
            if problema is not None:
                self.mensagem.setText(frase(problema))
                self.mensagem.setObjectName("erro_do_dialogo")
                repolir(self.mensagem)
                self.mensagem.show()
                self.nova.setFocus()
                return
        super()._confirmar()

    def accept(self) -> None:
        self.nova.clear()
        self.de_novo.clear()
        super().accept()

    def reject(self) -> None:
        a = self.sistema.acao
        if not (a is not None and a.estado == "rodando" and self._comecou):
            self.nova.clear()
            self.de_novo.clear()
        super().reject()

