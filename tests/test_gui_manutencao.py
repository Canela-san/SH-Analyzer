"""A seção Manutenção na tela (a F6.3), com o simulador por SSH, sem tela: o "Atualizar…" do diagnóstico abre a
página do firmware; a placa com o firmware antigo é atualizada pelo diálogo (os passos ao vivo, o log, o desfecho, o
caderno, o diagnóstico verde, a cópia na lista); a PRU que não sobe com o firmware novo volta sozinha (o passo
"Voltar à versão anterior" à vista); voltar a uma cópia pelo botão dela; as mudanças não commitadas pedem o "Enviar
assim mesmo"; e o "Recarregar…" da PRU desatualizada."""

from dataclasses import replace

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")
pytest.importorskip("asyncssh")

import test_gui_simulador  # noqa: E402
from sh_placa import atualizacao  # noqa: E402
from sh_placa.simulador import VERSAO_ANTIGA  # noqa: E402
from test_gui_simulador import ESPERA_MS  # noqa: E402

abrir = test_gui_simulador.abrir        # a fixture que conecta ao simulador

ESPERA_DA_ATUALIZACAO_MS = 90_000
FIRMWARE = atualizacao.firmware_do_aplicativo()


@pytest.fixture
def firmware_limpo(monkeypatch):
    """O firmware do repositório como se não tivesse mudanças não commitadas (o teste não depende da árvore de quem o
    roda); ``usar(firmware)`` troca o que o aplicativo manda."""
    atual = {"firmware": replace(FIRMWARE, versao=FIRMWARE.versao.removesuffix("-dirty"), mudancas=())}
    monkeypatch.setattr(atualizacao, "firmware_do_aplicativo", lambda *a, **k: atual["firmware"])

    def usar(firmware):
        atual["firmware"] = firmware

    return usar


def com_marca(firmware, nome, marca):
    arquivos = tuple(replace(a, conteudo=a.conteudo + f"\n// {marca}\n".encode()) if a.caminho == nome else a
                     for a in firmware.arquivos)
    return replace(firmware, arquivos=arquivos, mudancas=())


def esperar_o_plano(qtbot, area):
    m = area.servico_da_manutencao
    qtbot.waitUntil(lambda: m.plano is not None and not m.lendo, timeout=ESPERA_MS)
    return m


def atualizar_pela_tela(qtbot, area, botao):
    m = area.servico_da_manutencao
    botao.click()
    dialogo = area.manutencao.dialogo
    assert dialogo.isVisible() and not dialogo.caixa_da_senha.isVisible()     # a sessão conhece a senha do sudo
    dialogo.confirmar.click()
    qtbot.waitUntil(lambda: not dialogo.isVisible(), timeout=ESPERA_MS)
    qtbot.waitUntil(lambda: m.atualizacao is not None and m.atualizacao.estado == "terminou",
                    timeout=ESPERA_DA_ATUALIZACAO_MS)
    qtbot.waitUntil(lambda: not m.lendo and not area.saude.conferindo and m.plano is not None, timeout=ESPERA_MS)
    return m.atualizacao


def test_o_firmware_antigo_atualizado_pela_tela(qtbot, abrir, firmware_limpo):
    area = abrir("firmware_antigo")
    area.mostrar_secao("diagnostico")
    cartao = area.diagnostico.cartoes["firmware"]
    assert cartao.item.correcao == "firmware" and cartao.item.nivel in ("erro", "aviso")
    cartao.findChild(type(area.diagnostico.conferir), "corrigir_firmware").click()
    assert area.secao == "manutencao" and area.manutencao.pagina == "firmware"
    m = esperar_o_plano(qtbot, area)
    pagina = area.manutencao.firmware
    assert VERSAO_ANTIGA in pagina.subtitulo.text() and pagina.atualizar_placa.isEnabled()
    assert "ler_adc.c" in pagina.o_que_muda.text() and not pagina.sujo.isVisible()

    a = atualizar_pela_tela(qtbot, area, pagina.atualizar_placa)
    assert a.desfecho.estado == "atualizada" and a.desfecho.versao == FIRMWARE.versao.removesuffix("-dirty")
    assert pagina.cartao_da_atualizacao.isVisible() and pagina.selo.text() == "Firmware atualizado"
    for nome in ("enviar", "preparar", "compilar", "guardar", "instalar", "carregar", "conferir", "limpar"):
        assert pagina.linhas_dos_passos[nome].icone.property("nivel") == "ok", nome
    assert not pagina.linhas_dos_passos["voltar"].isVisible()
    assert "o ler_adc capturou um bloco" in pagina.linhas_dos_passos["conferir"].detalhe.text()
    assert "Captura concluída" in pagina.log.toPlainText() or "clpru" in pagina.log.toPlainText()
    assert m.plano.nada_muda and not pagina.atualizar_placa.isEnabled()          # a placa já tem este firmware
    assert [c.versao for c in m.copias] == [VERSAO_ANTIGA] and len(pagina.linhas_das_copias) == 1
    assert any("Firmware da placa atualizado" in e.texto for e in area.caderno.entradas)
    area.mostrar_secao("diagnostico")
    assert area.diagnostico.cartoes["firmware"].item.nivel == "ok"
    pagina.dispensar.click()
    assert not pagina.cartao_da_atualizacao.isVisible()

    # voltar à cópia do v0.7.0, pelo botão dela
    area.mostrar_secao("manutencao")
    a = atualizar_pela_tela(qtbot, area, pagina.linhas_das_copias[0].botao_voltar)
    assert a.desfecho.estado == "atualizada" and a.desfecho.versao == VERSAO_ANTIGA
    assert pagina.selo.text() == "De volta à versão escolhida"
    assert VERSAO_ANTIGA in pagina.subtitulo.text() and pagina.atualizar_placa.isEnabled()
    assert any("de volta a uma versão anterior" in e.texto for e in area.caderno.entradas)


def test_a_pru_que_nao_sobe_volta_sozinha_na_tela(qtbot, abrir, firmware_limpo):
    firmware_limpo(com_marca(FIRMWARE, "pru_main.c", "SHAN_PRU_NAO_SOBE"))
    area = abrir("normal")
    area.mostrar_secao("manutencao")
    esperar_o_plano(qtbot, area)
    pagina = area.manutencao.firmware
    a = atualizar_pela_tela(qtbot, area, pagina.atualizar_placa)
    assert a.desfecho.estado == "voltou" and pagina.selo.text() == "A placa voltou à versão anterior"
    assert pagina.linhas_dos_passos["carregar"].icone.property("nivel") in ("ok", "erro")
    assert pagina.linhas_dos_passos["voltar"].isVisible()
    assert pagina.linhas_dos_passos["voltar"].icone.property("nivel") == "ok"
    assert any("voltou à versão anterior" in e.texto for e in area.caderno.entradas)
    area.mostrar_secao("diagnostico")
    assert area.diagnostico.cartoes["firmware"].item.nivel == "ok"            # como estava


def test_as_mudancas_nao_commitadas_e_recarregar_a_pru(qtbot, abrir, firmware_limpo):
    firmware_limpo(replace(FIRMWARE, versao="v9.9-1-gabc-dirty", mudancas=("firmware/ler_adc.c",)))
    area = abrir("pru_desatualizada")
    area.mostrar_secao("manutencao")
    esperar_o_plano(qtbot, area)
    pagina = area.manutencao.firmware
    assert pagina.sujo.isVisible() and "firmware/ler_adc.c" in pagina.sujo.text()
    assert pagina.enviar_assim_mesmo.isVisible() and not pagina.atualizar_placa.isEnabled()
    pagina.enviar_assim_mesmo.setChecked(True)
    assert pagina.atualizar_placa.isEnabled()

    area.mostrar_secao("diagnostico")
    assert area.diagnostico.cartoes["firmware"].item.correcao == "pru"
    dialogo = area.corrigir("pru")
    assert "Recarregar" in dialogo.confirmar.text() and not dialogo.caixa_da_senha.isVisible()
    dialogo.confirmar.click()
    qtbot.waitUntil(lambda: not dialogo.isVisible(), timeout=ESPERA_MS)
    assert area.saude.correcao.estado == "feita"
    assert area.diagnostico.cartoes["firmware"].item.nivel == "ok"
    assert any("Firmware da PRU recarregado" in e.texto for e in area.caderno.entradas)
