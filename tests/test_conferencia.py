"""A conferência de uma captura curta (``supraharmonicos/conferencia.py``, o "Conferir antes" da F4.3): as regras do
``firmware/coleta/conferir.sh``, conferidas contra o próprio ``comum.sh`` (o ``medir_sinal`` e o
``faixa_para_o_pico``, com o bash e o awk de verdade) e numa captura com o cabeçalho v9."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest
from capturas_sinteticas import escrever_bin
from sh_placa import capturas_simuladas as cs
from supraharmonicos import conferencia as cf

RAIZ = Path(__file__).resolve().parents[1]
COMUM = RAIZ / "firmware" / "coleta" / "comum.sh"

pytestmark = pytest.mark.skipif(shutil.which("bash") is None or shutil.which("od") is None, reason="sem bash/od")


def _comum(comando: str) -> str:
    r = subprocess.run(["bash", "-c", f'source "{COMUM}"; {comando}'], capture_output=True, text=True,
                       env={**os.environ, "LC_ALL": "C", "NO_COLOR": "1"}, timeout=120)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


@pytest.mark.parametrize("pico", [0.0, 1.0, 2.176, 2.1761, 4.352, 4.3521, 8.0, -3.0, 9.9])
def test_a_faixa_para_o_pico_e_a_do_comum_sh(pico):
    assert cf.faixa_para_o_pico(pico) == float(_comum(f"faixa_para_o_pico {pico}"))


def _sinais(n: int, fs: float) -> dict[str, np.ndarray]:
    t = np.arange(n) / fs
    rng = np.random.default_rng(3)
    return {
        "rede": 1.2 * np.sin(2 * np.pi * 60 * t + 0.3) + 0.004 + rng.normal(0, 0.002, n),
        "quadrada": np.where(np.sin(2 * np.pi * 1000 * t) >= 0, 0.8, -0.8) + rng.normal(0, 0.001, n),
        "ruido": rng.normal(0, 0.0004, n),
        "parado": np.full(n, 0.25),
        "satura": 3.0 * np.sin(2 * np.pi * 50 * t),
    }


@pytest.mark.parametrize("nome", ["rede", "quadrada", "ruido", "parado", "satura"])
@pytest.mark.parametrize("faixa", [20.48, 5.12])
def test_o_nivel_de_cada_canal_e_o_do_medir_sinal(tmp_path, nome, faixa):
    """Os dois canais intercalados, cada um contra o ``medir_sinal`` dele (os mesmos N primeiros pontos)."""
    fs_total, n_total = 200_000, 262_144
    sinais = _sinais(n_total // 2, fs_total / 2)
    outro = "rede" if nome != "rede" else "quadrada"
    arquivo = escrever_bin(tmp_path / "c.bin", [sinais[outro], sinais[nome]], canais=(0, 3), grandezas=(0, 0),
                           sondas=("", ""), fs_total=fs_total, faixas_adc_total_v=[faixa, faixa])
    conferencia = cf.conferir_captura(arquivo)
    nivel = conferencia.canal(3)
    campos = _comum(f'medir_sinal "{arquivo}" 2 1 {faixa} {fs_total} {n_total}').split()
    minimo, maximo, media, rms, vpp = (float(x) for x in campos[:5])
    saturadas, constante = int(campos[5]), campos[6] == "1"
    assert nivel.minimo_v == pytest.approx(minimo, abs=2e-6)
    assert nivel.maximo_v == pytest.approx(maximo, abs=2e-6)
    assert nivel.media_v == pytest.approx(media, abs=2e-6)
    assert nivel.rms_v == pytest.approx(rms, abs=2e-6, rel=1e-5)
    assert nivel.vpp_v == pytest.approx(vpp, abs=2e-6)
    assert nivel.saturadas == saturadas and nivel.parado == constante
    if campos[7] == "nan":
        assert nivel.frequencia_hz is None
    else:
        assert nivel.frequencia_hz == pytest.approx(float(campos[7]), abs=1e-3)


def test_a_frequencia_de_uma_senoide_e_de_uma_quadrada():
    fs = 200_000.0
    sinais = _sinais(524_288, fs)
    assert cf.frequencia_pelas_subidas(cf_codigos(sinais["rede"]), fs) == pytest.approx(60, rel=1e-4)
    assert cf.frequencia_pelas_subidas(cf_codigos(sinais["quadrada"]), fs) == pytest.approx(1000, rel=1e-4)
    assert cf.frequencia_pelas_subidas(cf_codigos(sinais["parado"]), fs) is None
    assert cf.frequencia_pelas_subidas(cf_codigos(sinais["rede"][:2000]), fs) is None      # menos de 4 subidas


def cf_codigos(volts: np.ndarray, faixa: float = 20.48) -> np.ndarray:
    return cs.em_codigos(volts, faixa)


def test_o_nivel_diz_a_faixa_sugerida_o_ruido_e_o_problema():
    fs = 200_000.0
    sinais = _sinais(200_000, fs)
    rede = cf.medir_canal(cf_codigos(sinais["rede"]), 1, 20.48, fs)
    assert rede.faixa_sugerida_v == 5.12 and not rede.problema and not rede.so_ruido      # 1,2 V de pico
    assert rede.uso_da_faixa == pytest.approx(1.21 / 10.24, rel=0.02)
    assert rede.rms_lsb == pytest.approx(rede.rms_v / (20.48 / 65536))
    justa = cf.medir_canal(cf_codigos(sinais["rede"], 5.12), 1, 5.12, fs)
    assert justa.faixa_sugerida_v is None                                                   # já é a menor
    assert not rede.sem_folga and not justa.sem_folga
    # Saturado, o pico cortado não diz qual faixa cabe: a sugerida é a maior (a da faixa_automatica do comum.sh);
    # saturado já na maior, nenhuma.
    satura = cf.medir_canal(cf_codigos(sinais["satura"], 5.12), 1, 5.12, fs)
    assert satura.satura and satura.problema and satura.faixa_sugerida_v == 20.48 and not satura.sem_folga
    na_maior = cf.medir_canal(cf_codigos(sinais["satura"] * 4, 20.48), 1, 20.48, fs)
    assert na_maior.satura and na_maior.faixa_sugerida_v is None
    # A tomada no divisor (9,3 V de pico, como na placa em 18/11/2026): cabe na maior, sem os 15 % de folga.
    tomada = cf.medir_canal(cf_codigos(sinais["rede"] * 9.33 / 1.21, 20.48), 1, 20.48, fs)
    assert tomada.sem_folga and not tomada.satura and tomada.faixa_sugerida_v is None
    assert tomada.uso_da_faixa == pytest.approx(0.91, abs=0.01)
    meia = cf.medir_canal(cf_codigos(sinais["rede"] * 4.6 / 1.21, 10.24), 1, 10.24, fs)
    assert meia.sem_folga and meia.faixa_sugerida_v == 20.48                 # a maior faixa dá a folga
    parado = cf.medir_canal(cf_codigos(sinais["parado"]), 1, 20.48, fs)
    assert parado.parado and parado.problema and not parado.so_ruido
    ruido = cf.medir_canal(cf_codigos(sinais["ruido"]), 1, 20.48, fs)
    assert ruido.so_ruido and not ruido.problema


def _captura(caminho: Path, canais, faixas, *, integridade=(0, 0, 0), muda=False) -> Path:
    por_bloco = 65_536
    configuracao = cs.Configuracao(tuple(canais), 400_000, por_bloco, 0.0, "conferência", "", "400000",
                                   faixas=tuple(faixas))
    codigos = np.zeros(por_bloco, dtype="<u2") if muda else \
        cs.codigos_do_bloco(tuple(canais), 400_000.0, por_bloco, 0, faixas=tuple(faixas))
    medida = cs.Medida(len(canais))
    medida.somar(codigos)
    fim = medida.fim(1.0e9 + 0.2, 0.16, pior_bloco_ms=120, taxa_medida_hz=0.0, blocos=1, integridade=integridade)
    sistema = cs.Sistema("6.1.83-ti", "Debian 12", "A335BNLT 00C0 3714BBBK1234", versao_firmware="v0.9.0",
                         disco_total_kib=7_000_000, disco_livre_kib=150_000)
    cabecalho = cs.montar_cabecalho(configuracao, inicio=1.0e9, sistema=sistema, identidade="c", fim=fim)
    caminho.write_bytes(cabecalho + codigos.tobytes())
    return caminho


def test_a_conferencia_de_uma_captura_da_placa_simulada(tmp_path):
    """O canal 0 (a corrente da bancada simulada, ~0,7 V no pino) cabe em ±2,56 V; o 1 (a tomada, ~9 V de pico no
    pino) satura em ±5,12 V: um problema, e sem sugestão (a saturação esconde o pico)."""
    c = cf.conferir_captura(_captura(tmp_path / "c.bin", (0, 1), (20.48, 10.24)))
    assert c.integra and c.integridade == (0, 0, 0)
    corrente, tensao = c.canais
    assert (corrente.canal, corrente.faixa_v, tensao.faixa_v) == (0, 20.48, 10.24)
    assert corrente.faixa_sugerida_v == 5.12 and not corrente.problema
    assert corrente.frequencia_hz == pytest.approx(60, rel=0.01)
    assert tensao.satura and tensao.problema
    assert c.problemas == 1 and not c.pronta
    assert c.disco_quase_cheio                                          # 150 MB livres no cartão
    assert c.cabecalho.placa.startswith("A335BNLT") and c.cabecalho.versao_firmware == "v0.9.0"
    assert c.divergencias == (0, 0) and not c.pru_sem_acomodacao


def test_a_integridade_e_o_adc_mudo(tmp_path):
    c = cf.conferir_captura(_captura(tmp_path / "a.bin", (1,), (20.48,), integridade=(3, 0, 0)))
    assert not c.integra and c.problemas == 1
    mudo = cf.conferir_captura(_captura(tmp_path / "m.bin", (0, 1), (20.48, 20.48), muda=True))
    assert all(n.parado for n in mudo.canais) and mudo.problemas == 2


def test_um_arquivo_sem_o_cabecalho_ou_sem_amostras(tmp_path):
    (tmp_path / "x.bin").write_bytes(b"\x00" * 100)
    with pytest.raises(cf.ErroSHAN):
        cf.conferir_captura(tmp_path / "x.bin")
    captura = _captura(tmp_path / "c.bin", (1,), (20.48,))
    vazia = tmp_path / "v.bin"
    vazia.write_bytes(captura.read_bytes()[:4096])
    with pytest.raises(cf.ErroSHAN, match="não tem amostras"):
        cf.conferir_captura(vazia)
