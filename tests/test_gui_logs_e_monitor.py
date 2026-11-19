"""A página Logs e o monitor da página Sistema (a F6.6), com o simulador por SSH, sem tela: os logs lidos, filtrados
pelo nível, pela origem e pela busca, "Tudo", o ao vivo (só o que importa, e só com a página à vista), salvar e o
caderno; o monitor com as amostras nos gráficos e os processos, e o ``ler_adc`` esquecido parado pelo "Parar…"."""

import json
import time

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")
pytest.importorskip("asyncssh")

import test_gui_simulador  # noqa: E402
from sh_placa.correcoes import com_sudo  # noqa: E402
from test_gui_simulador import ESPERA_MS  # noqa: E402

abrir = test_gui_simulador.abrir        # a fixture que conecta ao simulador


def escrever_no_diario(conexao, **entrada):
    """Uma linha nova no diário da placa simulada (o journalctl -f dela a entrega)."""
    arquivo = conexao._sessao.simulador.raiz / "var/log/journal-do-simulador.json"
    entrada.setdefault("__REALTIME_TIMESTAMP", str(int(time.time() * 1e6)))
    with open(arquivo, "a", encoding="utf-8") as f:
        f.write(json.dumps(entrada) + "\n")


class Dialogos:
    def __init__(self, caminho):
        self.caminho = caminho

    def salvar_arquivo(self, _titulo, _filtro, _sugestao=""):
        return self.caminho


def test_os_logs_filtram_e_seguem_ao_vivo(qtbot, abrir, tmp_path):
    area = abrir("normal")
    c, m = area.conexao, area.servico_do_monitor
    area.mostrar_secao("manutencao")
    area.manutencao.mostrar_pagina("logs")
    pagina = area.manutencao.logs
    qtbot.waitUntil(lambda: m.logs is not None and not m.lendo_logs, timeout=ESPERA_MS)
    importam = len(pagina.visiveis)
    assert importam == pagina.tabela.rowCount() > 0 and "linha(s)" in pagina.contagem.text()
    pagina.nivel.setCurrentIndex(2)                                    # só erros
    assert pagina.visiveis and all(linha.nivel is not None and linha.nivel <= 3 for linha in pagina.visiveis)
    pagina.nivel.setCurrentIndex(0)
    pagina.origem.setCurrentIndex(1)                                   # só o kernel
    assert all(linha.origem == "kernel" for linha in pagina.visiveis)
    pagina.origem.setCurrentIndex(0)
    pagina.busca.setText("sudo")
    assert pagina.visiveis and all("sudo" in f"{x.texto} {x.origem}".lower() for x in pagina.visiveis)
    pagina.busca.clear()

    # "Tudo": o agente manda tudo, e há mais linhas
    pagina.escopo.escolher(1)
    qtbot.waitUntil(lambda: m.todos and m.logs is not None and not m.lendo_logs, timeout=ESPERA_MS)
    assert len(pagina.visiveis) > importam
    pagina.escopo.escolher(0)
    qtbot.waitUntil(lambda: not m.todos and not m.lendo_logs, timeout=ESPERA_MS)

    # ao vivo: só o que importa entra
    pagina.ao_vivo.setChecked(True)
    qtbot.waitUntil(lambda: m.ao_vivo, timeout=ESPERA_MS)
    antes = len(pagina.linhas)
    qtbot.wait(800)                                                    # o journalctl -f já está lendo
    escrever_no_diario(c, PRIORITY="6", SYSLOG_IDENTIFIER="systemd", MESSAGE="Started Session 99 of user debian.",
                       _TRANSPORT="journal")
    escrever_no_diario(c, PRIORITY="3", SYSLOG_IDENTIFIER="kernel", MESSAGE="musb-hdrc musb-hdrc.0: VBUS_ERROR",
                       _TRANSPORT="kernel")
    qtbot.waitUntil(lambda: any("VBUS_ERROR" in x.texto for x in pagina.linhas), timeout=ESPERA_MS)
    assert len(pagina.linhas) == antes + 1                             # a sessão nova não importa
    assert "VBUS_ERROR" in pagina.tabela.item(pagina.tabela.rowCount() - 1, 3).text()
    assert "Ao vivo" in pagina.subtitulo.text()

    # salvar e o caderno
    pagina.dialogos_de = lambda: Dialogos(tmp_path / "logs.txt")
    assert pagina._salvar() == tmp_path / "logs.txt"
    salvo = (tmp_path / "logs.txt").read_text()
    assert "VBUS_ERROR" in salvo and len(salvo.splitlines()) == len(pagina.visiveis)
    pagina.caderno.click()
    assert any(e.texto.startswith("Logs da placa (o que importa") and "VBUS_ERROR" in e.texto and "```" in e.texto
               for e in area.caderno.entradas)

    # a página some: o journalctl -f para
    area.manutencao.mostrar_pagina("firmware")
    qtbot.waitUntil(lambda: not m.ao_vivo, timeout=ESPERA_MS)
    assert m.ao_vivo_pedido is False


def test_o_monitor_anda_e_para_o_ler_adc_esquecido(qtbot, abrir):
    area = abrir("normal")
    c, m, s = area.conexao, area.servico_do_monitor, area.servico_do_sistema
    area.mostrar_secao("manutencao")
    area.manutencao.mostrar_pagina("sistema")
    cartao = area.manutencao.sistema_.monitor
    qtbot.waitUntil(lambda: m.monitorando and len(m.amostras) >= 3 and m.processos is not None, timeout=ESPERA_MS)
    for nome in ("cpu", "memoria", "temperatura", "carga"):
        grafico = cartao.graficos[nome]
        assert grafico.pontos and grafico.texto_do_valor(grafico.valor_atual) != "—", nome
        assert not grafico.aviso
    cartao.graficos["cpu"].definir([], time.monotonic())           # o desenho, com e sem pontos, não quebra
    cartao.graficos["cpu"].aviso = "sem dados"
    cartao.graficos["cpu"].grab()
    assert cartao.processos.rowCount() > 0 and not cartao.captura.isVisible()
    assert "a cada 1 s" in cartao.situacao.text()

    # um ler_adc que esta janela não começou (do terminal, de um coletar.sh)
    simulador = c._sessao.simulador
    roteiro = com_sudo("true\ncd \"$HOME\"/firmware && sudo -n sh -c 'setsid ./ler_adc 102400 0 --blocos 0 -o - "
                       "< /dev/null > /dev/null 2>&1 &'")
    async def lancar():
        return await c.conexao_ssh.executar(roteiro, entrada=simulador.senha_do_sudo + "\n")

    r = c.servico.laco.submeter(lancar).resultado(30)
    assert r.codigo == 0, r.erro
    m.ler_processos()
    qtbot.waitUntil(lambda: cartao.captura.isVisible(), timeout=ESPERA_MS)
    assert "PID" in cartao.texto_da_captura.text() and m.capturas

    cartao.parar.click()
    dialogo = area.manutencao.dialogo
    assert dialogo.confirmar.text() == "Parar" and str(m.capturas[0].pid) in dialogo.explicacao.text()
    dialogo.confirmar.click()
    qtbot.waitUntil(lambda: s.acao is not None and s.acao.estado in ("feita", "falhou"), timeout=ESPERA_MS)
    assert s.acao.estado == "feita", s.acao.mensagem
    assert "O ler_adc parou" in area.manutencao.sistema_.cartao_da_acao.texto.text()
    qtbot.waitUntil(lambda: not m.capturas and not cartao.captura.isVisible(), timeout=ESPERA_MS)

    # a página some: o monitor para
    area.manutencao.mostrar_pagina("firmware")
    qtbot.waitUntil(lambda: not m.monitorando, timeout=ESPERA_MS)
