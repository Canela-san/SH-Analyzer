"""A placa conectada da interface (``servicos/conexao_da_placa.py``, F3.5), sem a tela: a busca, o simulador, a
primeira conexão inteira pelo SSH (a impressão, a senha, a chave instalada, a senha padrão, o relógio lembrado), a
segunda sem perguntar nada, a chave de host trocada como bloqueio, o salto com a senha dele, a queda com a volta
sozinha e o fim da janela sem deixar nada aberto. O servidor SSH do teste roda num laço próprio, como uma placa de
verdade, fora do laço da interface."""

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")
pytest.importorskip("asyncssh")

from servidor_ssh import ServidorSSH  # noqa: E402
from sh_analyzer_gui import preferencias  # noqa: E402
from sh_analyzer_gui.servicos import conexao_da_placa as modulo  # noqa: E402
from sh_analyzer_gui.servicos.conexao_da_placa import ConexaoDaPlaca  # noqa: E402
from sh_analyzer_gui.servicos.placa import ServicoDaPlaca  # noqa: E402
from sh_placa.descoberta import Achado, Caminho, Descoberta, FonteSimulador  # noqa: E402
from sh_placa.destino import SENHA_PADRAO_DA_IMAGEM, Destino  # noqa: E402
from sh_placa.laco import LacoAsyncio  # noqa: E402
from sh_placa.simulador import SERIE_SIMULADA  # noqa: E402

ESPERA_MS = 15_000


class CofreFalso:
    """O cofre do sistema, num dicionário (os testes não tocam o cofre de quem desenvolve)."""

    def __init__(self, **senhas):
        self.senhas = dict(senhas)
        self.guardadas: list[str] = []

    def senha(self, conta):
        return self.senhas.get(conta)

    def guardar(self, conta, senha):
        self.senhas[conta] = senha
        self.guardadas.append(conta)


class Placas:
    """Os servidores SSH do teste (as placas), num laço próprio: a placa responde enquanto a interface espera."""

    def __init__(self, pasta):
        self.pasta = pasta
        self.laco = LacoAsyncio("placas-do-teste")
        self.laco.iniciar()
        self.servidores: list[ServidorSSH] = []

    def nova(self, nome="placa", **opcoes) -> ServidorSSH:
        servidor = ServidorSSH(self.pasta / nome, **opcoes)
        self.laco.submeter(servidor.iniciar).resultado(10)
        self.servidores.append(servidor)
        return servidor

    def rodar(self, funcao, *args):
        return self.laco.submeter(funcao, *args).resultado(10)

    def fechar(self):
        for servidor in self.servidores:
            self.laco.submeter(servidor.parar).resultado(10)
        assert self.laco.parar()


@pytest.fixture
def placas(tmp_path):
    p = Placas(tmp_path)
    yield p
    p.fechar()


def fonte_de(servidor: ServidorSSH, nome: str = "bbb-teste"):
    """Uma fonte da descoberta que acha o servidor do teste, como o mDNS acharia uma placa na LAN."""
    async def fonte(_conhecidas=()):
        return [Achado(Caminho("lan", Destino("127.0.0.1", servidor.porta), f"{nome}.local (mDNS)", 0.4),
                       impressao=servidor.impressao, nome=nome)]
    fonte.nome = "teste"
    return fonte


@pytest.fixture
def criar(qapp, config_limpa, tmp_path):
    criadas = []

    def _criar(*fontes, cofre=None):
        servico = ServicoDaPlaca()
        conexao = ConexaoDaPlaca(servico, descoberta=Descoberta([*fontes, FonteSimulador()]),
                                 pasta=tmp_path / "aplicativo", cofre=cofre if cofre is not None else CofreFalso())
        estados = []
        conexao.mudou.connect(lambda: estados.append(conexao.estado) if estados[-1:] != [conexao.estado] else None)
        conexao.estados = estados
        criadas.append((conexao, servico))
        return conexao

    yield _criar
    for conexao, servico in criadas:
        conexao.encerrar()
        assert servico.encerrar()


def esperar(qtbot, conexao, estado, timeout=ESPERA_MS):
    qtbot.waitUntil(lambda: conexao.estado == estado, timeout=timeout)


def procurar(qtbot, conexao):
    with qtbot.waitSignal(conexao.placasMudaram, timeout=ESPERA_MS):
        conexao.procurar()
    return {p.nome: p for p in conexao.placas}


def test_a_lista_e_o_simulador(qtbot, placas, criar):
    servidor = placas.nova()
    conexao = criar(fonte_de(servidor))
    lista = procurar(qtbot, conexao)
    assert set(lista) == {"bbb-teste", "Simulador (BeagleBone Black)"} and conexao.falhas_da_busca == []
    assert lista["bbb-teste"].melhor.destino == Destino("127.0.0.1", servidor.porta)

    conexao.conectar(lista["Simulador (BeagleBone Black)"])
    esperar(qtbot, conexao, "conectada")
    assert conexao.simulada and conexao.tipo_do_caminho == "simulador" and conexao.detalhe_do_caminho
    assert conexao.estado_da_placa.serie == SERIE_SIMULADA and conexao.enlace is None
    assert conexao.primeira_conexao is None                       # o simulador não pergunta nem é lembrado
    assert conexao.e_a_conectada(lista["Simulador (BeagleBone Black)"]) and not conexao.e_a_conectada(lista["bbb-teste"])
    pasta = conexao._sessao.simulador._pasta
    assert pasta.is_dir()
    conexao.desconectar()
    assert conexao.estado == "desconectada" and conexao.estado_da_placa is None
    qtbot.waitUntil(lambda: not pasta.exists(), timeout=ESPERA_MS)          # a placa simulada some
    assert preferencias.placas_conhecidas() == ()


def test_a_primeira_conexao_inteira_e_a_segunda_sem_perguntar(qtbot, placas, criar):
    servidor = placas.nova(senha=SENHA_PADRAO_DA_IMAGEM)
    cofre = CofreFalso()
    conexao = criar(fonte_de(servidor), cofre=cofre)
    placa = procurar(qtbot, conexao)["bbb-teste"]
    conexao.conectar(placa)
    esperar(qtbot, conexao, "confirmar_host")
    assert conexao.impressao_pedida == servidor.impressao and conexao.destino_pedido == placa.melhor.destino
    conexao.confirmar_host(True)
    esperar(qtbot, conexao, "pedir_senha")                       # a chave do aplicativo ainda não está na placa
    assert conexao.motivo == "" and conexao.destino_pedido == placa.melhor.destino
    conexao.informar_senha(SENHA_PADRAO_DA_IMAGEM, guardar=True, instalar_chave=True)
    esperar(qtbot, conexao, "conectada")
    primeira = conexao.primeira_conexao
    assert (primeira.host_confirmado, primeira.chave_instalada, primeira.sem_a_chave, primeira.senha_padrao,
            primeira.perguntar_relogio, primeira.aviso_do_cofre) == (True, True, False, True, True, "")
    assert conexao.autenticada_com == "senha" and conexao.tipo_do_caminho == "lan"
    assert cofre.guardadas == [f"debian@127.0.0.1:{servidor.porta}"]
    assert servidor.authorized_keys.read_text().count("ssh-ed25519") == 1
    (conhecida,) = preferencias.placas_conhecidas()
    assert (conhecida.serie, conhecida.nome, conhecida.impressao) == (SERIE_SIMULADA, "bbb-teste", servidor.impressao)
    qtbot.waitUntil(lambda: conexao.enlace is not None, timeout=ESPERA_MS)
    assert conexao.enlace.latencia_ms > 0 and conexao.enlace.vazao_bytes_s > 0 and not conexao.medindo_enlace
    conexao.responder_relogio(True)
    assert conexao.primeira_conexao is None and preferencias.placas_conhecidas()[0].acertar_relogio is True
    assert conexao.estados == ["conectando", "confirmar_host", "conectando", "pedir_senha", "conectando",
                               "conectada"]

    conexao.desconectar()
    conexao.estados.clear()
    conexao.conectar(procurar(qtbot, conexao)["bbb-teste"])
    esperar(qtbot, conexao, "conectada")
    assert conexao.estados == ["conectando", "conectada"]        # a chave, sem senha e sem pergunta nenhuma
    assert conexao.autenticada_com == "chave" and conexao.primeira_conexao is None
    assert servidor.autenticacoes.count(("senha", True)) == 1


def test_a_chave_de_uma_placa_conhecida_por_outro_endereco_passa_sem_perguntar(qtbot, placas, criar):
    """A mesma placa nos dois IPs do USB: confirmada num, é aceita no outro, e o registro diz por quê."""
    servidor = placas.nova(enderecos=("127.0.0.1", "127.0.0.2"))
    conexao = criar(cofre=CofreFalso(**{f"debian@127.0.0.1:{servidor.porta}": servidor.senha,
                                        f"debian@127.0.0.2:{servidor.porta}": servidor.senha}))
    conexao.conectar(destino=Destino("127.0.0.1", servidor.porta))
    esperar(qtbot, conexao, "confirmar_host")
    conexao.confirmar_host(True)
    esperar(qtbot, conexao, "conectada")                         # a senha do cofre, sem perguntar
    assert conexao.primeira_conexao.chave_instalada is None and conexao.primeira_conexao.sem_a_chave
    conexao.dispensar_primeira_conexao()
    conexao.estados.clear()
    conexao.conectar(destino=Destino("127.0.0.2", servidor.porta))
    esperar(qtbot, conexao, "conectada")
    assert "confirmar_host" not in conexao.estados
    assert any("é a de uma placa conhecida: aceita sem perguntar" in e.descricao for e in conexao.registro.entradas)


def test_a_chave_de_host_trocada_e_um_bloqueio(qtbot, placas, criar):
    servidor = placas.nova()
    conexao = criar(cofre=CofreFalso(**{f"debian@127.0.0.1:{servidor.porta}": servidor.senha}))
    destino = Destino("127.0.0.1", servidor.porta)
    conexao.conectar(destino=destino)
    esperar(qtbot, conexao, "confirmar_host")
    antiga = conexao.impressao_pedida
    conexao.confirmar_host(True)
    esperar(qtbot, conexao, "conectada")
    conexao.desconectar()

    placas.rodar(servidor.trocar_chave_do_host)                  # a placa regravada (ou alguém no meio)
    tentativas = len(servidor.autenticacoes)
    conexao.conectar(destino=destino)
    esperar(qtbot, conexao, "bloqueada")
    assert (conexao.bloqueio.conhecida, conexao.bloqueio.apresentada) == (antiga, servidor.impressao)
    assert "bloqueada antes de qualquer senha" in conexao.motivo
    assert len(servidor.autenticacoes) == tentativas             # nada saiu daqui

    conexao.esquecer_chave_do_host()                             # o usuário conferiu: a placa foi regravada
    esperar(qtbot, conexao, "confirmar_host")
    assert conexao.impressao_pedida == servidor.impressao        # a nova, para conferir (a conhecida não a aceita)
    conexao.confirmar_host(True)
    esperar(qtbot, conexao, "conectada")
    assert preferencias.placas_conhecidas()[0].impressao == servidor.impressao


def test_nao_confiar_cancelar_e_a_senha_errada(qtbot, placas, criar):
    servidor = placas.nova()
    conexao = criar()
    destino = Destino("127.0.0.1", servidor.porta)
    conexao.conectar(destino=destino)
    esperar(qtbot, conexao, "confirmar_host")
    conexao.confirmar_host(False)
    assert conexao.estado == "desconectada"
    conexao.conectar(destino=destino)
    esperar(qtbot, conexao, "confirmar_host")
    conexao.cancelar()
    assert conexao.estado == "desconectada"
    assert not (conexao._pasta / "known_hosts").exists() or str(servidor.porta) not in \
        (conexao._pasta / "known_hosts").read_text()            # nada fixado
    conexao.conectar(destino=destino)
    esperar(qtbot, conexao, "confirmar_host")
    conexao.confirmar_host(True)
    esperar(qtbot, conexao, "pedir_senha")
    conexao.informar_senha("errada", instalar_chave=True)
    esperar(qtbot, conexao, "pedir_senha")
    assert conexao.motivo == "A senha foi recusada."
    conexao.informar_senha(servidor.senha, instalar_chave=False)
    esperar(qtbot, conexao, "conectada")
    assert conexao.primeira_conexao.sem_a_chave and not servidor.authorized_keys.exists()


def test_pelo_salto_com_a_senha_dele(qtbot, placas, criar):
    salto = placas.nova("salto", permitir_tunel=True, senha="senha-do-salto")
    servidor = placas.nova()
    conexao = criar()
    destino = Destino("127.0.0.1", servidor.porta, salto=Destino("127.0.0.1", salto.porta))
    conexao.conectar(destino=destino)
    esperar(qtbot, conexao, "confirmar_host")
    assert conexao.destino_pedido == destino.salto and conexao.impressao_pedida == salto.impressao
    conexao.confirmar_host(True)
    esperar(qtbot, conexao, "pedir_senha")
    assert conexao.destino_pedido == destino.salto
    conexao.informar_senha("senha-do-salto")
    esperar(qtbot, conexao, "confirmar_host")
    assert conexao.destino_pedido == destino and conexao.impressao_pedida == servidor.impressao
    conexao.confirmar_host(True)
    esperar(qtbot, conexao, "pedir_senha")
    assert conexao.destino_pedido == destino
    conexao.informar_senha(servidor.senha)
    esperar(qtbot, conexao, "conectada")
    assert servidor.authorized_keys.exists() and not salto.authorized_keys.exists()   # a chave só na placa


def test_a_queda_e_a_volta_sozinha(qtbot, placas, criar, monkeypatch):
    monkeypatch.setattr(modulo, "ESPERAS_DA_RECONEXAO_S", (0.05, 0.1, 0.2))
    servidor = placas.nova()
    conexao = criar(cofre=CofreFalso(**{f"debian@127.0.0.1:{servidor.porta}": servidor.senha}))
    conexao.conectar(destino=Destino("127.0.0.1", servidor.porta))
    esperar(qtbot, conexao, "confirmar_host")
    conexao.confirmar_host(True)
    esperar(qtbot, conexao, "conectada")
    qtbot.waitUntil(lambda: conexao.enlace is not None, timeout=ESPERA_MS)
    conexao.estados.clear()
    placas.laco.agendar(servidor.derrubar)                       # o cabo USB que solta e volta
    qtbot.waitUntil(lambda: conexao.estados[-2:] == ["reconectando", "conectada"], timeout=ESPERA_MS)
    assert conexao.quedas == 1 and conexao.motivo == "" and conexao.estado_da_placa is not None

    placas.rodar(servidor.parar)                                 # agora a placa some de vez
    qtbot.waitUntil(lambda: conexao.estado == "falhou", timeout=ESPERA_MS)
    assert "não voltou" in conexao.motivo and conexao.estados[-2:] == ["reconectando", "falhou"]
    placas.servidores.remove(servidor)
