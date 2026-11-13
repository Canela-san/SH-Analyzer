"""O inspetor do traço (docs/gui-plan.md, 9.4): a identidade, a aparência e a escala e o tempo dos traços
selecionados. **Cada mudança é um comando de desfazer** (``MudarTracos``); com vários traços selecionados, o
inspetor mostra o que eles têm em comum ("vários" onde diferem), e mudar ali muda todos, num passo só.

Um valor que a receita recusa (o ganho zero) não entra: o campo fica vermelho, com o motivo na dica.
"""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QScrollArea,
    QSpinBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ...componentes.basicos import CampoComUnidade
from ...componentes.numeros import formatar_duracao, formatar_si
from ...dados.receita import ReceitaInvalida
from ...modelo.comandos import MudarTracos
from ...modelo.objetos import Projeto, Traco
from ...tema.aplicar import aparencia
from ...tema.tokens import NOMES_DOS_TRACOS, TAMANHOS, Tema, cor_do_traco

LARGURA_DO_ROTULO = 92
CORES_DA_PALETA = 6
LADO_DA_COR = 20


def _fonte(px: int, peso: QFont.Weight | None = None) -> QFont:
    f = QFont()
    f.setPixelSize(px)
    if peso is not None:
        f.setWeight(peso)
    return f


def _comum(valores):
    """O valor, se todos forem iguais; ``None`` se diferirem."""
    valores = list(valores)
    return valores[0] if valores and all(v == valores[0] for v in valores) else None


class InspetorDoTraco(QScrollArea):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("inspetor_do_traco")
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.projeto: Projeto | None = None
        self.tracos: tuple[Traco, ...] = ()
        self._montar()
        aparencia().mudou.connect(self._tema_mudou)

    # ------------------------------------------------------------------ montar

    def _montar(self) -> None:
        conteudo = QWidget()
        conteudo.setObjectName("painel")
        conteudo.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        coluna = QVBoxLayout(conteudo)
        coluna.setContentsMargins(12, 4, 12, 12)
        coluna.setSpacing(10)

        self.titulo = QLabel()
        self.titulo.setObjectName("titulo_inspetor")
        self.titulo.setFont(_fonte(TAMANHOS["titulo_painel"], QFont.Weight.DemiBold))
        self.titulo.setWordWrap(True)
        self.subtitulo = QLabel()
        self.subtitulo.setObjectName("subtitulo_inspetor")
        self.subtitulo.setFont(_fonte(TAMANHOS["secundario"]))
        self.subtitulo.setWordWrap(True)
        coluna.addWidget(self.titulo)
        coluna.addWidget(self.subtitulo)

        # Identidade
        self.nome = QLineEdit()
        self.nome.setObjectName("campo_nome")
        self.nome.editingFinished.connect(self._nome_editado)
        self.canal = QLabel()
        self.canal.setWordWrap(True)
        self.taxa = QLabel()
        coluna.addWidget(self._secao(self.tr("Identidade"), [(self.tr("Nome"), self.nome),
                                                             (self.tr("Canal"), self.canal),
                                                             (self.tr("Taxa e duração"), self.taxa)]))

        # Aparência
        cores = QWidget()
        linha = QHBoxLayout(cores)
        linha.setContentsMargins(0, 0, 0, 0)
        linha.setSpacing(6)
        self.grupo_de_cores = QButtonGroup(self)
        self.grupo_de_cores.setExclusive(False)
        self.botoes_de_cor: list[QToolButton] = []
        for i in range(CORES_DA_PALETA):
            b = QToolButton()
            b.setObjectName("cor_da_paleta")
            b.setCheckable(True)
            b.setFixedSize(QSize(LADO_DA_COR, LADO_DA_COR))
            b.setToolTip(NOMES_DOS_TRACOS[i])
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            self.grupo_de_cores.addButton(b, i)
            self.botoes_de_cor.append(b)
            linha.addWidget(b)
        linha.addStretch(1)
        self.grupo_de_cores.idClicked.connect(self._cor_escolhida)
        self.visivel = QCheckBox(self.tr("Visível"))
        self.visivel.setTristate(False)
        self.visivel.clicked.connect(self._visivel_mudou)
        coluna.addWidget(self._secao(self.tr("Aparência"), [(self.tr("Cor"), cores), ("", self.visivel)]))

        # Escala e tempo
        self.faixa = QSpinBox()
        self.faixa.setObjectName("campo_faixa")
        self.faixa.setRange(0, 64)
        self.faixa.setSpecialValueText(self.tr("vários"))         # o 0: os traços estão em faixas diferentes
        self.faixa.setKeyboardTracking(False)
        self.faixa.valueChanged.connect(self._faixa_mudou)
        self.ganho = CampoComUnidade("", 1.0, digitos=5)
        self.ganho.setObjectName("campo_ganho")
        self.ganho.valorMudou.connect(lambda v: self._mudar(self.ganho, ganho=v))
        inverter = QToolButton()
        inverter.setObjectName("botao_inverter")
        inverter.setText(self.tr("Inverter"))
        inverter.setToolTip(self.tr("Troca o sinal do ganho de cada traço"))
        inverter.clicked.connect(self._inverter)
        ganho = QWidget()
        linha = QHBoxLayout(ganho)
        linha.setContentsMargins(0, 0, 0, 0)
        linha.setSpacing(6)
        linha.addWidget(self.ganho, 1)
        linha.addWidget(inverter)
        self.offset = CampoComUnidade("V", 0.0, digitos=5)
        self.offset.setObjectName("campo_offset")
        self.offset.valorMudou.connect(lambda v: self._mudar(self.offset, offset=v))
        self.deslocamento = CampoComUnidade("s", 0.0, digitos=5)
        self.deslocamento.setObjectName("campo_deslocamento")
        self.deslocamento.valorMudou.connect(lambda v: self._mudar(self.deslocamento, deslocamento_s=v))
        coluna.addWidget(self._secao(self.tr("Escala e tempo"), [
            (self.tr("Faixa"), self.faixa), (self.tr("Ganho"), ganho), (self.tr("Offset"), self.offset),
            (self.tr("Deslocamento"), self.deslocamento)]))

        # Calibração
        self.calibracao = QLabel()
        self.calibracao.setWordWrap(True)
        self.calibracao.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        coluna.addWidget(self._secao(self.tr("Calibração"), [(self.tr("Sonda"), self.calibracao)]))
        coluna.addStretch(1)
        self.setWidget(conteudo)
        self._pintar_cores(aparencia().tema)

    def _secao(self, titulo: str, linhas) -> QWidget:
        secao = QWidget()
        coluna = QVBoxLayout(secao)
        coluna.setContentsMargins(0, 6, 0, 0)
        coluna.setSpacing(6)
        divisoria = QFrame()
        divisoria.setObjectName("divisoria")
        divisoria.setFixedHeight(1)
        coluna.addWidget(divisoria)
        rotulo = QLabel(titulo)
        rotulo.setFont(_fonte(TAMANHOS["corpo"], QFont.Weight.DemiBold))
        coluna.addWidget(rotulo)
        grade = QGridLayout()
        grade.setHorizontalSpacing(8)
        grade.setVerticalSpacing(6)
        grade.setColumnMinimumWidth(0, LARGURA_DO_ROTULO)
        grade.setColumnStretch(1, 1)
        for i, (nome, widget) in enumerate(linhas):
            r = QLabel(nome)
            r.setObjectName("rotulo_campo")
            r.setFont(_fonte(TAMANHOS["secundario"]))
            grade.addWidget(r, i, 0, Qt.AlignmentFlag.AlignVCenter)
            grade.addWidget(widget, i, 1)
        coluna.addLayout(grade)
        return secao

    # ------------------------------------------------------------------ mostrar

    def mostrar(self, projeto: Projeto, tracos) -> None:
        if self.projeto is not projeto:
            if self.projeto is not None:
                self.projeto.tracoMudou.disconnect(self._traco_mudou)
            projeto.tracoMudou.connect(self._traco_mudou)
            self.projeto = projeto
        self.tracos = tuple(tracos)
        self.atualizar()

    def _traco_mudou(self, traco: Traco, _campos) -> None:
        if traco in self.tracos:
            self.atualizar()

    def _canal_de(self, traco: Traco):
        try:
            fonte = self.projeto.fonte(traco.receita.fonte)
        except KeyError:
            return None, None
        return fonte, (None if fonte.esta_ausente else fonte.canal(traco.receita.canal))

    def atualizar(self) -> None:
        tracos = self.tracos
        if not tracos:
            return
        receitas = [t.receita for t in tracos]
        um = len(tracos) == 1
        self.titulo.setText(tracos[0].nome if um else self.tr("{} traços").format(len(tracos)))
        fontes_canais = [self._canal_de(t) for t in tracos]
        nomes_das_fontes = sorted({f.nome for f, _ in fontes_canais if f is not None})
        self.subtitulo.setText(" · ".join(nomes_das_fontes))

        self.nome.blockSignals(True)
        self.nome.setEnabled(um)
        self.nome.setText(tracos[0].nome if um else "")
        self.nome.setPlaceholderText("" if um else self.tr("vários"))
        self.nome.setCursorPosition(0)
        self.nome.blockSignals(False)
        canais = [c for _, c in fontes_canais if c is not None]
        if um and canais:
            c = canais[0]
            self.canal.setText(f"{c.numero} · {c.nome_grandeza} ({c.unidade})")
            self.taxa.setText(f"{formatar_si(c.taxa_hz, 'S/s', 4)} · {formatar_duracao(c.duracao_s)}")
        elif um:
            self.canal.setText(self.tr("{} (captura ausente)").format(receitas[0].canal))
            self.taxa.setText("—")
        else:
            self.canal.setText(self.tr("vários"))
            taxa = _comum(c.taxa_hz for c in canais)
            self.taxa.setText(formatar_si(taxa, "S/s", 4) if taxa is not None else self.tr("vários"))

        cor = _comum(r.cor for r in receitas)
        for i, b in enumerate(self.botoes_de_cor):
            b.setChecked(i == cor)
        visivel = _comum(r.visivel for r in receitas)
        self.visivel.setTristate(visivel is None)
        self.visivel.setCheckState(Qt.CheckState.PartiallyChecked if visivel is None
                                   else Qt.CheckState.Checked if visivel else Qt.CheckState.Unchecked)

        self.faixa.blockSignals(True)
        faixa = _comum(r.faixa for r in receitas)
        self.faixa.setValue(faixa + 1 if faixa is not None else 0)
        self.faixa.blockSignals(False)
        unidade = _comum(c.unidade for c in canais) if canais else None
        self.offset.unidade = unidade or ""
        for campo, valor in ((self.ganho, _comum(r.ganho for r in receitas)),
                             (self.offset, _comum(r.offset for r in receitas)),
                             (self.deslocamento, _comum(r.deslocamento_s for r in receitas))):
            if valor is None:
                campo.definir_varios()
            else:
                campo.definir_valor(valor)
            campo.setToolTip("")

        sondas = []
        for c in canais:
            if c.problema_sonda:
                sondas.append(c.problema_sonda)
            elif c.sonda_id:
                sondas.append(self.tr("{}: perfil {}").format(c.sonda_id, "aplicável" if c.perfil else "sem perfil"))
        self.calibracao.setText("\n".join(dict.fromkeys(sondas)) or self.tr("Nenhuma sonda registrada"))

    # ------------------------------------------------------------------ mudar (sempre pela pilha)

    def _mudar(self, campo: CampoComUnidade | None, **mudancas) -> bool:
        if not self.tracos or self.projeto is None:
            return False
        try:
            comando = MudarTracos(self.tracos, **mudancas)
        except ReceitaInvalida as e:
            if campo is not None:
                campo.marcar_invalido(str(e))
            return False
        if all(t.receita == d for t, d in zip(comando.tracos, comando.depois)):
            return False                       # nada muda: nada entra na pilha
        self.projeto.pilha.push(comando)
        return True

    def _nome_editado(self) -> None:
        texto = self.nome.text().strip()
        if len(self.tracos) == 1 and texto and texto != self.tracos[0].nome:
            self._mudar(None, nome=texto)
        elif len(self.tracos) == 1:
            self.nome.setText(self.tracos[0].nome)

    def _cor_escolhida(self, indice: int) -> None:
        self._mudar(None, cor=indice)
        self.atualizar()

    def _visivel_mudou(self, marcado: bool) -> None:
        self._mudar(None, visivel=bool(marcado))
        self.atualizar()

    def _faixa_mudou(self, valor: int) -> None:
        if valor >= 1:
            self._mudar(None, faixa=valor - 1)

    def _inverter(self) -> None:
        if not self.tracos or self.projeto is None:
            return
        # Um passo só, mesmo com ganhos diferentes: cada traço troca o sinal do seu.
        self.projeto.pilha.beginMacro(self.tr("Inverter {}").format(
            self.tracos[0].nome if len(self.tracos) == 1 else self.tr("{} traços").format(len(self.tracos))))
        try:
            for traco in self.tracos:
                self.projeto.pilha.push(MudarTracos([traco], ganho=-traco.receita.ganho))
        finally:
            self.projeto.pilha.endMacro()

    # ------------------------------------------------------------------ tema

    def _tema_mudou(self, t: Tema) -> None:
        self._pintar_cores(t)

    def _pintar_cores(self, t: Tema) -> None:
        for i, b in enumerate(self.botoes_de_cor):
            cor = QColor(cor_do_traco(i, t)[0])
            b.setStyleSheet(f"QToolButton#cor_da_paleta {{ background: {cor.name()}; border: 2px solid {t.superficie};"
                            f" border-radius: 5px; }} QToolButton#cor_da_paleta:checked {{ border-color: {t.texto}; }}")
