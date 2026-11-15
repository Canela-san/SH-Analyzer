"""A tela de configurações (docs/gui-plan.md, GE-05): as seções à esquerda (Aparência, Números, Unidades, Pastas,
Cache) e a página de cada uma à direita. Cada mudança vale na hora e fica gravada (``preferencias.py``): não há "Aplicar" nem
"Cancelar".

Abre pelo botão de ajustes da barra superior, por Ctrl+, e pela paleta de comandos. É uma janela só por janela
principal (:meth:`JanelaPrincipal.abrir_configuracoes`), não modal: dá para ver o efeito de uma mudança no gráfico
com ela aberta.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QSpinBox,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .. import preferencias
from ..componentes.basicos import Botao, Segmentado
from ..componentes.numeros import formatar_bytes, formatar_duracao, formatar_si
from ..componentes.toast import Toast
from ..dados import unidades
from ..graficos.faixa import prefixos_nos_eixos
from ..tema.aplicar import MODOS, MOVIMENTOS, aparencia
from ..tema.fontes import familias_disponiveis, fonte_escolhida
from ..tema.icones import icone
from ..tema.tokens import TAMANHOS

GIB = 1024**3
LIMITE_MAXIMO_GIB = 4096


def _dica(texto: str) -> QLabel:
    """O texto que explica uma configuração, embaixo dela, na cor secundária."""
    rotulo = QLabel(texto)
    rotulo.setObjectName("subtitulo_inspetor")
    rotulo.setWordWrap(True)
    return rotulo


class DialogoDeConfiguracoes(QDialog):
    """``janela``: a ``JanelaPrincipal`` (os serviços do cache e as perguntas ao usuário)."""

    SECOES = ("aparencia", "numeros", "unidades", "pastas", "cache")

    def __init__(self, janela):
        super().__init__(janela)
        self.janela = janela
        self.setObjectName("dialogo_configuracoes")
        self.setWindowTitle(self.tr("Configurações"))
        self.resize(760, 520)

        self.secoes = QListWidget()
        self.secoes.setObjectName("secoes_configuracoes")
        self.secoes.setIconSize(QSize(16, 16))
        self.paginas = QStackedWidget()
        paginas = {"aparencia": (self.tr("Aparência"), "sol", self._pagina_aparencia()),
                   "numeros": (self.tr("Números"), "regua", self._pagina_numeros()),
                   "unidades": (self.tr("Unidades"), "chip", self._pagina_unidades()),
                   "pastas": (self.tr("Pastas"), "pasta", self._pagina_pastas()),
                   "cache": (self.tr("Cache"), "disco", self._pagina_cache())}
        self._icones: list[tuple[QListWidgetItem, str]] = []
        for nome in self.SECOES:
            titulo, nome_do_icone, pagina = paginas[nome]
            item = QListWidgetItem(titulo)
            item.setData(Qt.ItemDataRole.UserRole, nome)
            self.secoes.addItem(item)
            self._icones.append((item, nome_do_icone))
            self.paginas.addWidget(pagina)
        self.secoes.currentRowChanged.connect(self.paginas.setCurrentIndex)
        self.secoes.currentRowChanged.connect(self._pagina_mudou)

        fechar = Botao(self.tr("Fechar"), "secundario")
        fechar.setObjectName("fechar_configuracoes")
        fechar.clicked.connect(self.close)
        rodape = QHBoxLayout()
        rodape.addStretch(1)
        rodape.addWidget(fechar)
        corpo = QHBoxLayout()
        corpo.setSpacing(16)
        corpo.addWidget(self.secoes)
        corpo.addWidget(self.paginas, 1)
        coluna = QVBoxLayout(self)
        coluna.setContentsMargins(16, 16, 16, 12)
        coluna.addLayout(corpo, 1)
        coluna.addLayout(rodape)

        aparencia().mudou.connect(self._tema_mudou)
        self._tema_mudou()
        self.secoes.setCurrentRow(0)

    def mostrar_secao(self, nome: str) -> None:
        self.secoes.setCurrentRow(self.SECOES.index(nome))

    @property
    def secao(self) -> str:
        return self.SECOES[self.secoes.currentRow()]

    # ------------------------------------------------------------------ as páginas

    def _pagina(self, titulo: str) -> tuple[QWidget, QFormLayout]:
        pagina = QWidget()
        coluna = QVBoxLayout(pagina)
        coluna.setContentsMargins(0, 0, 0, 0)
        coluna.setSpacing(12)
        cabecalho = QLabel(titulo)
        fonte = cabecalho.font()
        fonte.setPixelSize(TAMANHOS["titulo_painel"])
        fonte.setWeight(fonte.Weight.DemiBold)
        cabecalho.setFont(fonte)
        coluna.addWidget(cabecalho)
        formulario = QFormLayout()
        formulario.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        formulario.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        formulario.setHorizontalSpacing(16)
        formulario.setVerticalSpacing(10)
        coluna.addLayout(formulario)
        coluna.addStretch(1)
        return pagina, formulario

    @staticmethod
    def _com_dica(campo: QWidget, dica: str) -> QWidget:
        caixa = QWidget()
        coluna = QVBoxLayout(caixa)
        coluna.setContentsMargins(0, 0, 0, 0)
        coluna.setSpacing(4)
        linha = QHBoxLayout()
        linha.setContentsMargins(0, 0, 0, 0)
        linha.addWidget(campo)
        linha.addStretch(1)
        coluna.addLayout(linha)
        coluna.addWidget(_dica(dica))
        return caixa

    def _pagina_aparencia(self) -> QWidget:
        pagina, formulario = self._pagina(self.tr("Aparência"))
        self.tema = Segmentado([self.tr("Do sistema"), self.tr("Escuro"), self.tr("Claro")],
                               MODOS.index(aparencia().modo))
        self.tema.escolhaMudou.connect(lambda i: preferencias.mudar_tema(MODOS[i]))
        formulario.addRow(self.tr("Tema"), self._com_dica(
            self.tema, self.tr("O do sistema segue o claro ou o escuro do sistema operacional.")))
        self.fontes: dict[str, QComboBox] = {}
        for papel, rotulo, dica in (
                ("interface", self.tr("Fonte da interface"), self.tr("Os textos, os menus e os painéis.")),
                ("mono", self.tr("Fonte dos números"), self.tr("Os números dos eixos dos gráficos."))):
            caixa = QComboBox()
            caixa.setObjectName(f"fonte_{papel}")
            familias = familias_disponiveis(papel)
            caixa.addItems(familias)
            if fonte_escolhida(papel) in familias:
                caixa.setCurrentText(fonte_escolhida(papel))
            caixa.setEnabled(bool(familias))
            caixa.textActivated.connect(lambda familia, p=papel: preferencias.mudar_fonte(p, familia))
            self.fontes[papel] = caixa
            formulario.addRow(rotulo, self._com_dica(caixa, dica))
        largura = max(c.sizeHint().width() for c in self.fontes.values())    # as duas da mesma largura
        for caixa in self.fontes.values():
            caixa.setMinimumWidth(largura)
        self.movimento = Segmentado([self.tr("Do sistema"), self.tr("Reduzido"), self.tr("Normal")],
                                    MOVIMENTOS.index(aparencia().movimento))
        self.movimento.escolhaMudou.connect(lambda i: preferencias.mudar_movimento(MOVIMENTOS[i]))
        formulario.addRow(self.tr("Movimento"), self._com_dica(
            self.movimento, self.tr("Reduzido: nada desliza nem esmaece (as mensagens aparecem e somem de uma vez). "
                                    "O do sistema segue a opção de acessibilidade do sistema operacional.")))
        return pagina

    def _pagina_numeros(self) -> QWidget:
        pagina, formulario = self._pagina(self.tr("Números"))
        separadores = (",", ".")
        self.separador = Segmentado([self.tr("Vírgula"), self.tr("Ponto")],
                                    separadores.index(preferencias.separador_salvo()))
        self.separador.escolhaMudou.connect(lambda i: self._mudar_separador(separadores[i]))
        formulario.addRow(self.tr("Separador decimal"), self._com_dica(
            self.separador, self.tr("Como os números aparecem na tela e são copiados para uma planilha (a vírgula, "
                                    "para uma em português; o ponto, para uma em inglês). Os campos aceitam os "
                                    "dois.")))
        self.exemplo = QLabel()
        self.exemplo.setObjectName("exemplo_numeros")
        formulario.addRow(self.tr("Exemplo"), self.exemplo)
        self.prefixos = Segmentado([self.tr("Automáticos"), self.tr("Desligados")], 0 if prefixos_nos_eixos() else 1)
        self.prefixos.escolhaMudou.connect(lambda i: preferencias.mudar_prefixos_nos_eixos(i == 0))
        formulario.addRow(self.tr("Prefixos nos eixos"), self._com_dica(
            self.prefixos, self.tr("Os eixos dos gráficos escolhem o prefixo do SI pela faixa visível (a tensão em "
                                   "mV, a frequência em kHz); desligados, os números ficam na unidade (0,0012 V). O "
                                   "tempo vai até o segundo.")))
        self._escrever_exemplo()
        return pagina

    def _pagina_unidades(self) -> QWidget:
        pagina, _formulario = self._pagina(self.tr("Unidades"))
        coluna = pagina.layout()
        coluna.takeAt(coluna.count() - 1)                     # sem o espaço do fim: as tabelas esticam
        coluna.addWidget(_dica(self.tr(
            "Um traço aceita qualquer unidade digitada no inspetor. As suas, daqui, entram na lista com a grandeza "
            "e dizem se levam o prefixo do SI na escrita (1,5 mV) ou não (23,5 °C).")))

        self.tabela_unidades = self._tabela([self.tr("Símbolo"), self.tr("Grandeza"), self.tr("Prefixo do SI")], 1)
        self.tabela_unidades.setObjectName("tabela_unidades")
        self.tabela_unidades.itemSelectionChanged.connect(
            lambda: self.remover_unidade.setEnabled(bool(self.tabela_unidades.selectionModel().selectedRows())))
        coluna.addWidget(QLabel(self.tr("As suas")))
        coluna.addWidget(self.tabela_unidades, 1)

        self.novo_simbolo = QLineEdit()
        self.novo_simbolo.setObjectName("novo_simbolo")
        self.novo_simbolo.setPlaceholderText(self.tr("símbolo (ppm)"))
        self.novo_simbolo.setMaxLength(unidades.TAMANHO_MAXIMO)
        self.nova_grandeza = QLineEdit()
        self.nova_grandeza.setObjectName("nova_grandeza")
        self.nova_grandeza.setPlaceholderText(self.tr("grandeza (concentração)"))
        self.nova_grandeza.setMaxLength(unidades.TAMANHO_MAXIMO_DA_GRANDEZA)
        self.novo_com_prefixo = QCheckBox(self.tr("Leva prefixo do SI"))
        self.adicionar_unidade = Botao(self.tr("Adicionar"), "secundario")
        self.adicionar_unidade.setObjectName("adicionar_unidade")
        self.adicionar_unidade.clicked.connect(self._adicionar_unidade)
        for campo in (self.novo_simbolo, self.nova_grandeza):
            campo.returnPressed.connect(self._adicionar_unidade)
            campo.textEdited.connect(lambda _t: self._avisar_unidade(""))
            # O exemplo da dica inteiro, em qualquer fonte e língua.
            campo.setMinimumWidth(campo.fontMetrics().horizontalAdvance(campo.placeholderText()) + 24)
        self.remover_unidade = Botao(self.tr("Remover"), "secundario")
        self.remover_unidade.setObjectName("remover_unidade")
        self.remover_unidade.setEnabled(False)
        self.remover_unidade.clicked.connect(self._remover_unidades)
        linha = QHBoxLayout()
        linha.setSpacing(8)
        linha.addWidget(self.novo_simbolo, 1)
        linha.addWidget(self.nova_grandeza, 2)
        linha.addWidget(self.novo_com_prefixo)
        linha.addWidget(self.adicionar_unidade)
        linha.addWidget(self.remover_unidade)
        coluna.addLayout(linha)
        self.motivo_unidade = QLabel()
        self.motivo_unidade.setObjectName("aviso_inspetor")
        self.motivo_unidade.setWordWrap(True)
        self.motivo_unidade.hide()
        coluna.addWidget(self.motivo_unidade)

        self.tabela_catalogo = self._tabela([self.tr("Símbolo"), self.tr("Grandeza"), self.tr("Converte em")], 2)
        self.tabela_catalogo.setObjectName("tabela_catalogo")
        coluna.addWidget(QLabel(self.tr("Do catálogo (e os múltiplos das que levam prefixo: mV, mA, kPa)")))
        coluna.addWidget(self.tabela_catalogo, 2)
        self._mostrar_catalogo()
        self._mostrar_unidades()
        return pagina

    @staticmethod
    def _tabela(colunas: list[str], que_estica: int) -> QTableWidget:
        """Uma tabela só de leitura, de linhas inteiras; as colunas na largura do conteúdo, menos ``que_estica``."""
        tabela = QTableWidget(0, len(colunas))
        tabela.setHorizontalHeaderLabels(colunas)
        tabela.verticalHeader().hide()
        tabela.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        tabela.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        tabela.setShowGrid(False)
        cabecalho = tabela.horizontalHeader()
        cabecalho.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        cabecalho.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        cabecalho.setSectionResizeMode(que_estica, QHeaderView.ResizeMode.Stretch)
        return tabela

    def _preencher(self, tabela: QTableWidget, linhas) -> None:
        tabela.setRowCount(0)
        for linha in linhas:
            i = tabela.rowCount()
            tabela.insertRow(i)
            for j, texto in enumerate(linha):
                tabela.setItem(i, j, QTableWidgetItem(texto))

    def _mostrar_catalogo(self) -> None:
        self._preencher(self.tabela_catalogo, ((u.simbolo, u.grandeza, ", ".join(unidades.da_mesma_familia(u.simbolo)))
                                               for u in unidades.CATALOGO))

    def _mostrar_unidades(self) -> None:
        self._preencher(self.tabela_unidades, ((u.simbolo, u.grandeza, self.tr("sim") if u.prefixos else self.tr("não"))
                                               for u in unidades.proprias()))
        self.remover_unidade.setEnabled(False)

    def _adicionar_unidade(self) -> None:
        try:
            nova = unidades.propria(self.novo_simbolo.text(), self.nova_grandeza.text(), self.novo_com_prefixo.isChecked())
        except unidades.UnidadeInvalida as e:
            self._avisar_unidade(str(e))
            return
        if unidades.procurar(nova.simbolo) is not None:
            self._avisar_unidade(self.tr("{} já está nas suas").format(nova.simbolo))
            return
        preferencias.mudar_unidades((*unidades.proprias(), nova))
        self.novo_simbolo.clear()
        self.nova_grandeza.clear()
        self.novo_com_prefixo.setChecked(False)
        self._avisar_unidade("")
        self._mostrar_unidades()

    def _avisar_unidade(self, motivo: str) -> None:
        """O motivo de uma unidade recusada, embaixo dos campos (sem um, a linha some)."""
        self.motivo_unidade.setText(motivo)
        self.motivo_unidade.setVisible(bool(motivo))

    def _remover_unidades(self) -> None:
        """Tira as selecionadas da lista; os traços que as usam ficam com elas (o símbolo vale sem estar na lista),
        só sem a grandeza."""
        linhas = {i.row() for i in self.tabela_unidades.selectionModel().selectedRows()}
        preferencias.mudar_unidades(u for i, u in enumerate(unidades.proprias()) if i not in linhas)
        self._mostrar_unidades()

    def _pagina_pastas(self) -> QWidget:
        pagina, formulario = self._pagina(self.tr("Pastas"))
        dicas = {
            "dados": self.tr("Onde o diálogo de abrir começa quando não há um projeto aberto ($DADOS). Sem uma "
                             "escolhida, vale a do recente mais novo."),
            "sondas": self.tr("Onde ficam os perfis das sondas registradas nas capturas (<id>.json). Vale para as "
                              "capturas abertas daqui em diante: as já abertas mantêm o perfil que acharam."),
            "cache": self.tr("As pirâmides das capturas e os traços transformados (refeitos quando faltam). Os "
                             "arquivos da pasta antiga ficam lá: limpe o cache antes de trocar, se quiser apagá-los."),
        }
        rotulos = {"dados": self.tr("Dados"), "sondas": self.tr("Sondas"), "cache": self.tr("Cache")}
        self.campos_de_pasta: dict[str, QLineEdit] = {}
        self.botoes_de_padrao: dict[str, Botao] = {}
        for nome in preferencias.PASTAS:
            campo = QLineEdit()
            campo.setObjectName(f"pasta_{nome}")
            campo.setReadOnly(True)
            escolher = Botao(self.tr("Escolher…"), "secundario", "pasta")
            escolher.setObjectName(f"escolher_pasta_{nome}")
            escolher.clicked.connect(lambda _=False, n=nome: self._escolher_pasta(n))
            padrao = Botao(self.tr("Padrão"), "fantasma")
            padrao.setObjectName(f"padrao_pasta_{nome}")
            padrao.clicked.connect(lambda _=False, n=nome: self._mudar_pasta(n, None))
            self.campos_de_pasta[nome], self.botoes_de_padrao[nome] = campo, padrao
            caixa = QWidget()
            coluna = QVBoxLayout(caixa)
            coluna.setContentsMargins(0, 0, 0, 0)
            coluna.setSpacing(4)
            linha = QHBoxLayout()
            linha.setContentsMargins(0, 0, 0, 0)
            linha.addWidget(campo, 1)
            linha.addWidget(escolher)
            linha.addWidget(padrao)
            coluna.addLayout(linha)
            coluna.addWidget(_dica(dicas[nome]))
            formulario.addRow(rotulos[nome], caixa)
            self._mostrar_pasta(nome)
        return pagina

    def _pagina_cache(self) -> QWidget:
        pagina, formulario = self._pagina(self.tr("Cache"))
        dicas = {"piramides": self.tr("Os resumos das capturas que deixam a navegação imediata."),
                 "materializacoes": self.tr("Os traços com transformações, calculados na captura inteira.")}
        rotulos = {"piramides": self.tr("Pirâmides"), "materializacoes": self.tr("Traços transformados")}
        self.usos: dict[str, QLabel] = {}
        self.limites: dict[str, QSpinBox] = {}
        self.botoes_de_limpar: dict[str, Botao] = {}
        for nome in preferencias.CACHES:
            limite = QSpinBox()
            limite.setObjectName(f"limite_{nome}")
            limite.setRange(max(1, -(-preferencias.LIMITE_MINIMO_BYTES // GIB)), LIMITE_MAXIMO_GIB)
            limite.setSuffix(" GiB")
            limite.setKeyboardTracking(False)        # o limite vale ao confirmar, não a cada algarismo digitado
            limite.setValue(max(1, round(preferencias.limite(nome) / GIB)))
            limite.valueChanged.connect(lambda gib, n=nome: self._mudar_limite(n, gib))
            uso = QLabel()
            uso.setObjectName(f"uso_{nome}")
            limpar = Botao(self.tr("Limpar"), "secundario")
            limpar.setObjectName(f"limpar_{nome}")
            limpar.setToolTip(self.tr("Apaga o que está guardado, menos o que está aberto agora"))
            limpar.clicked.connect(lambda _=False, n=nome: self._limpar(n))
            self.usos[nome], self.limites[nome], self.botoes_de_limpar[nome] = uso, limite, limpar
            caixa = QWidget()
            coluna = QVBoxLayout(caixa)
            coluna.setContentsMargins(0, 0, 0, 0)
            coluna.setSpacing(4)
            linha = QHBoxLayout()
            linha.setContentsMargins(0, 0, 0, 0)
            linha.addWidget(QLabel(self.tr("Limite")))
            linha.addWidget(limite)
            linha.addSpacing(12)
            linha.addWidget(uso)
            linha.addStretch(1)
            linha.addWidget(limpar)
            coluna.addLayout(linha)
            coluna.addWidget(_dica(dicas[nome]))
            formulario.addRow(rotulos[nome], caixa)
        divisoria = QFrame()
        divisoria.setObjectName("divisoria")
        divisoria.setFixedHeight(1)
        formulario.addRow(divisoria)
        formulario.addRow(_dica(self.tr("Passar do limite apaga os menos usados; o que está aberto fica sempre. "
                                        "A pasta do cache fica em Pastas.")))
        return pagina

    # ------------------------------------------------------------------ as mudanças

    def _mudar_separador(self, separador: str) -> None:
        preferencias.mudar_separador(separador)
        self._escrever_exemplo()

    def _escrever_exemplo(self) -> None:
        self.exemplo.setText(" · ".join((formatar_si(2500, "Hz"), formatar_si(127.34, "V"), formatar_si(0.0015, "A"),
                                         formatar_duracao(4.2))))

    def _mostrar_pasta(self, nome: str) -> None:
        escolhida = preferencias.pasta_escolhida(nome)
        campo = self.campos_de_pasta[nome]
        campo.setText(str(escolhida) if escolhida is not None else "")
        campo.setPlaceholderText(self.tr("Padrão: {}").format(preferencias.pasta_padrao(nome)))
        campo.setToolTip(str(preferencias.pasta(nome)))
        self.botoes_de_padrao[nome].setEnabled(escolhida is not None)

    def _escolher_pasta(self, nome: str) -> None:
        titulos = {"dados": self.tr("A pasta dos dados"), "sondas": self.tr("A pasta das sondas"),
                   "cache": self.tr("A pasta do cache")}
        caminho = self.janela.controle.dialogos.escolher_pasta(titulos[nome], str(preferencias.pasta(nome)))
        if caminho is not None:
            self._mudar_pasta(nome, caminho)

    def _mudar_pasta(self, nome: str, caminho: Path | None) -> None:
        preferencias.mudar_pasta(nome, caminho)
        self._mostrar_pasta(nome)
        if nome == "cache":
            self.janela.aplicar_cache()
            self._mostrar_usos()

    def _mudar_limite(self, nome: str, gib: int) -> None:
        preferencias.mudar_limite(nome, gib * GIB)
        self.janela.aplicar_cache()
        self._mostrar_usos()

    def _servico(self, nome: str):
        return self.janela.servico_de_fontes if nome == "piramides" else self.janela.materializacoes

    def _limpar(self, nome: str) -> None:
        liberados = self._servico(nome).limpar_cache()
        self._mostrar_usos()
        Toast.mostrar(self, self.tr("{} liberados").format(formatar_bytes(liberados)), "sucesso")

    def _mostrar_usos(self) -> None:
        for nome, rotulo in self.usos.items():
            rotulo.setText(self.tr("em uso: {}").format(formatar_bytes(self._servico(nome).cache.tamanho_bytes)))

    def _pagina_mudou(self, linha: int) -> None:
        if 0 <= linha < len(self.SECOES) and self.SECOES[linha] == "cache":
            self._mostrar_usos()                     # medir a pasta só quando a página aparece

    def _ajustar_a_lista(self) -> None:
        """A lista das seções só tão larga quanto o nome mais comprido, com o ícone e o espaço do estilo (em
        qualquer fonte e língua)."""
        self.secoes.ensurePolished()
        self.secoes.setFixedWidth(self.secoes.sizeHintForColumn(0) + 2 * self.secoes.frameWidth() + 8)

    def _tema_mudou(self, _tema=None) -> None:
        """O tema mudou (também pelo botão da barra), o separador ou a fonte: os ícones, a escolha mostrada, os
        números e a largura da lista."""
        t = aparencia().tema
        for item, nome_do_icone in self._icones:
            item.setIcon(icone(nome_do_icone, t.texto2))
        self._ajustar_a_lista()
        if self.tema.escolhida != MODOS.index(aparencia().modo):
            self.tema.blockSignals(True)
            self.tema.escolher(MODOS.index(aparencia().modo))
            self.tema.blockSignals(False)
        self._escrever_exemplo()
        if self.secoes.currentRow() >= 0 and self.secao == "cache":
            self._mostrar_usos()

    def showEvent(self, evento) -> None:
        for nome in preferencias.PASTAS:              # o $DADOS pode ter mudado; a escolhida, não
            self._mostrar_pasta(nome)
        super().showEvent(evento)
