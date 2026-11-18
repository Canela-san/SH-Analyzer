"""As rotinas do ``coletar.sh`` (a F4.6, ``sh_placa/rotinas.py``): a tabela contra a ajuda do script (todo modo, toda
opção, o ``--simular`` e o ``--continuar``), o pedido da Capturar que preenche só a bancada, o comando com as aspas
do shell, e os comandos montados aceitos pelo ``coletar.sh`` do repositório (com ``--simular``, sem placa)."""

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from sh_placa import rotinas
from sh_placa.pedido import Canal, ErroDeUso, PedidoDeCaptura

RAIZ = Path(__file__).resolve().parents[1]
COLETAR = RAIZ / "firmware" / "coletar.sh"


def _ajuda(*args: str) -> str:
    r = subprocess.run(["bash", str(COLETAR), *args, "--help"], capture_output=True, text=True, timeout=30,
                       env={**os.environ, "LC_ALL": "C.UTF-8", "NO_COLOR": "1"})
    assert r.returncode == 0, r.stderr
    return r.stdout + r.stderr


def _tem(ajuda: str, flag: str) -> bool:
    return re.search(rf"(?<![\w-]){re.escape(flag)}(?![\w-])", ajuda) is not None


def test_a_tabela_tem_todo_modo_da_ajuda_na_mesma_ordem():
    bloco = _ajuda().split("Modos", 1)[1].split("Exemplos", 1)[0]
    modos = re.findall(r"^  ([a-z]+) ", bloco, re.MULTILINE)
    assert modos == [r.modo for r in rotinas.ROTINAS]


@pytest.mark.parametrize("r", rotinas.ROTINAS, ids=lambda r: r.modo)
def test_cada_opcao_da_tabela_esta_na_ajuda_do_modo(r):
    ajuda = _ajuda(r.modo)
    assert [o.flag for o in r.opcoes if not _tem(ajuda, o.flag)] == []
    assert _tem(ajuda, "--simular") == r.simulavel
    assert _tem(ajuda, "--continuar") == r.retomavel
    for o in r.opcoes:
        assert o.tipo in rotinas.TIPOS and (o.do_pedido in rotinas.DO_PEDIDO or not o.do_pedido)
        assert all(_tem(ajuda, e) or re.search(re.escape(e), ajuda) for e in o.escolhas), o.flag


def test_o_pedido_preenche_so_a_bancada():
    pedido = PedidoDeCaptura((Canal(1, "corrente", sonda="sct013_100a_sn001", faixa_v=5.12), Canal(3)),
                             taxa_hz=312_500, spi="rapido:a")
    assert rotinas.valores_do_pedido(rotinas.rotina("calibrar"), pedido) == {
        "--grandeza": "corrente", "--canal": "1", "--sonda": "sct013_100a_sn001"}
    assert rotinas.valores_do_pedido(rotinas.rotina("conferir"), pedido) == {
        "--canais": "1,3", "--faixa": "5.12", "--taxa": "312500", "--spi": "rapido"}
    assert rotinas.valores_do_pedido(rotinas.rotina("aliasing"), pedido) == {
        "--canais": "1,3", "--grandeza": "1:corrente,3:tensao", "--sonda": "1:sct013_100a_sn001", "--spi": "rapido"}
    assert rotinas.valores_do_pedido(rotinas.rotina("sonda"), pedido) == {
        "--taxa": "312500", "--canal-sonda": "1", "--grandeza": "corrente", "--sonda": "sct013_100a_sn001"}
    # A temperatura não é uma grandeza da calibração: fica o padrão do script.
    termopar = PedidoDeCaptura((Canal(2, "temperatura"),))
    assert "--grandeza" not in rotinas.valores_do_pedido(rotinas.rotina("calibrar"), termopar)


def test_o_comando_tem_as_aspas_do_shell_as_marcas_e_as_outras_opcoes():
    calibrar = rotinas.rotina("calibrar")
    valores = {"--sonda": "minha sonda", "--referencia": "sim", "--canal": "  ", "--faixas": "5.12"}
    assert rotinas.comando(calibrar, valores, outras="--espiras 3 --resistencia '0.1'") == (
        "cd ~/firmware && ./coletar.sh calibrar --sonda 'minha sonda' --referencia --faixas 5.12 "
        "--espiras 3 --resistencia 0.1")
    assert rotinas.comando(calibrar, {}, simular=True, continuar=True).endswith("calibrar --continuar --simular")
    assert rotinas.comando(calibrar, {}, pasta_firmware="f46") == "cd ~/f46 && ./coletar.sh calibrar"
    assert rotinas.ajuda(calibrar) == "cd ~/firmware && ./coletar.sh calibrar --help"


@pytest.mark.parametrize(("modo", "valores", "opcoes", "trecho"), [
    ("conferir", {"--faixa": "2.56"}, {}, "não é uma das opções"),
    ("calibrar", {}, {"outras": "--sonda 'sem fim"}, "aspas"),
    ("sonda", {}, {"simular": True}, "não tem o --simular"),
    ("teto", {}, {"continuar": True}, "não retoma"),
])
def test_o_que_nao_serve_e_recusado(modo, valores, opcoes, trecho):
    with pytest.raises(ErroDeUso, match=trecho):
        rotinas.comando(rotinas.rotina(modo), valores, **opcoes)
    with pytest.raises(ErroDeUso, match="não tem o modo"):
        rotinas.rotina("xyz")


@pytest.fixture
def placa_sem_pru(tmp_path):
    """Um ``$HOME`` com a pasta do firmware como o setup.sh deixa (o coletar.sh e a coleta/), sem a PRU."""
    firmware = tmp_path / "firmware"
    firmware.mkdir()
    shutil.copy2(COLETAR, firmware / "coletar.sh")
    shutil.copytree(RAIZ / "firmware" / "coleta", firmware / "coleta")
    return tmp_path


@pytest.mark.parametrize("r", [r for r in rotinas.ROTINAS if r.simulavel], ids=lambda r: r.modo)
def test_os_comandos_montados_sao_aceitos_pelo_coletar_sh(r, placa_sem_pru):
    """O comando da tela, com o pedido de uma bancada de dois canais e um valor em cada opção de texto que o pedido
    não preenche, roda com ``--simular`` (o plano, sem capturar) no script de verdade."""
    pedido = PedidoDeCaptura((Canal(1, "tensao", sonda="cadeia_tensao_fase", faixa_v=20.48), Canal(0, "corrente")))
    valores = rotinas.valores_do_pedido(r, pedido)
    exemplos = {"--segundos": "5", "--faixas": "20.48", "--taxas": "400000", "--blocos": "2",
                "--blocos-confirmacao": "3", "--spi": "rapido"}
    for o in r.opcoes:
        if o.tipo == "texto" and o.flag in exemplos and o.flag not in valores:
            valores[o.flag] = exemplos[o.flag]
    if r.modo == "bancada":
        valores["--grade"] = "sim"
    linha = rotinas.comando(r, valores, simular=True)
    s = subprocess.run(["bash", "-c", linha], capture_output=True, text=True, timeout=60,
                       env={**os.environ, "HOME": str(placa_sem_pru), "LC_ALL": "C.UTF-8", "NO_COLOR": "1"})
    assert s.returncode == 0, f"{linha}\n{s.stdout}\n{s.stderr}"
