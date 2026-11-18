"""O tema na aplicação: a ``QPalette`` e a folha QSS geradas dos tokens, e a troca de tema sem reiniciar
(docs/gui-plan.md, 12.9).

* o estilo ``Fusion`` de base (igual no Windows e no Linux), com a ``QPalette`` dos tokens;
* o QSS para o que a paleta não alcança (cantos, bordas, estados, variantes de botão por ``setProperty``);
* :func:`aparencia` devolve o objeto que avisa (``mudou``) quem desenha com as cores do tema por conta própria --
  os gráficos, os componentes pintados com ``QPainter``. O mesmo aviso sai quando muda o que se escreve com o tema
  (o separador decimal, a fonte dos números: :meth:`Aparencia.avisar`), e quem mostra números os escreve de novo;
* **o movimento** (docs/gui-plan.md, 12.7): reduzido (sem animações), normal ou o do sistema
  (``QStyleHints.accessibility().motionPreference``), em :attr:`Aparencia.movimento_reduzido`.

``"sistema"`` segue o tema claro ou escuro do sistema operacional (``QStyleHints.colorScheme``); quando o sistema não
informa, vale o escuro, o da marca.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QColor, QGuiApplication, QPalette
from PySide6.QtWidgets import QApplication

from .svgs import arquivo_svg
from .tokens import TEMAS, Tema

MODOS = ("sistema", "escuro", "claro")
MOVIMENTOS = ("sistema", "reduzido", "normal")


class Aparencia(QObject):
    """O tema em uso. ``mudou(Tema)`` sai a cada troca do tema e a cada :meth:`avisar`."""

    mudou = Signal(object)

    def __init__(self, app: QApplication):
        super().__init__(app)
        self._app = app
        self.modo = "sistema"
        self.tema: Tema = TEMAS["escuro"]
        self.movimento = "sistema"

    def aplicar(self, modo: str = "sistema") -> Tema:
        """Aplica ``modo`` (``"sistema"``, ``"escuro"`` ou ``"claro"``) e devolve o tema em uso."""
        if modo not in MODOS:
            raise ValueError(f"modo de tema desconhecido: {modo!r} (use {', '.join(MODOS)})")
        self.modo = modo
        self.tema = TEMAS[modo] if modo != "sistema" else tema_do_sistema()
        self._app.setStyle("Fusion")
        self._app.setPalette(gerar_paleta(self.tema))
        self._app.setStyleSheet(gerar_qss(self.tema))
        self.mudou.emit(self.tema)
        return self.tema

    def alternar(self) -> Tema:
        """Troca entre o escuro e o claro (o atalho da barra de status)."""
        return self.aplicar("claro" if self.tema.escuro else "escuro")

    def avisar(self) -> None:
        """Avisa ``mudou`` sem trocar o tema: mudou o que se escreve com ele (o separador decimal, a fonte dos
        números), e quem desenha ou mostra números por conta própria refaz."""
        self.mudou.emit(self.tema)

    def definir_movimento(self, modo: str) -> None:
        """``"sistema"`` (o padrão: o que o sistema operacional pede), ``"reduzido"`` ou ``"normal"``."""
        if modo not in MOVIMENTOS:
            raise ValueError(f"movimento desconhecido: {modo!r} (use {', '.join(MOVIMENTOS)})")
        self.movimento = modo

    @property
    def movimento_reduzido(self) -> bool:
        """Sem animações: as mudanças são instantâneas."""
        if self.movimento != "sistema":
            return self.movimento == "reduzido"
        return movimento_reduzido_do_sistema()


def movimento_reduzido_do_sistema() -> bool:
    """O sistema pede movimento reduzido (o Qt o lê das opções de acessibilidade; sem a informação, não)."""
    dicas = QGuiApplication.styleHints()
    acessibilidade = dicas.accessibility() if dicas is not None and hasattr(dicas, "accessibility") else None
    if acessibilidade is None or not hasattr(acessibilidade, "motionPreference"):
        return False
    return acessibilidade.motionPreference() == Qt.MotionPreference.ReducedMotion


def aparencia(app: QApplication | None = None) -> Aparencia:
    """O objeto de aparência da aplicação (criado na primeira chamada)."""
    app = app or QApplication.instance()
    if app is None:
        raise RuntimeError("crie a QApplication antes de aplicar o tema")
    existente = app.findChild(Aparencia)
    return existente if existente is not None else Aparencia(app)


def tema_do_sistema() -> Tema:
    """O tema que o sistema operacional pede; o escuro quando ele não informa."""
    esquema = QGuiApplication.styleHints().colorScheme()
    return TEMAS["claro"] if esquema == Qt.ColorScheme.Light else TEMAS["escuro"]


def gerar_paleta(t: Tema) -> QPalette:
    p = QPalette()
    papeis = {
        QPalette.ColorRole.Window: t.fundo, QPalette.ColorRole.WindowText: t.texto,
        QPalette.ColorRole.Base: t.afundada, QPalette.ColorRole.AlternateBase: t.superficie,
        QPalette.ColorRole.ToolTipBase: t.elevada, QPalette.ColorRole.ToolTipText: t.texto,
        QPalette.ColorRole.PlaceholderText: t.mudo, QPalette.ColorRole.Text: t.texto,
        QPalette.ColorRole.Button: t.elevada, QPalette.ColorRole.ButtonText: t.texto,
        QPalette.ColorRole.BrightText: t.erro, QPalette.ColorRole.Highlight: t.acento,
        QPalette.ColorRole.HighlightedText: t.acento_texto, QPalette.ColorRole.Link: t.acento,
        QPalette.ColorRole.LinkVisited: t.acento, QPalette.ColorRole.Light: t.borda_forte,
        QPalette.ColorRole.Midlight: t.borda, QPalette.ColorRole.Mid: t.borda,
        QPalette.ColorRole.Dark: t.afundada, QPalette.ColorRole.Shadow: "#000000",
    }
    for papel, cor in papeis.items():
        p.setColor(papel, QColor(cor))
    for papel in (QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText, QPalette.ColorRole.WindowText):
        p.setColor(QPalette.ColorGroup.Disabled, papel, QColor(t.mudo))
    return p


def _rgba(cor: str, alfa: float) -> str:
    """``#rrggbb`` com transparência, no formato do QSS."""
    return f"rgba({int(cor[1:3], 16)}, {int(cor[3:5], 16)}, {int(cor[5:7], 16)}, {alfa:g})"


def _url(arquivo) -> str:
    """O caminho de um arquivo para o ``url()`` do QSS (com ``/`` também no Windows)."""
    return arquivo.as_posix()


def gerar_qss(t: Tema) -> str:
    """A folha de estilos do tema. Os botões aceitam ``setProperty("variante", "primario" | "fantasma" |
    "perigo")``. Sem ``font-size``: o tamanho base vem da fonte da aplicação (``fontes.fonte_da_interface``), e um
    ``font-size`` no QSS passaria por cima do ``setFont`` de cada widget. Os campos numéricos (``QSpinBox``) ficam
    sem as setas, que o estilo do sistema desenharia (12.6: nunca ícones do sistema); o valor muda pela digitação,
    pelas setas do teclado e pela roda. A seta das caixas de escolha é a do SH-Analyzer, na cor do tema (o QSS só lê
    imagens de arquivos: ``svgs.arquivo_svg``)."""
    return f"""
QWidget {{ color: {t.texto}; }}
QMainWindow, QDialog {{ background: {t.fundo}; }}
QToolTip {{ background: {t.elevada}; color: {t.texto}; border: 1px solid {t.borda_forte}; padding: 4px 8px;
            border-radius: 6px; }}
QStatusBar {{ background: {t.fundo}; color: {t.texto2}; border-top: 1px solid {t.borda}; }}
QStatusBar QLabel {{ color: {t.texto2}; padding: 0 8px; }}
QStatusBar QLabel[nivel="ok"] {{ color: {t.ok}; }}
QStatusBar QLabel[nivel="erro"] {{ color: {t.erro}; }}
QLabel#rotulo_campo, QLabel#subtitulo_inspetor {{ color: {t.texto2}; }}
QLabel#aviso_inspetor {{ color: {t.aviso}; }}
QFrame#divisoria {{ background: {t.borda}; border: none; }}
QTreeView#arvore_projeto {{ background: transparent; border: none; }}
QTreeView#arvore_projeto::item:selected, QTreeView#arvore_projeto::item:hover {{ background: transparent; }}
QScrollArea#inspetor_da_fonte {{ background: transparent; border: none; }}
QListWidget#avisos {{ border: none; background: {t.superficie}; }}
QFrame#paleta {{ background: {t.elevada}; border: 1px solid {t.borda_forte}; border-radius: 12px; }}
QListWidget#resultados_paleta {{ background: transparent; border: none; }}
QListWidget#resultados_paleta::item {{ padding: 6px 10px; border-radius: 6px; }}
QListWidget#resultados_paleta::item:selected {{ background: {_rgba(t.acento, 0.13)}; color: {t.texto}; }}
QListWidget#secoes_configuracoes {{ background: transparent; border: none; outline: 0; }}
QListWidget#secoes_configuracoes::item {{ padding: 6px 10px; border-radius: 6px; color: {t.texto2}; }}
QListWidget#secoes_configuracoes::item:hover:!selected {{ color: {t.texto}; }}
QListWidget#secoes_configuracoes::item:selected {{ background: {_rgba(t.acento, 0.13)}; color: {t.acento}; }}
QStatusBar::item {{ border: none; }}
QMenuBar {{ background: {t.fundo}; }}
QMenu {{ background: {t.elevada}; border: 1px solid {t.borda_forte}; border-radius: 8px; padding: 4px; }}
QMenu::item {{ padding: 6px 16px; border-radius: 5px; }}
QMenu::item:selected {{ background: {t.superficie}; }}
QMenu::separator {{ height: 1px; background: {t.borda}; margin: 4px 8px; }}
QPushButton, QToolButton {{ background: {t.elevada}; color: {t.texto}; border: 1px solid {t.borda};
                            border-radius: 6px; padding: 5px 12px; }}
QToolButton {{ padding: 4px; }}
QPushButton:hover, QToolButton:hover {{ border-color: {t.borda_forte}; }}
QPushButton:pressed, QToolButton:pressed, QToolButton:checked {{ background: {t.superficie}; }}
QPushButton:focus, QToolButton:focus {{ border-color: {t.acento}; }}
QPushButton:disabled, QToolButton:disabled {{ color: {t.mudo}; }}
QPushButton[variante="primario"] {{ background: {t.acento}; color: {t.acento_texto}; border-color: {t.acento};
                                    font-weight: 600; }}
QPushButton[variante="fantasma"], QToolButton[variante="fantasma"] {{ background: transparent;
                                    border-color: transparent; color: {t.texto2}; }}
QPushButton[variante="fantasma"]:hover, QToolButton[variante="fantasma"]:hover {{ background: {t.superficie}; }}
QPushButton[variante="perigo"] {{ color: {t.erro}; border-color: {t.erro}; }}
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QPlainTextEdit, QTextEdit {{
    background: {t.afundada}; color: {t.texto}; border: 1px solid {t.borda}; border-radius: 6px; padding: 4px 8px;
    selection-background-color: {t.acento}; selection-color: {t.acento_texto}; }}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus, QPlainTextEdit:focus, QTextEdit:focus {{
    border-color: {t.acento}; }}
QAbstractSpinBox::up-button, QAbstractSpinBox::down-button {{ width: 0; border: none; }}
QComboBox QAbstractItemView {{ background: {t.elevada}; border: 1px solid {t.borda_forte};
                               selection-background-color: {t.superficie}; selection-color: {t.texto}; }}
QComboBox QAbstractItemView::item {{ padding: 3px 8px; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox::down-arrow {{ image: url("{_url(arquivo_svg("baixo", t.texto2))}"); width: 12px; height: 12px; }}
QComboBox::down-arrow:disabled {{ image: url("{_url(arquivo_svg("baixo", t.mudo))}"); }}
QTabBar::tab {{ background: transparent; color: {t.texto2}; padding: 6px 12px; border: none;
               border-top-left-radius: 7px; border-top-right-radius: 7px; }}
QTabBar::tab:selected {{ background: {t.afundada}; color: {t.texto}; border-top: 2px solid {t.acento}; }}
QTabBar::tab:hover:!selected {{ color: {t.texto}; }}
QToolButton#fechar_aba {{ border: none; border-radius: 4px; background: transparent; padding: 0; }}
QToolButton#fechar_aba:hover {{ background: {t.superficie}; }}
QTabWidget::pane {{ border: 1px solid {t.borda}; top: -1px; }}
QSplitter::handle {{ background: {t.borda}; }}
QProgressBar {{ background: {t.afundada}; border: 1px solid {t.borda}; border-radius: 4px; text-align: center;
               color: {t.texto2}; }}
QProgressBar::chunk {{ background: {t.acento}; border-radius: 3px; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 0; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 0; }}
QScrollBar::handle {{ background: {t.borda_forte}; border-radius: 5px; min-height: 24px; min-width: 24px; }}
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{
    background: none; border: none; width: 0; height: 0; }}
QLineEdit[invalido="true"], QComboBox[invalido="true"], QPlainTextEdit[invalido="true"] {{ border-color: {t.erro}; }}
QComboBox QLineEdit {{ background: transparent; border: none; padding: 0; }}
QWidget#segmentado {{ background: {t.superficie}; border: 1px solid {t.borda}; border-radius: 8px; }}
QWidget#segmentado QToolButton {{ background: transparent; border: none; border-radius: 6px; color: {t.texto2};
                                  padding: 4px 12px; }}
QWidget#segmentado QToolButton:checked {{ background: {_rgba(t.acento, 0.13)}; color: {t.acento}; font-weight: 600; }}
QWidget#segmentado QToolButton:hover:!checked {{ color: {t.texto}; }}
QFrame#cartao {{ background: {t.afundada}; border: 1px solid {t.borda}; border-radius: 8px; }}
QFrame#cartao QLabel#rotulo {{ color: {t.mudo}; }}
QFrame#cartao QLabel#unidade {{ color: {t.texto2}; }}
QFrame#toast {{ background: {t.elevada}; border: 1px solid {t.borda_forte}; border-radius: 10px; }}
QFrame#toast QLabel {{ color: {t.texto}; }}
QWidget#barra_superior {{ background: {t.fundo}; border-bottom: 1px solid {t.borda}; }}
QLabel#rotulo_projeto {{ color: {t.texto2}; }}
QLabel#tarefa_na_fila {{ color: {t.mudo}; }}
QToolButton#botao_projeto {{ padding: 3px 6px; }}
QToolButton::menu-indicator {{ image: none; width: 0; }}
QPushButton#campo_paleta {{ background: {t.superficie}; color: {t.mudo}; border: 1px solid {t.borda};
                            border-radius: 7px; padding: 0 10px; text-align: left; }}
QPushButton#campo_paleta:hover {{ border-color: {t.borda_forte}; }}
QLabel#kbd {{ color: {t.mudo}; border: 1px solid {t.borda}; border-radius: 4px; padding: 0 5px; }}
QToolButton#chip_placa {{ background: {t.superficie}; color: {t.texto2}; border: 1px solid {t.borda};
                          border-radius: 13px; padding: 0 10px 0 8px; min-width: 10px; }}
QToolButton#chip_placa[estado="conectando"] {{ color: {t.acento}; border-color: {_rgba(t.acento, 0.4)};
                                              background: {_rgba(t.acento, 0.1)}; }}
QToolButton#chip_placa[estado="conectada"] {{ color: {t.ok}; border-color: {_rgba(t.ok, 0.4)};
                                             background: {_rgba(t.ok, 0.1)}; }}
QToolButton#chip_placa[estado="atencao"] {{ color: {t.aviso}; border-color: {_rgba(t.aviso, 0.4)};
                                           background: {_rgba(t.aviso, 0.1)}; }}
QToolButton#chip_placa[estado="erro"] {{ color: {t.erro}; border-color: {_rgba(t.erro, 0.4)};
                                        background: {_rgba(t.erro, 0.1)}; }}
QMainWindow::separator {{ background: {t.borda}; width: 1px; height: 1px; }}
QMainWindow::separator:hover {{ background: {t.acento}; }}
QWidget#painel, QWidget#titulo_painel {{ background: {t.superficie}; }}
QLabel#titulo_painel_texto {{ color: {t.mudo}; }}
QStackedWidget#area_central {{ background: {t.afundada}; }}
QWidget#centro_com_trilhos {{ background: {t.afundada}; }}
QWidget#trilho {{ background: {t.superficie}; }}
QWidget#trilho[lado="esquerda"] {{ border-right: 1px solid {t.borda}; }}
QWidget#trilho[lado="direita"] {{ border-left: 1px solid {t.borda}; }}
QWidget#trilho[lado="baixo"] {{ border-top: 1px solid {t.borda}; }}
QToolButton#aba_do_trilho {{ color: {t.texto2}; padding: 4px 8px; }}
QToolButton#aba_do_trilho:hover {{ color: {t.texto}; }}
QLabel#titulo_vazio {{ color: {t.texto}; }}
QLabel#texto_vazio {{ color: {t.texto2}; }}
QTabWidget#vistas::pane, QTabWidget#painel_inferior::pane {{ border: none; }}
QTabWidget#vistas > QTabBar, QTabWidget#painel_inferior > QTabBar {{ background: {t.superficie}; }}
QTabWidget#painel_inferior {{ background: {t.superficie}; }}
QTabWidget#painel_inferior > QStackedWidget {{ background: {t.superficie}; }}
QLabel#badge {{ color: {t.texto2}; background: {t.elevada}; border: 1px solid {t.borda}; border-radius: 8px;
                padding: 0 5px; }}
QLabel#badge[nivel="acento"] {{ color: {t.acento}; border-color: {_rgba(t.acento, 0.4)};
                               background: {_rgba(t.acento, 0.13)}; }}
QLabel#badge[nivel="aviso"] {{ color: {t.aviso}; border-color: {_rgba(t.aviso, 0.4)};
                              background: {_rgba(t.aviso, 0.1)}; }}
QLabel#badge[nivel="erro"] {{ color: {t.erro}; border-color: {_rgba(t.erro, 0.4)};
                             background: {_rgba(t.erro, 0.1)}; }}
QStatusBar QLabel[nivel="aviso"] {{ color: {t.aviso}; }}
QPushButton[variante="perigo"]:disabled {{ color: {t.mudo}; border-color: {t.borda}; }}
QPushButton[variante="primario"]:disabled {{ background: {t.superficie}; color: {t.mudo}; border-color: {t.borda}; }}
QWidget#area_aquisicao, QStackedWidget#secoes_aquisicao {{ background: {t.fundo}; }}
QWidget#lateral_aquisicao {{ background: {t.superficie}; border-right: 1px solid {t.borda}; }}
QFrame#cartao_da_placa {{ background: {t.afundada}; border: 1px solid {t.borda}; border-radius: 10px; }}
QFrame#cartao_da_placa[nivel="aviso"] {{ border-color: {_rgba(t.aviso, 0.5)}; }}
QFrame#cartao_da_placa[nivel="erro"] {{ border-color: {_rgba(t.erro, 0.5)}; }}
QLabel[papel="sub"] {{ color: {t.mudo}; }}
QListWidget#navegacao_aquisicao {{ background: transparent; border: none; outline: 0; }}
QListWidget#navegacao_aquisicao::item {{ padding: 0 10px; border-radius: 6px; color: {t.texto}; }}
QListWidget#navegacao_aquisicao::item:hover:!selected {{ background: {t.elevada}; }}
QListWidget#navegacao_aquisicao::item:selected {{ background: {_rgba(t.acento, 0.13)}; color: {t.acento};
                                                 font-weight: 600; }}
QListView#lista_de_placas {{ background: transparent; border: none; outline: 0; }}
QLabel#aviso_da_lista {{ color: {t.mudo}; }}
QToolButton#conectar_por_ip {{ color: {t.acento}; padding: 4px 8px; }}
QFrame#rodape_lateral {{ border-top: 1px solid {t.borda}; }}
QFrame#indicador {{ background: {t.superficie}; border: 1px solid {t.borda}; border-radius: 10px; }}
QLabel#rotulo_do_indicador {{ color: {t.mudo}; }}
QLabel#detalhe_do_indicador, QLabel#subtitulo_da_secao {{ color: {t.texto2}; }}
QLabel#valor_do_indicador[nivel="aviso"] {{ color: {t.aviso}; }}
QLabel#valor_do_indicador[nivel="ok"] {{ color: {t.ok}; }}
QLabel#texto_mudo {{ color: {t.mudo}; }}
QLabel#erro_do_dialogo {{ color: {t.erro}; }}
QFrame#bloco_mono {{ background: {t.afundada}; border: 1px solid {t.borda}; border-radius: 6px; }}
QFrame#pergunta_do_relogio {{ background: {t.superficie}; border: 1px solid {t.borda}; border-radius: 10px; }}
QFrame#painel_da_placa, QFrame#item_do_diagnostico {{ background: {t.superficie}; border: 1px solid {t.borda};
                                                     border-radius: 10px; }}
QLabel#titulo_do_painel_da_placa {{ color: {t.texto}; }}
QLabel#conferida_em, QLabel#pasta_das_capturas, QLabel#resumo_da_linha {{ color: {t.mudo}; }}
QLabel#resumo_do_item {{ color: {t.texto2}; }}
QLabel#problema_erro {{ color: {t.erro}; }}
QLabel#problema_aviso {{ color: {t.aviso}; }}
QLabel#problema_info {{ color: {t.texto2}; }}
QWidget#linha_da_saude {{ border-top: 1px solid {t.borda}; }}
QFrame#linha_da_fila {{ border-top: 1px solid {t.borda}; }}
QTableWidget#arquivos_da_placa {{ border: 1px solid {t.borda}; border-radius: 8px; }}
QTableWidget#arquivos_da_placa::item {{ padding: 2px 8px; }}
QTableWidget#arquivos_da_placa::item:selected {{ background: {_rgba(t.acento, 0.15)}; color: {t.texto}; }}
QListWidget#lista_de_coletas, QTableWidget#resumo_da_coleta {{ border: 1px solid {t.borda}; border-radius: 6px; }}
QLabel#icone_do_nivel {{ border-radius: 6px; background: {_rgba(t.ok, 0.12)}; }}
QLabel#icone_do_nivel[nivel="info"] {{ background: {_rgba(t.acento, 0.12)}; }}
QLabel#icone_do_nivel[nivel="aviso"] {{ background: {_rgba(t.aviso, 0.12)}; }}
QLabel#icone_do_nivel[nivel="erro"] {{ background: {_rgba(t.erro, 0.12)}; }}
QLabel#badge[nivel="ok"] {{ color: {t.ok}; border-color: {_rgba(t.ok, 0.4)}; background: {_rgba(t.ok, 0.1)}; }}
QProgressBar#barra_de_uso {{ border: none; border-radius: 3px; background: {t.afundada}; }}
QProgressBar#barra_de_uso::chunk {{ border-radius: 3px; background: {t.acento}; }}
QProgressBar#barra_de_uso[nivel="aviso"]::chunk {{ background: {t.aviso}; }}
QListWidget#atividade, QTableWidget#capturas_na_placa {{ background: transparent; border: none;
                                                       border-top: 1px solid {t.borda}; }}
QListWidget#atividade {{ color: {t.texto2}; padding: 4px 8px; }}
QTableWidget#capturas_na_placa::item {{ padding: 2px 8px; }}
QWidget#conteudo_do_diagnostico {{ background: {t.fundo}; }}
QWidget#formulario_da_captura, QWidget#conteudo_do_formulario {{ background: {t.superficie}; }}
QWidget#formulario_da_captura {{ border-right: 1px solid {t.borda}; }}
QScrollArea#rolagem_do_formulario, QScrollArea#rolagem_da_captura {{ background: transparent; border: none; }}
QFrame#secao_do_formulario {{ border-bottom: 1px solid {t.borda}; }}
QLabel#titulo_do_formulario {{ color: {t.mudo}; }}
QLabel#rotulo_do_campo {{ color: {t.texto2}; }}
QWidget#centro_da_captura {{ background: {t.fundo}; }}
QTabWidget#abas_do_terminal::pane {{ border: 1px solid {t.borda}; border-radius: 0 0 8px 8px; top: -1px;
                                     background: {t.afundada}; }}
QAbstractScrollArea#terminal {{ background: {t.afundada}; border: none; }}
QFrame#busca_do_terminal {{ background: {t.superficie}; border-top: 1px solid {t.borda}; }}
QFrame#aviso_do_terminal {{ background: {t.superficie}; border-top: 1px solid {t.borda}; color: {t.texto2}; }}
QFrame#aviso_do_terminal[nivel="aviso"] {{ background: {_rgba(t.aviso, 0.08)}; border-top-color: {_rgba(t.aviso, 0.5)}; }}
QPushButton#atalho_do_terminal {{ background: transparent; border: none; border-top: 1px solid {t.borda};
                                  border-radius: 0; text-align: left; }}
QPushButton#atalho_do_terminal:hover {{ background: {_rgba(t.acento, 0.08)}; }}
QPushButton#atalho_do_terminal:focus {{ background: {_rgba(t.acento, 0.12)}; }}
QPushButton#atalho_do_terminal QLabel {{ color: {t.texto}; }}
QPushButton#atalho_do_terminal QLabel#comando_do_atalho {{ color: {t.texto2}; }}
QPushButton#atalho_do_terminal QLabel:disabled {{ color: {t.mudo}; }}
QScrollArea#rolagem_do_diagnostico {{ background: {t.fundo}; border: none; }}
QHeaderView::section {{ background: {t.superficie}; color: {t.mudo}; border: none;
                        border-bottom: 1px solid {t.borda}; padding: 6px 10px; font-weight: 600; }}
QTableView, QTreeView, QListView {{ background: {t.superficie}; alternate-background-color: {t.fundo};
    border: 1px solid {t.borda}; selection-background-color: {t.superficie}; selection-color: {t.texto}; }}
QTreeView::item:selected, QListView::item:selected, QTableView::item:selected {{
    background: {t.elevada}; color: {t.texto}; }}
"""
