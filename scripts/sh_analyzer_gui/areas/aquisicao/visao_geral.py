"""A visão geral da placa (o B1; docs/gui-plan.md, 11.4). Nesta etapa (a F3.5): o cabeçalho da placa conectada (o
modelo, o nº de série, o sistema, o kernel e o firmware) e o enlace (o caminho, a latência, a vazão e desde quando).
Os indicadores, a saúde e as capturas chegam na F3.6.

Sem placa, ela diz o que fazer; conectando, o que está acontecendo; com uma falha, o motivo e o "Tentar de novo".
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ...componentes.basicos import Botao, RotuloDeIcone
from ...componentes.painel import EstadoVazio
from ...servicos.conexao_da_placa import ConexaoDaPlaca
from ...tema.tokens import TAMANHOS
from .textos import (
    caminho_curto,
    frase,
    hora,
    nome_da_placa,
    texto_da_folga,
    texto_da_latencia,
    texto_da_vazao,
    traduzir,
)

LARGURA_DO_TEXTO_VAZIO = 440


def _fonte(tamanho: str, peso: QFont.Weight | None = None) -> QFont:
    fonte = QFont()
    fonte.setPixelSize(TAMANHOS[tamanho])
    if peso is not None:
        fonte.setWeight(peso)
    return fonte


class Indicador(QFrame):
    """Um cartão da faixa de indicadores do B1: o rótulo com o ícone, o valor grande e uma linha do que ele quer
    dizer."""

    def __init__(self, rotulo: str, nome_do_icone: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("indicador")
        self.icone = RotuloDeIcone(nome_do_icone)
        self.rotulo = QLabel(rotulo)
        self.rotulo.setObjectName("rotulo_do_indicador")
        self.rotulo.setFont(_fonte("secundario"))
        self.valor = QLabel("—")
        self.valor.setObjectName("valor_do_indicador")
        self.valor.setFont(_fonte("secao", QFont.Weight.DemiBold))
        self.valor.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.detalhe = QLabel()
        self.detalhe.setObjectName("detalhe_do_indicador")
        self.detalhe.setFont(_fonte("secundario"))
        self.detalhe.setWordWrap(True)
        topo = QHBoxLayout()
        topo.setSpacing(6)
        topo.addWidget(self.icone)
        topo.addWidget(self.rotulo)
        topo.addStretch(1)
        coluna = QVBoxLayout(self)
        coluna.setContentsMargins(14, 12, 14, 12)
        coluna.setSpacing(2)
        coluna.addLayout(topo)
        coluna.addWidget(self.valor)
        coluna.addWidget(self.detalhe)
        coluna.addStretch(1)

    def definir(self, valor: str, detalhe: str = "", nivel: str = "") -> None:
        self.valor.setText(valor)
        self.valor.setProperty("nivel", nivel)
        self.valor.style().unpolish(self.valor)
        self.valor.style().polish(self.valor)
        self.detalhe.setText(detalhe)
        self.detalhe.setVisible(bool(detalhe))


class VisaoGeral(QWidget):
    """A seção "Visão geral". ``conectarPorIp`` sai no botão do estado vazio e ``verBloqueio``, no da conexão
    bloqueada (a área abre o diálogo da conexão)."""

    conectarPorIp = Signal()
    verBloqueio = Signal()

    def __init__(self, conexao: ConexaoDaPlaca, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("visao_geral")
        self.conexao = conexao
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
        self.atualizar()

    def _criar_conectada(self) -> QWidget:
        pagina = QWidget()
        self.titulo = QLabel(traduzir("Visão geral"))
        self.titulo.setObjectName("titulo_da_secao")
        self.titulo.setFont(_fonte("tela", QFont.Weight.DemiBold))
        self.subtitulo = QLabel()
        self.subtitulo.setObjectName("subtitulo_da_secao")
        self.subtitulo.setWordWrap(True)
        self.subtitulo.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.caminho = Indicador(traduzir("Caminho"), "usb")
        self.latencia = Indicador(traduzir("Latência"), "relogio")
        self.vazao = Indicador(traduzir("Vazão"), "baixar")
        self.desde = Indicador(traduzir("Conectada"), "link")
        faixa = QGridLayout()
        faixa.setSpacing(12)
        for i, indicador in enumerate((self.caminho, self.latencia, self.vazao, self.desde)):
            indicador.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            faixa.addWidget(indicador, 0, i)
            faixa.setColumnStretch(i, 1)
        self.a_seguir = EstadoVazio(
            traduzir("O resto da visão geral chega na v0.10"),
            traduzir("O relógio, a PRU, o cartão, o processador e a placa de aquisição; a saúde da placa, com o "
                     "\"Corrigir\" de cada problema; as capturas na placa e o registro de atividade."),
            icone_nome="pulso", compacto=True, largura_do_texto=LARGURA_DO_TEXTO_VAZIO)
        coluna = QVBoxLayout(pagina)
        coluna.setContentsMargins(24, 20, 24, 20)
        coluna.setSpacing(16)
        cabecalho = QVBoxLayout()
        cabecalho.setSpacing(2)
        cabecalho.addWidget(self.titulo)
        cabecalho.addWidget(self.subtitulo)
        coluna.addLayout(cabecalho)
        coluna.addLayout(faixa)
        coluna.addWidget(self.a_seguir, 1)
        return pagina

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
        c = self.conexao
        e = c.estado_da_placa
        partes = [nome_da_placa(c)]
        if e is not None:
            if e.serie and not c.simulada:
                partes.append(traduzir("nº {}").format(e.serie))
            partes += [x for x in (e.sistema, traduzir("kernel {}").format(e.kernel) if e.kernel else "",
                                   traduzir("firmware {}").format(e.versao_do_firmware) if e.versao_do_firmware
                                   else traduzir("sem o firmware")) if x]
        self.subtitulo.setText(" · ".join(partes))
        if c.simulada:
            self.caminho.definir(traduzir("Simulador"), traduzir("neste computador, sem rede"))
        else:
            como = traduzir("com a chave do aplicativo") if c.autenticada_com == "chave" else traduzir("com a senha")
            self.caminho.definir(caminho_curto(c) or "—", " · ".join(
                x for x in (c.detalhe_do_caminho, str(c.destino) if c.destino else "", como) if x))
        enlace = c.enlace
        if c.simulada:
            self.latencia.definir("—", traduzir("sem rede no simulador"))
            self.vazao.definir("—", traduzir("sem rede no simulador"))
        elif c.estado == "reconectando":
            self.latencia.definir("—", traduzir("a conexão caiu"), "aviso")
            self.vazao.definir("—", traduzir("a conexão caiu"), "aviso")
        elif c.medindo_enlace or (enlace is None and not c.erro_do_enlace):
            self.latencia.definir("…", traduzir("medindo"))
            self.vazao.definir("…", traduzir("medindo, num teste curto"))
        elif enlace is None:
            self.latencia.definir("—", frase(c.erro_do_enlace))
            self.vazao.definir("—", traduzir("não medida"))
        else:
            self.latencia.definir(texto_da_latencia(enlace.latencia_ms), traduzir("ida e volta pelo SSH"))
            if enlace.vazao_bytes_s:
                folga, da = texto_da_folga(enlace.vazao_bytes_s)
                self.vazao.definir(texto_da_vazao(enlace.vazao_bytes_s), folga, "" if da else "aviso")
            else:
                self.vazao.definir("—", traduzir("não deu para medir"))
        if c.estado == "reconectando":
            self.desde.definir(traduzir("Caiu"), traduzir("tentando de novo sozinho"), "aviso")
        else:
            quedas = traduzir("sem quedas") if not c.quedas else traduzir("caiu {}× e voltou").format(c.quedas)
            self.desde.definir(hora(c.conectada_em) if c.conectada_em else "—", quedas, "aviso" if c.quedas else "")


SECOES_QUE_CHEGAM = {
    "capturar": ("Capturar", "play", "v0.10",
                 "O formulário do cabeçalho e dos canais, validado enquanto se escreve; o sinal ao vivo, com os "
                 "contadores de integridade; e a saída contínua direto para o computador."),
    "arquivos": ("Arquivos", "pasta", "v0.10",
                 "As capturas da placa com o resumo de cada uma, a transferência com retomada, a conferência do CRC "
                 "e o \"Abrir na Análise\"."),
    "terminal": ("Terminal", "terminal", "v0.10",
                 "Um terminal na placa, com abas, busca, os atalhos de comandos e a gravação na pasta da sessão."),
    "diagnostico": ("Diagnóstico", "escudo", "v0.10",
                    "Cada conferência da placa (o relógio, a PRU, os pinos, a memória dos buffers, o firmware, o "
                    "disco), com o \"Corrigir\" das simples e o relatório para copiar."),
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
