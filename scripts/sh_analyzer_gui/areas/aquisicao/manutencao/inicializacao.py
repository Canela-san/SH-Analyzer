"""A página Inicialização da Manutenção (a F6.4): o ``/boot/uEnv.txt`` da placa e o que este boot carregou; as
mudanças que a PRU precisa, marcáveis (as necessárias marcadas, a opcional do vídeo desmarcada), com o diff ao vivo;
"Gravar…" (o diálogo confirma, com o diff, o comando, o reiniciar logo depois e o sudo); o que já está gravado e
espera um reinício; as cópias que o assistente fez, com "Restaurar…" (o diff da cópia contra o de agora, antes). Um
``uEnv.txt`` que o assistente não reconhece não é tocado: a página diz por quê.
"""

from __future__ import annotations

import re
import time

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QCheckBox, QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget
from sh_placa import uenv

from ....componentes.basicos import Botao
from ....componentes.numeros import formatar_bytes
from ....servicos.sistema_da_placa import SistemaDaPlaca
from ..pecas import fonte
from ..textos import frase, traduzir
from .comuns import CartaoDaAcao, Diff, TextoMono, cartao, coluna_central, fato, texto

CARIMBO = re.compile(r"(\d{8})-(\d{6})$")


def quando_da_copia(nome: str) -> str:
    """"19/11/2026 18:38": a data no nome da cópia (a deste computador, quando ela foi feita)."""
    m = CARIMBO.search(nome)
    if m is None:
        return ""
    try:
        return time.strftime("%d/%m/%Y %H:%M", time.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S"))
    except ValueError:
        return ""


class LinhaDaMudanca(QWidget):
    """Uma mudança proposta: a caixa (com o título) e o porquê, embaixo."""

    def __init__(self, mudanca, parent: QWidget | None = None):
        super().__init__(parent)
        self.mudanca = mudanca
        self.caixa = QCheckBox(traduzir(mudanca.titulo))
        self.caixa.setObjectName(f"mudanca_{mudanca.nome}")
        self.caixa.setChecked(mudanca.necessaria)
        porque = texto(traduzir(mudanca.porque) + ("" if mudanca.necessaria else ""), "texto_mudo")
        porque.setFont(fonte("secundario"))
        porque.setContentsMargins(26, 0, 0, 0)
        coluna = QVBoxLayout(self)
        coluna.setContentsMargins(0, 2, 0, 2)
        coluna.setSpacing(0)
        coluna.addWidget(self.caixa)
        coluna.addWidget(porque)


class LinhaDaCopiaDoUenv(QFrame):
    restaurar = Signal(str)

    def __init__(self, copia: dict, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("linha_da_copia")
        self.nome = copia["nome"]
        titulo = QLabel(quando_da_copia(self.nome) or self.nome)
        titulo.setFont(fonte("corpo", QFont.Weight.DemiBold))
        detalhe = texto(f"/boot/{self.nome} · {formatar_bytes(copia.get('bytes') or 0)}", "texto_mudo")
        detalhe.setFont(fonte("secundario"))
        self.botao = Botao(traduzir("Restaurar…"), "secundario")
        self.botao.setObjectName(f"restaurar_{self.nome}")
        self.botao.clicked.connect(lambda: self.restaurar.emit(self.nome))
        linha = QHBoxLayout(self)
        linha.setContentsMargins(0, 4, 0, 4)
        textos = QVBoxLayout()
        textos.setSpacing(0)
        textos.addWidget(titulo)
        textos.addWidget(detalhe)
        linha.addLayout(textos, 1)
        linha.addWidget(self.botao)


class PaginaDaInicializacao(QWidget):
    """A página Inicialização. ``confirmar(tipo, argumento)`` pede à seção o diálogo: ``("gravar_uenv", nomes)``,
    ``("restaurar_uenv", (nome, texto))`` ou ``("reiniciar", None)``."""

    confirmar = Signal(str, object)

    def __init__(self, sistema: SistemaDaPlaca, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("pagina_da_inicializacao")
        self.sistema = sistema
        self.titulo = QLabel(traduzir("Inicialização"))
        self.titulo.setFont(fonte("tela", QFont.Weight.DemiBold))
        self.subtitulo = texto("", "subtitulo_da_secao")
        self.ler_de_novo = Botao(traduzir("Ler de novo"), "secundario", "girar")
        self.ler_de_novo.setObjectName("ler_a_inicializacao_de_novo")
        self.ler_de_novo.clicked.connect(sistema.ler)
        cabecalho = QHBoxLayout()
        textos = QVBoxLayout()
        textos.setSpacing(2)
        textos.addWidget(self.titulo)
        textos.addWidget(self.subtitulo)
        cabecalho.addLayout(textos, 1)
        cabecalho.addWidget(self.ler_de_novo, 0, Qt.AlignmentFlag.AlignTop)

        self.cartao_da_acao = CartaoDaAcao(sistema, ("gravar_uenv", "restaurar_uenv"))

        # o que falta reiniciar
        self.cartao_pendente, pendente = cartao(traduzir("Gravado, esperando um reinício"), "cartao_pendente")
        self.pendente = texto("", "resumo_do_item")
        self.reiniciar = Botao(traduzir("Reiniciar a placa…"), "secundario", "energia")
        self.reiniciar.setObjectName("reiniciar_pela_inicializacao")
        self.reiniciar.clicked.connect(lambda: self.confirmar.emit("reiniciar", None))
        pendente.addWidget(self.pendente)
        linha = QHBoxLayout()
        linha.addWidget(self.reiniciar)
        linha.addStretch(1)
        pendente.addLayout(linha)
        self.cartao_pendente.hide()

        # o uEnv.txt: as mudanças, o diff, gravar
        self.cartao_do_uenv, corpo = cartao(traduzir("O /boot/uEnv.txt"))
        self.situacao = texto("", "resumo_do_item")
        self.estranho = texto("", "problema_aviso")
        self.estranho.hide()
        corpo.addWidget(self.situacao)
        corpo.addWidget(self.estranho)
        self.caixa_das_mudancas = QVBoxLayout()
        self.caixa_das_mudancas.setSpacing(4)
        corpo.addLayout(self.caixa_das_mudancas)
        self.linhas_das_mudancas: dict[str, LinhaDaMudanca] = {}
        self.diff = Diff(9)
        self.diff.hide()
        corpo.addWidget(self.diff)
        self.arquivo = TextoMono(14)
        self.arquivo.setObjectName("uenv_inteiro")
        self.arquivo.hide()
        corpo.addWidget(self.arquivo)
        self.gravar = Botao(traduzir("Gravar…"), "primario")
        self.gravar.setObjectName("gravar_o_uenv")
        self.gravar.clicked.connect(self._gravar)
        self.ver_o_arquivo = Botao(traduzir("Ver o arquivo inteiro"), "fantasma")
        self.ver_o_arquivo.setObjectName("ver_o_uenv")
        self.ver_o_arquivo.setCheckable(True)
        self.ver_o_arquivo.toggled.connect(self.arquivo.setVisible)
        acoes = QHBoxLayout()
        acoes.setContentsMargins(0, 6, 0, 0)
        acoes.addWidget(self.gravar)
        acoes.addStretch(1)
        acoes.addWidget(self.ver_o_arquivo)
        corpo.addLayout(acoes)

        # este boot
        self.cartao_do_boot, self.corpo_do_boot = cartao(traduzir("Este boot"))
        self.fatos_do_boot: list[QWidget] = []

        # as cópias
        self.cartao_das_copias, self.corpo_das_copias = cartao(traduzir("Cópias que o assistente fez"))
        self.sem_copias = texto(traduzir("Nenhuma ainda: cada gravação guarda o uEnv.txt de antes em "
                                         "/boot/uEnv.txt.sh-analyzer-<data>."), "texto_mudo")
        self.corpo_das_copias.addWidget(self.sem_copias)
        self.linhas_das_copias: list[LinhaDaCopiaDoUenv] = []

        conteudo = QWidget()
        coluna = QVBoxLayout(conteudo)
        coluna.setContentsMargins(24, 20, 24, 20)
        coluna.setSpacing(14)
        coluna.addLayout(cabecalho)
        for w in (self.cartao_da_acao, self.cartao_pendente, self.cartao_do_uenv, self.cartao_do_boot,
                  self.cartao_das_copias):
            coluna.addWidget(w)
        coluna.addStretch(1)
        fora = QVBoxLayout(self)
        fora.setContentsMargins(0, 0, 0, 0)
        fora.addWidget(coluna_central(conteudo, "rolagem_da_inicializacao"))
        sistema.mudou.connect(self.atualizar)
        sistema.acaoMudou.connect(self._acao_mudou)
        sistema.copiaLida.connect(lambda nome, texto_: self.confirmar.emit("restaurar_uenv", (nome, texto_)))
        self.atualizar()

    # ------------------------------------------------------------------ preencher

    def atualizar(self) -> None:
        s = self.sistema
        i = s.inicializacao
        self.ler_de_novo.setEnabled(not s.lendo)
        if i is None:
            self.subtitulo.setText(traduzir("Lendo a inicialização da placa…") if s.lendo else frase(s.erro))
            for w in (self.cartao_pendente, self.cartao_do_uenv, self.cartao_do_boot, self.cartao_das_copias):
                w.hide()
            return
        self.subtitulo.setText(traduzir(
            "O que o u-boot carrega antes do Linux: os overlays (a PRU, o HDMI) e a memória reservada aos buffers. "
            "Muda só no próximo boot.") + (" " + frase(s.erro) if s.erro else ""))
        for w in (self.cartao_do_uenv, self.cartao_do_boot, self.cartao_das_copias):
            w.show()
        self._boot(i)
        self._uenv()
        self._pendente(i)
        self._copias(s.copias_do_uenv)

    def _boot(self, i: dict) -> None:
        for w in self.fatos_do_boot:
            w.hide()
            w.deleteLater()
        cmdline = i.get("cmdline") or ""
        overlays = i.get("overlays")
        u = {}
        try:
            u = uenv.chaves(uenv.ler_o_uenv(self.sistema.texto_do_uenv or ""))
        except uenv.UenvEstranho:
            pass
        pru = u.get("uboot_overlay_pru")
        fatos = [
            (traduzir("Kernel"), i.get("kernel") or "", False),
            (traduzir("Linha do kernel"), cmdline, True),
            (traduzir("Overlays aplicados"), ", ".join(overlays) if overlays else
             traduzir("nenhum (o u-boot não aplicou overlay)") if overlays is not None else traduzir("não deu para ler"),
             False),
            (traduzir("Overlay da PRU no uEnv.txt"), pru.rsplit("/", 1)[-1] if pru else traduzir("nenhum"), False),
            (traduzir(".dtbo da PRU nesta placa"), ", ".join(i.get("dtbos_da_pru") or []) or traduzir("nenhum"),
             False),
            (traduzir("Memória dos buffers"), traduzir("reservada (mem=496M neste boot)") if uenv.MEM in cmdline.split()
             else traduzir("não reservada neste boot (sem mem=496M)"), False),
        ]
        self.fatos_do_boot = [fato(nome, valor, mono) for nome, valor, mono in fatos]
        for w in self.fatos_do_boot:
            self.corpo_do_boot.addWidget(w)

    def _uenv(self) -> None:
        s = self.sistema
        texto_ = s.texto_do_uenv or ""
        if texto_ != self.arquivo.toPlainText():
            self.arquivo.setPlainText(texto_)
        for linha in self.linhas_das_mudancas.values():
            linha.hide()
            linha.deleteLater()
        self.linhas_das_mudancas = {}
        self.estranho.setVisible(bool(s.uenv_estranho))
        if s.uenv_estranho:
            self.situacao.setText(traduzir("O assistente não mexe neste arquivo."))
            self.estranho.setText(frase(s.uenv_estranho) + " " + traduzir(
                "Mexer num uEnv.txt que ele não entende poderia deixar a placa sem boot: edite-o pelo Terminal, se "
                "precisar."))
            self._diff()
            return
        necessarias = [m for m in s.propostas if m.necessaria]
        if not s.propostas:
            self.situacao.setText(traduzir("Nada a mudar: o uEnv.txt já tem o que a PRU precisa."))
        elif not necessarias:
            self.situacao.setText(traduzir("O uEnv.txt já tem o que a PRU precisa. Há uma mudança opcional:"))
        else:
            self.situacao.setText(traduzir("A PRU precisa de {} mudança(s) no uEnv.txt (cada uma mexe numa linha "
                                           "só; o resto fica como está):").format(len(necessarias)))
        for m in s.propostas:
            linha = LinhaDaMudanca(m)
            linha.caixa.toggled.connect(lambda _l: self._diff())
            self.caixa_das_mudancas.addWidget(linha)
            self.linhas_das_mudancas[m.nome] = linha
        self._diff()

    def marcadas(self) -> list[str]:
        return [nome for nome, linha in self.linhas_das_mudancas.items() if linha.caixa.isChecked()]

    def _diff(self) -> None:
        s = self.sistema
        novo = s.novo_uenv(self.marcadas()) if not s.uenv_estranho else None
        antes = s.texto_do_uenv
        diff = uenv.diff(antes, novo) if novo is not None and antes is not None and novo != antes else ""
        if diff != self.diff.toPlainText():
            self.diff.setPlainText(diff)
        self.diff.setVisible(bool(diff))
        self.gravar.setVisible(bool(s.propostas) and not s.uenv_estranho)
        self.gravar.setEnabled(bool(diff) and not s.ocupado and self.sistema.conexao.estado == "conectada")

    def _pendente(self, i: dict) -> None:
        faltam = uenv.pendentes(i)
        ocupado = self.sistema.ocupado
        self.cartao_pendente.setVisible(bool(faltam) and not ocupado)
        self.pendente.setText(traduzir("O uEnv.txt já pede {}, mas este boot ainda não tem: vale depois de "
                                       "reiniciar.").format(", ".join(faltam)))
        self.reiniciar.setEnabled(not ocupado)

    def _copias(self, copias: list[dict]) -> None:
        for linha in self.linhas_das_copias:
            linha.hide()
            linha.deleteLater()
        self.linhas_das_copias = []
        for copia in copias:
            linha = LinhaDaCopiaDoUenv(copia)
            linha.botao.setEnabled(not self.sistema.ocupado)
            linha.restaurar.connect(self.sistema.ler_copia)
            self.corpo_das_copias.addWidget(linha)
            self.linhas_das_copias.append(linha)
        self.sem_copias.setVisible(not copias)

    def _acao_mudou(self) -> None:
        if self.sistema.inicializacao is not None:
            self._diff()
            self._pendente(self.sistema.inicializacao)
            for linha in self.linhas_das_copias:
                linha.botao.setEnabled(not self.sistema.ocupado)

    def _gravar(self) -> None:
        self.confirmar.emit("gravar_uenv", self.marcadas())
