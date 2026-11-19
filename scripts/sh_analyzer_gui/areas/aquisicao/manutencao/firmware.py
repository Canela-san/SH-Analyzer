"""A página Firmware da Manutenção (a F6.3): a versão da placa e a deste aplicativo, iguais pelo código (o plano compara
os hashes), o que muda, o aviso das mudanças não commitadas; "Atualizar a placa…" e "Compilar e carregar de novo…" (o
diálogo da atualização confirma, mostra o roteiro e pede a senha do sudo quando a sessão e o cofre não a têm); os
passos ao vivo, com o log, e o desfecho (atualizada, voltou à anterior, falhou); as cópias anteriores na placa, com
"Voltar a esta…" e "Apagar…". Nada roda na placa sem a confirmação.
"""

from __future__ import annotations

import time

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)
from sh_placa.atualizacao import PASSOS, roteiro_da_atualizacao

from ....componentes.basicos import Botao
from ....componentes.numeros import formatar_bytes
from ....servicos.manutencao_da_placa import EstadoDaAtualizacao, ManutencaoDaPlaca
from ....tema.tokens import TAMANHOS
from ..pecas import IconeDoNivel, Selo, fonte, repolir
from ..textos import frase, traduzir
from .comuns import LARGURA_DO_DIALOGO, TextoMono, cartao, coluna_central
from .comuns import texto as _texto

NOMES_DOS_PASSOS = dict(PASSOS)
NIVEL_DO_PASSO = {"comecou": "info", "ok": "ok", "aviso": "aviso", "falhou": "erro"}
NIVEL_DO_DESFECHO = {"atualizada": "ok", "voltou": "aviso", "falhou_antes": "erro", "falhou_ao_voltar": "erro",
                     "interrompida": "erro", "rodando": "info"}
TITULOS_DOS_DESFECHOS = {"atualizada": "Firmware atualizado", "voltou": "A placa voltou à versão anterior",
                         "falhou_antes": "A atualização não mudou a placa", "falhou_ao_voltar": "A placa precisa de você",
                         "interrompida": "A atualização foi interrompida", "rodando": "Ainda roda"}


# ------------------------------------------------------------------ a confirmação

class DialogoDaAtualizacao(QDialog):
    """A confirmação de uma atualização: o que vai acontecer, o roteiro exato ("Ver o roteiro") e, se a sessão e o
    cofre não a têm, a senha do sudo. Fecha quando a atualização começa (os passos ficam na página)."""

    def __init__(self, manutencao: ManutencaoDaPlaca, origem, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("dialogo_da_atualizacao")
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.manutencao, self.origem = manutencao, origem
        plano = manutencao.plano_para(origem)
        self.titulo = _texto(nome="titulo_do_dialogo", selecionavel=False)
        fonte_do_titulo = QFont()
        fonte_do_titulo.setPixelSize(TAMANHOS["secao"])
        fonte_do_titulo.setWeight(QFont.Weight.DemiBold)
        self.titulo.setFont(fonte_do_titulo)
        self.explicacao = _texto()
        self.passos = _texto(nome="texto_mudo")
        self.roteiro = TextoMono(14)
        self.roteiro.setPlainText(roteiro_da_atualizacao(plano, "<id>") if plano is not None else "")
        self.roteiro.hide()
        self.ver = Botao(traduzir("Ver o roteiro"), "fantasma")
        self.ver.setObjectName("ver_o_roteiro")
        self.ver.setCheckable(True)
        self.ver.toggled.connect(self.roteiro.setVisible)
        self.ver.toggled.connect(lambda _l: self.adjustSize())
        self.campo_senha = QLineEdit()
        self.campo_senha.setObjectName("senha_do_sudo")
        self.campo_senha.setEchoMode(QLineEdit.EchoMode.Password)
        self.campo_senha.setPlaceholderText(traduzir("a senha do sudo na placa"))
        self.guardar = QCheckBox(traduzir("Guardar a senha no cofre do sistema"))
        self.guardar.setObjectName("guardar_senha_do_sudo")
        self.caixa_da_senha = QWidget()
        senha = QVBoxLayout(self.caixa_da_senha)
        senha.setContentsMargins(0, 0, 0, 0)
        senha.setSpacing(6)
        senha.addWidget(self.campo_senha)
        senha.addWidget(self.guardar)
        self.caixa_da_senha.hide()
        self.mensagem = _texto("", "erro_do_dialogo")
        self.mensagem.hide()
        self.barra = QProgressBar()
        self.barra.setRange(0, 0)
        self.barra.setTextVisible(False)
        self.barra.setFixedHeight(6)
        self.barra.hide()
        self.cancelar = Botao(traduzir("Cancelar"), "secundario")
        self.cancelar.clicked.connect(self.reject)
        self.confirmar = Botao("", "primario")
        self.confirmar.setObjectName("confirmar_atualizacao")
        self.confirmar.setDefault(True)
        self.confirmar.clicked.connect(self._confirmar)
        self.campo_senha.returnPressed.connect(self._confirmar)
        botoes = QHBoxLayout()
        botoes.setContentsMargins(0, 8, 0, 0)
        botoes.addWidget(self.ver)
        botoes.addStretch(1)
        botoes.addWidget(self.cancelar)
        botoes.addWidget(self.confirmar)
        coluna = QVBoxLayout(self)
        coluna.setContentsMargins(24, 20, 24, 18)
        coluna.setSpacing(12)
        coluna.setSizeConstraint(QVBoxLayout.SizeConstraint.SetFixedSize)
        for widget in (self.titulo, self.explicacao, self.passos, self.roteiro, self.caixa_da_senha, self.mensagem,
                       self.barra):
            widget.setFixedWidth(LARGURA_DO_DIALOGO - 48)
            coluna.addWidget(widget)
        coluna.addLayout(botoes)
        self._preencher(plano)
        manutencao.atualizacaoMudou.connect(self._mudou)

    def _preencher(self, plano) -> None:
        f = plano.firmware if plano is not None else None
        versao_da_placa = (plano.versao_da_placa if plano is not None else None) or traduzir("sem versão")
        envio = ""
        if self.origem == "aplicativo":
            self.setWindowTitle(traduzir("Atualizar o firmware"))
            self.titulo.setText(traduzir("Atualizar a placa para {}").format(f.versao if f else "—"))
            n = len(plano.novos) + len(plano.mudados) if plano is not None else 0
            envio = traduzir("Envia {} arquivo(s) ({}) para uma pasta de preparação; ").format(
                n, formatar_bytes(plano.bytes_a_enviar if plano is not None else 0))
            self.confirmar.setText(traduzir("Atualizar"))
            self.explicacao.setText(traduzir(
                "A placa tem o firmware {} e passa para o deste aplicativo. As capturas da pasta do firmware não são "
                "tocadas.").format(versao_da_placa))
        elif self.origem == "placa":
            self.setWindowTitle(traduzir("Compilar e carregar de novo"))
            self.titulo.setText(traduzir("Compilar e carregar de novo o firmware da placa"))
            self.confirmar.setText(traduzir("Compilar e carregar"))
            self.explicacao.setText(traduzir(
                "O próprio código da placa ({}), compilado de novo e carregado na PRU, como o setup.sh faz.").format(
                versao_da_placa))
        else:
            self.setWindowTitle(traduzir("Voltar a uma versão anterior"))
            self.titulo.setText(traduzir("Voltar o firmware a {}").format(f.versao if f else "—"))
            self.confirmar.setText(traduzir("Voltar a esta versão"))
            self.explicacao.setText(traduzir(
                "A cópia {} da placa volta a ser o firmware dela (a de agora, {}, vira uma cópia também).").format(
                self.origem.nome, versao_da_placa))
        self.passos.setText(traduzir(
            "{}compila lá (cerca de 25 s na BeagleBone); guarda o firmware de agora em ~/firmware-anteriores/; "
            "instala, carrega na PRU e confere com uma captura de um bloco. Se instalar, carregar ou conferir falhar, "
            "a placa volta sozinha à cópia. Roda como uma tarefa da placa: o cabo pode cair no meio, e ela segue. "
            "Pede o sudo (a senha vai só pelo stdin, para um arquivo na RAM da placa que some logo depois).").format(
            envio).capitalize())

    def _confirmar(self) -> None:
        senha = self.campo_senha.text() if self.caixa_da_senha.isVisible() else None
        if self.caixa_da_senha.isVisible() and not senha:
            self.campo_senha.setFocus()
            return
        self.campo_senha.clear()
        self.mensagem.hide()
        self.manutencao.atualizar(self.origem, senha, guardar=self.guardar.isChecked())

    def _mudou(self) -> None:
        a = self.manutencao.atualizacao
        if a is None:
            return
        if a.estado in ("rodando", "reconectando"):
            self.accept()
            return
        enviando = a.estado == "enviando"
        self.barra.setVisible(enviando)
        self.confirmar.setEnabled(not enviando)
        self.cancelar.setEnabled(not enviando)
        if a.estado in ("precisa_da_senha", "senha_recusada"):
            self.caixa_da_senha.show()
            self.campo_senha.setFocus()
        if a.estado in ("precisa_da_senha", "senha_recusada", "nao_comecou"):
            self.mensagem.setText(frase(a.mensagem))
            self.mensagem.setObjectName("texto_mudo" if a.estado == "precisa_da_senha" else "erro_do_dialogo")
            repolir(self.mensagem)
            self.mensagem.show()


# ------------------------------------------------------------------ o firmware

class LinhaDoPasso(QWidget):
    def __init__(self, nome: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.nome = nome
        self.icone = IconeDoNivel("info")
        self.rotulo = QLabel(traduzir(NOMES_DOS_PASSOS.get(nome, nome)))
        self.rotulo.setFont(fonte("corpo", QFont.Weight.Medium))
        self.detalhe = _texto("", "texto_mudo")
        self.detalhe.setFont(fonte("secundario"))
        linha = QHBoxLayout(self)
        linha.setContentsMargins(0, 0, 0, 0)
        linha.setSpacing(10)
        linha.addWidget(self.icone, 0, Qt.AlignmentFlag.AlignTop)
        textos = QVBoxLayout()
        textos.setSpacing(0)
        textos.addWidget(self.rotulo)
        textos.addWidget(self.detalhe)
        linha.addLayout(textos, 1)

    def definir(self, estado: str | None, detalhe: str = "") -> None:
        """``None``: ainda não chegou (apagado)."""
        self.icone.setVisible(estado is not None)
        if estado is not None:
            self.icone.definir(NIVEL_DO_PASSO.get(estado, "info"))
        self.rotulo.setEnabled(estado is not None)
        self.detalhe.setText(detalhe)
        self.detalhe.setVisible(bool(detalhe))


class LinhaDaCopia(QFrame):
    voltar = Signal(object)
    apagar = Signal(object)

    def __init__(self, copia, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("linha_da_copia")
        self.copia = copia
        titulo = QLabel(copia.versao or traduzir("sem versão"))
        titulo.setFont(fonte("corpo", QFont.Weight.DemiBold))
        quando = time.strftime("%d/%m/%Y %H:%M", time.localtime(copia.modificado)) if copia.modificado else ""
        extras = [quando, formatar_bytes(copia.bytes), traduzir("com o firmware da PRU") if copia.pru_instalada
                  else traduzir("sem o firmware da PRU (do enviar)")]
        detalhe = _texto(" · ".join(x for x in extras if x), "texto_mudo")
        detalhe.setFont(fonte("secundario"))
        detalhe.setToolTip(copia.nome)
        self.botao_voltar = Botao(traduzir("Voltar a esta…"), "secundario")
        self.botao_voltar.setObjectName(f"voltar_a_{copia.nome}")
        self.botao_voltar.setEnabled(copia.codigo)
        if not copia.codigo:
            self.botao_voltar.setToolTip(traduzir("A cópia não tem o código para compilar (o ler_adc.c e o Makefile)."))
        self.botao_voltar.clicked.connect(lambda: self.voltar.emit(self.copia))
        self.botao_apagar = Botao(traduzir("Apagar…"), "fantasma")
        self.botao_apagar.setObjectName(f"apagar_{copia.nome}")
        self.botao_apagar.clicked.connect(lambda: self.apagar.emit(self.copia))
        linha = QHBoxLayout(self)
        linha.setContentsMargins(0, 4, 0, 4)
        textos = QVBoxLayout()
        textos.setSpacing(0)
        textos.addWidget(titulo)
        textos.addWidget(detalhe)
        linha.addLayout(textos, 1)
        linha.addWidget(self.botao_voltar)
        linha.addWidget(self.botao_apagar)


class PaginaDoFirmware(QWidget):
    """A página Firmware da Manutenção. ``confirmar(origem)`` abre o diálogo da atualização (a seção o liga);
    ``perguntar`` confirma o apagar de uma cópia (o ``dialogos_de`` da janela)."""

    confirmar = Signal(object)

    def __init__(self, manutencao: ManutencaoDaPlaca, dialogos_de=None, captura_rodando=None,
                 parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("pagina_do_firmware")
        self.manutencao, self.dialogos_de = manutencao, dialogos_de
        self.captura_rodando = captura_rodando or (lambda: False)
        self.titulo = QLabel(traduzir("Firmware"))
        self.titulo.setFont(fonte("tela", QFont.Weight.DemiBold))
        self.subtitulo = _texto("", "subtitulo_da_secao")
        self.ler_de_novo = Botao(traduzir("Ler de novo"), "secundario", "girar")
        self.ler_de_novo.setObjectName("ler_o_firmware_de_novo")
        self.ler_de_novo.clicked.connect(manutencao.ler)
        cabecalho = QHBoxLayout()
        textos = QVBoxLayout()
        textos.setSpacing(2)
        textos.addWidget(self.titulo)
        textos.addWidget(self.subtitulo)
        cabecalho.addLayout(textos, 1)
        cabecalho.addWidget(self.ler_de_novo, 0, Qt.AlignmentFlag.AlignTop)

        # as duas versões e o que muda
        self.cartao_das_versoes, versoes = cartao(traduzir("A placa e este aplicativo"))
        self.na_placa = _texto()
        self.no_aplicativo = _texto()
        self.o_que_muda = _texto("", "texto_mudo")
        self.o_que_muda.setFont(fonte("secundario"))
        self.sujo = _texto("", "problema_aviso")
        self.sujo.hide()
        self.enviar_assim_mesmo = QCheckBox(traduzir("Enviar assim mesmo (a versão vai com -dirty)"))
        self.enviar_assim_mesmo.setObjectName("enviar_assim_mesmo")
        self.enviar_assim_mesmo.hide()
        self.enviar_assim_mesmo.toggled.connect(lambda _l: self.atualizar())
        for w in (self.na_placa, self.no_aplicativo, self.o_que_muda, self.sujo, self.enviar_assim_mesmo):
            versoes.addWidget(w)
        self.atualizar_placa = Botao(traduzir("Atualizar a placa…"), "primario", "baixar")
        self.atualizar_placa.setObjectName("atualizar_a_placa")
        self.atualizar_placa.clicked.connect(lambda: self.confirmar.emit("aplicativo"))
        self.compilar = Botao(traduzir("Compilar e carregar de novo…"), "secundario", "girar")
        self.compilar.setObjectName("compilar_de_novo")
        self.compilar.setToolTip(traduzir("O código da placa, compilado de novo e carregado na PRU (o setup.sh)"))
        self.compilar.clicked.connect(lambda: self.confirmar.emit("placa"))
        acoes = QHBoxLayout()
        acoes.setContentsMargins(0, 6, 0, 0)
        acoes.addWidget(self.atualizar_placa)
        acoes.addWidget(self.compilar)
        acoes.addStretch(1)
        versoes.addLayout(acoes)

        # a atualização de agora
        self.cartao_da_atualizacao, corpo = cartao()
        self.titulo_da_atualizacao = QLabel()
        self.titulo_da_atualizacao.setFont(fonte("corpo", QFont.Weight.DemiBold))
        self.selo = Selo("info")
        topo = QHBoxLayout()
        topo.addWidget(self.titulo_da_atualizacao)
        topo.addWidget(self.selo)
        topo.addStretch(1)
        self.dispensar = Botao(traduzir("Fechar"), "fantasma")
        self.dispensar.setObjectName("dispensar_a_atualizacao")
        self.dispensar.clicked.connect(manutencao.dispensar)
        topo.addWidget(self.dispensar)
        corpo.addLayout(topo)
        self.desfecho = _texto("", "resumo_do_item")
        corpo.addWidget(self.desfecho)
        self.linhas_dos_passos = {nome: LinhaDoPasso(nome) for nome, _t in PASSOS}
        for linha in self.linhas_dos_passos.values():
            corpo.addWidget(linha)
        self.log = TextoMono(10)
        self.log.setObjectName("log_da_atualizacao")
        corpo.addWidget(self.log)
        self.cartao_da_atualizacao.hide()

        # as cópias anteriores
        self.cartao_das_copias, self.corpo_das_copias = cartao(traduzir("Versões anteriores na placa"))
        self.sem_copias = _texto(traduzir("Nenhuma cópia em ~/firmware-anteriores/ ainda: a primeira atualização "
                                          "guarda a de agora."), "texto_mudo")
        self.corpo_das_copias.addWidget(self.sem_copias)
        self.linhas_das_copias: list[LinhaDaCopia] = []

        conteudo = QWidget()
        coluna = QVBoxLayout(conteudo)
        coluna.setContentsMargins(24, 20, 24, 20)
        coluna.setSpacing(14)
        coluna.addLayout(cabecalho)
        coluna.addWidget(self.cartao_da_atualizacao)
        coluna.addWidget(self.cartao_das_versoes)
        coluna.addWidget(self.cartao_das_copias)
        coluna.addStretch(1)
        fora = QVBoxLayout(self)
        fora.setContentsMargins(0, 0, 0, 0)
        fora.addWidget(coluna_central(conteudo, "rolagem_do_firmware"))
        manutencao.mudou.connect(self.atualizar)
        manutencao.atualizacaoMudou.connect(self._atualizacao_mudou)
        manutencao.logDaAtualizacao.connect(self.log.acrescentar)
        self.atualizar()
        self._atualizacao_mudou()

    # ------------------------------------------------------------------ as versões

    def atualizar(self) -> None:
        m = self.manutencao
        plano, f = m.plano, m.firmware
        rodando = m.atualizacao is not None and m.atualizacao.rodando
        self.ler_de_novo.setEnabled(not m.lendo and not rodando)
        if plano is None:
            self.subtitulo.setText(traduzir("Lendo o firmware da placa…") if m.lendo else frase(m.erro) if m.erro
                                   else traduzir("O firmware deste aplicativo não foi achado (nem o repositório, nem "
                                                 "a pasta do instalador).") if f is None and not m.lendo else "")
            self.na_placa.setText("")
            self.no_aplicativo.setText("")
            self.o_que_muda.setText("")
            self.atualizar_placa.setEnabled(False)
            self.compilar.setEnabled(False)
            self._copias([])
            return
        muda = len(plano.novos) + len(plano.mudados)
        if plano.nada_muda:
            resumo = traduzir("A placa tem o firmware deste aplicativo: o código é o mesmo ({}).").format(
                plano.versao_da_placa or f.versao)
        else:
            resumo = traduzir("A placa tem o {}; este aplicativo, o {}: {} arquivo(s) mudam.").format(
                plano.versao_da_placa or traduzir("sem versão"), f.versao, muda)
        if m.erro:
            resumo += " " + frase(m.erro)
        self.subtitulo.setText(resumo)
        self.na_placa.setText(traduzir("Na placa: {} · {} arquivo(s) do código{}").format(
            plano.versao_da_placa or traduzir("sem versão"), len(plano.codigo_da_placa),
            "" if plano.pru_igual is not False else traduzir(" · o firmware instalado na PRU não é o compilado")))
        origem = {"repositorio": traduzir("do repositório"), "pacote": traduzir("do instalador")}.get(f.origem, "")
        self.no_aplicativo.setText(traduzir("Neste aplicativo: {} ({}) · {} arquivo(s)").format(
            f.versao, origem, len(f.arquivos)))
        partes = []
        if plano.mudados:
            partes.append(traduzir("mudam: {}").format(", ".join(plano.mudados)))
        if plano.novos:
            partes.append(traduzir("novos: {}").format(", ".join(plano.novos)))
        partes.append(traduzir("iguais: {}").format(len(plano.iguais)))
        if plano.sobrando:
            partes.append(traduzir("ficam (não são deste firmware): {}").format(", ".join(plano.sobrando)))
        if muda:
            partes.append(traduzir("{} a enviar").format(formatar_bytes(plano.bytes_a_enviar)))
        self.o_que_muda.setText(" · ".join(partes).capitalize())
        self.sujo.setVisible(f.sujo)
        self.enviar_assim_mesmo.setVisible(f.sujo and not plano.nada_muda)
        if f.sujo:
            self.sujo.setText(traduzir(
                "O firmware/ deste repositório tem mudanças não commitadas ({}). A versão gravada em cada captura "
                "apontaria para um código que não existe: commite antes de atualizar a placa.").format(
                ", ".join(f.mudancas)))
        captura = self.captura_rodando()
        pode = not rodando and not m.lendo and not captura
        self.atualizar_placa.setEnabled(pode and not plano.nada_muda and (not f.sujo or
                                                                          self.enviar_assim_mesmo.isChecked()))
        self.atualizar_placa.setToolTip(traduzir("Uma captura está rodando: espere ela terminar.") if captura else
                                        traduzir("A placa já tem este firmware.") if plano.nada_muda else "")
        self.compilar.setEnabled(pode and bool(plano.codigo_da_placa))
        self._copias(m.copias)

    def _copias(self, copias) -> None:
        for linha in self.linhas_das_copias:
            linha.hide()
            linha.deleteLater()
        self.linhas_das_copias = []
        rodando = self.manutencao.atualizacao is not None and self.manutencao.atualizacao.rodando
        for copia in copias:
            linha = LinhaDaCopia(copia)
            linha.botao_voltar.setEnabled(copia.codigo and not rodando and not self.captura_rodando())
            linha.botao_apagar.setEnabled(not rodando)
            linha.voltar.connect(self.confirmar.emit)
            linha.apagar.connect(self.apagar_copia)
            self.corpo_das_copias.addWidget(linha)
            self.linhas_das_copias.append(linha)
        self.sem_copias.setVisible(not copias)

    def apagar_copia(self, copia) -> None:
        if self.dialogos_de is not None:
            resposta = self.dialogos_de().perguntar(
                traduzir("Apagar a cópia do firmware"),
                traduzir("A cópia {} ({}) sai da placa para sempre: não dá mais para voltar a ela.").format(
                    copia.nome, formatar_bytes(copia.bytes)), {"apagar": traduzir("Apagar")}, "apagar")
            if resposta != "apagar":
                return
        self.manutencao.apagar_copia(copia)

    # ------------------------------------------------------------------ a atualização

    def _atualizacao_mudou(self) -> None:
        a: EstadoDaAtualizacao | None = self.manutencao.atualizacao
        visivel = a is not None and a.estado not in ("precisa_da_senha", "senha_recusada", "enviando") or (
            a is not None and a.estado == "enviando" and a.a_enviar > 0)
        self.cartao_da_atualizacao.setVisible(bool(visivel))
        self.atualizar()
        if not visivel:
            return
        self.titulo_da_atualizacao.setText(traduzir(a.titulo))
        estados = a.tarefa.estados() if a.tarefa is not None else {}
        for nome, linha in self.linhas_dos_passos.items():
            if nome == "enviar":
                feito = a.estado != "enviando"
                linha.definir("ok" if feito else "comecou",
                              traduzir("{} de {} arquivo(s)").format(a.enviados, a.a_enviar) if a.a_enviar else
                              traduzir("nada a enviar: os arquivos já estão na placa"))
                linha.setVisible(a.origem == "aplicativo")
                continue
            p = estados.get(nome)
            linha.definir(p.estado if p is not None else None, p.texto if p is not None else "")
            linha.setVisible(nome != "voltar" or p is not None)
        self.dispensar.setVisible(not a.rodando)
        if a.rodando:
            texto = {"enviando": traduzir("enviando"), "reconectando": traduzir("a conexão caiu: a atualização segue "
                                                                               "na placa, e volta a aparecer aqui")}
            self.selo.definir("info", texto.get(a.estado, traduzir("rodando")))
            self.desfecho.setText(texto.get(a.estado, "") if a.estado == "reconectando" else "")
            self.desfecho.setVisible(a.estado == "reconectando")
            return
        d = a.desfecho
        if d is None:
            self.selo.definir("erro", traduzir("falhou"))
            self.desfecho.setText(frase(a.mensagem))
        else:
            titulo = TITULOS_DOS_DESFECHOS.get(d.estado, d.estado)
            if d.estado == "atualizada":
                titulo = {"placa": "Compilado e carregado", "anterior": "De volta à versão escolhida"}.get(
                    a.origem, titulo)
            self.selo.definir(NIVEL_DO_DESFECHO.get(d.estado, "info"), traduzir(titulo))
            texto = frase(d.mensagem) + (" " + frase(d.aviso) if d.aviso else "")
            if a.de_antes:
                texto = traduzir("Achada ao conectar (ninguém tinha visto o fim dela): ") + texto
            if d.copia and d.estado in ("atualizada", "falhou_ao_voltar"):
                texto += " " + traduzir("A cópia de antes ficou em {}.").format(d.copia)
            self.desfecho.setText(texto)
        self.desfecho.show()
        if not self.log.toPlainText() and a.log:
            self.log.setPlainText("".join(a.log))
