"""A taxa e os canais de uma captura sem o cabeçalho do SH-Analyzer (PD-02): o ``.bin`` legado, o ``.csv`` do
``adc_tool -c`` e o ``.h5`` exportado de um legado. O arquivo não diz como a captura foi feita, e o diálogo pergunta
o que o ``adc_tool`` pediria (o ``-f`` e o ``--canais``), com as regras dele (``api.ParametrosSemCabecalho``).

* **A taxa** é a total, a soma dos canais (a do ``-f``): "400k", "400 kHz". Embaixo, o que ela dá por canal e a
  duração da captura, para conferir com o que se sabe dela.
* **Os canais** vão na ordem da intercalação ("0, 1"). Quando o arquivo os diz (a coluna 'canal' do ``.csv``, o
  ``.h5``), aparecem escritos e não se editam.
* **A sugestão** é a última resposta: numa sessão de bancada, as capturas são parecidas.

Sem uma resposta válida, o botão fica desligado e o motivo aparece embaixo.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QGridLayout, QLabel, QLineEdit, QVBoxLayout, QWidget
from supraharmonicos.api import ErroSHAN, ParametrosSemCabecalho

from ...componentes.basicos import CampoComUnidade
from ...componentes.numeros import NumeroInvalido, formatar_duracao, formatar_si, ler_numero


class DialogoSemCabecalho(QDialog):
    """Pergunta a taxa total e os canais de ``nome``; ``parametros()`` dá a resposta depois do ``accepted``.

    ``tipo`` é o do arquivo (``"bin"``, ``"csv"`` ou ``"h5"``), ``canais_do_arquivo`` os que ele diz (ou None),
    ``n_amostras`` as brutas, de todos os canais (para a duração), e ``sugestao`` a resposta que já vem escrita."""

    def __init__(self, nome: str, tipo: str, canais_do_arquivo: tuple[int, ...] | None, n_amostras: int | None,
                 sugestao: ParametrosSemCabecalho | None = None, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("dialogo_sem_cabecalho")
        self.setWindowTitle(self.tr("Abrir {}").format(nome))
        self.n_amostras = n_amostras
        porque = {
            "bin": self.tr("{} não tem o cabeçalho do SH-Analyzer (é do formato antigo do ler_adc)."),
            "csv": self.tr("{} é um .csv do adc_tool, que não guarda a taxa."),
            "h5": self.tr("{} foi exportado de um .bin sem o cabeçalho do SH-Analyzer."),
        }[tipo].format(nome)
        explicacao = QLabel(porque + " " + self.tr("Diga como a captura foi feita: o que o adc_tool pediria em "
                                                   "-f e --canais."))
        explicacao.setWordWrap(True)

        self.taxa = CampoComUnidade("Hz", sugestao.taxa_total_hz if sugestao is not None else 0.0, minimo=0.0,
                                    digitos=6)
        self.taxa.setObjectName("taxa_total")
        if sugestao is None:
            self.taxa.clear()
        self.taxa.setPlaceholderText(self.tr("ex.: 400k"))
        self.taxa.setToolTip(self.tr("A taxa de todos os canais somados (o -f do adc_tool); cada canal tem a taxa "
                                     "total dividida pelo número de canais."))
        canais = canais_do_arquivo if canais_do_arquivo is not None else \
            (sugestao.canais if sugestao is not None else ())
        self.canais = QLineEdit(", ".join(str(c) for c in canais))
        self.canais.setObjectName("canais")
        self.canais.setPlaceholderText(self.tr("ex.: 0, 1"))
        if canais_do_arquivo is not None:
            self.canais.setReadOnly(True)
            self.canais.setEnabled(False)
            self.canais.setToolTip(self.tr("O arquivo diz os canais."))
        else:
            self.canais.setToolTip(self.tr("Os canais do ADC (0 a 7) na ordem da intercalação do arquivo (o --canais "
                                           "do adc_tool)."))
        grade = QGridLayout()
        grade.setHorizontalSpacing(8)
        grade.setVerticalSpacing(6)
        for linha, (rotulo, campo) in enumerate(((self.tr("Taxa total"), self.taxa), (self.tr("Canais"), self.canais))):
            grade.addWidget(QLabel(rotulo), linha, 0)
            grade.addWidget(campo, linha, 1)
        grade.setColumnStretch(1, 1)

        self.resumo = QLabel()
        self.resumo.setObjectName("resumo_sem_cabecalho")
        self.resumo.setWordWrap(True)
        self.resumo.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        botoes = QDialogButtonBox()
        # Botões próprios, e não os padrão: o Qt não traz a tradução deles para o português.
        self.abrir = botoes.addButton(self.tr("Abrir"), QDialogButtonBox.ButtonRole.AcceptRole)
        self.abrir.setDefault(True)
        botoes.addButton(self.tr("Cancelar"), QDialogButtonBox.ButtonRole.RejectRole)
        botoes.accepted.connect(self.accept)
        botoes.rejected.connect(self.reject)

        coluna = QVBoxLayout(self)
        coluna.setContentsMargins(16, 16, 16, 16)
        coluna.setSpacing(12)
        coluna.addWidget(explicacao)
        coluna.addLayout(grade)
        coluna.addWidget(self.resumo)
        coluna.addWidget(botoes)
        self.setMinimumWidth(self.fontMetrics().averageCharWidth() * 60)
        for campo in (self.taxa, self.canais):
            campo.textChanged.connect(lambda _t: self._calcular())
        next((c for c in (self.taxa, self.canais) if c.isEnabled() and not c.text().strip()), self.taxa).setFocus()
        self._calcular()

    def parametros(self) -> ParametrosSemCabecalho:
        """A resposta como está escrita agora. Levanta ``ValueError`` com o motivo."""
        if not self.taxa.text().strip():
            raise ValueError(self.tr("falta a taxa total"))
        try:
            taxa = ler_numero(self.taxa.text(), "Hz")
        except NumeroInvalido as e:
            raise ValueError(self.tr("a taxa total: {}").format(e)) from None
        if not self.canais.text().strip():
            raise ValueError(self.tr("faltam os canais"))
        try:
            return ParametrosSemCabecalho.de_texto(taxa, self.canais.text())
        except ErroSHAN as e:
            raise ValueError(str(e).rstrip(".")) from None

    def _calcular(self) -> None:
        try:
            p = self.parametros()
        except ValueError as e:
            self.resumo.setText(self.tr("Não dá para abrir: {}.").format(e))
            self.abrir.setEnabled(False)
            return
        por_canal = p.taxa_total_hz / len(p.canais)
        partes = [self.tr("{} por canal").format(formatar_si(por_canal, "Hz", 6))]
        if self.n_amostras:
            n = self.n_amostras // len(p.canais)
            partes += [self.tr("{} amostras por canal").format(f"{n:,}".replace(",", "\u202f")),
                       self.tr("{} de captura").format(formatar_duracao(n / por_canal))]
        self.resumo.setText(" · ".join(partes))
        self.abrir.setEnabled(True)

    def accept(self) -> None:
        try:
            self.parametros()
        except ValueError:
            return                                  # o motivo já está embaixo; o diálogo fica
        super().accept()
