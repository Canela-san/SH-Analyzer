"""O diagnóstico item a item e o relatório (``sh_placa/diagnostico.py``) e o firmware do aplicativo comparado pelo código
(``sh_placa/versao.py``), F3.6: cada cenário do simulador dá os itens certos, todo código do agente tem um item, um
código desconhecido não some, o relatório traz o que importa, e a versão do firmware só muda quando o firmware muda.
Sem Qt e sem placa."""

import asyncio
import re
import subprocess
import time
from pathlib import Path

import pytest
from sh_placa.diagnostico import CATEGORIAS, itens_do_diagnostico, relatorio
from sh_placa.estado import EstadoDaPlaca
from sh_placa.registro import Entrada
from sh_placa.simulador import CENARIOS, VERSAO_SIMULADA, Simulador
from sh_placa.versao import commit_da_versao, firmware_do_aplicativo

AGENTE = Path(__file__).resolve().parents[1] / "firmware" / "agente" / "shan_agente.py"
ITENS_DE_CADA_CENARIO = {
    "normal": {"disco": "info"},
    "pru_com_falha": {"pru": "erro", "disco": "info"},
    "pinos_errados": {"pinos": "erro", "disco": "info"},
    "sem_mem_496m": {"memoria_dos_buffers": "erro", "disco": "info"},
    "firmware_antigo": {"firmware": "aviso", "disco": "info"},
    "sem_compilar": {"firmware": "erro", "disco": "info"},
    "pru_desatualizada": {"firmware": "erro", "disco": "info"},
    "audio_hdmi": {"overlays": "erro", "pinos": "erro", "disco": "info"},
    "sem_overlay_da_pru": {"pru": "erro", "disco": "info"},
    "adc_mudo": {"aquisicao": "aviso", "disco": "info"},
    "disco_cheio": {"disco": "erro"},
    "conexao_instavel": {"disco": "info"},
    "relogio_errado": {"relogio": "aviso", "disco": "info"},
}
SAUDE: dict[str, EstadoDaPlaca] = {}


def saude(cenario: str) -> EstadoDaPlaca:
    if cenario not in SAUDE:
        with Simulador(cenario) as cliente:
            SAUDE[cenario] = asyncio.run(cliente.saude())
    return SAUDE[cenario]


def test_todo_codigo_do_agente_tem_um_item():
    emitidos = set(re.findall(r'\bitem\(\s*"(?:erro|aviso|info)",\s*"([a-z_0-9]+)"', AGENTE.read_text(encoding="utf-8")))
    assert len(emitidos) > 20
    com_item = {codigo for _chave, _titulo, codigos in CATEGORIAS for codigo in codigos}
    assert emitidos - com_item == set()
    assert {"relogio", "firmware_diferente"} <= com_item                  # os dois do computador


@pytest.mark.parametrize("cenario", CENARIOS)
def test_os_itens_de_cada_cenario(cenario):
    itens = itens_do_diagnostico(saude(cenario), VERSAO_SIMULADA)
    assert [i.chave for i in itens] == [c[0] for c in CATEGORIAS]
    assert {i.chave: i.nivel for i in itens if i.nivel != "ok"} == ITENS_DE_CADA_CENARIO[cenario]
    assert all(i.resumo for i in itens)
    pinos = next(i for i in itens if i.chave == "pinos")
    assert pinos.correcao == ("pinos" if cenario in ("pinos_errados", "audio_hdmi") else None)
    relogio = next(i for i in itens if i.chave == "relogio")
    assert relogio.correcao == ("relogio" if cenario == "relogio_errado" else None)   # os outros, sincronizados


def test_os_resumos_dizem_o_que_foi_lido():
    resumos = {i.chave: i.resumo for i in itens_do_diagnostico(saude("normal"), VERSAO_SIMULADA)}
    assert resumos["pinos"] == "P9_28, P9_29 e P9_31 em pruout; P9_30 em pruin"
    assert resumos["pru"] == "parada (o normal entre capturas) · am335x-pru0-fw · protocolo 5"
    assert resumos["memoria_dos_buffers"] == "mem=496M no boot de agora e no próximo"
    assert resumos["firmware"] == f"{VERSAO_SIMULADA} · o deste aplicativo · ler_adc compilado"
    assert resumos["relogio"].endswith("sincronizado (timesyncd)") and " s do computador (±" in resumos["relogio"]
    assert re.fullmatch(r"\d+ °C · carga 0,\d\d · [\d,]+ MiB de memória livres · ligada há .+", resumos["sistema"])
    assert "livres de" in resumos["disco"] and "min de captura a 400 kS/s" in resumos["disco"]
    errados = {i.chave: i.resumo for i in itens_do_diagnostico(saude("pinos_errados"))}
    assert errados["pinos"] == "P9_28 em default (a PRU pede pruout); P9_31 em default (a PRU pede pruout)"


def test_o_relogio_sem_ntp_e_o_codigo_desconhecido():
    agora = 2_000_000_000.0
    estado = EstadoDaPlaca({"conferencias": [
        {"nivel": "info", "codigo": "relogio_sem_ntp", "texto": "Sem NTP."},
        {"nivel": "aviso", "codigo": "de_um_agente_mais_novo", "texto": "?"}],
        "relogio": {"utc": agora - 41.7, "sincronizado": False}}, recebido_em=agora)
    itens = {i.chave: i for i in itens_do_diagnostico(estado, agora=agora)}
    assert itens["relogio"].nivel == "aviso" and itens["relogio"].correcao == "relogio"
    assert [p.codigo for p in itens["relogio"].problemas] == ["relogio", "relogio_sem_ntp"]
    assert itens["relogio"].resumo.startswith("−41,70 s do computador")
    # Dias de diferença (a placa que ficou desligada sem a bateria do RTC): o tempo legível, e os segundos ao lado.
    estado = EstadoDaPlaca({"conferencias": [], "relogio": {"utc": agora - 191_607.5, "sincronizado": False}},
                           recebido_em=agora)
    (relogio,) = [i for i in itens_do_diagnostico(estado, agora=agora) if i.chave == "relogio"]
    assert relogio.resumo == "2 dias e 5 h atrasado (−191\u2009608 s) · sem NTP"
    assert "está 2 dias e 5 h atrasado em relação ao do computador" in relogio.problemas[0].texto
    assert itens["outros"].nivel == "aviso" and itens["outros"].problemas[0].codigo == "de_um_agente_mais_novo"
    with pytest.raises(ValueError, match="saúde"):
        itens_do_diagnostico(EstadoDaPlaca({"placa": {}}))


def test_a_placa_de_aquisicao_pela_captura_mais_recente():
    """O item da placa de aquisição: o sinal da captura mais recente (o ADC que não respondeu fica em 0)."""
    def item(ultima, conferencias=()):
        estado = EstadoDaPlaca({"conferencias": list(conferencias), "ultima_captura": ultima})
        return next(i for i in itens_do_diagnostico(estado) if i.chave == "aquisicao")

    def captura(parados, canais=(0, 1)):
        return {"arquivo": "conferir_1015.bin", "bytes": 1, "modificado": 0.0,
                "cabecalho": {"canais": list(canais), "canais_parados": parados}}

    assert item(None).resumo.startswith("nenhuma captura na placa") and item(None).nivel == "ok"
    assert item(captura([])).resumo == "sinal nos 2 canais da captura mais recente (conferir_1015.bin)"
    assert item(captura([], canais=(3,))).resumo == "sinal no canal da captura mais recente (conferir_1015.bin)"
    assert "não traz o sinal de cada canal" in item(captura(None)).resumo
    mudo = item(captura([{"canal": 0, "codigo": 0}, {"canal": 1, "codigo": 0}]),
                [{"nivel": "aviso", "codigo": "adc_mudo", "texto": "O ADC não respondeu."}])
    assert mudo.nivel == "aviso" and mudo.resumo == "os 2 canais em 0 na captura mais recente (conferir_1015.bin)"
    assert [p.codigo for p in mudo.problemas] == ["adc_mudo"]
    saturado = item(captura([{"canal": 1, "codigo": 65535}]))
    assert saturado.resumo == "o canal 1 parado em 0xFFFF na captura mais recente (conferir_1015.bin)"
    dois = item(captura([{"canal": 0, "codigo": 32768}, {"canal": 1, "codigo": 65535}]))
    assert dois.resumo == ("o canal 0 parado em 0x8000 e o canal 1 parado em 0xFFFF na captura mais recente "
                           "(conferir_1015.bin)")


def test_o_relatorio():
    agora = time.time()
    registro = [Entrada(agora - 5, "debian@192.168.6.2", "comando", "agente: saude", "python3 - saude", 0.6, 0),
                Entrada(agora - 4, "debian@192.168.6.2", "conexao", "conectado, com a chave do aplicativo")]
    texto = relatorio(saude("pinos_errados"), VERSAO_SIMULADA, conexao="USB (ECM) · latência 1,1 ms",
                      registro=registro, agora=agora, aplicativo="SH-Analyzer 0.8.0")
    assert texto.startswith("# Diagnóstico da placa\n")
    assert "- **Placa:** BeagleBone Black, nº 3714BBBK1234" in texto
    assert "- **Conexão:** USB (ECM) · latência 1,1 ms" in texto and "pelo SH-Analyzer 0.8.0" in texto
    assert "**Não está pronta para capturar:** 1 erro(s) e 0 aviso(s)." in texto
    assert "| Erro | Pinos da PRU | P9_28 em default" in texto and texto.count("\n| ") == 1 + len(CATEGORIAS)
    assert "- **Erro (Pinos da PRU):** Pinos fora do modo da PRU: P9_28, P9_31." in texto
    assert "  - Correção: config-pin" in texto
    assert "## Registro de atividade" in texto and "agente: saude (0,60 s, código 0)" in texto
    assert "**Pronta para capturar.**" in relatorio(saude("normal"), VERSAO_SIMULADA)


def test_o_commit_de_uma_versao():
    assert commit_da_versao("v0.8-137-g9b0ae82") == "9b0ae82"
    assert commit_da_versao("v0.8-137-g9b0ae82-dirty") == "9b0ae82"
    assert commit_da_versao("9b0ae82") == "9b0ae82"
    assert commit_da_versao("v0.8.0") is None and commit_da_versao("v0.8.0-simulador") is None


def _git(raiz, *argumentos):
    return subprocess.run(["git", "-C", str(raiz), *argumentos], capture_output=True, text=True, check=True).stdout


@pytest.fixture
def repositorio(tmp_path):
    """Um repositório com um firmware: o código, o agente e o VERSAO (fora do git, como o do enviar)."""
    raiz = tmp_path / "repo"
    (raiz / "firmware" / "agente").mkdir(parents=True)
    _git(raiz, "init", "-q")
    _git(raiz, "config", "user.email", "teste@exemplo")
    _git(raiz, "config", "user.name", "teste")
    (raiz / ".gitignore").write_text("firmware/VERSAO\n")
    (raiz / "firmware" / "ler_adc.c").write_text("int main(void) { return 0; }\n")
    (raiz / "firmware" / "agente" / "shan_agente.py").write_text("# o agente\n")
    _git(raiz, "add", "-A")
    _git(raiz, "commit", "-qm", "o firmware")
    return raiz


def test_a_versao_do_firmware_muda_so_com_o_firmware(repositorio):
    enviada = _git(repositorio, "describe", "--always").strip()        # o que o enviar gravou na placa
    (repositorio / "firmware" / "VERSAO").write_text(enviada + "\n")
    (repositorio / "README.md").write_text("a interface mudou\n")
    (repositorio / "firmware" / "agente" / "shan_agente.py").write_text("# o agente, de outro jeito\n")
    _git(repositorio, "add", "-A")
    _git(repositorio, "commit", "-qm", "a interface e o agente")
    assert firmware_do_aplicativo(enviada, repositorio) == enviada      # o mesmo código: a mesma versão

    (repositorio / "firmware" / "ler_adc.c").write_text("int main(void) { return 1; }\n")
    assert firmware_do_aplicativo(enviada, repositorio).endswith("-dirty")
    _git(repositorio, "commit", "-qam", "o firmware mudou")
    agora = _git(repositorio, "describe", "--always").strip()
    assert firmware_do_aplicativo(enviada, repositorio) == agora != enviada
    assert firmware_do_aplicativo("v9.9-1-gdeadbee", repositorio) == agora   # um commit que este repositório não tem
    assert firmware_do_aplicativo(f"{enviada}-dirty", repositorio) == agora  # o da placa tinha mudanças
    assert firmware_do_aplicativo(None, repositorio) == agora


def test_fora_de_um_repositorio(tmp_path):
    assert firmware_do_aplicativo("v0.8-137-g9b0ae82", tmp_path) is None
