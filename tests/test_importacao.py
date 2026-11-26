"""Os dados de fora (``supraharmonicos.importacao``, PD-03, PD-10, FG-10): o WAV, o CSV genérico com o assistente,
o osciloscópio e o COMTRADE viram um ``.h5`` que abre como captura, com a taxa, a grandeza e os valores (até a
quantização de 16 bits); o COMTRADE escrito volta igual. Sem Qt."""

import numpy as np
import pytest
from supraharmonicos import api
from supraharmonicos import importacao as imp

pytest.importorskip("h5py")

TAXA = 50_000.0


def _rede(n=5000):
    t = np.arange(n) / TAXA
    return t, 180 * np.sin(2 * np.pi * 60 * t) + 3 * np.sin(2 * np.pi * 9000 * t), 7 * np.sin(2 * np.pi * 60 * t - 0.4)


def _abrir(importado, tmp_path):
    destino = imp.gravar_como_captura(importado, tmp_path / "importada.h5")
    return api.abrir_captura(destino, sondas_dir=tmp_path)


def test_o_csv_generico_com_o_assistente(tmp_path):
    t, v, i = _rede()
    linhas = ["Registro do analisador", "tempo (s);tensão (V);corrente (A)"]
    linhas += [f"{a:.9f};{b:.6f};{c:.6f}".replace(".", ",") for a, b, c in zip(t, v, i)]
    caminho = tmp_path / "rede.csv"
    caminho.write_text("\n".join(linhas), encoding="utf-8")
    previa = imp.previa_do_csv(caminho)
    assert (previa.separador, previa.decimal, previa.pular, previa.coluna_de_tempo) == (";", ",", 2, 0)
    assert previa.colunas == ("tempo (s)", "tensão (V)", "corrente (A)")
    lido = imp.ler_csv(caminho, [1, 2], coluna_de_tempo=0)
    assert lido.taxa_hz == pytest.approx(TAXA) and [c.unidade for c in lido.canais] == ["V", "A"]
    captura = _abrir(lido, tmp_path)
    assert captura.canais[0].taxa_hz == pytest.approx(TAXA) and captura.parametros.taxa_total_hz == pytest.approx(2 * TAXA)
    tensao, corrente = (api.sinal_do_canal(captura, c.numero) for c in captura.canais)
    assert np.max(np.abs(tensao - v)) < 1e-4 * 180 and np.max(np.abs(corrente - i)) < 1e-4 * 7
    assert [c.nome_grandeza for c in captura.canais] == ["tensão", "corrente"]
    assert all(c.faixa_confiavel for c in captura.canais)                  # a calibração exata, sem "suposta"
    secoes = dict(api.descrever_cabecalho(captura))
    assert dict(secoes["Captura"])["Importado de"].startswith("CSV: rede.csv")
    with pytest.raises(api.ErroSHAN, match="taxa"):
        imp.ler_csv(caminho, [1])                                          # sem o tempo nem a taxa


def test_o_wav_de_16_bits_passa_sem_perda(tmp_path):
    from scipy.io import wavfile

    rng = np.random.default_rng(3)
    pcm = rng.integers(-30000, 30000, size=(4000, 2)).astype(np.int16)
    wavfile.write(tmp_path / "s.wav", 48_000, pcm)
    lido = imp.ler(tmp_path / "s.wav")
    assert lido.taxa_hz == 48_000 and len(lido.canais) == 2 and lido.avisos
    captura = _abrir(lido.com(escalas=[2.0, 1.0]), tmp_path)
    primeiro = api.sinal_do_canal(captura, captura.canais[0].numero)
    assert np.max(np.abs(primeiro - 2.0 * pcm[:, 0] / 32768)) < 2.0 * 1.3 / 32768        # meio código, no máximo


def test_o_osciloscopio_com_dois_canais(tmp_path):
    t, v, i = _rede(2000)
    np.savetxt(tmp_path / "osc.csv", np.column_stack([t, v, i]), delimiter=",", header="t,ch1,ch2", comments="")
    lido = imp.ler(tmp_path / "osc.csv")
    assert lido.taxa_hz == pytest.approx(TAXA, rel=1e-6) and len(lido.canais) == 2
    assert np.allclose(lido.canais[1].valores, i)


def test_o_comtrade_vai_e_volta(tmp_path):
    _, v, i = _rede(3000)
    cfg, dat = imp.gravar_comtrade(tmp_path / "reg.cfg", ["Va", "Ia"], ["kV", "A"], [v / 1000, i], TAXA)
    assert cfg.is_file() and dat.stat().st_size == 3000 * (8 + 2 * 2)
    lido = imp.ler(cfg)
    assert lido.taxa_hz == TAXA and [c.unidade for c in lido.canais] == ["V", "A"]
    assert np.max(np.abs(lido.canais[0].valores - v)) < 180 / 32767 * 1.01          # kV para V, um código
    assert np.max(np.abs(lido.canais[1].valores - i)) < 7 / 32767 * 1.01


def test_o_que_nao_se_importa(tmp_path):
    (tmp_path / "x.xyz").write_text("1")
    with pytest.raises(api.ErroSHAN, match="formato"):
        imp.ler(tmp_path / "x.xyz")
    with pytest.raises(api.ErroSHAN, match="tamanhos"):
        imp.Importado((imp.CanalImportado("a", np.zeros(3)), imp.CanalImportado("b", np.zeros(4))), 1.0, "teste")
