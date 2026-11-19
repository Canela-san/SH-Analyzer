"""A seção Manutenção da Aquisição (docs/gui-plan.md, 11.10; a Fase 6): as páginas no alto (:data:`PAGINAS`), cada
uma numa coluna no meio, como o diagnóstico; sem placa, o estado vazio. As confirmações (o diálogo da atualização, o
das ações do sistema) abrem daqui, sobre a janela."""

from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QStackedWidget, QVBoxLayout, QWidget

from ....componentes.basicos import Segmentado
from ....componentes.numeros import formatar_bytes
from ....componentes.painel import EstadoVazio
from ....servicos.conexao_da_placa import ConexaoDaPlaca
from ....servicos.manutencao_da_placa import ManutencaoDaPlaca
from ....servicos.monitor_da_placa import MonitorDaPlaca
from ....servicos.sistema_da_placa import SistemaDaPlaca
from ..textos import traduzir
from .comuns import DialogoDaAcao, DialogoDaSenhaNova
from .firmware import DialogoDaAtualizacao, PaginaDoFirmware
from .inicializacao import PaginaDaInicializacao
from .logs import PaginaDosLogs
from .sistema import PaginaDoSistema

PAGINAS = (("firmware", "Firmware", "chave"), ("inicializacao", "Inicialização", "chip"),
           ("sistema", "Sistema", "energia"), ("logs", "Logs", "pagina"))


class Manutencao(QWidget):
    """A seção Manutenção: as páginas (:data:`PAGINAS`) no alto e a escolhida embaixo; sem placa, o estado vazio."""

    def __init__(self, conexao: ConexaoDaPlaca, manutencao: ManutencaoDaPlaca, sistema: SistemaDaPlaca,
                 monitor: MonitorDaPlaca, dialogos_de=None, captura_rodando=None, registrar_no_caderno=None,
                 senha_padrao=None, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("secao_manutencao")
        self.conexao, self.manutencao, self.sistema, self.dialogos_de = conexao, manutencao, sistema, dialogos_de
        self.captura_rodando = captura_rodando or (lambda: False)
        self.dialogo: DialogoDaAtualizacao | DialogoDaAcao | None = None
        self.firmware = PaginaDoFirmware(manutencao, dialogos_de, captura_rodando)
        self.firmware.confirmar.connect(self.confirmar_atualizacao)
        self.inicializacao = PaginaDaInicializacao(sistema)
        self.inicializacao.confirmar.connect(self.confirmar_acao)
        self.monitor = monitor
        self.sistema_ = PaginaDoSistema(sistema, monitor, captura_rodando, senha_padrao)
        self.sistema_.confirmar.connect(self.confirmar_acao)
        self.logs = PaginaDosLogs(monitor, dialogos_de)
        if registrar_no_caderno is not None:
            self.logs.paraOCaderno.connect(registrar_no_caderno)
        self.paginas: dict[str, QWidget] = {"firmware": self.firmware, "inicializacao": self.inicializacao,
                                            "sistema": self.sistema_, "logs": self.logs}
        self.escolha = Segmentado([traduzir(t) for _n, t, _i in PAGINAS], icones=[i for _n, _t, i in PAGINAS])
        self.escolha.setObjectName("paginas_da_manutencao")
        self.pilha = QStackedWidget()
        for nome, _t, _i in PAGINAS:
            self.pilha.addWidget(self.paginas[nome])
        self.escolha.escolhaMudou.connect(lambda i: self.pilha.setCurrentIndex(i))
        conectada = QWidget()
        coluna = QVBoxLayout(conectada)
        coluna.setContentsMargins(0, 12, 0, 0)
        coluna.setSpacing(0)
        topo = QHBoxLayout()
        topo.addStretch(1)
        topo.addWidget(self.escolha)
        topo.addStretch(1)
        coluna.addLayout(topo)
        coluna.addWidget(self.pilha, 1)
        self.vazio = EstadoVazio(traduzir("Nenhuma placa conectada"),
                                 traduzir("A manutenção cuida da placa conectada: o firmware (atualizar com a volta "
                                          "sozinha, voltar a uma versão anterior), a inicialização (o uEnv.txt), o "
                                          "sistema (o monitor, reiniciar e desligar com segurança) e os logs."),
                                 icone_nome="chave", largura_do_texto=440)
        self.estados = QStackedWidget()
        self.estados.addWidget(self.vazio)
        self.estados.addWidget(conectada)
        fora = QVBoxLayout(self)
        fora.setContentsMargins(0, 0, 0, 0)
        fora.addWidget(self.estados)
        conexao.mudou.connect(self._conexao_mudou)
        self._conexao_mudou()

    def _conexao_mudou(self) -> None:
        self.estados.setCurrentIndex(1 if self.conexao.estado in ("conectada", "reconectando") else 0)
        if self.isVisible():
            self.manutencao.ler_se_preciso()
            self.sistema.ler_se_preciso()

    def showEvent(self, evento) -> None:
        super().showEvent(evento)
        self.manutencao.ler_se_preciso()           # o firmware é lido quando a seção aparece (o git, o plano)
        self.sistema.ler_se_preciso()

    def mostrar_pagina(self, nome: str) -> None:
        indice = [n for n, _t, _i in PAGINAS].index(nome)
        self.escolha.escolher(indice)
        self.pilha.setCurrentIndex(indice)

    @property
    def pagina(self) -> str:
        return PAGINAS[self.pilha.currentIndex()][0]

    def confirmar_atualizacao(self, origem) -> DialogoDaAtualizacao:
        if self.dialogo is not None:
            self.dialogo.deleteLater()
        self.dialogo = DialogoDaAtualizacao(self.manutencao, origem, self.window())
        self.dialogo.open()
        return self.dialogo

    def _abrir(self, dialogo):
        if self.dialogo is not None:
            self.dialogo.deleteLater()
        self.dialogo = dialogo
        dialogo.open()
        return dialogo

    def confirmar_acao(self, tipo: str, argumento=None) -> DialogoDaAcao | None:
        """O diálogo de uma ação do sistema (``"gravar_uenv"``, ``"restaurar_uenv"``, ``"reiniciar"``,
        ``"desligar"``): nada roda na placa antes do "sim" nele."""
        from sh_placa import sistema as sh_sistema
        from sh_placa import uenv

        s = self.sistema
        capturando = bool(self.captura_rodando())
        comando_do_reinicio = sh_sistema.roteiro_de_energia("reboot")
        if tipo in ("gravar_uenv", "restaurar_uenv"):
            antes, sha = s.texto_do_uenv, s.sha_do_uenv
            if antes is None or sha is None:
                return None
            if tipo == "gravar_uenv":
                nomes = list(argumento or [])
                novo = s.novo_uenv(nomes)
                if novo is None or novo == antes:
                    return None
                titulos = [traduzir(m.titulo) for m in s.propostas if m.nome in nomes]
                janela, titulo = traduzir("Gravar o uEnv.txt"), traduzir("Gravar o /boot/uEnv.txt da placa")
                explicacao = traduzir("Muda: {}. Antes, a placa guarda o de agora em "
                                      "/boot/uEnv.txt.sh-analyzer-<data> (a página mostra a cópia, com Restaurar…); "
                                      "a gravação é atômica e conferida pelo hash.").format("; ".join(titulos))

                def comecar(senha, guardar, reiniciar, mesmo):
                    return s.gravar_mudancas(nomes, "reiniciar" if reiniciar else None, senha, guardar, mesmo)
            else:
                nome, novo = argumento
                janela, titulo = traduzir("Restaurar o uEnv.txt"), traduzir("Restaurar a cópia {}").format(nome)
                explicacao = traduzir("O /boot/uEnv.txt volta a ser a cópia /boot/{} (o de agora também vira uma "
                                      "cópia). Abaixo, o que muda.").format(nome)

                def comecar(senha, guardar, reiniciar, mesmo):
                    return s.restaurar(nome, novo, "reiniciar" if reiniciar else None, senha, guardar, mesmo)
            comando = uenv.roteiro_de_gravar(sha, "<data>") + "\n# e, se marcado, o reinício:\n" + comando_do_reinicio
            return self._abrir(DialogoDaAcao(
                s, janela=janela, titulo=titulo, explicacao=explicacao, confirmar=traduzir("Gravar"),
                comecar=comecar, diff=uenv.diff(antes, novo), comando=comando, reiniciar_depois=True,
                captura_rodando=capturando, parent=self.window()))
        if tipo == "reiniciar":
            return self._abrir(DialogoDaAcao(
                s, janela=traduzir("Reiniciar a placa"), titulo=traduzir("Reiniciar a placa"),
                explicacao=traduzir("O sistema para (os programas fecham, o cartão é desmontado) e a placa liga de "
                                    "novo. A conexão cai e volta sozinha, com o boot novo (cerca de 1 min); o relógio "
                                    "é acertado de novo, se a placa deixou."),
                confirmar=traduzir("Reiniciar"), comando=comando_do_reinicio, captura_rodando=capturando,
                comecar=lambda senha, guardar, _r, mesmo: s.reiniciar(senha, guardar, mesmo),
                parent=self.window()))
        if tipo == "desligar":
            return self._abrir(DialogoDaAcao(
                s, janela=traduzir("Desligar a placa"), titulo=traduzir("Desligar a placa"),
                explicacao=traduzir("O sistema para e a placa desliga: para ligá-la de novo, alguém precisa estar na "
                                    "bancada (tirar e pôr na tomada, ou o botão POWER). O aplicativo avisa quando ela "
                                    "sumir: aí já pode tirar da tomada."),
                confirmar=traduzir("Desligar"), comando=sh_sistema.roteiro_de_energia("poweroff"),
                captura_rodando=capturando, perigo=True,
                comecar=lambda senha, guardar, _r, mesmo: s.desligar(senha, guardar, mesmo),
                parent=self.window()))
        if tipo == "parar_ler_adc":
            capturas = self.monitor.capturas
            return self._abrir(DialogoDaAcao(
                s, janela=traduzir("Parar o ler_adc"), titulo=traduzir("Parar o ler_adc que roda na placa"),
                explicacao=traduzir("{} Ele recebe o INT, como o Ctrl+C: fecha o arquivo da captura (o que ela "
                                    "gravou até ali fica) e para a PRU; só se não sair em 10 s, o TERM.").format(
                    "; ".join(f"PID {c.pid}: {c.linha}" for c in capturas) or traduzir("Nenhum ler_adc à vista agora.")),
                confirmar=traduzir("Parar"), comando=sh_sistema.roteiro_de_parar_ler_adc(), perigo=True,
                comecar=lambda senha, guardar, _r, _m: s.parar_ler_adc(senha, guardar), parent=self.window()))
        if tipo == "servico":
            unidade, ligar = argumento
            servico = next((x for x in s.servicos if x.get("unidade") == unidade), {})
            memoria = servico.get("memoria_kib")
            explicacao = traduzir(servico.get("texto") or "") + " " + (
                traduzir("Ele volta a rodar agora e sobe nos próximos boots.") if ligar else
                traduzir("Ele para agora e não sobe mais no boot{}; dá para ligar de novo por aqui.").format(
                    traduzir(" (libera {} de memória)").format(formatar_bytes(memoria * 1024)) if memoria else ""))
            return self._abrir(DialogoDaAcao(
                s, janela=traduzir("Serviços da imagem"),
                titulo=(traduzir("Ligar o {}") if ligar else traduzir("Desligar o {}")).format(unidade),
                explicacao=explicacao.strip(), confirmar=traduzir("Ligar") if ligar else traduzir("Desligar"),
                comando=sh_sistema.roteiro_do_servico(unidade, ligar),
                comecar=lambda senha, guardar, _r, _m: s.ligar_servico(unidade, ligar, senha, guardar),
                parent=self.window()))
        if tipo == "limpar":
            qual = argumento
            tamanho = ((s.detalhe or {}).get("ocupacao") or {}).get(qual) or 0
            textos = {"apt": traduzir("Os pacotes que o apt baixou ({}) saem de /var/cache/apt/archives; o apt baixa de "
                                      "novo se um dia precisar."),
                      "diario": traduzir("O diário do systemd guardado no cartão ({}) fica com 16 MB: o mais antigo "
                                         "sai; o deste boot fica inteiro."),
                      "tarefas": traduzir("As pastas das tarefas da manutenção que terminaram ({}) saem de "
                                          "~/.sh-analyzer/tarefas; a que roda fica.")}
            return self._abrir(DialogoDaAcao(
                s, janela=traduzir("Limpar o cartão"), titulo=traduzir("Limpar {}").format(
                    traduzir(sh_sistema.LIMPEZAS[qual])),
                explicacao=textos[qual].format(formatar_bytes(tamanho)), confirmar=traduzir("Limpar"),
                comando="" if qual == "tarefas" else sh_sistema.roteiro_de_limpar(qual),
                comecar=lambda senha, guardar, _r, _m: s.limpar(qual, senha, guardar), parent=self.window()))
        if tipo == "expandir":
            cartao = (s.detalhe or {}).get("cartao") or {}
            return self._abrir(DialogoDaAcao(
                s, janela=traduzir("Expandir a partição"), titulo=traduzir("Expandir a partição até o fim do cartão"),
                explicacao=traduzir("O script da imagem ({}) muda a tabela de partições: a {} passa a ir até o fim do "
                                    "cartão, ganhando {}. O sistema de arquivos cresce no boot seguinte. Faça antes "
                                    "de encher o cartão, com as capturas já no computador.").format(
                    cartao.get("script_de_expandir"), cartao.get("particao"),
                    formatar_bytes(cartao.get("fora_bytes") or 0)),
                confirmar=traduzir("Expandir"),
                comando=sh_sistema.roteiro_de_expandir(cartao.get("script_de_expandir") or "/opt/x") + "\n" +
                comando_do_reinicio, reiniciar_depois=True, rotulo_do_reinicio=traduzir(
                    "Reiniciar a placa logo depois (o sistema de arquivos só cresce no boot)"),
                captura_rodando=capturando,
                comecar=lambda senha, guardar, reiniciar, _m: s.expandir_a_particao(
                    "reiniciar" if reiniciar else None, senha, guardar), parent=self.window()))
        if tipo == "trocar_senha":
            return self._abrir(DialogoDaSenhaNova(s, comando=sh_sistema.roteiro_da_senha(
                s.conexao.conexao_ssh.destino.usuario if s.conexao.conexao_ssh is not None else "debian"),
                parent=self.window()))
        raise ValueError(f"ação desconhecida: {tipo!r}")
