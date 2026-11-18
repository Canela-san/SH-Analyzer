"""A seção Capturar da Aquisição (docs/gui-plan.md, 11.5; o B2, a F4.3): à esquerda, o formulário da captura
(``formulario_de_captura.py``); no centro, o comando montado, o que impede ou avisa e o "Conferir antes".

**A validação ao vivo:** a cada mudança do pedido (e do que se sabe da placa: o espaço no cartão, as capturas dele, a
vazão do enlace), ``sh_placa.pedido.validar`` com o :class:`~sh_placa.pedido.Contexto` daqui (os perfis da pasta das
sondas, o espaço livre na pasta da sessão do dia). Os problemas voltam ao formulário, cada um na seção do campo, e o
resumo deles fica no centro.

**Os modelos de captura** (o "Modelo:" do topo do formulário) são do projeto (``.shproj`` versão 4): guardar,
atualizar e apagar entram no desfazer. O formulário guarda o pedido da última vez nas preferências e volta com ele.

**"Conferir antes"** (``servicos/conferencia_da_placa.py``): um bloco do pedido, medido com as regras do
``coletar.sh conferir``; o resultado fica aqui, com a faixa sugerida de cada canal (o "usar" do formulário). Um pedido
que mudou depois da conferência (os canais, as faixas, a taxa, o SPI) pede outra.

**Capturar** chega na v0.10 (a F4.4): até lá, o botão diz como fazer pelo terminal, com o comando à vista.
"""

from __future__ import annotations

import shutil
import time
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMenu,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)
from sh_placa import pedido as pd
from sh_placa.conferencia import ConferenciaFeita, segundos_da_conferencia
from sh_placa.pedido import Contexto, PedidoDeCaptura, Problema

from ... import preferencias
from ...componentes.basicos import Botao
from ...componentes.numeros import formatar_bytes, formatar_duracao, formatar_si
from ...dados.projeto import ModeloDeCaptura
from ...modelo.comandos import ApagarModeloDeCaptura, GuardarModeloDeCaptura
from ...servicos.conexao_da_placa import ConexaoDaPlaca
from ...servicos.conferencia_da_placa import ConferenciaDaPlaca
from ...servicos.saude_da_placa import SaudeDaPlaca
from .formulario_de_captura import FormularioDeCaptura, ListaDeProblemas, texto_da_faixa
from .pecas import BlocoDeComando, IconeDoNivel, Painel, fonte
from .textos import frase, hora, traduzir

ATRASO_PARA_LEMBRAR_MS = 400
CAPTURAR_CHEGA = ("A captura pela interface chega na v0.10. Por enquanto, copie o comando e rode-o na pasta "
                  "~/firmware da placa (o Terminal da Aquisição abre uma sessão nela).")


def livre_em(pasta: Path) -> int | None:
    """O espaço livre no disco de ``pasta`` (a primeira pasta que existe no caminho dela)."""
    pasta = Path(pasta)
    for candidata in (pasta, *pasta.parents):
        if candidata.exists():
            try:
                return shutil.disk_usage(candidata).free
            except OSError:
                return None
    return None


def resumo_do_pedido(p: PedidoDeCaptura) -> str:
    """Uma frase do pedido: "2 canais · 400 kS/s · 10 min · 480 MB, direto no computador"."""
    partes = [traduzir("1 canal") if len(p.canais) == 1 else traduzir("{} canais").format(len(p.canais))]
    if 1 <= p.taxa_hz <= pd.FREQUENCIA_MAXIMA_HZ:
        partes.append(formatar_si(p.taxa_hz, "S/s", 6))
        if p.ate_parar:
            partes.append(traduzir("até o Parar"))
        elif p.blocos_pedidos > 0 and p.duracao_real_s is not None:
            partes.append(formatar_duracao(p.duracao_real_s))
            partes.append(formatar_bytes(p.bytes_do_arquivo))
    destino = traduzir("direto no computador") if p.destino == "computador" else traduzir("no cartão da placa")
    return " · ".join(partes) + ", " + destino


def _o_que_a_conferencia_mede(p: PedidoDeCaptura) -> PedidoDeCaptura:
    """O que de um pedido muda a conferência (os canais, as faixas, a taxa, o avançado): o resto não."""
    return p.com(duracao_s=None, blocos=1, titulo="", descricao="", destino="computador", arquivo_no_cartao="")


class Capturar(QWidget):
    """A seção. ``pasta_das_sondas()`` e ``pasta_do_destino()``: as pastas das preferências (os testes passam outras);
    ``pedir_nome(titulo, rotulo, texto)``: o nome de um modelo (``None`` cancela); ``livre`` mede o espaço livre."""

    capturarPedido = Signal(object)              # a F4.4

    def __init__(self, conexao: ConexaoDaPlaca, saude: SaudeDaPlaca, conferencia: ConferenciaDaPlaca, *,
                 pasta_das_sondas: Callable[[], Path] = lambda: preferencias.pasta("sondas"),
                 pasta_do_destino: Callable[[], Path] = preferencias.pasta_da_sessao,
                 livre: Callable[[Path], int | None] = livre_em,
                 pedir_nome: Callable[[str, str, str], str | None] | None = None,
                 lembrar: bool = True, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("secao_capturar")
        self.conexao, self.saude, self.conferencia = conexao, saude, conferencia
        self.pasta_das_sondas, self.pasta_do_destino, self.livre = pasta_das_sondas, pasta_do_destino, livre
        self.pedir_nome = pedir_nome or self._pedir_nome
        self.lembrar = lembrar
        self.projeto = None
        self.modelo_atual: str | None = None
        self.perfis: dict = {}
        self.problemas: list[Problema] = []

        self.formulario = FormularioDeCaptura()
        self.menu_dos_modelos = QMenu(self)
        self.menu_dos_modelos.setObjectName("menu_dos_modelos")
        self.menu_dos_modelos.aboutToShow.connect(self._montar_o_menu)
        self.formulario.botao_do_modelo.setMenu(self.menu_dos_modelos)

        centro = QWidget()
        centro.setObjectName("centro_da_captura")
        coluna = QVBoxLayout(centro)
        coluna.setContentsMargins(24, 20, 24, 20)
        coluna.setSpacing(14)
        titulo = QLabel(traduzir("Capturar"))
        titulo.setFont(fonte("tela", QFont.Weight.DemiBold))
        self.subtitulo = QLabel()
        self.subtitulo.setObjectName("subtitulo_da_secao")
        self.subtitulo.setWordWrap(True)
        coluna.addWidget(titulo)
        coluna.addWidget(self.subtitulo)
        coluna.addWidget(self._criar_comando())
        coluna.addWidget(self._criar_antes())
        coluna.addStretch(1)
        self.capturar = Botao(traduzir("Capturar"), "primario", "play")
        self.capturar.setObjectName("capturar")
        self.capturar.setEnabled(False)
        self.capturar.setToolTip(traduzir(CAPTURAR_CHEGA))
        rodape = QHBoxLayout()
        rodape.addStretch(1)
        rodape.addWidget(self.capturar)
        coluna.addLayout(rodape)
        rolagem = QScrollArea()
        rolagem.setObjectName("rolagem_da_captura")
        rolagem.setWidgetResizable(True)
        rolagem.setFrameShape(QFrame.Shape.NoFrame)
        rolagem.setWidget(centro)
        linha = QHBoxLayout(self)
        linha.setContentsMargins(0, 0, 0, 0)
        linha.setSpacing(0)
        linha.addWidget(self.formulario)
        linha.addWidget(rolagem, 1)

        self._para_lembrar = QTimer(self)
        self._para_lembrar.setSingleShot(True)
        self._para_lembrar.setInterval(ATRASO_PARA_LEMBRAR_MS)
        self._para_lembrar.timeout.connect(self._lembrar_o_pedido)
        self.formulario.pedidoMudou.connect(self._pedido_mudou)
        conexao.mudou.connect(self.validar)
        saude.mudou.connect(self.validar)
        conferencia.mudou.connect(self._conferencia_mudou)
        self.ler_os_perfis()
        if lembrar:
            guardado = preferencias.ultimo_pedido()
            if guardado is not None:
                self.formulario.definir_pedido(guardado)
        self._mostrar_o_modelo()
        self.validar()
        self._conferencia_mudou()

    # ------------------------------------------------------------------ montar o centro

    def _criar_comando(self) -> Painel:
        painel = Painel(traduzir("O comando"))
        self.comando = BlocoDeComando()
        self.comando.setObjectName("comando_da_captura")
        self.nota_do_comando = QLabel(traduzir("Na pasta ~/firmware da placa. Na captura direto no computador, o -o - "
                                               "manda as amostras pelo SSH; o aplicativo grava o arquivo e, no fim, "
                                               "ele é byte a byte o que o ler_adc gravaria no cartão."))
        self.nota_do_comando.setObjectName("texto_mudo")
        self.nota_do_comando.setFont(fonte("secundario"))
        self.nota_do_comando.setWordWrap(True)
        corpo = QVBoxLayout()
        corpo.setContentsMargins(14, 0, 14, 12)
        corpo.setSpacing(8)
        corpo.addWidget(self.comando)
        corpo.addWidget(self.nota_do_comando)
        painel.corpo.addLayout(corpo)
        return painel

    def _criar_antes(self) -> Painel:
        painel = Painel(traduzir("Antes de capturar"))
        self.conferir = Botao(traduzir("Conferir antes"), "secundario", "pulso")
        self.conferir.setObjectName("conferir_antes")
        self.conferir.clicked.connect(lambda: self.conferir_antes())
        self.cancelar = Botao(traduzir("Cancelar"), "fantasma")
        self.cancelar.setObjectName("cancelar_conferencia")
        self.cancelar.clicked.connect(self.conferencia.cancelar)
        painel.lado.addWidget(self.cancelar)
        painel.lado.addWidget(self.conferir)
        self.icone_do_estado = IconeDoNivel("ok")
        self.estado = QLabel()
        self.estado.setObjectName("estado_do_pedido")
        self.estado.setWordWrap(True)
        topo = QHBoxLayout()
        topo.setSpacing(10)
        topo.addWidget(self.icone_do_estado, 0, Qt.AlignmentFlag.AlignTop)
        topo.addWidget(self.estado, 1)
        self.lista_do_pedido = ListaDeProblemas()
        self.andamento = QLabel()
        self.andamento.setObjectName("texto_mudo")
        self.andamento.setWordWrap(True)
        self.andamento.setFont(fonte("secundario"))

        self.pedido_da_senha = QWidget()
        senha = QVBoxLayout(self.pedido_da_senha)
        senha.setContentsMargins(0, 0, 0, 0)
        senha.setSpacing(6)
        self.texto_da_senha = QLabel()
        self.texto_da_senha.setWordWrap(True)
        self.campo_da_senha = QLineEdit()
        self.campo_da_senha.setObjectName("senha_do_sudo")
        self.campo_da_senha.setEchoMode(QLineEdit.EchoMode.Password)
        self.campo_da_senha.setPlaceholderText(traduzir("a senha do sudo da placa"))
        self.campo_da_senha.returnPressed.connect(self._conferir_com_a_senha)
        self.guardar_a_senha = QCheckBox(traduzir("Guardar a senha no cofre do sistema"))
        self.guardar_a_senha.setObjectName("guardar_a_senha")
        com_a_senha = Botao(traduzir("Conferir"), "primario")
        com_a_senha.setObjectName("conferir_com_a_senha")
        com_a_senha.clicked.connect(self._conferir_com_a_senha)
        linha = QHBoxLayout()
        linha.addWidget(self.campo_da_senha, 1)
        linha.addWidget(com_a_senha)
        senha.addWidget(self.texto_da_senha)
        senha.addLayout(linha)
        senha.addWidget(self.guardar_a_senha)

        self.titulo_da_conferencia = QLabel()
        self.titulo_da_conferencia.setObjectName("titulo_do_painel_da_placa")
        self.titulo_da_conferencia.setFont(fonte("corpo", QFont.Weight.DemiBold))
        self.lista_da_conferencia = ListaDeProblemas()
        self.usar_as_faixas = Botao(traduzir("Usar as faixas sugeridas"), "secundario")
        self.usar_as_faixas.setObjectName("usar_as_faixas")
        self.usar_as_faixas.clicked.connect(self.usar_as_faixas_sugeridas)
        corpo = QVBoxLayout()
        corpo.setContentsMargins(14, 0, 14, 12)
        corpo.setSpacing(8)
        corpo.addLayout(topo)
        corpo.addWidget(self.lista_do_pedido)
        corpo.addWidget(self.andamento)
        corpo.addWidget(self.pedido_da_senha)
        corpo.addWidget(self.titulo_da_conferencia)
        corpo.addWidget(self.lista_da_conferencia)
        corpo.addWidget(self.usar_as_faixas, 0, Qt.AlignmentFlag.AlignLeft)
        painel.corpo.addLayout(corpo)
        return painel

    # ------------------------------------------------------------------ o projeto e os modelos

    def acompanhar(self, projeto) -> None:
        """O projeto da janela (os modelos de captura são dele)."""
        if self.projeto is not None:
            try:
                self.projeto.modelosMudaram.disconnect(self._modelos_mudaram)
            except (RuntimeError, TypeError):
                pass
        self.projeto = projeto
        self.modelo_atual = None
        if projeto is not None:
            projeto.modelosMudaram.connect(self._modelos_mudaram)
        self._mostrar_o_modelo()

    def _modelos_mudaram(self) -> None:
        if self.modelo_atual is not None and self.projeto.modelo_de_captura(self.modelo_atual) is None:
            self.modelo_atual = None
        self._mostrar_o_modelo()

    def _mostrar_o_modelo(self) -> None:
        botao = self.formulario.botao_do_modelo
        botao.setEnabled(self.projeto is not None)
        botao.setToolTip("" if self.projeto is not None else traduzir("Os modelos ficam no projeto."))
        if self.modelo_atual is None:
            botao.setText(traduzir("Modelo: nenhum"))
            return
        modelo = self.projeto.modelo_de_captura(self.modelo_atual)
        mudado = modelo is not None and modelo.pedido != self.formulario.pedido
        botao.setText(traduzir("Modelo: {}").format(self.modelo_atual) + (traduzir(" · mudado") if mudado else ""))

    def _montar_o_menu(self) -> None:
        menu = self.menu_dos_modelos
        menu.clear()
        if self.projeto is None:
            return
        for modelo in self.projeto.modelos_de_captura:
            acao = menu.addAction(modelo.nome)
            acao.setCheckable(True)
            acao.setChecked(modelo.nome == self.modelo_atual)
            acao.triggered.connect(lambda _=False, nome=modelo.nome: self.carregar_modelo(nome))
        if self.projeto.modelos_de_captura:
            menu.addSeparator()
        menu.addAction(traduzir("Guardar como modelo…"), self.guardar_como_modelo)
        atual = self.projeto.modelo_de_captura(self.modelo_atual) if self.modelo_atual else None
        if atual is not None:
            atualizar = menu.addAction(traduzir("Atualizar «{}»").format(atual.nome),
                                       lambda: self.guardar_modelo(atual.nome))
            atualizar.setEnabled(atual.pedido != self.formulario.pedido)
            menu.addAction(traduzir("Apagar «{}»").format(atual.nome), lambda: self.apagar_modelo(atual.nome))

    def carregar_modelo(self, nome: str) -> None:
        modelo = self.projeto.modelo_de_captura(nome) if self.projeto is not None else None
        if modelo is None:
            return
        self.modelo_atual = nome
        self.formulario.definir_pedido(modelo.pedido)
        self._mostrar_o_modelo()

    def guardar_como_modelo(self) -> None:
        sugestao = self.modelo_atual or self.formulario.pedido.titulo[:40]
        nome = self.pedir_nome(traduzir("Guardar como modelo"), traduzir("O nome do modelo de captura:"), sugestao)
        if nome and nome.strip():
            self.guardar_modelo(nome.strip())

    def guardar_modelo(self, nome: str) -> None:
        if self.projeto is None:
            return
        self.projeto.pilha.push(GuardarModeloDeCaptura(self.projeto, ModeloDeCaptura(nome, self.formulario.pedido)))
        self.modelo_atual = nome
        self._mostrar_o_modelo()

    def apagar_modelo(self, nome: str) -> None:
        if self.projeto is not None and self.projeto.modelo_de_captura(nome) is not None:
            self.projeto.pilha.push(ApagarModeloDeCaptura(self.projeto, nome))

    def _pedir_nome(self, titulo: str, rotulo: str, texto: str) -> str | None:
        nome, ok = QInputDialog.getText(self.window(), titulo, rotulo, QLineEdit.EchoMode.Normal, texto)
        return nome if ok else None

    # ------------------------------------------------------------------ a validação

    def ler_os_perfis(self) -> None:
        """Os perfis da pasta das sondas (lidos de novo a cada vez que a seção aparece: um perfil novo entra)."""
        self.perfis = pd.perfis_de_sonda(self.pasta_das_sondas())
        self.formulario.definir_perfis(self.perfis)

    def contexto(self) -> Contexto:
        conectada = self.conexao.conectada
        estado = self.saude.saude if conectada else None
        disco = estado.disco_bytes if estado is not None else None
        capturas = self.saude.capturas if conectada else None
        enlace = self.conexao.enlace if conectada else None
        return Contexto(perfis=self.perfis, pasta_das_sondas=self.pasta_das_sondas(),
                        livre_no_computador=self.livre(self.pasta_do_destino()),
                        livre_no_cartao=disco[0] if disco is not None else None,
                        vazao_do_enlace=enlace.vazao_bytes_s if enlace is not None and not self.conexao.simulada
                        else None,
                        capturas_no_cartao=frozenset(c.arquivo for c in capturas.capturas) if capturas else frozenset())

    def _pedido_mudou(self, _pedido: PedidoDeCaptura) -> None:
        self.validar()
        self._mostrar_o_modelo()
        self._mostrar_a_conferencia()
        if self.lembrar:
            self._para_lembrar.start()

    def _lembrar_o_pedido(self) -> None:
        preferencias.mudar_ultimo_pedido(self.formulario.pedido)

    def validar(self) -> list[Problema]:
        pedido = self.formulario.pedido
        contexto = self.contexto()
        self.problemas = pd.validar(pedido, contexto)
        self.formulario.mostrar_problemas(self.problemas)
        self.formulario.definir_texto_do_destino(self._texto_do_destino(pedido, contexto))
        self.comando.definir(pd.comando(pedido))
        self.subtitulo.setText(resumo_do_pedido(pedido))
        erros = [p for p in self.problemas if p.impede]
        avisos = [p for p in self.problemas if p.nivel == "aviso"]
        if erros:
            nivel = "erro"
            texto = traduzir("1 problema impede a captura") if len(erros) == 1 else \
                traduzir("{} problemas impedem a captura").format(len(erros))
        elif avisos:
            nivel = "aviso"
            texto = traduzir("Pode capturar, com 1 aviso") if len(avisos) == 1 else \
                traduzir("Pode capturar, com {} avisos").format(len(avisos))
        else:
            nivel, texto = "ok", traduzir("O pedido está certo para capturar")
        self.icone_do_estado.definir(nivel)
        self.estado.setText(texto)
        self.lista_do_pedido.definir(p for p in self.problemas if p.nivel != "info")
        self._mostrar_os_botoes()
        return self.problemas

    def _texto_do_destino(self, p: PedidoDeCaptura, ctx: Contexto) -> str:
        if p.destino == "computador":
            livre = traduzir(" {} livres aqui.").format(formatar_bytes(ctx.livre_no_computador)) \
                if ctx.livre_no_computador is not None else ""
            return traduzir("Sem o limite do cartão. Vai para {}; se a conexão cair, a captura para, e o que chegou "
                            "fica válido.{}").format(self.pasta_do_destino(), livre)
        if ctx.livre_no_cartao is None:
            return traduzir("Fica na pasta do firmware da placa; depois, a seção Arquivos a traz. Conecte a placa para "
                            "ver o espaço no cartão.")
        return traduzir("Fica na pasta do firmware da placa ({} livres no cartão); depois, a seção Arquivos a "
                        "traz.").format(formatar_bytes(ctx.livre_no_cartao))

    # ------------------------------------------------------------------ conferir antes

    def conferir_antes(self, senha: str | None = None, guardar: bool = False) -> None:
        pedido = self.formulario.pedido
        if pd.impede(self.problemas) or not self.conferencia.pode_conferir():
            return
        self.conferencia.conferir(pedido, senha, guardar)

    def _conferir_com_a_senha(self) -> None:
        senha = self.campo_da_senha.text()
        if not senha:
            return
        self.campo_da_senha.clear()
        self.conferir_antes(senha, self.guardar_a_senha.isChecked())

    def usar_as_faixas_sugeridas(self) -> None:
        feita = self.conferencia.resultado
        if feita is None:
            return
        pedido = self.formulario.pedido
        for numero, faixa in feita.faixas_sugeridas.items():
            if numero in pedido.numeros:
                pedido = pedido.com_canal(replace(pedido.canal(numero), faixa_v=faixa))
        self.formulario.definir_pedido(pedido)

    def _conferencia_mudou(self) -> None:
        self._mostrar_a_conferencia()
        self._mostrar_os_botoes()

    def _mostrar_os_botoes(self) -> None:
        c = self.conferencia
        rodando = c.rodando
        self.cancelar.setVisible(rodando)
        pode = c.pode_conferir() and not pd.impede(self.problemas)
        self.conferir.setEnabled(pode)
        if not self.conexao.conectada:
            dica = traduzir("Conecte uma placa para conferir.")
        elif pd.impede(self.problemas):
            dica = traduzir("Resolva o que impede a captura antes.")
        elif rodando:
            dica = traduzir("Conferindo…")
        else:
            dica = traduzir("Uma captura curta com este pedido (um bloco, ~{}): o ADC, a integridade e, em cada "
                            "canal, o nível, a frequência e a faixa que o comporta.").format(
                formatar_duracao(segundos_da_conferencia(self.formulario.pedido)))
        self.conferir.setToolTip(dica)

    def _mostrar_a_conferencia(self) -> None:
        c = self.conferencia
        self.pedido_da_senha.setVisible(c.estado in ("precisa_da_senha", "senha_recusada"))
        if c.estado == "precisa_da_senha":
            self.texto_da_senha.setText(traduzir("A conferência usa o sudo da placa: qual é a senha?"))
        elif c.estado == "senha_recusada":
            self.texto_da_senha.setText(traduzir("A placa recusou a senha do sudo. Tente de novo:"))
        if c.rodando:
            progresso = c.progresso
            blocos = progresso.bytes_recebidos if progresso is not None else 0
            self.andamento.setText(traduzir("Conferindo: um bloco a {} (~{}){}").format(
                formatar_si(c.pedido.taxa_hz, "S/s", 6), formatar_duracao(segundos_da_conferencia(c.pedido)),
                traduzir(" · {} recebidos").format(formatar_bytes(blocos)) if blocos else "…"))
        elif c.estado in ("falhou", "cancelada"):
            self.andamento.setText(frase(c.erro) if c.estado == "falhou" else traduzir("Conferência cancelada."))
        else:
            self.andamento.setText("")
        self.andamento.setObjectName("problema_erro" if c.estado == "falhou" else "texto_mudo")
        self.andamento.style().unpolish(self.andamento)
        self.andamento.style().polish(self.andamento)
        self.andamento.setVisible(bool(self.andamento.text()))

        feita = c.resultado
        self.titulo_da_conferencia.setVisible(feita is not None)
        self.lista_da_conferencia.setVisible(feita is not None)
        if feita is None:
            self.lista_da_conferencia.definir(())
            self.usar_as_faixas.setVisible(False)
            self.formulario.definir_sugestoes({})
            return
        self.titulo_da_conferencia.setText(
            traduzir("Conferência das {}: pronto para capturar").format(hora(feita.feita_em)) if feita.pronta else
            traduzir("Conferência das {}: {} problema(s)").format(hora(feita.feita_em), max(1, feita.problemas)))
        linhas = linhas_da_conferencia(feita)
        if _o_que_a_conferencia_mede(feita.pedido) != _o_que_a_conferencia_mede(self.formulario.pedido):
            linhas.insert(0, Problema("conferencia", "aviso", traduzir("o pedido mudou depois da conferência (os "
                                                                       "canais, as faixas, a taxa ou o SPI): confira "
                                                                       "de novo")))
        self.lista_da_conferencia.definir(linhas)
        sugeridas = {n: f for n, f in feita.faixas_sugeridas.items() if n in self.formulario.pedido.numeros}
        self.formulario.definir_sugestoes(sugeridas)
        pedido = self.formulario.pedido
        diferentes = [n for n, f in sugeridas.items() if pd.faixa_conhecida(pedido.canal(n).faixa_v) != f]
        self.usar_as_faixas.setVisible(bool(diferentes))


def linhas_da_conferencia(feita: ConferenciaFeita) -> list[Problema]:
    """O resultado como linhas, com o nível de cada uma (o ✓, o ! e o ✗ do ``conferir.sh``)."""
    conf = feita.conferencia
    cab = conf.cabecalho
    linhas: list[Problema] = []
    if feita.adc_mudo:
        linhas.append(Problema("adc", "erro", traduzir("o ADC não está respondendo (amostras todas iguais): a placa de "
                                                       "aquisição sem alimentação (pelo USB, ela fica desligada: a "
                                                       "BeagleBone tem de estar na fonte de 5 V) ou os pinos da PRU "
                                                       "sem configuração")))
    atrasadas, sobrescritos, sdo = conf.integridade
    if conf.integra:
        folga = cab.folga_minima_ciclos
        texto = traduzir("captura íntegra") + (traduzir(", grade exata (folga de {} ciclos)").format(folga)
                                               if folga is not None else "")
        linhas.append(Problema("integridade", "info", texto))
    else:
        linhas.append(Problema("integridade", "erro", traduzir("integridade: {} amostras atrasadas, {} buffers "
                                                               "sobrescritos, {} quadros com ruído no SDO").format(
            atrasadas, sobrescritos, sdo)))
    divergencias = conf.divergencias
    if divergencias is not None and any(divergencias):
        linhas.append(Problema("spi", "aviso", traduzir("divergências de leitura no SPI rápido: {} na fase A e {} na "
                                                        "C").format(*divergencias)))
    for n in conf.canais:
        if n.parado:
            linhas.append(Problema("nivel", "erro", traduzir("todas as amostras iguais (o ADC mudo ou a entrada "
                                                             "saturada)"), n.canal))
            continue
        partes = [traduzir("{}pp no pino").format(formatar_si(n.vpp_v, "V", 4))]
        if n.frequencia_hz is not None:
            partes.append(formatar_si(n.frequencia_hz, "Hz", 5))
        partes.append(traduzir("offset {}").format(formatar_si(n.media_v, "V", 3)))
        partes.append(traduzir("{} rms ({} LSB)").format(formatar_si(n.rms_v, "V", 3), f"{n.rms_lsb:.1f}"))
        partes.append(traduzir("usa {} % da faixa").format(round(100 * n.uso_da_faixa)))
        sugerida = n.faixa_sugerida_v
        if n.satura:
            texto = traduzir("{} amostras no fundo de escala em {} (saturou)").format(n.saturadas,
                                                                                     texto_da_faixa(n.faixa_v))
            texto += (traduzir(": confira em {}, a maior faixa (o pico cortado não diz qual cabe)").format(
                texto_da_faixa(sugerida)) if sugerida is not None else
                traduzir(", a maior faixa: o sinal passa do que o ADC lê; reduza-o na sonda ou no divisor"))
            linhas.append(Problema("nivel", "erro", texto, n.canal))
            continue
        linhas.append(Problema("nivel", "info", " · ".join(partes), n.canal))
        pico, uso = formatar_si(n.pico_v, "V", 3), round(100 * n.uso_da_faixa)
        if sugerida is not None and sugerida < n.faixa_v:
            linhas.append(Problema("faixa", "info", traduzir("o pico ({}) cabe em {}: mais resolução").format(
                pico, texto_da_faixa(sugerida)), n.canal))
        elif sugerida is not None:
            linhas.append(Problema("faixa", "aviso", traduzir("o pico ({}) usa {} % de {}: {} dá a folga de 15 %").format(
                pico, uso, texto_da_faixa(n.faixa_v), texto_da_faixa(sugerida)), n.canal))
        elif n.sem_folga:
            linhas.append(Problema("faixa", "aviso", traduzir("o pico ({}) usa {} % de {}, a maior faixa: um surto de "
                                                              "{} % satura").format(
                pico, uso, texto_da_faixa(n.faixa_v), max(1, round(100 / n.uso_da_faixa - 100))), n.canal))
        if n.so_ruido:
            linhas.append(Problema("nivel", "aviso", traduzir("quase só ruído (menos de 3 LSB rms): o sinal chegou?"),
                                   n.canal))
    if cab.relogio_sincronizado is False:
        linhas.append(Problema("relogio", "aviso", traduzir("o relógio da placa não está sincronizado por NTP: o "
                                                            "cabeçalho diz {}").format(
            time.strftime("%d/%m/%Y %H:%M:%S", time.localtime(cab.timestamp_unix)))))
    if conf.disco_quase_cheio:
        linhas.append(Problema("disco", "aviso", traduzir("o cartão da placa está quase cheio: {} livres").format(
            formatar_bytes(cab.disco_saida_livre_fim_kib * 1024))))
    if conf.pru_sem_acomodacao:
        linhas.append(Problema("pru", "aviso", traduzir("a PRU é de antes de 11/11/2026 (sem a espera de acomodação do "
                                                        "ADC): pule o começo das capturas depois de trocar a faixa")))
    return linhas
