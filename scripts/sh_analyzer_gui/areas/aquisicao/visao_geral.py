"""A visão geral da placa (o B1; docs/gui-plan.md, 11.4; a F3.6).

Com a placa conectada:

* **o cabeçalho:** o modelo, o nº de série, o sistema, o kernel e o firmware (e se ele é o deste aplicativo,
  comparado pelo código);
* **os indicadores:** o relógio (a diferença para o computador e quando foi acertado), a PRU0, o cartão (o espaço e
  os minutos de captura que cabem), o processador (a temperatura, a carga, a memória) e a placa de aquisição (a última
  conferência na placa);
* **a saúde resumida:** a conexão e cada item do diagnóstico, os problemas primeiro, com o "Corrigir" dos dois
  simples (os pinos e o relógio), que a área confirma num diálogo antes de rodar;
* **as capturas na placa**, com a integridade de cada uma, e **a atividade:** cada comando que o aplicativo rodou
  na placa, ao vivo.

Sem placa, ela diz o que fazer; conectando, o que está acontecendo; com uma falha, o motivo e o "Tentar de novo".
"""

from __future__ import annotations

import time
from pathlib import PurePosixPath

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QSizePolicy,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from sh_placa.diagnostico import ItemDoDiagnostico
from sh_placa.registro import Entrada

from ...componentes.basicos import Botao
from ...componentes.numeros import decimal, formatar_bytes, formatar_duracao, formatar_si
from ...componentes.painel import EstadoVazio
from ...servicos.conexao_da_placa import ConexaoDaPlaca
from ...servicos.saude_da_placa import SaudeDaPlaca
from ...tema.fontes import fonte_mono
from ...tema.tokens import TAMANHOS
from .arquivos import estado_no_computador
from .itens import TEXTOS_DAS_CORRECOES, itens_da_placa
from .pecas import IconeDoNivel, Indicador, Painel, Selo, fonte
from .textos import frase, hora, nome_da_placa, traduzir

LARGURA_DO_TEXTO_VAZIO = 440
ATIVIDADE_MAXIMA = 200
ESTADOS_DA_PRU = {"running": ("Rodando", "ok"), "offline": ("Parada", ""), "crashed": ("Com falha", "erro"),
                  "suspended": ("Suspensa", "aviso")}


def texto_da_diferenca(segundos: float) -> str:
    """"+1,14 s", "−0,02 s" (o sinal de menos tipográfico, como no B1)."""
    return decimal(f"{segundos:+.2f}").replace("-", "−") + " s"


class LinhaDaSaude(QWidget):
    """Uma linha da saúde resumida: o ícone do nível, o título, os fatos e, à direita, o selo ou o "Corrigir"."""

    def __init__(self, item: ItemDoDiagnostico, ao_corrigir, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("linha_da_saude")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.item = item
        self.icone = IconeDoNivel(item.nivel)
        problema = item.problemas[0].texto if item.problemas and item.nivel in ("aviso", "erro") else ""
        self.titulo = QLabel(problema or item.titulo)
        self.titulo.setObjectName("titulo_da_linha")
        self.titulo.setWordWrap(True)
        self.resumo = QLabel(item.resumo if not problema else f"{item.titulo} · {item.resumo}")
        self.resumo.setObjectName("resumo_da_linha")
        self.resumo.setFont(fonte("secundario"))
        self.resumo.setWordWrap(True)
        self.setToolTip("\n".join([f"{item.titulo}: {item.resumo}",
                                   *(f"• {p.texto}" + (f"\n  Correção: {p.correcao}" if p.correcao else "")
                                     for p in item.problemas)]))
        textos = QVBoxLayout()
        textos.setSpacing(1)
        textos.addWidget(self.titulo)
        textos.addWidget(self.resumo)
        linha = QHBoxLayout(self)
        linha.setContentsMargins(14, 8, 14, 8)
        linha.setSpacing(12)
        linha.addWidget(self.icone, 0, Qt.AlignmentFlag.AlignTop)
        linha.addLayout(textos, 1)
        self.acao: Botao | None = None
        if item.correcao is not None:
            self.acao = Botao(traduzir(TEXTOS_DAS_CORRECOES[item.correcao]), "secundario")
            self.acao.setObjectName(f"corrigir_{item.correcao}")
            self.acao.clicked.connect(lambda: ao_corrigir(item.correcao))
            linha.addWidget(self.acao, 0, Qt.AlignmentFlag.AlignVCenter)
        else:
            linha.addWidget(Selo(item.nivel), 0, Qt.AlignmentFlag.AlignVCenter)


class VisaoGeral(QWidget):
    """A seção "Visão geral". ``conectarPorIp`` sai no botão do estado vazio, ``verBloqueio`` no da conexão
    bloqueada e ``corrigir(nome)`` no "Corrigir" de um item (a área confirma e roda)."""

    conectarPorIp = Signal()
    verBloqueio = Signal()
    corrigir = Signal(str)

    def __init__(self, conexao: ConexaoDaPlaca, saude: SaudeDaPlaca, transferencias=None,
                 parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("visao_geral")
        self.conexao, self.saude, self.transferencias = conexao, saude, transferencias
        self.paginas = QStackedWidget()

        por_ip = Botao(traduzir("Conectar por IP…"), "primario", "mais")
        por_ip.setObjectName("conectar_por_ip_vazio")
        por_ip.clicked.connect(self.conectarPorIp)
        self.vazia = EstadoVazio(
            traduzir("Nenhuma placa conectada"),
            traduzir("Escolha uma placa na lista à esquerda: as do USB e da rede local aparecem sozinhas, e o "
                     "simulador está sempre lá. Para uma placa em outra rede, conecte pelo endereço."),
            icone_nome="chip", botao=por_ip, largura_do_texto=LARGURA_DO_TEXTO_VAZIO)
        cancelar = Botao(traduzir("Cancelar"), "secundario")
        cancelar.clicked.connect(conexao.cancelar)
        self.conectando = EstadoVazio(traduzir("Conectando…"), "", icone_nome="usb", botao=cancelar,
                                      largura_do_texto=LARGURA_DO_TEXTO_VAZIO)
        self.botao_de_tentar = Botao(traduzir("Tentar de novo"), "primario", "girar")
        self.botao_de_tentar.setObjectName("tentar_de_novo_vazio")
        self.botao_de_tentar.clicked.connect(self._agir_na_falha)
        self.falha = EstadoVazio(traduzir("Sem conexão"), "", icone_nome="alerta", botao=self.botao_de_tentar,
                                 largura_do_texto=LARGURA_DO_TEXTO_VAZIO)
        self.conectada = self._criar_conectada()
        for pagina in (self.vazia, self.conectando, self.falha, self.conectada):
            self.paginas.addWidget(pagina)
        coluna = QVBoxLayout(self)
        coluna.setContentsMargins(0, 0, 0, 0)
        coluna.addWidget(self.paginas)
        conexao.mudou.connect(self.atualizar)
        saude.mudou.connect(self.atualizar)
        saude.atividade.connect(self._nova_atividade)
        if transferencias is not None:
            transferencias.mudou.connect(self.atualizar)
        for entrada in conexao.registro.entradas[-ATIVIDADE_MAXIMA:]:
            self._nova_atividade(entrada)
        self.atualizar()

    # ------------------------------------------------------------------ montar

    def _criar_conectada(self) -> QWidget:
        pagina = QWidget()
        self.titulo = QLabel(traduzir("Visão geral"))
        self.titulo.setObjectName("titulo_da_secao")
        self.titulo.setFont(fonte("tela", QFont.Weight.DemiBold))
        self.subtitulo = QLabel()
        self.subtitulo.setObjectName("subtitulo_da_secao")
        self.subtitulo.setWordWrap(True)
        self.subtitulo.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.botao_conferir = Botao(traduzir("Conferir de novo"), "secundario", "girar")
        self.botao_conferir.setObjectName("conferir_de_novo")
        self.botao_conferir.clicked.connect(self.saude.conferir)
        cabecalho = QHBoxLayout()
        textos = QVBoxLayout()
        textos.setSpacing(2)
        textos.addWidget(self.titulo)
        textos.addWidget(self.subtitulo)
        cabecalho.addLayout(textos, 1)
        cabecalho.addWidget(self.botao_conferir, 0, Qt.AlignmentFlag.AlignTop)

        self.relogio = Indicador(traduzir("Relógio"), "relogio")
        self.pru = Indicador(traduzir("PRU0"), "chip")
        self.cartao = Indicador(traduzir("Cartão"), "disco", com_barra=True)
        self.processador = Indicador(traduzir("Processador"), "pulso")
        self.aquisicao = Indicador(traduzir("Placa de aquisição"), "raio")
        faixa = QGridLayout()
        faixa.setSpacing(12)
        for i, indicador in enumerate((self.relogio, self.pru, self.cartao, self.processador, self.aquisicao)):
            indicador.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            faixa.addWidget(indicador, 0, i)
            faixa.setColumnStretch(i, 1)

        self.painel_da_saude = Painel(traduzir("Saúde da placa"))
        self.conferida = QLabel()
        self.conferida.setObjectName("conferida_em")
        self.conferida.setFont(fonte("secundario"))
        self.painel_da_saude.lado.addWidget(self.conferida)
        self.linhas: dict[str, LinhaDaSaude] = {}          # as linhas de agora, pela chave do item
        self.linhas_da_saude = QVBoxLayout()
        self.linhas_da_saude.setContentsMargins(0, 0, 0, 0)
        self.linhas_da_saude.setSpacing(0)
        self.painel_da_saude.corpo.addLayout(self.linhas_da_saude)
        self.painel_da_saude.corpo.addStretch(1)

        self.painel_das_capturas = Painel(traduzir("Capturas na placa"))
        self.pasta_das_capturas = QLabel()
        self.pasta_das_capturas.setObjectName("pasta_das_capturas")
        self.pasta_das_capturas.setFont(fonte("secundario"))
        self.painel_das_capturas.lado.addWidget(self.pasta_das_capturas)
        self.tabela = QTableWidget(0, 6)
        self.tabela.setObjectName("capturas_na_placa")
        self.tabela.setHorizontalHeaderLabels([traduzir(t) for t in ("Arquivo", "Início", "Duração", "Taxa", "Tamanho",
                                                                     "Estado")])
        self.tabela.verticalHeader().hide()
        self.tabela.setShowGrid(False)
        self.tabela.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tabela.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.tabela.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        cabeca = self.tabela.horizontalHeader()
        cabeca.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for coluna in range(1, 5):
            cabeca.setSectionResizeMode(coluna, QHeaderView.ResizeMode.ResizeToContents)
        cabeca.setSectionResizeMode(5, QHeaderView.ResizeMode.Fixed)      # o selo é um widget: o Qt não o mede
        cabeca.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.sem_capturas = QLabel(traduzir("Nenhuma captura na pasta do firmware."))
        self.sem_capturas.setObjectName("texto_mudo")
        self.sem_capturas.setContentsMargins(14, 8, 14, 12)
        self.painel_das_capturas.corpo.addWidget(self.tabela, 1)
        self.painel_das_capturas.corpo.addWidget(self.sem_capturas)

        self.painel_da_atividade = Painel(traduzir("Atividade"))
        legenda = QLabel(traduzir("tudo o que o aplicativo fez na placa"))
        legenda.setObjectName("texto_mudo")
        legenda.setFont(fonte("secundario"))
        self.painel_da_atividade.lado.addWidget(legenda)
        self.atividade = QListWidget()
        self.atividade.setObjectName("atividade")
        self.atividade.setFont(fonte_mono(TAMANHOS["secundario"]))
        self.atividade.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.atividade.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.atividade.setWordWrap(False)
        self.atividade.setTextElideMode(Qt.TextElideMode.ElideRight)            # a linha inteira fica na dica
        self.atividade.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.painel_da_atividade.corpo.addWidget(self.atividade, 1)
        self.painel_da_atividade.setMinimumHeight(150)

        direita = QVBoxLayout()
        direita.setSpacing(16)
        direita.addWidget(self.painel_das_capturas, 3)
        direita.addWidget(self.painel_da_atividade, 2)
        duas = QHBoxLayout()
        duas.setSpacing(16)
        duas.addWidget(self.painel_da_saude, 4)
        duas.addLayout(direita, 5)

        coluna = QVBoxLayout(pagina)
        coluna.setContentsMargins(24, 20, 24, 20)
        coluna.setSpacing(16)
        coluna.addLayout(cabecalho)
        coluna.addLayout(faixa)
        coluna.addLayout(duas, 1)
        return pagina

    # ------------------------------------------------------------------ atualizar

    def atualizar(self) -> None:
        c = self.conexao
        estado = c.estado
        if estado in ("conectada", "reconectando"):
            self._preencher()
            self.paginas.setCurrentWidget(self.conectada)
        elif estado in ("conectando", "confirmar_host", "pedir_senha"):
            alvo = str(c.destino) if c.destino is not None else traduzir("o simulador")
            self.conectando.texto.setText(traduzir("A caminho de {}.").format(alvo) if estado == "conectando" else
                                          traduzir("A conexão espera a sua resposta, no diálogo da conexão."))
            self.conectando.texto.show()
            self.paginas.setCurrentWidget(self.conectando)
        elif estado == "bloqueada":
            conta = c.bloqueio.destino.conta if c.bloqueio is not None else ""
            self.falha.titulo.setText(traduzir("Conexão bloqueada"))
            self.falha.texto.setText(traduzir(
                "A placa em {} apresentou uma chave de host diferente da que este computador conhece, e nada foi "
                "enviado a ela. Pode ser uma placa regravada, ou alguém no meio da conexão.").format(conta))
            self.falha.texto.show()
            self.botao_de_tentar.setText(traduzir("Ver o que fazer"))
            self.paginas.setCurrentWidget(self.falha)
        elif estado == "falhou":
            self.falha.titulo.setText(traduzir("Sem conexão"))
            self.falha.texto.setText(frase(c.motivo))
            self.falha.texto.show()
            self.botao_de_tentar.setText(traduzir("Tentar de novo"))
            self.paginas.setCurrentWidget(self.falha)
        else:
            self.paginas.setCurrentWidget(self.vazia)

    def _agir_na_falha(self) -> None:
        if self.conexao.estado == "bloqueada":
            self.verBloqueio.emit()
        else:
            self.conexao.tentar_de_novo()

    def _preencher(self) -> None:
        c, s = self.conexao, self.saude
        e = s.saude or c.estado_da_placa
        partes = [nome_da_placa(c)]
        if e is not None:
            if e.serie and not c.simulada:
                partes.append(traduzir("nº {}").format(e.serie))
            partes += [x for x in (e.sistema, traduzir("kernel {}").format(e.kernel) if e.kernel else "") if x]
            versao = e.versao_do_firmware
            if versao is None:
                partes.append(traduzir("sem o firmware"))
            elif s.firmware_do_aplicativo is None:
                partes.append(traduzir("firmware {}").format(versao))
            elif versao == s.firmware_do_aplicativo:
                partes.append(traduzir("firmware {} (o deste aplicativo)").format(versao))
            else:
                partes.append(traduzir("firmware {} (o deste aplicativo é {})").format(versao, s.firmware_do_aplicativo))
        self.subtitulo.setText(" · ".join(partes))
        self.botao_conferir.setEnabled(not s.conferindo and c.estado == "conectada")
        self.botao_conferir.setText(traduzir("Conferindo…") if s.conferindo else traduzir("Conferir de novo"))
        if e is None:
            return
        self._preencher_indicadores(e)
        self._preencher_a_saude(e)
        self._preencher_as_capturas()

    def _preencher_indicadores(self, e) -> None:
        s = self.saude
        relogio = e.relogio
        if relogio is None:
            self.relogio.definir("—", traduzir("sem a hora da placa"))
        else:
            diferenca = relogio.diferenca_s()
            if s.aviso_do_relogio:
                detalhe, nivel = s.aviso_do_relogio, "aviso"
            elif s.relogio_acertado_em is not None:
                detalhe = traduzir("acertado pelo computador às {}").format(hora(s.relogio_acertado_em))
                nivel = ""
            elif relogio.sincronizado:
                detalhe, nivel = traduzir("sincronizado ({})").format(relogio.fonte), ""
            else:
                detalhe, nivel = traduzir("sem NTP: acerte pelo computador"), ""
            if abs(diferenca) > 2:
                nivel = "aviso"
            if relogio.incerteza_s is not None:
                detalhe = f"±{decimal(f'{relogio.incerteza_s:.2f}')} s · {detalhe}"
            self.relogio.definir(texto_da_diferenca(diferenca), detalhe, nivel)
        pru = e.pru
        if not pru:
            self.pru.definir(traduzir("Ausente"), traduzir("sem a PRU0 no remoteproc"), "erro")
        else:
            texto, nivel = ESTADOS_DA_PRU.get(pru.get("estado"), (str(pru.get("estado") or "?"), "aviso"))
            detalhes = [traduzir("protocolo {}").format(e.protocolo_da_pru) if e.protocolo_da_pru else "",
                        str(pru.get("firmware") or "")]
            self.pru.definir(traduzir(texto), " · ".join(x for x in detalhes if x), nivel)
        disco = e.disco_bytes
        if disco is None:
            self.cartao.definir("—", traduzir("o espaço livre não deu para ler"))
        else:
            livre, total = disco
            minutos = e.minutos_de_captura_no_disco
            detalhe = traduzir("livres de {}").format(formatar_bytes(total))
            if minutos is not None:
                detalhe += " · " + traduzir("≈ {} a 400 kS/s").format(formatar_duracao(round(minutos) * 60))
            self.cartao.definir(formatar_bytes(livre), detalhe, "aviso" if livre < 0.1 * total else "",
                                uso=1 - livre / total)
        # A temperatura, se a placa tem o sensor (a imagem da BeagleBone Black não expõe um); senão, a carga.
        temperatura, carga = e.temperatura_c, e.carga
        detalhes = []
        if temperatura is not None and carga is not None:
            detalhes.append(traduzir("carga {}").format(decimal(f"{carga:.2f}")))
        if e.memoria_disponivel_bytes is not None:
            detalhes.append(traduzir("{} de memória livres").format(formatar_bytes(e.memoria_disponivel_bytes)))
        if temperatura is not None:
            valor = f"{temperatura:.0f} °C"
        elif carga is not None:
            valor = traduzir("carga {}").format(decimal(f"{carga:.2f}"))
        else:
            valor = "—"
        self.processador.definir(valor, " · ".join(detalhes),
                                 "aviso" if temperatura is not None and temperatura >= 75 else "")
        self._preencher_a_aquisicao()

    def _preencher_a_aquisicao(self) -> None:
        capturas = self.saude.capturas
        conferencias = [c for c in (capturas.capturas if capturas is not None else ())
                        if PurePosixPath(c.arquivo).name.startswith("conferir")]
        if capturas is None:
            self.aquisicao.definir("…", traduzir("lendo as capturas"))
        elif not conferencias:
            self.aquisicao.definir("—", traduzir("nenhuma conferência na placa; a conferência curta do ADC chega com "
                                                 "o Capturar"))
        else:
            ultima = max(conferencias, key=lambda c: c.inicio)
            nivel = "aviso" if ultima.problemas else ""
            self.aquisicao.definir(time.strftime("%d/%m %H:%M", time.localtime(ultima.inicio)),
                                   traduzir("a última conferência ({})").format(PurePosixPath(ultima.arquivo).name),
                                   nivel)

    def _preencher_a_saude(self, e) -> None:
        s = self.saude
        if s.conferindo:
            self.conferida.setText(traduzir("conferindo…"))
        elif s.erro:
            self.conferida.setText(traduzir("a conferência falhou"))
            self.conferida.setToolTip(frase(s.erro))
        elif s.conferida_em is not None:
            self.conferida.setText(traduzir("conferida às {}").format(time.strftime("%H:%M:%S",
                                                                                   time.localtime(s.conferida_em))))
        while self.linhas_da_saude.count():
            widget = self.linhas_da_saude.takeAt(0).widget()
            if widget is not None:
                widget.hide()                          # já fora da tela; o Qt o apaga na volta do laço
                widget.deleteLater()
        self.linhas = {}
        for item in itens_da_placa(self.conexao, self.saude):
            if item.nivel == "ok" and item.chave in ("ferramentas", "overlays"):
                continue                               # o detalhe disso fica no diagnóstico
            self.linhas[item.chave] = LinhaDaSaude(item, self.corrigir.emit)
            self.linhas_da_saude.addWidget(self.linhas[item.chave])

    def _preencher_as_capturas(self) -> None:
        capturas = self.saude.capturas
        lista = sorted(capturas.capturas, key=lambda c: c.inicio, reverse=True) if capturas is not None else []
        self.tabela.setRowCount(len(lista))
        largura_do_selo = self.tabela.horizontalHeader().sectionSizeHint(5)
        for linha, c in enumerate(lista):
            valores = [c.arquivo, time.strftime("%d/%m %H:%M", time.localtime(c.inicio)),
                       formatar_duracao(c.duracao_s) if c.duracao_s else "—",
                       formatar_si(c.taxa_hz, "S/s", 3) if c.taxa_hz else "—", formatar_bytes(c.bytes)]
            for coluna, valor in enumerate(valores):
                item = QTableWidgetItem(valor)
                item.setToolTip(c.titulo or c.arquivo)
                if coluna in (2, 3, 4):
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.tabela.setItem(linha, coluna, item)
            n = len(c.problemas)
            if self.transferencias is not None:              # onde ela está (como no B1), com a integridade na dica
                texto, nivel = estado_no_computador(self.transferencias, c)
                selo = Selo("aviso" if n and nivel == "ok" else nivel, texto)
            else:
                selo = Selo("aviso" if n else "ok", (traduzir("1 problema") if n == 1 else
                                                     traduzir("{} problemas").format(n)) if n else traduzir("íntegra"))
            selo.setToolTip("\n".join(c.problemas) or traduzir("íntegra"))
            selo.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.tabela.setCellWidget(linha, 5, selo)
            largura_do_selo = max(largura_do_selo, selo.sizeHint().width() + 16)
        self.tabela.setColumnWidth(5, largura_do_selo)
        self.tabela.setVisible(bool(lista))
        self.sem_capturas.setVisible(capturas is not None and not lista)
        if capturas is None:
            self.pasta_das_capturas.setText(traduzir("lendo…"))
        else:
            self.pasta_das_capturas.setText(traduzir("{} · {}").format(
                traduzir("{} captura(s)").format(capturas.total), formatar_bytes(capturas.bytes)))

    def _nova_atividade(self, entrada: Entrada) -> None:
        texto = f"{entrada.hora}  {entrada.descricao}"
        if entrada.tipo == "comando":
            fim = entrada.falha if entrada.codigo is None else traduzir("código {}").format(entrada.codigo)
            texto += f"  ({decimal(f'{entrada.duracao_s:.2f}')} s, {fim})"
        item = QListWidgetItem(texto)
        item.setToolTip(entrada.em_texto())
        if entrada.tipo == "comando" and entrada.codigo not in (0, None) or entrada.falha:
            item.setData(Qt.ItemDataRole.UserRole, "aviso")
        self.atividade.insertItem(0, item)
        while self.atividade.count() > ATIVIDADE_MAXIMA:
            self.atividade.takeItem(self.atividade.count() - 1)


SECOES_QUE_CHEGAM = {
    "capturar": ("Capturar", "play", "v0.10",
                 "O formulário do cabeçalho e dos canais, validado enquanto se escreve; o sinal ao vivo, com os "
                 "contadores de integridade; e a saída contínua direto para o computador."),
    "terminal": ("Terminal", "terminal", "v0.10",
                 "Um terminal na placa, com abas, busca, os atalhos de comandos e a gravação na pasta da sessão."),
    "manutencao": ("Manutenção", "chave", "v1.0",
                   "Atualizar o firmware, o assistente de pinos e overlays, os logs filtrados, reiniciar e desligar "
                   "com segurança."),
}


class SecaoQueChega(EstadoVazio):
    """Uma seção que ainda não existe: o que ela vai ter e em que versão chega."""

    def __init__(self, nome: str, parent: QWidget | None = None):
        titulo, nome_do_icone, versao, texto = SECOES_QUE_CHEGAM[nome]
        super().__init__(traduzir("{}: chega na {}").format(traduzir(titulo), versao), traduzir(texto),
                         icone_nome=nome_do_icone, largura_do_texto=LARGURA_DO_TEXTO_VAZIO, parent=parent)
        self.setObjectName(f"secao_{nome}")
