"""O diagnóstico da placa item a item (docs/gui-plan.md, 11.9; a F3.6): cada linha da tabela 11.9 com o nível, o que
foi lido, os problemas com a correção sugerida e, nos dois corrigíveis daqui, o "Corrigir" e o "Ver o comando" (o que
vai rodar na placa, exatamente). O relatório em Markdown, para copiar ou salvar, é o registro do estado da placa antes
de um ensaio (a Fase 4 o põe no caderno).

Só lê: nada roda daqui sem passar pelo diálogo da correção, que a área abre (``corrigir(nome)``).
"""

from __future__ import annotations

import time

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QGuiApplication
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)
from sh_placa.diagnostico import ItemDoDiagnostico, relatorio

from ...componentes.basicos import Botao
from ...componentes.painel import EstadoVazio
from ...componentes.toast import Toast
from ...servicos.conexao_da_placa import ConexaoDaPlaca
from ...servicos.saude_da_placa import SaudeDaPlaca
from .entradas_do_caderno import frase_do_relatorio
from .itens import TEXTOS_DAS_CORRECOES, comando_da_correcao, itens_da_placa, resumo_da_conexao
from .pecas import BlocoDeComando, IconeDoNivel, Selo, fonte
from .textos import frase, nome_da_placa, traduzir

LARGURA_MAXIMA = 920


class CartaoDoItem(QFrame):
    """Um item do diagnóstico: o ícone e o título com o selo, o que foi lido, os problemas e, se couber, o
    "Corrigir" e o "Ver o comando"."""

    def __init__(self, item: ItemDoDiagnostico, saude: SaudeDaPlaca, ao_corrigir, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("item_do_diagnostico")
        self.item = item
        titulo = QLabel(item.titulo)
        titulo.setFont(fonte("corpo", QFont.Weight.DemiBold))
        resumo = QLabel(item.resumo)
        resumo.setObjectName("resumo_do_item")
        resumo.setWordWrap(True)
        resumo.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        topo = QHBoxLayout()
        topo.setSpacing(10)
        topo.addWidget(IconeDoNivel(item.nivel), 0, Qt.AlignmentFlag.AlignTop)
        textos = QVBoxLayout()
        textos.setSpacing(2)
        linha_do_titulo = QHBoxLayout()
        linha_do_titulo.setSpacing(8)
        linha_do_titulo.addWidget(titulo)
        linha_do_titulo.addWidget(Selo(item.nivel))
        linha_do_titulo.addStretch(1)
        textos.addLayout(linha_do_titulo)
        textos.addWidget(resumo)
        for problema in item.problemas:
            texto = QLabel(problema.texto)
            texto.setObjectName(f"problema_{problema.nivel}")
            texto.setWordWrap(True)
            texto.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            textos.addWidget(texto)
            if problema.correcao:
                correcao = QLabel(traduzir("Correção: {}").format(problema.correcao))
                correcao.setObjectName("texto_mudo")
                correcao.setFont(fonte("secundario"))
                correcao.setWordWrap(True)
                correcao.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
                textos.addWidget(correcao)
        topo.addLayout(textos, 1)
        coluna = QVBoxLayout(self)
        coluna.setContentsMargins(14, 12, 14, 12)
        coluna.setSpacing(8)
        coluna.addLayout(topo)
        self.comando: BlocoDeComando | None = None
        if item.correcao is not None:
            comando = comando_da_correcao(item.correcao, saude)
            self.comando = BlocoDeComando(comando)
            self.comando.hide()
            ver = Botao(traduzir("Ver o comando"), "fantasma")
            ver.setObjectName(f"ver_o_comando_{item.correcao}")
            ver.setCheckable(True)
            ver.toggled.connect(self.comando.setVisible)
            corrigir = Botao(traduzir(TEXTOS_DAS_CORRECOES[item.correcao]), "secundario")
            corrigir.setObjectName(f"corrigir_{item.correcao}")
            corrigir.clicked.connect(lambda: ao_corrigir(item.correcao))
            acoes = QHBoxLayout()
            acoes.setContentsMargins(36, 0, 0, 0)
            acoes.addWidget(corrigir)
            acoes.addWidget(ver)
            acoes.addStretch(1)
            coluna.addLayout(acoes)
            coluna.addWidget(self.comando)


class Diagnostico(QWidget):
    """A seção "Diagnóstico". ``corrigir(nome)`` vai para a área, que confirma e roda. ``dialogos_de()`` dá quem
    pergunta onde salvar o relatório (o ``controle.dialogos`` da janela, lido na hora: os testes o trocam por
    respostas prontas)."""

    corrigir = Signal(str)

    def __init__(self, conexao: ConexaoDaPlaca, saude: SaudeDaPlaca, dialogos_de=None, caderno=None,
                 parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("diagnostico")
        self.conexao, self.saude, self.dialogos_de, self.caderno = conexao, saude, dialogos_de, caderno
        self.paginas = QStackedWidget()
        self.vazio = EstadoVazio(traduzir("Nenhuma placa conectada"),
                                 traduzir("O diagnóstico confere a placa conectada: o relógio, o firmware, a PRU, a "
                                          "memória dos buffers, os pinos, os overlays, o cartão e o sistema."),
                                 icone_nome="escudo", largura_do_texto=440)
        self.paginas.addWidget(self.vazio)
        self.paginas.addWidget(self._criar_conectada())
        coluna = QVBoxLayout(self)
        coluna.setContentsMargins(0, 0, 0, 0)
        coluna.addWidget(self.paginas)
        conexao.mudou.connect(self.atualizar)
        saude.mudou.connect(self.atualizar)
        self.atualizar()

    def _criar_conectada(self) -> QWidget:
        self.titulo = QLabel(traduzir("Diagnóstico"))
        self.titulo.setFont(fonte("tela", QFont.Weight.DemiBold))
        self.subtitulo = QLabel()
        self.subtitulo.setObjectName("subtitulo_da_secao")
        self.subtitulo.setWordWrap(True)
        self.conferir = Botao(traduzir("Conferir de novo"), "secundario", "girar")
        self.conferir.setObjectName("conferir_diagnostico")
        self.conferir.clicked.connect(self.saude.conferir)
        self.copiar = Botao(traduzir("Copiar o relatório"), "secundario", "copiar")
        self.copiar.setObjectName("copiar_relatorio")
        self.copiar.clicked.connect(self.copiar_relatorio)
        self.salvar = Botao(traduzir("Salvar o relatório…"), "secundario", "baixar")
        self.salvar.setObjectName("salvar_relatorio")
        self.salvar.clicked.connect(self.salvar_relatorio)
        self.para_o_caderno = Botao(traduzir("Para o caderno"), "secundario", "livro")
        self.para_o_caderno.setObjectName("relatorio_para_o_caderno")
        self.para_o_caderno.setToolTip(traduzir("O relatório numa entrada do caderno de bancada da sessão"))
        self.para_o_caderno.clicked.connect(self.relatorio_para_o_caderno)
        self.para_o_caderno.setVisible(self.caderno is not None)
        cabecalho = QHBoxLayout()
        textos = QVBoxLayout()
        textos.setSpacing(2)
        textos.addWidget(self.titulo)
        textos.addWidget(self.subtitulo)
        cabecalho.addLayout(textos, 1)
        for botao in (self.conferir, self.copiar, self.para_o_caderno, self.salvar):
            cabecalho.addWidget(botao, 0, Qt.AlignmentFlag.AlignTop)
        self.cartoes: dict[str, CartaoDoItem] = {}         # os itens de agora, pela chave
        self.lista = QVBoxLayout()
        self.lista.setSpacing(10)
        conteudo = QWidget()
        conteudo.setObjectName("conteudo_do_diagnostico")
        conteudo.setMaximumWidth(LARGURA_MAXIMA)
        coluna = QVBoxLayout(conteudo)
        coluna.setContentsMargins(24, 20, 24, 20)
        coluna.setSpacing(16)
        coluna.addLayout(cabecalho)
        coluna.addLayout(self.lista)
        coluna.addStretch(1)
        centro = QWidget()                                 # a coluna no meio, como um documento
        centro.setObjectName("conteudo_do_diagnostico")
        linha = QHBoxLayout(centro)
        linha.setContentsMargins(0, 0, 0, 0)
        linha.addStretch(1)
        linha.addWidget(conteudo, 100)
        linha.addStretch(1)
        rolagem = QScrollArea()
        rolagem.setObjectName("rolagem_do_diagnostico")
        rolagem.setWidgetResizable(True)
        rolagem.setFrameShape(QFrame.Shape.NoFrame)
        rolagem.setWidget(centro)
        return rolagem

    def atualizar(self) -> None:
        if self.conexao.estado not in ("conectada", "reconectando") or self.saude.saude is None:
            self.paginas.setCurrentIndex(0)
            return
        self.paginas.setCurrentIndex(1)
        s = self.saude
        itens = itens_da_placa(self.conexao, s)
        erros = sum(1 for i in itens for p in i.problemas if p.nivel == "erro")
        avisos = sum(1 for i in itens for p in i.problemas if p.nivel == "aviso")
        if erros:
            resumo = traduzir("Não está pronta para capturar: {} erro(s) e {} aviso(s).").format(erros, avisos)
        else:
            resumo = traduzir("Pronta para capturar") + (traduzir(", com {} aviso(s).").format(avisos) if avisos
                                                         else ".")
        quando = time.strftime("%H:%M:%S", time.localtime(s.conferida_em)) if s.conferida_em else "—"
        self.subtitulo.setText(f"{nome_da_placa(self.conexao)} · {resumo} " +
                               traduzir("Conferida às {}.").format(quando) +
                               (" " + traduzir("A última conferência falhou: {}").format(frase(s.erro)) if s.erro
                                else ""))
        self.conferir.setEnabled(not s.conferindo and self.conexao.estado == "conectada")
        while self.lista.count():
            widget = self.lista.takeAt(0).widget()
            if widget is not None:
                widget.hide()                          # já fora da tela; o Qt o apaga na volta do laço
                widget.deleteLater()
        self.cartoes = {}
        for item in itens:
            self.cartoes[item.chave] = CartaoDoItem(item, s, self.corrigir.emit)
            self.lista.addWidget(self.cartoes[item.chave])

    # ------------------------------------------------------------------ o relatório

    def relatorio(self) -> str:
        e = self.saude.saude
        if e is None:
            return ""
        app = QApplication.instance()
        aplicativo = f"{app.applicationName() or 'SH-Analyzer'} {app.applicationVersion() or 'dev'}"
        return relatorio(e, self.saude.firmware_do_aplicativo, conexao=resumo_da_conexao(self.conexao),
                         registro=self.conexao.registro.entradas, agora=self.saude.conferida_em,
                         aplicativo=aplicativo)

    def copiar_relatorio(self) -> None:
        QGuiApplication.clipboard().setText(self.relatorio())
        Toast.mostrar(self.window(), traduzir("O relatório do diagnóstico foi copiado (Markdown)."), "sucesso")

    def relatorio_para_o_caderno(self) -> None:
        """O relatório numa entrada do caderno (o plano, 11.9: o estado da placa antes de um ensaio)."""
        texto = self.relatorio()
        if self.caderno is None or not texto:
            return
        if self.caderno.registrar(frase_do_relatorio(texto)):
            Toast.mostrar(self.window(), traduzir("O relatório do diagnóstico foi para o caderno de bancada."),
                          "sucesso")
        else:
            Toast.mostrar(self.window(), self.caderno.erro, "erro")

    def salvar_relatorio(self) -> None:
        if self.dialogos_de is None:
            return
        e = self.saude.saude
        sugestao = f"diagnostico_{e.serie or 'placa'}_{time.strftime('%Y-%m-%d_%H%M')}.md" if e is not None else ""
        caminho = self.dialogos_de().salvar_arquivo(traduzir("Salvar o relatório do diagnóstico"),
                                               traduzir("Markdown (*.md)"), sugestao)
        if caminho is None:
            return
        try:
            caminho.write_text(self.relatorio(), encoding="utf-8")
        except OSError as erro:
            Toast.mostrar(self.window(), traduzir("O relatório não foi salvo: {}").format(erro.strerror or erro), "erro")
            return
        Toast.mostrar(self.window(), traduzir("Relatório salvo em {}.").format(caminho.name), "sucesso")
