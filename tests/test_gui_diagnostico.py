"""A visão geral e o diagnóstico na tela (F3.6), com o servidor SSH do teste: os itens de cada cenário, o "Corrigir"
que só roda depois da confirmação, uma vez, e fica no registro; o relógio que pede a senha do sudo só quando a sessão
não a tem; a senha do sudo em lugar nenhum; e o relatório copiado e salvo. Sem placa e sem tela."""

import logging

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")
pytest.importorskip("asyncssh")

from dialogos_falsos import DialogosFalsos  # noqa: E402
from placas_de_teste import CofreFalso, Placas  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402
from PySide6.QtWidgets import QAbstractButton  # noqa: E402
from sh_analyzer_gui.app import criar_aplicacao  # noqa: E402
from sh_analyzer_gui.areas.aquisicao.area import AreaDeAquisicao  # noqa: E402
from sh_analyzer_gui.areas.aquisicao.visao_geral import LinhaDaSaude  # noqa: E402
from sh_analyzer_gui.servicos.conexao_da_placa import ConexaoDaPlaca  # noqa: E402
from sh_analyzer_gui.servicos.placa import ServicoDaPlaca  # noqa: E402
from sh_analyzer_gui.servicos.saude_da_placa import SaudeDaPlaca  # noqa: E402
from sh_placa.correcoes import ARQUIVO_DO_RELOGIO_SIMULADO  # noqa: E402
from sh_placa.descoberta import Descoberta, FonteSimulador  # noqa: E402
from sh_placa.destino import Destino  # noqa: E402

ESPERA_MS = 15_000
SENHA_DO_SUDO = "a-senha-do-sudo-do-teste"


@pytest.fixture
def placas(tmp_path):
    p = Placas(tmp_path)
    yield p
    p.fechar()


@pytest.fixture
def conectar(qapp, config_limpa, qtbot, tmp_path):
    """A área à vista, conectada ao servidor (a impressão confirmada, a senha do SSH do cofre), com as capturas
    lidas."""
    criar_aplicacao([], tema="escuro")
    abertas = []

    def _conectar(servidor, dialogos=None):
        servico = ServicoDaPlaca()
        conta = f"debian@127.0.0.1:{servidor.porta}"
        conexao = ConexaoDaPlaca(servico, descoberta=Descoberta([FonteSimulador()]), pasta=tmp_path / "aplicativo",
                                 cofre=CofreFalso(**{conta: servidor.senha}))
        saude = SaudeDaPlaca(conexao)
        area = AreaDeAquisicao(conexao, saude, (lambda: dialogos) if dialogos is not None else None)
        area.resize(1400, 860)
        area.show()
        qtbot.waitExposed(area)
        abertas.append((area, conexao, servico))
        conexao.conectar(destino=Destino("127.0.0.1", servidor.porta))
        qtbot.waitUntil(lambda: conexao.estado == "confirmar_host", timeout=ESPERA_MS)
        conexao.confirmar_host(True)
        qtbot.waitUntil(lambda: conexao.estado == "conectada", timeout=ESPERA_MS)
        conexao.dispensar_primeira_conexao()
        if area._dialogo is not None:
            area._dialogo.done(0)
        qtbot.waitUntil(lambda: saude.capturas is not None and not saude.conferindo and conexao.enlace is not None,
                        timeout=ESPERA_MS)
        return area

    yield _conectar
    for area, conexao, servico in abertas:
        for dialogo in (area._dialogo, area.dialogo_de_correcao):
            if dialogo is not None:
                dialogo.done(0)
        area.close()
        conexao.encerrar()
        assert servico.encerrar()
        area.deleteLater()


def linhas(area) -> dict[str, LinhaDaSaude]:
    return area.visao_geral.linhas


def niveis(area) -> dict[str, str]:
    return {chave: cartao.item.nivel for chave, cartao in area.diagnostico.cartoes.items()}


@pytest.mark.parametrize("cenario, esperado", [
    ("normal", {"pinos": "ok", "pru": "ok", "memoria_dos_buffers": "ok"}),
    ("pinos_errados", {"pinos": "erro", "pru": "ok"}),
    ("sem_overlay_da_pru", {"pru": "erro", "pinos": "ok"}),
    ("sem_mem_496m", {"memoria_dos_buffers": "erro"}),
])
def test_os_itens_de_cada_cenario_na_tela(qtbot, placas, conectar, cenario, esperado):
    area = conectar(placas.nova(cenario=cenario))
    area.mostrar_secao("diagnostico")
    qtbot.waitUntil(lambda: bool(niveis(area)), timeout=ESPERA_MS)
    vistos = niveis(area)
    assert vistos["conexao"] == "ok" and {k: vistos[k] for k in esperado} == esperado
    assert (linhas(area)["pinos"].acao is not None) is (cenario == "pinos_errados")
    pronta = "Pronta para capturar" in area.diagnostico.subtitulo.text()
    assert pronta is (cenario == "normal")


def test_o_corrigir_dos_pinos_so_roda_depois_de_confirmar(qtbot, placas, conectar):
    servidor = placas.nova(cenario="pinos_errados")
    area = conectar(servidor)
    linhas(area)["pinos"].acao.click()
    dialogo = area.dialogo_de_correcao
    assert dialogo.isVisible() and dialogo.confirmar.text() == "Pôr P9_28 e P9_31 no modo da PRU"
    dialogo.ver.setChecked(True)
    assert dialogo.comando.rotulo.text() == "config-pin P9_31 pruout && config-pin P9_28 pruout"
    assert not any("config-pin" in c for c in servidor.comandos)            # nada rodou antes de confirmar
    dialogo.reject()
    assert not any("config-pin" in c for c in servidor.comandos)            # nem depois de cancelar

    area.corrigir("pinos").confirmar.click()
    qtbot.waitUntil(lambda: not area.dialogo_de_correcao.isVisible(), timeout=ESPERA_MS)
    assert [c for c in servidor.comandos if "config-pin" in c] == ["config-pin P9_31 pruout && config-pin P9_28 pruout"]
    (registrado,) = [e for e in area.conexao.registro.entradas if "config-pin" in e.comando]
    assert registrado.codigo == 0 and area.saude.saude.pinos_errados == []
    pinos = linhas(area)["pinos"]
    assert pinos.item.nivel == "ok" and pinos.acao is None


def test_o_relogio_pede_a_senha_do_sudo_e_ela_nao_aparece(qtbot, placas, conectar, caplog):
    caplog.set_level(logging.DEBUG)
    servidor = placas.nova(senha_do_sudo=SENHA_DO_SUDO)                   # outra senha que a do SSH
    area = conectar(servidor)
    dialogo = area.corrigir("relogio")
    assert not dialogo.caixa_da_senha.isVisible() and dialogo.a_cada_conexao.isVisible()
    assert servidor.comandos_de_root == []
    dialogo.confirmar.click()                                              # a da sessão (a do SSH): recusada
    qtbot.waitUntil(lambda: dialogo.caixa_da_senha.isVisible(), timeout=ESPERA_MS)
    assert "recusou a senha do sudo" in dialogo.mensagem.text() and servidor.comandos_de_root == []
    dialogo.campo_senha.setText(SENHA_DO_SUDO)
    dialogo.confirmar.click()
    assert dialogo.campo_senha.text() == ""                                # não fica no campo
    qtbot.waitUntil(lambda: not dialogo.isVisible(), timeout=ESPERA_MS)
    assert len(servidor.comandos_de_root) == 1 and (servidor.raiz / ARQUIVO_DO_RELOGIO_SIMULADO).exists()
    assert "acertado pelo computador às " in area.visao_geral.relogio.detalhe.text()
    for texto in (area.conexao.registro.em_texto(), caplog.text, *servidor.comandos, *servidor.comandos_de_root,
                  area.diagnostico.relatorio()):
        assert SENHA_DO_SUDO not in texto


def test_o_relatorio_copiado_e_salvo(qtbot, placas, conectar, tmp_path):
    destino = tmp_path / "relatorio.md"
    dialogos = DialogosFalsos(str(destino))
    area = conectar(placas.nova(cenario="pinos_errados"), dialogos)
    area.mostrar_secao("diagnostico")
    area.diagnostico.findChild(QAbstractButton, "copiar_relatorio").click()
    copiado = QGuiApplication.clipboard().text()
    assert copiado.startswith("# Diagnóstico da placa") and "Pinos fora do modo da PRU" in copiado
    assert "## Registro de atividade" in copiado and "agente: saude" in copiado
    area.diagnostico.findChild(QAbstractButton, "salvar_relatorio").click()
    assert dialogos.perguntas == ["Salvar o relatório do diagnóstico"]
    assert destino.read_text(encoding="utf-8").startswith("# Diagnóstico da placa")
