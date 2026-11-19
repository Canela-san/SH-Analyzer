"""As páginas Inicialização e Sistema da Manutenção (a F6.4 e a F6.5), com o simulador por SSH, sem tela: o "Ajustar…"
do diagnóstico abre a Inicialização; as mudanças do ``uEnv.txt`` marcadas, o diff, a gravação com a cópia e o
reinício que volta com o boot novo (o diagnóstico verde, o caderno); restaurar a cópia sem reiniciar; reiniciar com a
senha errada na sessão (o diálogo pede outra); a queda do cabo no meio da espera do reinício não vira um reinício;
desligar até a placa sumir ("pode tirar da tomada")."""

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")
pytest.importorskip("asyncssh")

import test_gui_simulador  # noqa: E402
from PySide6.QtWidgets import QLabel  # noqa: E402
from sh_analyzer_gui.servicos import conexao_da_placa  # noqa: E402
from test_gui_simulador import ESPERA_MS  # noqa: E402

abrir = test_gui_simulador.abrir        # a fixture que conecta ao simulador

ESPERA_DO_REINICIO_MS = 60_000


@pytest.fixture(autouse=True)
def reinicio_rapido(monkeypatch):
    """A placa simulada volta do reinício em ~6 s: tenta a cada meio segundo, em vez de 3 s."""
    monkeypatch.setattr(conexao_da_placa, "INTERVALO_DO_REINICIO_S", 0.5)


def esperar_a_leitura(qtbot, area):
    s = area.servico_do_sistema
    qtbot.waitUntil(lambda: s.inicializacao is not None and s.detalhe is not None and not s.lendo, timeout=ESPERA_MS)
    return s


def confirmar(qtbot, area, senha=None):
    dialogo = area.manutencao.dialogo
    assert dialogo.isVisible()
    if senha is not None:
        dialogo.campo_senha.setText(senha)
    dialogo.confirmar.click()
    qtbot.waitUntil(lambda: not dialogo.isVisible() or dialogo.caixa_da_senha.isVisible(), timeout=ESPERA_MS)
    return dialogo


def esperar_o_fim(qtbot, area):
    s = area.servico_do_sistema
    qtbot.waitUntil(lambda: s.acao is not None and s.acao.estado in ("feita", "falhou"),
                    timeout=ESPERA_DO_REINICIO_MS)
    return s.acao


def test_o_uenv_ajustado_e_a_placa_reiniciada_pela_tela(qtbot, abrir):
    area = abrir("audio_hdmi")
    c = area.conexao
    area.mostrar_secao("diagnostico")
    cartao = area.diagnostico.cartoes["overlays"]
    assert cartao.item.correcao == "uenv" and cartao.item.nivel == "erro"
    cartao.findChild(type(area.diagnostico.conferir), "corrigir_uenv").click()
    assert area.secao == "manutencao" and area.manutencao.pagina == "inicializacao"
    s = esperar_a_leitura(qtbot, area)
    pagina = area.manutencao.inicializacao
    mudancas = pagina.linhas_das_mudancas
    assert set(mudancas) == {"audio", "video"}
    assert mudancas["audio"].caixa.isChecked() and not mudancas["video"].caixa.isChecked()
    assert pagina.diff.linhas() == [("-", "#disable_uboot_overlay_audio=1"), ("+", "disable_uboot_overlay_audio=1")]
    mudancas["video"].caixa.setChecked(True)                          # o diff acompanha a escolha
    assert ("+", "disable_uboot_overlay_video=1") in pagina.diff.linhas()
    mudancas["video"].caixa.setChecked(False)
    assert not pagina.cartao_pendente.isVisible()

    pagina.gravar.click()
    dialogo = area.manutencao.dialogo
    assert dialogo.reiniciar_depois.isChecked() and dialogo.confirmar.text().endswith("e reiniciar")
    assert dialogo.diff.linhas() == pagina.diff.linhas()
    boot_antes = c.estado_da_placa.boot
    confirmar(qtbot, area)
    a = esperar_o_fim(qtbot, area)
    assert a.estado == "feita", a.mensagem
    assert c.reinicios == 1 and c.quedas == 0 and c.estado == "conectada" and c.estado_da_placa.boot != boot_antes
    assert a.detalhes["copia"].startswith("/boot/uEnv.txt.sh-analyzer-") and a.detalhes["voltou_em_s"] > 0
    assert pagina.cartao_da_acao.isVisible() and "voltou" in pagina.cartao_da_acao.texto.text()
    assert "Os pinos da PRU voltam ao padrão" in pagina.cartao_da_acao.texto.text()
    entradas = [e.texto for e in area.caderno.entradas]
    assert any("/boot/uEnv.txt da placa gravado" in e and "a placa reiniciou" in e and "```diff" in e
               for e in entradas)

    # depois do boot novo: nada mais a mudar, a cópia na lista, o diagnóstico verde
    qtbot.waitUntil(lambda: s.inicializacao is not None and not s.lendo and not area.saude.conferindo,
                    timeout=ESPERA_MS)
    assert [m.nome for m in s.propostas if m.necessaria] == [] and len(pagina.linhas_das_copias) == 1
    assert "disable_uboot_overlay_audio=1" in s.inicializacao["uenv"]["texto"].splitlines()
    area.mostrar_secao("diagnostico")
    qtbot.waitUntil(lambda: area.diagnostico.cartoes["overlays"].item.nivel == "ok", timeout=ESPERA_MS)
    pagina.cartao_da_acao.dispensar.click()
    assert s.acao is None

    # restaurar a cópia, sem reiniciar: o diff ao contrário, e o diagnóstico avisa o próximo boot
    area.mostrar_secao("manutencao")
    pagina.linhas_das_copias[0].botao.click()
    qtbot.waitUntil(lambda: area.manutencao.dialogo is not dialogo and area.manutencao.dialogo.isVisible(),
                    timeout=ESPERA_MS)
    dialogo = area.manutencao.dialogo
    assert dialogo.diff.linhas() == [("-", "disable_uboot_overlay_audio=1"), ("+", "#disable_uboot_overlay_audio=1")]
    dialogo.reiniciar_depois.setChecked(False)
    assert dialogo.confirmar.text() == "Gravar"
    confirmar(qtbot, area)
    a = esperar_o_fim(qtbot, area)
    assert a.estado == "feita" and a.energia is None and c.reinicios == 1
    assert "vale no próximo boot" in pagina.cartao_da_acao.texto.text()
    assert "pinos" not in pagina.cartao_da_acao.texto.text()
    qtbot.waitUntil(lambda: not s.lendo and "audio" in [m.nome for m in s.propostas], timeout=ESPERA_MS)
    assert len(pagina.linhas_das_copias) == 2
    assert any("restaurado da cópia" in e.texto and "vale no próximo boot" in e.texto for e in area.caderno.entradas)


def test_reiniciar_com_a_senha_errada_na_sessao(qtbot, abrir):
    area = abrir("normal")
    c, s = area.conexao, area.servico_do_sistema
    senha_certa = c._sessao.simulador.senha_do_sudo
    area.saude.lembrar_senha_do_sudo("nao-e-esta")
    area.mostrar_secao("manutencao")
    area.manutencao.mostrar_pagina("sistema")
    esperar_a_leitura(qtbot, area)
    pagina = area.manutencao.sistema_
    assert pagina.cartao_da_placa.isVisible() and pagina.reiniciar.isEnabled()
    pagina.reiniciar.click()
    dialogo = confirmar(qtbot, area)
    assert dialogo.isVisible() and dialogo.caixa_da_senha.isVisible() and s.acao.estado == "senha_recusada"
    assert c.queda_esperada is None                                   # o pedido não foi: nenhuma queda esperada
    confirmar(qtbot, area, senha=senha_certa)
    a = esperar_o_fim(qtbot, area)
    assert a.estado == "feita" and c.reinicios == 1
    assert area.saude.senha_do_sudo == senha_certa
    assert any("Placa reiniciada" in e.texto for e in area.caderno.entradas)
    for comando in c._sessao.simulador.comandos:
        assert senha_certa not in comando


def test_a_queda_do_cabo_na_espera_nao_vira_reinicio(qtbot, abrir, monkeypatch):
    """Esperando o reinício, o cabo cai (a placa nem reiniciou): a conexão volta no mesmo boot e diz que a placa não
    reiniciou, sem contar um reinício."""
    monkeypatch.setattr(conexao_da_placa, "ESPERA_DO_MESMO_BOOT_S", 1.5)
    area = abrir("normal")
    c = area.conexao
    nao_veio = []
    c.quedaNaoVeio.connect(nao_veio.append)
    c.esperar("reinicio")
    assert c.queda_esperada == "reinicio"
    assert c.servico.laco.agendar(c._sessao.simulador.derrubar)
    qtbot.waitUntil(lambda: nao_veio == ["reinicio"], timeout=ESPERA_MS)
    assert c.estado == "conectada" and c.reinicios == 0 and c.queda_esperada is None


def test_desligar_pela_tela(qtbot, abrir):
    area = abrir("normal")
    c = area.conexao
    area.mostrar_secao("manutencao")
    area.manutencao.mostrar_pagina("sistema")
    esperar_a_leitura(qtbot, area)
    area.manutencao.sistema_.desligar.click()
    dialogo = area.manutencao.dialogo
    assert dialogo.confirmar.text() == "Desligar" and dialogo.confirmar.variante == "perigo"
    confirmar(qtbot, area)
    a = esperar_o_fim(qtbot, area)
    assert a.estado == "feita", a.mensagem
    assert c.estado == "desconectada" and c.desligada and c.quedas == 0
    assert area.manutencao.sistema_.cartao_da_acao.texto.text() == "A placa desligou: já pode tirar da tomada."
    assert any("A placa desligou" in w.text() for w in area.lateral.findChildren(QLabel))
    assert any("Placa desligada" in e.texto for e in area.caderno.entradas)
