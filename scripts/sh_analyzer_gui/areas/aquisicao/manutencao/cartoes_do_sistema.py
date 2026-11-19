"""Os cartões da página Sistema que a F6.7 acrescenta: o cartão (o espaço, a partição, a limpeza), os serviços da
imagem, a rede e a senha. Cada um lê o ``SistemaDaPlaca`` (o detalhe do comando ``sistema`` do agente) e pede as
ações pelo sinal ``confirmar(tipo, argumento)``, que a seção transforma no diálogo (nada roda na placa antes do "sim").
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QProgressBar, QVBoxLayout, QWidget

from ....componentes.basicos import Botao
from ....componentes.numeros import formatar_bytes
from ....servicos.sistema_da_placa import SistemaDaPlaca
from ..pecas import fonte
from ..textos import frase, traduzir
from .comuns import texto

MINIMO_PARA_EXPANDIR = 64 * 1024 * 1024
LIMPEZAS = (("apt", "Os pacotes que o apt baixou", "/var/cache/apt/archives: o apt baixa de novo se precisar."),
            ("diario", "O diário do systemd guardado no cartão",
             "/var/log/journal: fica com 16 MB (o deste boot inteiro, e o mais recente de antes)."),
            ("tarefas", "As tarefas terminadas da manutenção",
             "~/.sh-analyzer/tarefas: os passos e o log das atualizações que já terminaram."))


class _Cartao(QFrame):
    confirmar = Signal(str, object)

    def __init__(self, titulo: str, sistema: SistemaDaPlaca, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("item_do_diagnostico")
        self.sistema = sistema
        self.coluna = QVBoxLayout(self)
        self.coluna.setContentsMargins(14, 12, 14, 12)
        self.coluna.setSpacing(6)
        rotulo = QLabel(titulo)
        rotulo.setFont(fonte("corpo", QFont.Weight.DemiBold))
        self.coluna.addWidget(rotulo)
        self.linhas: list[QWidget] = []
        sistema.mudou.connect(self.atualizar)
        sistema.acaoMudou.connect(self.atualizar)

    def _limpar(self) -> None:
        for w in self.linhas:
            w.hide()
            w.deleteLater()
        self.linhas = []

    def _linha(self, titulo: str, detalhe: str = "", botao: Botao | None = None, nome: str = "") -> QWidget:
        linha = QWidget()
        if nome:
            linha.setObjectName(nome)
        caixa = QHBoxLayout(linha)
        caixa.setContentsMargins(0, 4, 0, 4)
        textos = QVBoxLayout()
        textos.setSpacing(0)
        cabeca = QLabel(titulo)
        cabeca.setFont(fonte("corpo", QFont.Weight.Medium))
        cabeca.setWordWrap(True)
        textos.addWidget(cabeca)
        if detalhe:
            pe = texto(detalhe, "texto_mudo")
            pe.setFont(fonte("secundario"))
            textos.addWidget(pe)
        caixa.addLayout(textos, 1)
        if botao is not None:
            caixa.addWidget(botao, 0, Qt.AlignmentFlag.AlignVCenter)
        self.coluna.addWidget(linha)
        self.linhas.append(linha)
        return linha

    @property
    def livre(self) -> bool:
        return not self.sistema.ocupado and self.sistema.conexao.estado == "conectada"

    def atualizar(self) -> None:
        raise NotImplementedError


class CartaoDoCartao(_Cartao):
    """O cartão da placa: o espaço, a partição (com "Expandir…" quando ela não ocupa o cartão todo e a imagem tem o
    script) e o que pode ser limpo, cada um com o tamanho e "Limpar…"."""

    def __init__(self, sistema: SistemaDaPlaca, parent: QWidget | None = None):
        super().__init__(traduzir("Cartão e limpeza"), sistema, parent)
        self.uso = QProgressBar()
        self.uso.setObjectName("uso_do_cartao")
        self.uso.setTextVisible(False)
        self.uso.setFixedHeight(8)
        self.resumo = texto("", "resumo_do_item")
        self.coluna.addWidget(self.resumo)
        self.coluna.addWidget(self.uso)
        self.botoes: dict[str, Botao] = {}
        self.atualizar()

    def atualizar(self) -> None:
        self._limpar()
        self.botoes = {}
        d = self.sistema.detalhe or {}
        disco, cartao, ocupacao = d.get("disco") or {}, d.get("cartao") or {}, d.get("ocupacao") or {}
        total, livre = disco.get("total_kib"), disco.get("livre_kib")
        if total and livre is not None:
            self.uso.setRange(0, 1000)
            self.uso.setValue(int(1000 * (total - livre) / total))
            self.resumo.setText(traduzir("{} livres de {} na partição da raiz.").format(
                formatar_bytes(livre * 1024), formatar_bytes(total * 1024)))
        else:
            self.resumo.setText(traduzir("Não deu para ler o espaço do cartão.") if d else "")
        self.uso.setVisible(bool(total))
        fora = cartao.get("fora_bytes")
        if fora is not None and cartao.get("bytes"):
            if fora >= MINIMO_PARA_EXPANDIR and cartao.get("script_de_expandir"):
                botao = Botao(traduzir("Expandir…"), "secundario")
                botao.setObjectName("expandir_a_particao")
                botao.setEnabled(self.livre)
                botao.clicked.connect(lambda: self.confirmar.emit("expandir", None))
                self.botoes["expandir"] = botao
                self._linha(traduzir("A partição não ocupa o cartão todo: {} sobrando").format(formatar_bytes(fora)),
                            traduzir("O cartão tem {}; a partição {} ({}). Expandir a deixa até o fim do cartão "
                                     "(vale depois de reiniciar).").format(
                                formatar_bytes(cartao["bytes"]), cartao.get("particao") or "",
                                formatar_bytes(cartao.get("particao_bytes") or 0)), botao, "linha_da_particao")
            else:
                self._linha(traduzir("A partição ocupa o cartão todo ({})").format(formatar_bytes(cartao["bytes"])),
                            traduzir("{} em {}.").format(cartao.get("particao") or "", cartao.get("disco") or ""))
        for qual, titulo, detalhe in LIMPEZAS:
            tamanho = ocupacao.get(qual)
            if not tamanho:
                continue
            botao = Botao(traduzir("Limpar…"), "secundario")
            botao.setObjectName(f"limpar_{qual}")
            botao.setEnabled(self.livre)
            botao.clicked.connect(lambda _c=False, q=qual: self.confirmar.emit("limpar", q))
            self.botoes[qual] = botao
            self._linha(f"{traduzir(titulo)}: {formatar_bytes(tamanho)}", traduzir(detalhe), botao, f"limpeza_{qual}")
        outras = []
        if ocupacao.get("anteriores"):
            outras.append(traduzir("as cópias do firmware ({}, na página Firmware)").format(
                formatar_bytes(ocupacao["anteriores"])))
        if ocupacao.get("capturas"):
            outras.append(traduzir("as capturas ({}, na seção Arquivos: só as conferidas no computador)").format(
                formatar_bytes(ocupacao["capturas"])))
        if ocupacao.get("diario_na_ram"):
            outras.append(traduzir("o diário na RAM ({}, some no reinício)").format(
                formatar_bytes(ocupacao["diario_na_ram"])))
        if outras:
            self._linha(traduzir("Também ocupam"), "; ".join(outras) + ".")


class CartaoDosServicos(_Cartao):
    """Os serviços da imagem: o que cada um é, se roda, se sobe no boot e a memória; os opcionais (o Cloud9, o
    BoneScript, o Node-RED, o nginx) com "Desligar…" e "Ligar…"; os necessários (o SSH, o ``dnsmasq`` do USB, o
    ``avahi``) sem botão."""

    def __init__(self, sistema: SistemaDaPlaca, parent: QWidget | None = None):
        super().__init__(traduzir("Serviços da imagem"), sistema, parent)
        self.explicacao = texto(traduzir("Os opcionais não servem ao SH-Analyzer e disputam o núcleo único com a "
                                         "captura: desligá-los vale agora e nos próximos boots."), "resumo_do_item")
        self.coluna.addWidget(self.explicacao)
        self.botoes: dict[str, Botao] = {}
        self.atualizar()

    def atualizar(self) -> None:
        self._limpar()
        self.botoes = {}
        sockets = {s.get("unidade", "").removesuffix(".socket") for s in self.sistema.servicos
                   if s.get("unidade", "").endswith(".socket") and s.get("ativo") is not None}
        for s in self.sistema.servicos:
            unidade = s.get("unidade") or ""
            pelo_socket = unidade.endswith(".service") and unidade.removesuffix(".service") in sockets
            if s.get("ativo") is None:
                continue
            ativo = s.get("ativo") == "active"
            no_boot = s.get("no_boot") or ""
            estado = [traduzir("rodando") if ativo else traduzir("parado")]
            if no_boot in ("enabled", "disabled"):
                estado.append(traduzir("sobe no boot") if no_boot == "enabled" else traduzir("não sobe no boot"))
            if s.get("memoria_kib"):
                estado.append(formatar_bytes(s["memoria_kib"] * 1024))
            botao = None
            if pelo_socket:
                estado.append(traduzir("aberto pelo {}.socket").format(unidade.removesuffix(".service")))
            elif s.get("papel") == "opcional" and no_boot in ("enabled", "disabled"):
                ligar = not ativo and no_boot == "disabled"
                botao = Botao(traduzir("Ligar…") if ligar else traduzir("Desligar…"), "secundario")
                botao.setObjectName(f"{'ligar' if ligar else 'desligar'}_{unidade}")
                botao.setEnabled(self.livre)
                botao.clicked.connect(lambda _c=False, u=unidade, lg=ligar: self.confirmar.emit("servico", (u, lg)))
                self.botoes[unidade] = botao
            elif s.get("papel") == "necessario":
                estado.append(traduzir("necessário"))
            self._linha(f"{unidade} · {' · '.join(estado)}", traduzir(s.get("texto") or s.get("descricao") or ""),
                        botao, f"servico_{unidade}")


class CartaoDaRede(_Cartao):
    """As interfaces ligadas, com os endereços e os bytes; as desligadas numa linha; "Testar a internet"."""

    def __init__(self, sistema: SistemaDaPlaca, parent: QWidget | None = None):
        super().__init__(traduzir("Rede"), sistema, parent)
        self.internet = texto("", "resumo_do_item")
        self.testar = Botao(traduzir("Testar a internet"), "secundario")
        self.testar.setObjectName("testar_a_internet")
        self.testar.clicked.connect(sistema.testar_internet)
        linha = QHBoxLayout()
        linha.addWidget(self.internet, 1)
        linha.addWidget(self.testar)
        self.coluna.addLayout(linha)
        self.atualizar()

    def atualizar(self) -> None:
        self._limpar()
        s = self.sistema
        rede = (s.detalhe or {}).get("rede") or []
        desligadas = []
        for i in rede:
            if i.get("estado") != "up":
                desligadas.append(i.get("nome") or "")
                continue
            self._linha(f"{i.get('nome')} · {', '.join(i.get('enderecos') or []) or traduzir('sem endereço')}",
                        traduzir("recebidos {} · enviados {} · {}").format(
                            formatar_bytes(i.get("rx_bytes") or 0), formatar_bytes(i.get("tx_bytes") or 0),
                            i.get("mac") or ""), nome=f"interface_{i.get('nome')}")
        if desligadas:
            self._linha(traduzir("Desligadas: {}").format(", ".join(desligadas)))
        self.testar.setEnabled(not s.testando_internet and s.conexao.estado == "conectada")
        r = s.internet
        if s.testando_internet:
            self.internet.setText(traduzir("Testando a internet da placa…"))
        elif r is None:
            self.internet.setText(traduzir("A internet serve ao apt e ao relógio pelo NTP; a captura não precisa "
                                           "dela."))
        elif r.get("erro"):
            self.internet.setText(frase(r["erro"]))
        elif r.get("alcanca"):
            self.internet.setText(traduzir("A placa alcança a internet ({} ms até o deb.debian.org).").format(
                int(r.get("ms") or 0)))
        elif r.get("dns"):
            self.internet.setText(traduzir("A placa resolve nomes, mas não alcança a internet."))
        else:
            self.internet.setText(traduzir("A placa não alcança a internet (sem rota, ou sem DNS)."))


class CartaoDaSenha(_Cartao):
    """A senha do usuário da placa (a do SSH e a do sudo): "Trocar a senha…"; o aviso da senha padrão da imagem."""

    def __init__(self, sistema: SistemaDaPlaca, senha_padrao=None, parent: QWidget | None = None):
        super().__init__(traduzir("Senha"), sistema, parent)
        self.senha_padrao = senha_padrao or (lambda: False)
        self.explicacao = texto("", "resumo_do_item")
        self.trocar = Botao(traduzir("Trocar a senha…"), "secundario", "cadeado")
        self.trocar.setObjectName("trocar_a_senha")
        self.trocar.clicked.connect(lambda: self.confirmar.emit("trocar_senha", None))
        linha = QHBoxLayout()
        linha.addWidget(self.explicacao, 1)
        linha.addWidget(self.trocar, 0, Qt.AlignmentFlag.AlignVCenter)
        self.coluna.addLayout(linha)
        self.atualizar()

    def atualizar(self) -> None:
        c = self.sistema.conexao.conexao_ssh
        usuario = c.destino.usuario if c is not None else "debian"
        texto_ = traduzir("A senha do usuário {} na placa: a do SSH e a do sudo. O aplicativo entra pela chave dele; a "
                          "senha vale no sudo e para quem entrar sem a chave.").format(usuario)
        if self.senha_padrao():
            texto_ += " " + traduzir("A placa ainda usa a senha padrão da imagem: troque-a se ela fica numa rede "
                                     "compartilhada.")
        self.explicacao.setText(texto_)
        self.trocar.setEnabled(self.livre)
