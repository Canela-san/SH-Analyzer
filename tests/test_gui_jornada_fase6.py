"""A jornada da Fase 6, de ponta a ponta (a F6.9: o "pronto quando" da fase, docs/gui-plan.md): na janela e pelos
gestos do usuário, com o simulador servido por SSH neste computador. A placa com o firmware antigo: o "Atualizar…" do
diagnóstico, uma atualização cuja PRU não sobe (a placa volta sozinha à versão de antes) e a que dá certo; a placa com o
``uEnv.txt`` que deixa o HDMI pegar os pinos: o "Ajustar…", a gravação com a cópia e o reinício, que volta com o boot
novo; os logs ao vivo, levados ao caderno; um serviço da imagem desligado; e a placa desligada até sumir, com o
caderno contando a manutenção toda. Sem placa e sem tela."""

from dataclasses import replace

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")
pytest.importorskip("asyncssh")

from dialogos_falsos import DialogosFalsos  # noqa: E402
from placas_de_teste import CofreFalso  # noqa: E402
from PySide6.QtWidgets import QLabel  # noqa: E402
from sh_analyzer_gui import preferencias  # noqa: E402
from sh_analyzer_gui.app import criar_aplicacao  # noqa: E402
from sh_analyzer_gui.areas.aquisicao.manutencao.secao import PAGINAS  # noqa: E402
from sh_analyzer_gui.janela import AREA_AQUISICAO, JanelaPrincipal  # noqa: E402
from sh_analyzer_gui.servicos import conexao_da_placa  # noqa: E402
from sh_placa import atualizacao, chaves  # noqa: E402
from sh_placa.descoberta import Descoberta, FonteSimulador  # noqa: E402
from sh_placa.simulador import VERSAO_ANTIGA  # noqa: E402
from test_gui_jornada_aquisicao import clicar, esperar_a_placa, secao  # noqa: E402
from test_gui_logs_e_monitor import escrever_no_diario  # noqa: E402

ESPERA_MS = 30_000
ESPERA_LONGA_MS = 90_000                      # a compilação na placa simulada, o reinício
FIRMWARE = atualizacao.firmware_do_aplicativo()
LIMPO = replace(FIRMWARE, versao=FIRMWARE.versao.removesuffix("-dirty"), mudancas=())


def com_marca(firmware, nome, marca):
    """O firmware com uma marca num arquivo (a ``SHAN_PRU_NAO_SOBE`` faz a PRU simulada não subir com ele)."""
    arquivos = tuple(replace(a, conteudo=a.conteudo + f"\n// {marca}\n".encode()) if a.caminho == nome else a
                     for a in firmware.arquivos)
    return replace(firmware, arquivos=arquivos, mudancas=())


@pytest.fixture
def janela(qapp, config_limpa, qtbot, tmp_path, monkeypatch):
    """A janela, com a lista de placas só com o simulador, o cofre falso e o firmware do repositório como se não
    tivesse mudanças não commitadas (``janela.firmware["atual"]`` troca o que o aplicativo manda); o reinício simulado
    é conferido a cada meio segundo."""
    monkeypatch.setenv("DADOS", str(tmp_path / "dados"))
    monkeypatch.setattr(chaves, "CofreDeSenhas", CofreFalso)
    monkeypatch.setattr(conexao_da_placa, "INTERVALO_DO_REINICIO_S", 0.5)
    firmware = {"atual": LIMPO}
    monkeypatch.setattr(atualizacao, "firmware_do_aplicativo", lambda *a, **k: firmware["atual"])
    preferencias.mudar_cenario_do_simulador("firmware_antigo")
    criar_aplicacao([], tema="escuro")
    j = JanelaPrincipal()
    j.controle.dialogos = DialogosFalsos()
    j.conexao_da_placa.descoberta = Descoberta([FonteSimulador()])
    j.firmware = firmware
    j.resize(1440, 900)
    j.show()
    qtbot.waitExposed(j)
    yield j
    j.projeto.pilha.setClean()
    j.close()
    j.deleteLater()


def pagina(area, nome) -> None:
    """O clique no seletor das páginas da Manutenção."""
    area.manutencao.escolha.botao([n for n, _t, _i in PAGINAS].index(nome)).click()
    assert area.manutencao.pagina == nome


def usar_o_firmware(qtbot, janela, firmware) -> None:
    """O firmware do aplicativo muda (outra versão na árvore), e o "Ler de novo" da página refaz o plano."""
    area = janela.aquisicao
    m = area.servico_da_manutencao
    janela.firmware["atual"] = firmware
    area.manutencao.firmware.ler_de_novo.click()
    qtbot.waitUntil(lambda: m.plano is not None and not m.lendo and m.plano.firmware is firmware, timeout=ESPERA_MS)


def atualizar(qtbot, area, botao):
    m = area.servico_da_manutencao
    botao.click()
    dialogo = area.manutencao.dialogo
    assert dialogo.isVisible() and not dialogo.caixa_da_senha.isVisible()     # o sudo: a senha da imagem
    dialogo.confirmar.click()
    qtbot.waitUntil(lambda: not dialogo.isVisible(), timeout=ESPERA_MS)
    qtbot.waitUntil(lambda: m.atualizacao is not None and m.atualizacao.estado == "terminou",
                    timeout=ESPERA_LONGA_MS)
    qtbot.waitUntil(lambda: not m.lendo and not area.saude.conferindo and m.plano is not None, timeout=ESPERA_MS)
    return m.atualizacao


def confirmar_a_acao(qtbot, area):
    s, dialogo = area.servico_do_sistema, area.manutencao.dialogo
    assert dialogo.isVisible() and not dialogo.caixa_da_senha.isVisible()
    dialogo.confirmar.click()
    qtbot.waitUntil(lambda: not dialogo.isVisible(), timeout=ESPERA_MS)
    qtbot.waitUntil(lambda: s.acao is not None and s.acao.estado in ("feita", "falhou"), timeout=ESPERA_LONGA_MS)
    assert s.acao.estado == "feita", s.acao.mensagem
    return s.acao


def nivel(area, item) -> str:
    return area.diagnostico.cartoes[item].item.nivel


def test_a_manutencao_da_placa_pela_janela(janela, qtbot):
    area, conexao = janela.aquisicao, janela.conexao_da_placa

    # 1. A placa com o firmware antigo: um clique na lista conecta, e o diagnóstico manda atualizar.
    janela.barra.areas.botao(AREA_AQUISICAO).click()
    qtbot.waitUntil(lambda: [p.estado for p in conexao.placas] == ["simulador"], timeout=ESPERA_MS)
    lista = area.lateral.lista
    clicar(lista, lista.model().index(0, 0))
    esperar_a_placa(qtbot, janela, "firmware_antigo")
    secao(area, "diagnostico")
    assert nivel(area, "firmware") in ("erro", "aviso")
    area.diagnostico.cartoes["firmware"].findChild(type(area.diagnostico.conferir), "corrigir_firmware").click()
    assert area.secao == "manutencao" and area.manutencao.pagina == "firmware"
    m = area.servico_da_manutencao
    qtbot.waitUntil(lambda: m.plano is not None and not m.lendo, timeout=ESPERA_MS)
    firmware = area.manutencao.firmware
    assert VERSAO_ANTIGA in firmware.subtitulo.text() and firmware.atualizar_placa.isEnabled()

    # 2. Uma versão cuja PRU não sobe: a placa volta sozinha à de antes, e o diagnóstico continua pedindo.
    usar_o_firmware(qtbot, janela, com_marca(LIMPO, "pru_main.c", "SHAN_PRU_NAO_SOBE"))
    a = atualizar(qtbot, area, firmware.atualizar_placa)
    assert a.desfecho.estado == "voltou" and firmware.selo.text() == "A placa voltou à versão anterior"
    assert firmware.linhas_dos_passos["voltar"].isVisible()
    assert firmware.linhas_dos_passos["voltar"].icone.property("nivel") == "ok"
    assert VERSAO_ANTIGA in firmware.subtitulo.text() and firmware.atualizar_placa.isEnabled()
    firmware.dispensar.click()

    # 3. A versão deste aplicativo: atualizada, conferida por um bloco do ler_adc, e o diagnóstico verde.
    usar_o_firmware(qtbot, janela, LIMPO)
    a = atualizar(qtbot, area, firmware.atualizar_placa)
    assert a.desfecho.estado == "atualizada" and a.desfecho.versao == LIMPO.versao
    assert firmware.selo.text() == "Firmware atualizado" and not firmware.atualizar_placa.isEnabled()
    assert "o ler_adc capturou um bloco" in firmware.linhas_dos_passos["conferir"].detalhe.text()
    secao(area, "diagnostico")
    assert nivel(area, "firmware") == "ok"

    # 4. Outra placa: a do uEnv.txt que deixa o HDMI pegar os pinos (o cenário, pela visão geral).
    secao(area, "visao_geral")
    v = area.visao_geral
    v.cenario.setCurrentIndex(v.cenario.findData("audio_hdmi"))
    v.cenario.activated.emit(v.cenario.currentIndex())
    esperar_a_placa(qtbot, janela, "audio_hdmi")
    secao(area, "diagnostico")
    assert nivel(area, "overlays") == "erro"
    area.diagnostico.cartoes["overlays"].findChild(type(area.diagnostico.conferir), "corrigir_uenv").click()
    assert area.secao == "manutencao" and area.manutencao.pagina == "inicializacao"
    s = area.servico_do_sistema
    qtbot.waitUntil(lambda: s.inicializacao is not None and s.detalhe is not None and not s.lendo,
                    timeout=ESPERA_MS)
    inicializacao = area.manutencao.inicializacao
    assert inicializacao.linhas_das_mudancas["audio"].caixa.isChecked()
    assert ("+", "disable_uboot_overlay_audio=1") in inicializacao.diff.linhas()

    # 5. Gravar e reiniciar: a cópia guardada, a queda esperada e a volta com o boot novo; o diagnóstico verde.
    boot_antes = conexao.estado_da_placa.boot
    inicializacao.gravar.click()
    dialogo = area.manutencao.dialogo
    assert dialogo.reiniciar_depois.isChecked() and dialogo.confirmar.text().endswith("e reiniciar")
    a = confirmar_a_acao(qtbot, area)
    assert conexao.reinicios == 1 and conexao.quedas == 0 and conexao.estado == "conectada"
    assert conexao.estado_da_placa.boot != boot_antes
    assert a.detalhes["copia"].startswith("/boot/uEnv.txt.sh-analyzer-")
    assert "voltou" in inicializacao.cartao_da_acao.texto.text()
    qtbot.waitUntil(lambda: s.inicializacao is not None and not s.lendo and not area.saude.conferindo,
                    timeout=ESPERA_MS)
    assert len(inicializacao.linhas_das_copias) == 1 and inicializacao.se_nao_voltar.isVisible()
    secao(area, "diagnostico")
    qtbot.waitUntil(lambda: nivel(area, "overlays") == "ok", timeout=ESPERA_MS)
    secao(area, "manutencao")
    inicializacao.cartao_da_acao.dispensar.click()

    # 6. Os logs ao vivo: a linha do USB chega sozinha; a vista vai para o caderno.
    pagina(area, "logs")
    monitor, logs = area.servico_do_monitor, area.manutencao.logs
    qtbot.waitUntil(lambda: monitor.logs is not None and not monitor.lendo_logs, timeout=ESPERA_MS)
    logs.ao_vivo.setChecked(True)
    qtbot.waitUntil(lambda: monitor.ao_vivo, timeout=ESPERA_MS)
    qtbot.wait(800)                                                    # o journalctl -f já está lendo
    escrever_no_diario(conexao, PRIORITY="3", SYSLOG_IDENTIFIER="kernel", _TRANSPORT="kernel",
                       MESSAGE="musb-hdrc musb-hdrc.0: VBUS_ERROR in a_wait_vrise")
    qtbot.waitUntil(lambda: any("VBUS_ERROR" in x.texto for x in logs.linhas), timeout=ESPERA_MS)
    logs.busca.setText("vbus")
    assert [x.texto for x in logs.visiveis] == ["musb-hdrc musb-hdrc.0: VBUS_ERROR in a_wait_vrise"]
    logs.caderno.click()

    # 7. O sistema: um serviço da imagem desligado (e o monitor anda enquanto isso).
    pagina(area, "sistema")
    qtbot.waitUntil(lambda: not monitor.ao_vivo, timeout=ESPERA_MS)                 # os logs saíram de vista
    sistema = area.manutencao.sistema_
    sistema.servicos.botoes["bonescript-autorun.service"].click()
    assert area.manutencao.dialogo.confirmar.text() == "Desligar"
    confirmar_a_acao(qtbot, area)
    qtbot.waitUntil(lambda: not s.lendo and sistema.servicos.botoes["bonescript-autorun.service"].text() == "Ligar…",
                    timeout=ESPERA_MS)
    qtbot.waitUntil(lambda: len(monitor.amostras) >= 2, timeout=ESPERA_MS)
    sistema.cartao_da_acao.dispensar.click()

    # 8. Desligar: a placa some, e a coluna da esquerda diz que já pode tirar da tomada.
    sistema.desligar.click()
    assert area.manutencao.dialogo.confirmar.text() == "Desligar"
    confirmar_a_acao(qtbot, area)
    assert conexao.estado == "desconectada" and conexao.desligada and conexao.quedas == 0
    assert sistema.cartao_da_acao.texto.text() == "A placa desligou: já pode tirar da tomada."
    assert any("A placa desligou" in w.text() for w in area.lateral.findChildren(QLabel))

    # 9. O caderno conta a manutenção, na ordem.
    entradas = [e.texto for e in area.caderno.entradas]
    marcos = ("voltou à versão anterior", "Firmware da placa atualizado", "/boot/uEnv.txt da placa gravado",
              "Logs da placa (o que importa", "Serviço da placa desligado", "Placa desligada")
    posicoes = [next(i for i, e in enumerate(entradas) if marco in e) for marco in marcos]
    assert posicoes == sorted(posicoes), entradas
    assert "VBUS_ERROR" in entradas[posicoes[3]]
