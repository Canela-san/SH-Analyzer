"""A barra lateral da Aquisição (o B1; docs/gui-plan.md, 13.2): no alto, o cartão da placa (o estado da conexão, o
caminho e o enlace, com o que fazer quando algo deu errado); as seções (Visão geral, Capturar, Arquivos, Terminal,
Diagnóstico, Manutenção); a lista de placas ao alcance, com "Conectar por IP…"; e, embaixo, "Desconectar"."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ...ajuda import botao_de_ajuda
from ...componentes.basicos import Botao
from ...componentes.painel import fonte_de_titulo
from ...servicos.conexao_da_placa import ConexaoDaPlaca
from ...tema.aplicar import aparencia
from ...tema.icones import IconeDoTema, icone_de_lista
from ...tema.tokens import TAMANHOS
from .placas import ListaDePlacas, Ponto
from .textos import caminho_curto, frase, hora, nome_da_placa, texto_do_enlace, titulo_do_cenario, traduzir

LARGURA = 248
SECOES = (("visao_geral", "Visão geral", "pulso"), ("capturar", "Capturar", "play"), ("rotinas", "Rotinas", "livro"),
          ("arquivos", "Arquivos", "pasta"),
          ("terminal", "Terminal", "terminal"), ("diagnostico", "Diagnóstico", "escudo"),
          ("manutencao", "Manutenção", "chave"))
NOMES_DAS_FONTES = {"USB": "o USB", "mDNS": "a rede local (mDNS)", "conhecidas": "as placas conhecidas",
                    "simulador": "o simulador"}


def _fonte(tamanho: str, peso: QFont.Weight | None = None) -> QFont:
    fonte = QFont()
    fonte.setPixelSize(TAMANHOS[tamanho])
    if peso is not None:
        fonte.setWeight(peso)
    return fonte


class CartaoDaPlaca(QFrame):
    """O alto da barra: a placa conectada (o nome, o nº de série, o caminho, o enlace e desde quando) ou o que está
    acontecendo (conectando, a resposta que falta, a queda, o bloqueio, a falha), com o botão do próximo passo.
    ``responder`` sai no "Responder" e no "Ver" (a área abre o diálogo da conexão)."""

    responder = Signal()

    def __init__(self, conexao: ConexaoDaPlaca, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("cartao_da_placa")
        self.conexao = conexao
        self.ponto = Ponto()
        self.titulo = QLabel()
        self.titulo.setObjectName("titulo_do_cartao")
        self.titulo.setFont(_fonte("corpo", QFont.Weight.DemiBold))
        self.titulo.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.linhas = []
        for nome in ("linha_1", "linha_2"):
            rotulo = QLabel()
            rotulo.setObjectName(nome)
            rotulo.setProperty("papel", "sub")
            rotulo.setFont(_fonte("secundario"))
            rotulo.setWordWrap(True)
            rotulo.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            self.linhas.append(rotulo)
        self.botao_principal = Botao("", "secundario")
        self.botao_principal.setObjectName("acao_do_cartao")
        self.botao_secundario = Botao("", "fantasma")
        self.botao_secundario.setObjectName("acao_secundaria_do_cartao")
        self.botao_principal.clicked.connect(lambda: self._agir(self.botao_principal))
        self.botao_secundario.clicked.connect(lambda: self._agir(self.botao_secundario))

        topo = QHBoxLayout()
        topo.setContentsMargins(0, 0, 0, 0)
        topo.setSpacing(8)
        topo.addWidget(self.ponto, 0, Qt.AlignmentFlag.AlignVCenter)
        topo.addWidget(self.titulo, 1)
        botoes = QHBoxLayout()
        botoes.setContentsMargins(0, 4, 0, 0)
        botoes.setSpacing(6)
        botoes.addWidget(self.botao_principal)
        botoes.addWidget(self.botao_secundario)
        botoes.addStretch(1)
        coluna = QVBoxLayout(self)
        coluna.setContentsMargins(12, 10, 12, 10)
        coluna.setSpacing(2)
        coluna.addLayout(topo)
        for rotulo in self.linhas:
            coluna.addWidget(rotulo)
        coluna.addLayout(botoes)
        conexao.mudou.connect(self.atualizar)
        self.atualizar()

    def _agir(self, botao: Botao) -> None:
        acao = botao.property("acao")
        if acao == "responder":
            self.responder.emit()
        elif acao == "tentar":
            self.conexao.tentar_de_novo()
        elif acao == "cancelar":
            self.conexao.cancelar()

    def _botoes(self, *pares: tuple[str, str]) -> None:
        for botao, par in zip((self.botao_principal, self.botao_secundario), (*pares, None, None), strict=False):
            botao.setVisible(par is not None)
            if par is not None:
                botao.setText(par[0])
                botao.setProperty("acao", par[1])

    def _linhas(self, *textos: str) -> None:
        for rotulo, texto in zip(self.linhas, (*textos, "", ""), strict=False):
            rotulo.setText(texto)
            rotulo.setToolTip(texto if len(texto) > 60 else "")
            rotulo.setVisible(bool(texto))

    def atualizar(self) -> None:
        c = self.conexao
        estado = c.estado
        alvo = str(c.destino) if c.destino is not None else traduzir("o simulador")
        if estado == "conectada" and c.simulada:
            desde = traduzir("desde as {}").format(hora(c.conectada_em)) if c.conectada_em else ""
            segunda = [traduzir("neste computador"), desde]
            if c.quedas:
                segunda.append(traduzir("caiu {}× e voltou").format(c.quedas))
            self._mostrar("ok", True, nome_da_placa(c), titulo_do_cenario(c), " · ".join(x for x in segunda if x))
        elif estado == "conectada":
            # Como no B1: "nº 3714BBBK1234 · USB · 192.168.6.2" e "latência 1 ms · 6,3 MB/s" (o resto, na dica e
            # na visão geral).
            serie = c.estado_da_placa.serie if c.estado_da_placa is not None else None
            curto = caminho_curto(c)
            primeira = " · ".join(x for x in (traduzir("nº {}").format(serie) if serie else "", curto,
                                              c.destino.host if c.destino is not None and c.destino.host != curto
                                              else "") if x)
            segunda = [texto_do_enlace(c)]
            if c.quedas:
                segunda.append(traduzir("caiu {}× e voltou").format(c.quedas))
            self._mostrar("ok", True, nome_da_placa(c), primeira, " · ".join(x for x in segunda if x))
            self.linhas[0].setToolTip(" · ".join(x for x in (c.detalhe_do_caminho, str(c.destino)) if x))
        elif estado == "conectando":
            self._mostrar("acento", True, traduzir("Conectando…"), alvo)
            self._botoes((traduzir("Cancelar"), "cancelar"))
            return
        elif estado in ("confirmar_host", "pedir_senha"):
            pedido = (c.destino_pedido or c.destino).conta
            texto = traduzir("Confira a impressão digital de {}.") if estado == "confirmar_host" else \
                traduzir("{} pede a senha.")
            self._mostrar("acento", True, traduzir("Esperando a sua resposta"), texto.format(pedido))
            self._botoes((traduzir("Responder"), "responder"), (traduzir("Cancelar"), "cancelar"))
            return
        elif estado == "reconectando" and c.queda_esperada == "reinicio":
            self._mostrar("aviso", True, nome_da_placa(c), traduzir("Reiniciando: a conexão volta sozinha."))
        elif estado == "reconectando":
            self._mostrar("aviso", True, nome_da_placa(c), traduzir("A conexão caiu: tentando de novo sozinho."),
                          frase(c.motivo))
        elif estado == "desligando":
            self._mostrar("aviso", True, nome_da_placa(c), traduzir("Desligando: ainda não a tire da tomada."))
        elif estado == "desconectada" and c.desligada:
            self._mostrar("mudo", False, traduzir("A placa desligou"),
                          frase(c.aviso_do_desligamento) or traduzir("Já pode tirar da tomada."))
        elif estado == "bloqueada":
            conta = c.bloqueio.destino.conta if c.bloqueio is not None else alvo
            self._mostrar("erro", True, traduzir("Conexão bloqueada"),
                          traduzir("A chave de host de {} mudou. Nada foi enviado.").format(conta))
            self._botoes((traduzir("Ver"), "responder"), (traduzir("Fechar"), "cancelar"))
            return
        elif estado == "falhou":
            self._mostrar("erro", True, traduzir("Sem conexão"), frase(c.motivo))
            self._botoes((traduzir("Tentar de novo"), "tentar"), (traduzir("Fechar"), "cancelar"))
            return
        else:
            self._mostrar("mudo", False, traduzir("Nenhuma placa conectada"),
                          traduzir("Escolha uma placa na lista abaixo, ou conecte por IP."))
        self._botoes()

    def _mostrar(self, papel: str, cheio: bool, titulo: str, *linhas: str) -> None:
        self.ponto.definir(papel, cheio)
        self.titulo.setText(self.titulo.fontMetrics().elidedText(titulo, Qt.TextElideMode.ElideRight, LARGURA - 70))
        self.titulo.setToolTip(titulo)
        self.setProperty("nivel", papel)
        self._linhas(*linhas)


class NavegacaoDaAquisicao(QListWidget):
    """As seções do B1, com o ícone na cor do acento na escolhida. ``secaoEscolhida(nome)`` a cada troca."""

    secaoEscolhida = Signal(str)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("navegacao_aquisicao")
        self.setIconSize(QSize(16, 16))
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        for nome, titulo, _icone in SECOES:
            item = QListWidgetItem(traduzir(titulo))
            item.setData(Qt.ItemDataRole.UserRole, nome)
            item.setSizeHint(QSize(0, 34))
            self.addItem(item)
        self.currentRowChanged.connect(lambda linha: self.secaoEscolhida.emit(SECOES[linha][0]) if linha >= 0
                                       else None)
        self.setFixedHeight(len(SECOES) * 34 + 2 * self.frameWidth() + 2)
        aparencia().mudou.connect(self._tema_mudou)
        self._tema_mudou()

    def _tema_mudou(self, _tema=None) -> None:
        t = aparencia().tema
        for linha, (_nome, _titulo, nome_do_icone) in enumerate(SECOES):
            self.item(linha).setIcon(icone_de_lista(nome_do_icone, t.texto2, t.acento))

    def escolher(self, nome: str) -> None:
        self.setCurrentRow([s[0] for s in SECOES].index(nome))

    @property
    def secao(self) -> str:
        return SECOES[max(0, self.currentRow())][0]


class BarraLateral(QWidget):
    """A coluna da esquerda da Aquisição. ``conectarPorIp`` e ``responder`` (o cartão) vão para a área, que abre o
    diálogo da conexão; ``conectadaClicada`` (a placa conectada na lista), também, que mostra a visão geral."""

    conectarPorIp = Signal()

    def __init__(self, conexao: ConexaoDaPlaca, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("lateral_aquisicao")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedWidth(LARGURA)
        self.conexao = conexao
        self.cartao = CartaoDaPlaca(conexao)
        self.navegacao = NavegacaoDaAquisicao()

        titulo = QLabel(traduzir("Placas").upper())
        titulo.setObjectName("titulo_painel_texto")
        titulo.setFont(fonte_de_titulo())
        self.botao_procurar = QToolButton()
        self.botao_procurar.setObjectName("procurar_placas")
        self.botao_procurar.setProperty("variante", "fantasma")
        self.botao_procurar.setAutoRaise(True)
        self.botao_procurar.setIconSize(QSize(14, 14))
        self.botao_procurar.setFixedSize(QSize(24, 24))
        IconeDoTema(self.botao_procurar, "girar", "texto2", tamanho=14)
        self.botao_procurar.clicked.connect(conexao.procurar)
        cabecalho = QHBoxLayout()
        cabecalho.setContentsMargins(18, 14, 10, 4)
        cabecalho.addWidget(titulo)
        cabecalho.addStretch(1)
        cabecalho.addWidget(self.botao_procurar)
        cabecalho.addWidget(botao_de_ajuda("aquisicao"))

        self.lista = ListaDePlacas(conexao)
        self.aviso_da_lista = QLabel()
        self.aviso_da_lista.setObjectName("aviso_da_lista")
        self.aviso_da_lista.setFont(_fonte("secundario"))
        self.aviso_da_lista.setWordWrap(True)
        self.por_ip = QToolButton()
        self.por_ip.setObjectName("conectar_por_ip")
        self.por_ip.setText(traduzir("Conectar por IP…"))
        self.por_ip.setToolTip(traduzir("Conectar a uma placa pelo endereço (host, porta, usuário e, se precisar, "
                                        "um salto)"))
        self.por_ip.setProperty("variante", "fantasma")
        self.por_ip.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.por_ip.setIconSize(QSize(16, 16))
        self.por_ip.setAutoRaise(True)
        IconeDoTema(self.por_ip, "mais", "acento")
        self.por_ip.clicked.connect(self.conectarPorIp)

        self.desconectar = Botao(traduzir("Desconectar"), "secundario", "x")
        self.desconectar.setObjectName("desconectar_placa")
        self.desconectar.clicked.connect(conexao.desconectar)
        self.rodape = rodape = QFrame()
        rodape.setObjectName("rodape_lateral")
        linha = QHBoxLayout(rodape)
        linha.setContentsMargins(10, 10, 10, 10)
        linha.addWidget(self.desconectar, 1)

        coluna = QVBoxLayout(self)
        coluna.setContentsMargins(0, 0, 0, 0)
        coluna.setSpacing(0)
        externo = QVBoxLayout()
        externo.setContentsMargins(10, 10, 10, 8)
        externo.addWidget(self.cartao)
        coluna.addLayout(externo)
        navegacao = QVBoxLayout()
        navegacao.setContentsMargins(8, 0, 8, 0)
        navegacao.addWidget(self.navegacao)
        coluna.addLayout(navegacao)
        coluna.addLayout(cabecalho)
        lista = QVBoxLayout()
        lista.setContentsMargins(0, 0, 0, 0)
        lista.setSpacing(2)
        lista.addWidget(self.lista)
        aviso = QHBoxLayout()
        aviso.setContentsMargins(18, 0, 10, 0)
        aviso.addWidget(self.aviso_da_lista)
        lista.addLayout(aviso)
        por_ip = QHBoxLayout()
        por_ip.setContentsMargins(10, 0, 10, 0)
        por_ip.addWidget(self.por_ip)
        por_ip.addStretch(1)
        lista.addLayout(por_ip)
        coluna.addLayout(lista)
        coluna.addStretch(1)
        coluna.addWidget(rodape)

        conexao.placasMudaram.connect(self._placas_mudaram)
        conexao.mudou.connect(self._conexao_mudou)
        self._placas_mudaram()
        self._conexao_mudou()

    def _placas_mudaram(self) -> None:
        c = self.conexao
        if not c.placas:
            texto = traduzir("Procurando…") if c.procurando or not c.falhas_da_busca else \
                traduzir("Nenhuma placa achada.")
        else:
            texto = ""
        if c.falhas_da_busca:
            nomes = [NOMES_DAS_FONTES.get(f.split(":")[0], f.split(":")[0]) for f in c.falhas_da_busca]
            texto = " ".join(x for x in (texto, traduzir("Não deu para procurar por {}.").format(", ".join(nomes)))
                             if x)
        self.aviso_da_lista.setText(texto)
        self.aviso_da_lista.setToolTip("\n".join(c.falhas_da_busca))
        self.aviso_da_lista.setVisible(bool(texto))
        self.lista.setVisible(bool(c.placas))
        self.botao_procurar.setToolTip(traduzir("Procurando as placas…") if c.procurando
                                       else traduzir("Procurar as placas de novo"))

    def _conexao_mudou(self) -> None:
        self.rodape.setVisible(self.conexao.estado in ("conectada", "reconectando"))
