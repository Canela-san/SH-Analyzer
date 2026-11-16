"""A saúde da placa conectada (``servicos/saude_da_placa.py``, F3.6), sem a tela: a saúde chega com a conexão, as
capturas e o firmware logo depois, a atividade sai ao vivo, os pinos são corrigidos, o relógio é acertado com a senha
da sessão, a do cofre ou a que o usuário dá (e a recusada pede outra), o relógio a cada conexão roda sozinho com a
permissão lembrada, e tudo some ao desconectar. Com o servidor SSH do teste (o sudo falso), sem placa."""

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")
pytest.importorskip("asyncssh")

from placas_de_teste import CofreFalso, Placas  # noqa: E402
from sh_analyzer_gui import preferencias  # noqa: E402
from sh_analyzer_gui.servicos.conexao_da_placa import ConexaoDaPlaca  # noqa: E402
from sh_analyzer_gui.servicos.placa import ServicoDaPlaca  # noqa: E402
from sh_analyzer_gui.servicos.saude_da_placa import SaudeDaPlaca  # noqa: E402
from sh_placa import conhecidas  # noqa: E402
from sh_placa.correcoes import ARQUIVO_DO_RELOGIO_SIMULADO  # noqa: E402
from sh_placa.descoberta import Descoberta, FonteSimulador  # noqa: E402
from sh_placa.destino import Destino  # noqa: E402

ESPERA_MS = 15_000


@pytest.fixture
def placas(tmp_path):
    p = Placas(tmp_path)
    yield p
    p.fechar()


@pytest.fixture
def criar(qapp, config_limpa, tmp_path):
    criadas = []

    def _criar(cofre=None):
        servico = ServicoDaPlaca()
        conexao = ConexaoDaPlaca(servico, descoberta=Descoberta([FonteSimulador()]), pasta=tmp_path / "aplicativo",
                                 cofre=cofre if cofre is not None else CofreFalso())
        saude = SaudeDaPlaca(conexao)
        saude.entradas = []
        saude.atividade.connect(saude.entradas.append)
        criadas.append((conexao, servico))
        return conexao, saude

    yield _criar
    for conexao, servico in criadas:
        conexao.encerrar()
        assert servico.encerrar()


def conectar(qtbot, conexao, servidor, senha=None):
    """Conecta ao servidor (confiando na impressão e dando a senha, se pedir) e espera as capturas."""
    conexao.conectar(destino=Destino("127.0.0.1", servidor.porta))
    qtbot.waitUntil(lambda: conexao.estado in ("confirmar_host", "pedir_senha", "conectada"), timeout=ESPERA_MS)
    if conexao.estado == "confirmar_host":
        conexao.confirmar_host(True)
        qtbot.waitUntil(lambda: conexao.estado in ("pedir_senha", "conectada"), timeout=ESPERA_MS)
    if conexao.estado == "pedir_senha":
        conexao.informar_senha(senha, instalar_chave=True)
    qtbot.waitUntil(lambda: conexao.estado == "conectada", timeout=ESPERA_MS)
    conexao.dispensar_primeira_conexao()


def esperar_a_correcao(qtbot, saude, *estados):
    qtbot.waitUntil(lambda: saude.correcao is not None and saude.correcao.estado in estados, timeout=ESPERA_MS)
    return saude.correcao


def test_a_saude_as_capturas_a_atividade_e_os_pinos(qtbot, placas, criar):
    servidor = placas.nova(cenario="pinos_errados")
    conexao, saude = criar(CofreFalso(**{f"debian@127.0.0.1:{servidor.porta}": servidor.senha}))
    conectar(qtbot, conexao, servidor)
    assert saude.saude is not None and saude.saude.tem_diagnostico and saude.conferida_em
    assert "pinos" in [p.codigo for p in saude.saude.diagnostico()]
    qtbot.waitUntil(lambda: saude.capturas is not None and not saude.conferindo, timeout=ESPERA_MS)
    assert saude.capturas.total == 2 and saude.firmware_do_aplicativo
    assert any(e.descricao == "agente: capturas" for e in saude.entradas)        # a atividade, ao vivo

    saude.corrigir_pinos()
    correcao = esperar_a_correcao(qtbot, saude, "feita", "falhou")
    assert (correcao.nome, correcao.estado, correcao.mensagem) == ("pinos", "feita", "Os pinos estão no modo da PRU.")
    assert saude.saude.pinos_errados == [] and "pinos" not in [p.codigo for p in saude.saude.diagnostico()]
    assert servidor.comandos_de_root == []

    saude.conferir()
    assert saude.conferindo
    qtbot.waitUntil(lambda: not saude.conferindo, timeout=ESPERA_MS)
    conexao.desconectar()
    assert saude.saude is None and saude.capturas is None and saude.correcao is None


def test_o_relogio_com_a_senha_da_sessao(qtbot, placas, criar):
    """Na primeira conexão o usuário digitou a senha da placa: o sudo usa a mesma, sem perguntar."""
    servidor = placas.nova()
    conexao, saude = criar()
    conectar(qtbot, conexao, servidor, senha=servidor.senha)
    saude.acertar_relogio()
    correcao = esperar_a_correcao(qtbot, saude, "feita", "falhou", "precisa_da_senha", "senha_recusada")
    assert correcao.estado == "feita" and correcao.mensagem.startswith("O relógio da placa já estava certo")
    assert saude.relogio_acertado is not None and (servidor.raiz / ARQUIVO_DO_RELOGIO_SIMULADO).exists()
    assert any(e.descricao.startswith("acertar o relógio") and e.codigo == 0 for e in conexao.registro.entradas)
    for texto in (conexao.registro.em_texto(), *servidor.comandos, *servidor.comandos_de_root):
        assert servidor.senha not in texto


def test_o_relogio_pede_a_senha_e_a_guarda(qtbot, placas, criar):
    """Só com a chave (a sessão não sabe a senha) e o cofre vazio: a correção pede a senha; a recusada pede outra;
    a certa acerta e, a pedido, vai para o cofre."""
    servidor = placas.nova(senha_do_sudo="a-do-sudo")
    cofre = CofreFalso()
    conexao, saude = criar(cofre)
    conectar(qtbot, conexao, servidor, senha=servidor.senha)          # instala a chave
    conexao.desconectar()
    conectar(qtbot, conexao, servidor)                                # agora só com a chave
    assert conexao.autenticada_com == "chave" and conexao.senha_da_placa() is None
    saude.acertar_relogio()
    assert esperar_a_correcao(qtbot, saude, "precisa_da_senha", "feita").estado == "precisa_da_senha"
    saude.acertar_relogio("errada")
    correcao = esperar_a_correcao(qtbot, saude, "senha_recusada", "feita")
    assert correcao.estado == "senha_recusada" and servidor.comandos_de_root == []
    saude.acertar_relogio("a-do-sudo", guardar=True)
    assert esperar_a_correcao(qtbot, saude, "feita", "falhou").estado == "feita"
    assert cofre.senhas == {f"debian@127.0.0.1:{servidor.porta}": "a-do-sudo"}
    saude.acertar_relogio()                                          # a da sessão, agora
    qtbot.waitUntil(lambda: saude.correcao.estado != "rodando", timeout=ESPERA_MS)
    assert saude.correcao.estado == "feita" and len(servidor.comandos_de_root) >= 2


def test_o_relogio_a_cada_conexao(qtbot, placas, criar):
    """Com a permissão lembrada com a placa, o relógio é acertado sozinho ao conectar (com a senha do cofre); sem
    senha nenhuma, fica o aviso, e nada roda."""
    servidor = placas.nova()
    cofre = CofreFalso()
    conexao, saude = criar(cofre)
    conectar(qtbot, conexao, servidor, senha=servidor.senha)
    serie = conexao.estado_da_placa.serie
    preferencias.mudar_placas_conhecidas(conhecidas.definir_relogio(preferencias.placas_conhecidas(), serie, True))
    conexao.desconectar()

    conectar(qtbot, conexao, servidor)                                # só a chave, e o cofre vazio
    qtbot.waitUntil(lambda: bool(saude.aviso_do_relogio), timeout=ESPERA_MS)
    assert "falta a senha do sudo" in saude.aviso_do_relogio and servidor.comandos_de_root == []
    conexao.desconectar()

    cofre.senhas[f"debian@127.0.0.1:{servidor.porta}"] = servidor.senha
    conectar(qtbot, conexao, servidor)
    correcao = esperar_a_correcao(qtbot, saude, "feita", "falhou")
    assert correcao.automatica and correcao.estado == "feita" and saude.aviso_do_relogio == ""
    assert len(servidor.comandos_de_root) == 1
