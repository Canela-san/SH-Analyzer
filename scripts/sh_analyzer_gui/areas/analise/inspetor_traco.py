"""O inspetor do traço (docs/gui-plan.md, 9.4): a identidade, a aparência, a escala e o tempo, o processamento (a
cadeia de transformações, ``processamento.py``) e a calibração dos traços selecionados. **Cada mudança é um comando de desfazer** (``MudarTracos``); com vários traços selecionados, o
inspetor mostra o que eles têm em comum ("vários" onde diferem), e mudar ali muda todos, num passo só.

Um valor que a receita recusa (o ganho zero) não entra: o campo fica vermelho, com o motivo na dica.

**A unidade do traço** (``dados/unidades.py``): escolher uma da mesma família da de agora (°C e K, V e mV) converte o
ganho e o offset de cada traço, e os números continuam os mesmos, noutra unidade; escolher uma de outra família (V
para °C) só diz o que o sinal mede, e a escala vem do ganho e do offset, ou dos dois pontos (``dois_pontos.py``). O
ganho mostra a unidade dele quando o traço não está na do canal (100 °C/V).
"""

from __future__ import annotations

import datetime
from pathlib import Path

import supraharmonicos.api as api
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
from ...componentes.seletor_de_unidade import SeletorDeUnidade
from ...componentes.toast import Toast
from ...dados import unidades
from ...dados.cadeia import CorrecaoSonda
from ...dados.receita import ReceitaInvalida
from ...modelo.comandos import MudarTracos
from ...modelo.objetos import Projeto, Traco
from ...tema.aplicar import aparencia
from ...tema.tokens import NOMES_DOS_TRACOS, TAMANHOS, Tema, cor_do_traco
from .dois_pontos import DialogoDeDoisPontos, unidade_do_ganho
from .processamento import SecaoDeProcessamento
from .secao_do_espectro import SecaoDoEspectro

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
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
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

        # A análise da vista de espectro ativa (só nela): no alto, perto de onde o usuário clicou na curva.
        self.espectro = SecaoDoEspectro(LARGURA_DO_ROTULO)
        self.secao_espectro = self._secao(self.tr("Análise do espectro"), [], corpo=self.espectro)
        self.secao_espectro.hide()
        coluna.addWidget(self.secao_espectro)

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
        self.unidade = SeletorDeUnidade()
        self.unidade.setObjectName("campo_unidade")
        self.unidade.unidadeEscolhida.connect(self._unidade_escolhida)
        self.dois_pontos = QToolButton()
        self.dois_pontos.setObjectName("botao_dois_pontos")
        self.dois_pontos.setText(self.tr("Dois pontos…"))
        self.dois_pontos.setToolTip(self.tr("A escala do sensor por dois valores conhecidos (4 mA → 0 bar, "
                                            "20 mA → 10 bar)"))
        self.dois_pontos.clicked.connect(self.calibrar_por_dois_pontos)
        self.dialogo_dois_pontos: DialogoDeDoisPontos | None = None
        unidade = QWidget()
        linha = QHBoxLayout(unidade)
        linha.setContentsMargins(0, 0, 0, 0)
        linha.setSpacing(6)
        linha.addWidget(self.unidade, 1)
        linha.addWidget(self.dois_pontos)
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
            (self.tr("Faixa"), self.faixa), (self.tr("Unidade"), unidade), (self.tr("Ganho"), ganho),
            (self.tr("Offset"), self.offset), (self.tr("Deslocamento"), self.deslocamento)]))

        # Processamento
        self.processamento = SecaoDeProcessamento()
        coluna.addWidget(self._secao(self.tr("Processamento"), [], corpo=self.processamento))

        # Calibração
        self.calibracao = QLabel()
        self.calibracao.setObjectName("texto_calibracao")
        self.calibracao.setWordWrap(True)
        self.calibracao.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.aplicar_correcao = QToolButton()
        self.aplicar_correcao.setObjectName("aplicar_correcao")
        self.aplicar_correcao.setText(self.tr("Aplicar a correção de sonda"))
        self.aplicar_correcao.setToolTip(self.tr("Põe a correção pelo perfil no começo da cadeia (como o adc_tool faz)"))
        self.aplicar_correcao.clicked.connect(lambda _=False: self.processamento.adicionar("correcao_sonda"))
        corpo = QWidget()
        linhas = QVBoxLayout(corpo)
        linhas.setContentsMargins(0, 0, 0, 0)
        linhas.setSpacing(4)
        linhas.addWidget(self.calibracao)
        linhas.addWidget(self.aplicar_correcao, 0, Qt.AlignmentFlag.AlignLeft)
        coluna.addWidget(self._secao(self.tr("Calibração"), [], corpo=corpo))
        coluna.addStretch(1)
        self.setWidget(conteudo)
        self._pintar_cores(aparencia().tema)

    def minimumSizeHint(self) -> QSize:
        """A largura mínima do conteúdo (mais a barra de rolagem vertical): o dock do inspetor não encolhe abaixo do
        que cabe, e se alarga sozinho quando entra uma etapa que pede mais (nada sai pela direita, em nenhuma fonte
        nem língua)."""
        conteudo = self.widget()
        largura = (conteudo.minimumSizeHint().width() if conteudo is not None else 0) + \
            self.verticalScrollBar().sizeHint().width() + 2 * self.frameWidth()
        return QSize(largura, super().minimumSizeHint().height())

    def _secao(self, titulo: str, linhas, corpo: QWidget | None = None) -> QWidget:
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
        if corpo is not None:
            coluna.addWidget(corpo)
        return secao

    # ------------------------------------------------------------------ mostrar

    def mostrar(self, projeto: Projeto, tracos) -> None:
        if self.projeto is not projeto:
            if self.projeto is not None:
                self.projeto.tracoMudou.disconnect(self._traco_mudou)
                self.projeto.vistaMudou.disconnect(self._vista_mudou)
            projeto.tracoMudou.connect(self._traco_mudou)
            projeto.vistaMudou.connect(self._vista_mudou)
            self.projeto = projeto
        self.tracos = tuple(tracos)
        self.atualizar()

    def _traco_mudou(self, traco: Traco, _campos) -> None:
        if traco in self.tracos:
            self.atualizar()

    def _vista_mudou(self, vista, campos) -> None:
        """Uma vista passou a sobrepor os traços (ou deixou): a faixa dos dela vale ou não."""
        if "opcoes" in campos and any(t in vista.tracos for t in self.tracos):
            self.atualizar()

    def _sobreposto(self, traco: Traco) -> bool:
        """Se o traço está numa vista de tempo que sobrepõe os traços (a faixa dele não vale ali)."""
        return any(v.tipo == "tempo" and v.opcoes.sobrepor and traco in v.tracos
                   for v in self.projeto.vistas)

    def definir_vista(self, projeto: Projeto | None, vista, f1=None) -> None:
        """A vista ativa: numa de espectro, a seção da análise dela aparece."""
        espectro = vista is not None and vista.tipo == "espectro"
        self.espectro.mostrar(projeto if espectro else None, vista if espectro else None, f1)
        self.secao_espectro.setVisible(espectro)

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
        sobrepostos = self.projeto is not None and all(self._sobreposto(t) for t in tracos)
        self.faixa.setEnabled(not sobrepostos)
        self.faixa.setToolTip(self.tr("A vista sobrepõe os traços numa faixa só; a faixa volta a valer ao "
                                      "separá-los") if sobrepostos else "")
        do_canal = self._unidade_comum_dos_canais()
        unidade = _comum(self._unidade_do_traco(t, c) for t, (_, c) in zip(tracos, fontes_canais))
        self.unidade.definir(unidade)
        self.unidade.definir_dica(self._dica_da_unidade(unidade, do_canal))
        self.dois_pontos.setEnabled(do_canal is not None)
        self.offset.unidade = unidade or ""
        self.ganho.unidade = unidade_do_ganho(unidade or "", do_canal or "")
        for campo, valor in ((self.ganho, _comum(r.ganho for r in receitas)),
                             (self.offset, _comum(r.offset for r in receitas)),
                             (self.deslocamento, _comum(r.deslocamento_s for r in receitas))):
            if valor is None:
                campo.definir_varios()
            else:
                campo.definir_valor(valor)
            campo.setToolTip("")

        self.processamento.mostrar(self.projeto, tracos, [c.taxa_hz for c in canais])
        self.updateGeometry()                    # a largura mínima pode ter mudado (os cartões das etapas)
        if um and canais:
            fonte = fontes_canais[0][0]
            linhas, falta_aplicar = self._calibracao(fonte, canais[0], receitas[0].cadeia)
        else:
            linhas, falta_aplicar = [self.tr("Selecione um traço só para ver a calibração dele.")], False
        self.calibracao.setText("\n".join(dict.fromkeys(linhas)))
        self.aplicar_correcao.setVisible(falta_aplicar)

    @staticmethod
    def _unidade_do_traco(traco: Traco, canal) -> str:
        """A unidade dos valores do traço (a dele ou a do canal; só a dele, se a captura está ausente)."""
        return traco.receita.unidade_de(canal.unidade if canal is not None else "")

    def _unidade_comum_dos_canais(self) -> str | None:
        """A unidade dos canais dos traços selecionados, se todos têm canal e ela é uma só; ``None`` se não."""
        canais = [self._canal_de(t)[1] for t in self.tracos]
        if not canais or any(c is None for c in canais):
            return None
        return _comum(c.unidade for c in canais)

    def _dica_da_unidade(self, unidade: str | None, do_canal: str | None) -> str:
        if unidade is None:
            return self.tr("Os traços estão em unidades diferentes")
        grandeza = unidades.grandeza(unidade)
        if do_canal is not None and unidade == do_canal:
            return self.tr("{} (a do canal)").format(grandeza or unidade)
        return grandeza

    def _calibracao(self, fonte, canal, cadeia) -> tuple[list[str], bool]:
        """O texto da calibração do canal com esta cadeia, e se falta aplicar a correção de um perfil que existe."""
        etapa = next((e for e in cadeia.ligadas if isinstance(e, CorrecaoSonda)), None)
        linhas = [canal.problema_sonda] if canal.problema_sonda else []
        perfil, origem = canal.perfil, self.tr("o da captura")
        if etapa is not None and etapa.perfil is not None:
            try:
                perfil, origem = api.carregar_perfil(Path(etapa.perfil)), self.tr("escolhido")
            except api.ErroSHAN as e:
                return [*linhas, self.tr("O perfil escolhido não abre: {}").format(e)], False
        if perfil is None:
            if etapa is not None and canal.problema_sonda:
                linhas.append(self.tr("A correção automática não muda nada: a sonda registrada não pôde ser usada "
                                      "(acima). Escolha um perfil na etapa."))
            elif etapa is not None:
                linhas.append(self.tr("A correção automática não tem o que aplicar: a captura não registra uma sonda "
                                      "para este canal. Escolha um perfil na etapa."))
            elif not linhas:
                linhas.append(self.tr("Nenhuma sonda registrada para este canal."))
            return linhas, False
        linhas.append(self.tr("Perfil {} ({}): {}").format(perfil.id, origem, Path(perfil.caminho).name))
        faixa = perfil.faixa_valida
        if faixa is not None:
            linhas.append(self.tr("Faixa válida: {} a {}").format(formatar_si(faixa[0], "Hz", 3),
                                                                  formatar_si(faixa[1], "Hz", 3)))
        if perfil.data_calibracao is not None:
            captura = fonte.fonte.captura.cabecalho
            try:
                dia = datetime.datetime.fromtimestamp(captura.timestamp_unix, tz=datetime.timezone.utc).date()
                dias = (dia - perfil.data_calibracao).days
                quando = self.tr(" ({} dias antes da captura)").format(dias) if dias >= 0 else \
                    self.tr(" (depois da captura)")
            except (OverflowError, OSError, ValueError):
                quando = ""
            linhas.append(self.tr("Calibrado em {}{}").format(perfil.data_calibracao.isoformat(), quando))
        if etapa is None:
            linhas.append(self.tr("A correção não está na cadeia: o traço mostra a saída da sonda, sem corrigir a "
                                  "resposta em frequência."))
        else:
            linhas.append(self.tr("A correção está na cadeia."))
        return linhas, etapa is None

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

    def _quais(self, tracos) -> str:
        return tracos[0].nome if len(tracos) == 1 else self.tr("{} traços").format(len(tracos))

    def _inverter(self) -> None:
        if not self.tracos or self.projeto is None:
            return
        # Um passo só, mesmo com ganhos diferentes: cada traço troca o sinal do seu.
        self.projeto.pilha.push(MudarTracos({t: {"ganho": -t.receita.ganho} for t in self.tracos},
                                            texto=self.tr("Inverter {}").format(self._quais(self.tracos))))

    def _unidade_escolhida(self, nova: str) -> None:
        """Cada traço vai para ``nova``: convertendo o ganho e o offset dele quando a de agora se converte nela;
        só trocando o rótulo quando não (e o aviso diz que a escala ficou como estava)."""
        if not self.tracos or self.projeto is None:
            return
        de_cada, sem_conversao = {}, []
        for traco in self.tracos:
            canal = self._canal_de(traco)[1]
            r, atual = traco.receita, self._unidade_do_traco(traco, canal)
            mudancas: dict = {"unidade": "" if canal is not None and nova == canal.unidade else nova}
            conversao = unidades.conversao(atual, nova) if atual else None
            if conversao is not None:
                c, d = conversao
                mudancas.update(ganho=c * r.ganho, offset=c * r.offset + d)
            elif atual != nova:
                sem_conversao.append(atual or "?")
            de_cada[traco] = mudancas
        try:
            comando = MudarTracos(de_cada, texto=self.tr("Unidade de {}: {}").format(self._quais(self.tracos), nova))
        except ReceitaInvalida as e:
            self.unidade.marcar_invalido(str(e))
            return
        if not comando.muda_algo:
            self.atualizar()
            return
        self.projeto.pilha.push(comando)
        if sem_conversao:
            de = ", ".join(dict.fromkeys(sem_conversao))
            Toast.mostrar(self.window(), self.tr("De {} para {} não há conversão: a escala é a do ganho e do offset "
                                                 "(ou dos dois pontos).").format(de, nova))

    def calibrar_por_dois_pontos(self) -> DialogoDeDoisPontos | None:
        """Abre o diálogo dos dois pontos (sem bloquear); o "Aplicar" muda a unidade, o ganho e o offset de todos os
        traços selecionados, num passo só."""
        do_canal = self._unidade_comum_dos_canais()
        if do_canal is None or self.projeto is None:
            return None
        receitas = [t.receita for t in self.tracos]
        unidade = _comum(r.unidade_de(do_canal) for r in receitas) or do_canal
        ganho, offset = _comum(r.ganho for r in receitas), _comum(r.offset for r in receitas)
        dialogo = DialogoDeDoisPontos(do_canal, unidade, ganho if ganho is not None else 1.0,
                                      offset if offset is not None else 0.0, self)
        tracos = self.tracos                         # os de agora, mesmo que a seleção mude com o diálogo aberto
        dialogo.accepted.connect(lambda: self._aplicar_dois_pontos(dialogo, do_canal, tracos))
        dialogo.finished.connect(lambda _r: self._dois_pontos_fechou(dialogo))
        self.dialogo_dois_pontos = dialogo
        dialogo.open()
        return dialogo

    def _aplicar_dois_pontos(self, dialogo: DialogoDeDoisPontos, do_canal: str, tracos) -> None:
        unidade, ganho, offset = dialogo.escala()
        comando = MudarTracos(tracos, unidade="" if unidade == do_canal else unidade, ganho=ganho, offset=offset,
                              texto=self.tr("Dois pontos em {}").format(self._quais(tracos)))
        if comando.muda_algo:
            self.projeto.pilha.push(comando)

    def _dois_pontos_fechou(self, dialogo: DialogoDeDoisPontos) -> None:
        if self.dialogo_dois_pontos is dialogo:
            self.dialogo_dois_pontos = None
        dialogo.deleteLater()

    # ------------------------------------------------------------------ tema

    def _tema_mudou(self, t: Tema) -> None:
        """As cores da paleta e os números escritos de novo (o separador decimal pode ter mudado)."""
        self._pintar_cores(t)
        self.atualizar()

    def _pintar_cores(self, t: Tema) -> None:
        for i, b in enumerate(self.botoes_de_cor):
            cor = QColor(cor_do_traco(i, t)[0])
            b.setStyleSheet(f"QToolButton#cor_da_paleta {{ background: {cor.name()}; border: 2px solid {t.superficie};"
                            f" border-radius: 5px; }} QToolButton#cor_da_paleta:checked {{ border-color: {t.texto}; }}")
