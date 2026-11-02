"""A fase (e a magnitude) da cadeia por ondas quadradas, sem osciloscópio: ``fase_quadrada`` e ``medir_fase.py`` (S2).

As capturas são sintéticas (``quadrada_pela_cadeia``): a quadrada passa pelo 2ª ordem do T3 e por um atraso puro, o
gerador anda 43 ppm à frente da PRU, os harmônicos acima da Nyquist dobram, e há ruído e quantização. Curtas (0,3 s)
para o teste ser rápido; na bancada são 10 s, com ~6 vezes menos ruído.
"""

import csv
import dataclasses
import json

import numpy as np
import pytest
from capturas_sinteticas import escrever_m_osciloscopio, montar_cabecalho, quadrada_pela_cadeia
from supraharmonicos import fase_quadrada as fq
from supraharmonicos.cli_medir_fase import _piso_das_variantes, main
from supraharmonicos.sonda import carregar_perfil_sonda

FS = 312_500.0
F0, Q = fq.F0_PADRAO_HZ, fq.Q_PADRAO


def medir(f1=1280.0, fs=FS, dur=0.3, **kw):
    return fq.medir_quadrada(quadrada_pela_cadeia(fs, f1, dur, **kw).astype(float), fs)


def erros(r: fq.RespostaQuadrada, f0=F0, q=Q):
    """(erro de fase em graus, erro de magnitude em dB), nos harmônicos usados."""
    u = r.usado
    fase = np.degrees(r.fase_rel_rad - fq.fase_relativa_modelo(r.freq_hz, r.f1_hz, f0, q))[u]
    rel = np.abs(fq.h_segunda_ordem(r.freq_hz, f0, q)) / abs(fq.h_segunda_ordem(r.f1_hz, f0, q))
    return fase, 20 * np.log10(r.ganho_rel / rel)[u]


def test_fase_e_magnitude_da_cadeia_sem_referencia_externa():
    r = medir()
    fase, mag = erros(r)
    assert r.usado.sum() >= 55 and r.freq_hz[r.usado][-1] > 140e3
    assert np.max(np.abs(fase)) < 0.3 and np.max(np.abs(mag)) < 0.05
    # a 140 kHz a fase relativa passa de 400°: só a referência interna da quadrada a mede sem ambiguidade
    assert np.degrees(r.fase_rel_rad[r.usado][-1]) > 400


def test_um_atraso_puro_nao_muda_a_medida():
    """A conversão do ADC e o instante da amostra são atrasos puros: somem de arg Xₙ − n·arg X₁."""
    a = medir(atraso_s=0.0, seed=5)
    b = medir(atraso_s=20e-6, seed=5)
    diferenca = np.abs(np.degrees(a.fase_rel_rad - b.fase_rel_rad))[a.usado & b.usado]
    # 20 µs que não sumissem seriam 2π·140 kHz·20 µs ≈ 1000° no último harmônico; sobra só o ruído das capturas curtas
    assert np.max(diferenca) < 1.0 and np.mean(diferenca) < 0.1


def test_quadrada_invertida_da_a_mesma_fase():
    x = quadrada_pela_cadeia(FS, 1280.0, 0.3, seed=3)
    a = fq.medir_quadrada(x.astype(float), FS)
    b = fq.medir_quadrada((65535 - x).astype(float), FS)
    assert np.max(np.abs(np.degrees(a.fase_rel_rad - b.fase_rel_rad))) < 0.01


def test_o_duty_e_estimado_e_corrigido_na_magnitude_e_nao_muda_a_fase():
    r = medir(duty=0.503, seed=7)
    assert r.duty_desvio == pytest.approx(0.003, abs=2e-4)
    fase, mag = erros(r)
    assert np.max(np.abs(fase)) < 0.5 and np.max(np.abs(mag)) < 0.15
    sem_correcao = r.ganho_rel * np.abs(np.cos(np.pi * r.n * r.duty_desvio))     # o que daria ignorar o duty
    rel = np.abs(fq.h_segunda_ordem(r.freq_hz, F0, Q)) / abs(fq.h_segunda_ordem(r.f1_hz, F0, Q))
    assert np.max(np.abs(20 * np.log10(sem_correcao / rel))) > 1.0


def test_harmonico_perto_de_um_nulo_do_duty_fica_de_fora():
    r = medir(f1=256.0, duty=0.501, dur=0.5, seed=2)
    perto = np.abs(np.cos(np.pi * r.n * r.duty_desvio)) < fq.FATOR_DUTY_MINIMO
    assert np.any(perto) and not np.any(r.usado[perto])
    assert any("nulo do duty" in m for m in r.motivo)


def test_aliasing_sobre_um_harmonico_e_previsto_e_descartado():
    """Taxa/f₁ par (312,5 kS/s com 1250 Hz) e os dois relógios iguais: os harmônicos perto da taxa dobram em cima dos
    ímpares medidos. Com 1280 Hz (taxa/f₁ = 244,14), nenhum."""
    ruim = medir(f1=1250.0, ppm=0.0, seed=4)
    assert any(m.startswith("aliasing") for m in ruim.motivo)
    fase, _ = erros(ruim)
    assert np.max(np.abs(fase)) < 0.5                    # o que sobrou está limpo
    bom = medir(f1=1280.0, ppm=0.0, seed=4)
    assert not any(m.startswith("aliasing") for m in bom.motivo)


def test_ajuste_recupera_f0_e_q_pela_fase_sozinha_e_pela_magnitude():
    medidas = [medir(f1=1280.0, seed=1), medir(f1=6400.0, seed=2)]
    for usar_mag, usar_fase in ((True, True), (True, False), (False, True)):
        aj = fq.ajustar_segunda_ordem(medidas, usar_mag, usar_fase, f0_inicial=20000, q_inicial=0.7)
        assert aj.f0_hz == pytest.approx(F0, rel=1e-3) and aj.q == pytest.approx(Q, rel=1e-3), aj


def test_o_erro_da_fase_da_fundamental_nao_entra_no_ajuste():
    """Um erro δ em arg X₁ (o INL do ADC; ~0,01° no T3f) entra em arg Xₙ − n·arg X₁ como −n·δ: 6° no harmônico 100.
    O ajuste e a costura o tiram por captura e ficam com a curvatura; f0, Q, o χ² e a fase costurada não mudam."""
    limpas = [medir(f1=1280.0, seed=1), medir(f1=6400.0, seed=2)]
    tortas = [dataclasses.replace(r, fase_rel_rad=r.fase_rel_rad - r.n * np.radians(d) * (r.n > 1))
              for r, d in zip(limpas, (0.06, -0.03))]
    a, b = fq.ajustar_segunda_ordem(limpas, False, True), fq.ajustar_segunda_ordem(tortas, False, True)
    assert b.f0_hz == pytest.approx(a.f0_hz, rel=1e-6) and b.q == pytest.approx(a.q, rel=1e-6)
    assert b.chi2_reduzido == pytest.approx(a.chi2_reduzido, rel=1e-3) and b.chi2_reduzido < 2
    # nem na fase costurada: na captura-base, que ancora as outras, ele viraria um atraso puro a mais
    for limpa, torta in zip(fq.costurar(limpas, F0, Q), fq.costurar(tortas, F0, Q)):
        assert np.max(np.abs(torta.fase_rad - limpa.fase_rad)) < 1e-6



def test_o_piso_das_variantes_nao_conta_o_erro_da_fundamental():
    """O erro de |X₁| e de arg X₁ de cada variante a costura já tira; o piso por harmônico não pode contá-lo (no T3f,
    contado, ele dobrava o piso)."""
    a, b = medir(f1=1280.0, seed=1), medir(f1=1280.0, seed=2)
    torta = dataclasses.replace(b, fase_rel_rad=b.fase_rel_rad - b.n * np.radians(0.01) * (b.n > 1),
                                ganho_rel=b.ganho_rel * np.where(b.n > 1, 1.001, 1.0))
    assert _piso_das_variantes([a, torta]) == pytest.approx(_piso_das_variantes([a, b]), rel=0.02)


def test_fase_absoluta_supondo_fase_minima_e_a_do_filtro():
    r = medir(seed=9)
    psi = fq.fase_absoluta(r, F0, Q)
    verdade = np.unwrap(np.angle(fq.h_segunda_ordem(r.freq_hz, F0, Q)))
    assert np.max(np.abs(np.degrees(psi - verdade)[r.usado])) < 0.3


def test_a_costura_nao_depende_do_modelo_e_a_grade_e_coerente():
    """1280 Hz é o 5º harmônico de 256 Hz: a quadrada de 256 Hz mede |H| e ψ na fundamental da de 1280 Hz, e a costura
    usa isso, e não o modelo. Com um modelo errado (f0 5 % abaixo), as duas capturas continuam emendadas: onde as duas
    medem (múltiplos ímpares de 1280 Hz), dão o mesmo ganho e a mesma fase."""
    medidas = [medir(f1=256.0, dur=0.5, seed=11), medir(f1=1280.0, seed=12)]
    for f0 in (F0, 0.95 * F0):
        base, rapida = fq.costurar(medidas, f0, Q)
        assert base.ancora.startswith("modelo") and rapida.ancora.startswith("f₁ = 256")
        comuns = np.intersect1d(np.round(base.freq_hz, 3), np.round(rapida.freq_hz, 3))
        assert len(comuns) >= 15
        ib = np.isin(np.round(base.freq_hz, 3), comuns)
        ir = np.isin(np.round(rapida.freq_hz, 3), comuns)
        baixo = base.freq_hz[ib] < 60e3                      # onde os dois têm sinal de sobra
        assert np.max(np.abs(base.ln_ganho[ib] - rapida.ln_ganho[ir])[baixo]) * 8.686 < 0.05
        assert np.max(np.abs(np.degrees(base.fase_rad[ib] - rapida.fase_rad[ir]))[baixo]) < 0.3
    grade = fq.combinar_em_grade(fq.costurar(medidas, F0, Q), F0, Q)
    assert np.nanmedian(grade.chi2_fase) < 3 and np.nanmedian(grade.chi2_ln) < 3
    verdade = np.unwrap(np.angle(fq.h_segunda_ordem(grade.freq_hz, F0, Q)))
    assert np.max(np.abs(np.degrees(grade.fase_rad - verdade))) < 0.3


def test_quadrada_rapida_demais_e_recusada():
    with pytest.raises(fq.ErroSHAN, match="harmônico"):
        fq.medir_quadrada(quadrada_pela_cadeia(FS, 60_000.0, 0.05).astype(float), FS)


# --------------------------------------------------------------------------------------
# A CLI: medir_fase.py
# --------------------------------------------------------------------------------------
def gravar(pasta, nome, fs, f1, spi=0, **kw):
    x = quadrada_pela_cadeia(float(fs), f1, 0.3, **kw)
    caminho = pasta / nome
    caminho.write_bytes(montar_cabecalho(len(x), (1,), (0,), ("",), int(fs), versao=7,
                                         descricao=f"quadrada f={f1:g}Hz", spi=(spi, 0, 0)) + x.tobytes())
    return caminho


@pytest.fixture
def capturas(tmp_path):
    return [gravar(tmp_path, "F_312500_q1280.bin", 312_500, 1280.0, seed=1),
            gravar(tmp_path, "F_400000_q1280.bin", 400_000, 1280.0, spi=2, seed=2)]


def test_medir_fase_ajusta_grava_csv_grafico_e_perfil_com_fase(cli, capturas, tmp_path):
    saida = tmp_path / "cadeia_fase.json"
    rc, out, err = cli(main, *capturas, "--csv", tmp_path / "fase.csv", "--plot", tmp_path / "bode.png",
                       "--perfil-base", "scripts/sondas/cadeia_tensao_312k.json", "--saida-perfil", saida)
    assert rc == 0, err
    assert "400 kS/s (SPI rápido)" in out and "FASE MÍNIMA" in out
    assert "312.5 kS/s × 400 kS/s: diferença rms" in out and "Grade combinada" in out
    grade = list(csv.DictReader(open(tmp_path / "fase_grade.csv", encoding="utf-8")))
    assert len(grade) > 20 and float(grade[-1]["freq_hz"]) > 170e3      # faixas sem harmônico ficam de fora
    linhas = list(csv.DictReader(open(tmp_path / "fase.csv", encoding="utf-8")))
    assert {linha["arquivo"] for linha in linhas} == {c.name for c in capturas}
    assert all(linha["usado"] in ("sim", "não") for linha in linhas)
    assert (tmp_path / "bode.png").read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    perfil = json.loads(saida.read_text(encoding="utf-8"))
    assert perfil["id"] == "cadeia_fase" and perfil["resposta_fase"]["segunda_ordem"]["f0_hz"] == pytest.approx(F0, rel=2e-3)
    assert perfil["calibracao_adc"]["faixa_v"] == {"sonda": 20.48}        # a das capturas, não a do perfil base
    assert perfil["resposta_fase"]["k_baixa_frequencia"] == pytest.approx(0.998, abs=1e-3)
    medidos = [p for p in perfil["pontos"] if "sigma_fase_rad" in p]
    assert len(medidos) > 20 and all("fase_rad" in p for p in perfil["pontos"])     # a grade: 20 faixas por década
    assert perfil["faixa_freq_valida_hz"][0] < 100 and perfil["faixa_freq_valida_hz"][1] > 170e3   # base + quadradas
    carregado = carregar_perfil_sonda(saida)               # a correção de magnitude de sempre continua valendo
    alto = carregado.ganho_em(np.array([100e3]))[0]
    assert alto == pytest.approx(0.998 * abs(fq.h_segunda_ordem(100e3, F0, Q)), rel=0.01)


def test_polo_real_a_mais_e_achado_pelo_bic_e_sem_ele_ha_aviso(cli, tmp_path):
    """Com um polo real a 60 kHz a mais, o 2ª ordem sozinho não explica a cadeia: a magnitude e a fase pedem filtros
    diferentes, e o aviso diz para usar a fase medida (--polo nao). No automático, o BIC põe o polo, que sai no lugar,
    e a magnitude e a fase voltam a concordar."""
    arquivos = [gravar(tmp_path, f"F_{f1}.bin", 312_500, f1, polo_hz=60e3, seed=s)
                for f1, s in ((1280.0, 1), (6400.0, 2))]
    rc, out, err = cli(main, *arquivos, "--polo", "nao")
    assert rc == 0 and "NÃO dão o mesmo filtro" in err
    rc, out, err = cli(main, *arquivos, "--saida-perfil", tmp_path / "p.json",
                       "--perfil-base", "scripts/sondas/cadeia_tensao_312k.json")
    assert rc == 0 and "→ COM o polo" in out and "NÃO dão" not in err
    so = json.loads((tmp_path / "p.json").read_text(encoding="utf-8"))["resposta_fase"]["segunda_ordem"]
    assert so["f0_hz"] == pytest.approx(F0, rel=2e-3) and so["q"] == pytest.approx(Q, rel=3e-3)
    assert so["polo_real_hz"] == pytest.approx(60e3, rel=0.03)


def test_ajuste_com_polo_o_recupera_e_sem_polo_na_cadeia_nao_o_inventa():
    com = [medir(f1=f1, polo_hz=150e3, seed=s) for f1, s in ((1280.0, 1), (6400.0, 2))]
    aj = fq.ajustar_segunda_ordem(com, com_polo=True)
    assert aj.polo_hz == pytest.approx(150e3, rel=0.05) and aj.f0_hz == pytest.approx(F0, rel=1e-3), aj
    assert fq.ajustar_segunda_ordem(com).bic - aj.bic > 100
    sem = [medir(f1=f1, seed=s) for f1, s in ((1280.0, 1), (6400.0, 2))]
    aj = fq.ajustar_segunda_ordem(sem, com_polo=True)
    assert aj.polo_hz > 2e6 and fq.ajustar_segunda_ordem(sem).bic - aj.bic < 10      # não se paga


def test_medir_fase_recusa_misturar_faixas_do_adc(cli, capturas, tmp_path):
    x = quadrada_pela_cadeia(312_500.0, 1280.0, 0.3, seed=5)
    outra = tmp_path / "F_faixa_5.bin"
    outra.write_bytes(montar_cabecalho(len(x), (1,), (0,), ("",), 312_500, versao=7, descricao="quadrada f=1280Hz",
                                       codigos_faixa_adc=(2,), spi=(0, 0, 0)) + x.tobytes())     # ±2,56 V
    rc, _, err = cli(main, capturas[0], outra)
    assert rc == 2 and "faixas diferentes" in err


def test_medir_fase_saida_de_perfil_pede_o_perfil_base(cli, capturas, tmp_path):
    rc, _, err = cli(main, capturas[0], "--saida-perfil", tmp_path / "p.json")
    assert rc == 2 and "--perfil-base" in err


# --------------------------------------------------------------------------------------
# A entrada medida (o osciloscópio na entrada da sonda): a forma real da entrada sai da medida
# --------------------------------------------------------------------------------------
FS_OSC = 1e6
BORDA_HZ = 60e3          # a borda do gerador, exagerada (um RC de 2,7 µs) para aparecer em capturas de 0,3 s


def entrada_no_osciloscopio(f1, dur=0.1, borda_hz=BORDA_HZ, duty=0.5, seed=0):
    """O que o osciloscópio vê na entrada: a quadrada com a borda do gerador (um polo), sem o filtro da cadeia, no
    relógio do osciloscópio (o do ADC anda 63 ppm à frente dele), a 1 MS/s, sem aliasing (o Hi Res)."""
    return quadrada_pela_cadeia(FS_OSC, f1, dur, duty=duty, f0=1e12, atraso_s=0.0, ppm=-20.0, amplitude_lsb=20000.0,
                                ruido_lsb=2.0, ate_hz=0.45 * FS_OSC, seed=seed, polo_hz=borda_hz).astype(float)


def medir_entrada(f1, **kw):
    return fq.medir_quadrada(entrada_no_osciloscopio(f1, **kw), FS_OSC, f1, 1e12, Q, fq.FRACAO_DA_NYQUIST * FS / 2,
                             piso_sistematico=0.02, prever_aliasing=False)


def test_a_entrada_medida_tira_a_borda_do_gerador_e_o_duty_da_medida():
    """A borda do gerador (um polo de 60 kHz na entrada) a quadrada ideal põe na cadeia; dividida pela entrada medida
    no osciloscópio, sobra a cadeia (o 2ª ordem), e o duty fora do lugar sai sem a correção pelos pares."""
    for f1, seed in ((1280.0, 1), (6400.0, 2)):
        saida = medir(f1=f1, duty=0.503, polo_hz=BORDA_HZ, seed=seed)
        _, mag = erros(saida)
        assert np.max(np.abs(mag)) > 3.0                         # a borda: dB em 100 kHz
        r = fq.dividir_pela_entrada(saida, medir_entrada(f1, duty=0.503, seed=seed + 10), F0, Q, nome="ref.csv")
        fase, mag = erros(r)
        z_fase = fase / np.degrees(r.sigma_fase_rad[r.usado])
        z_mag = mag / (8.686 * r.sigma_ln_ganho[r.usado])
        assert r.usado.sum() >= 10 and r.entrada == "ref.csv"
        assert np.max(np.abs(z_fase)) < 5 and np.max(np.abs(z_mag)) < 5, (fase, mag)
        baixo = r.freq_hz[r.usado] < BORDA_HZ                     # acima, a borda deixa os harmônicos fracos (ruído)
        assert np.max(np.abs(mag[baixo])) < 0.05 and np.max(np.abs(fase[baixo])) < 0.3


def test_o_desvio_da_entrada_contra_a_quadrada_ideal_mostra_a_borda():
    ideal = fq.desvio_da_quadrada_ideal(medir_entrada(1280.0, borda_hz=1e12, seed=3))
    borda = fq.desvio_da_quadrada_ideal(medir_entrada(1280.0, seed=3))
    assert ideal[0] < 0.01 and ideal[1] < 0.05
    assert borda[0] > 5 and borda[1] > 5 and borda[2] > 140e3     # o polo de 60 kHz: -8 dB e dezenas de graus a 148 kHz


def test_entrada_de_outra_quadrada_e_recusada():
    with pytest.raises(fq.ErroSHAN, match="não são a mesma quadrada"):
        fq.dividir_pela_entrada(medir(f1=1280.0, seed=1), medir_entrada(6400.0, seed=2))


def test_registro_com_poucos_periodos_por_bloco_e_recusado():
    """Um registro curto do osciloscópio (8 períodos, 2 por bloco): a janela não separa os harmônicos vizinhos."""
    with pytest.raises(fq.ErroSHAN, match="2.0 períodos da quadrada"):
        fq.medir_quadrada(entrada_no_osciloscopio(256.0, dur=8 / 256.0), FS_OSC, 256.0, 1e12, Q, 150e3,
                          prever_aliasing=False)


def gravar_entrada(pasta, nome, f1, **kw):
    return escrever_m_osciloscopio(pasta / nome, entrada_no_osciloscopio(f1, **kw), FS_OSC)


def test_medir_fase_com_a_entrada_medida_nao_inventa_o_polo_da_borda(cli, tmp_path):
    """Sem --entrada, a borda do gerador vira um polo real da cadeia (o BIC o põe, em 60 kHz); com ela, o 2ª ordem
    sozinho explica tudo, f0 e Q saem no lugar, e o perfil diz de onde veio a referência."""
    arquivos = [gravar(tmp_path, f"F_cspadrao_312500_quadrada{f1:g}Hz_30s.bin", 312_500, f1, polo_hz=BORDA_HZ, seed=s)
                for f1, s in ((1280.0, 1), (6400.0, 2))]
    refs = [gravar_entrada(tmp_path, f"ref_quadrada{f1:g}Hz.m", f1, seed=s) for f1, s in ((1280.0, 11), (6400.0, 12))]
    rc, out, _ = cli(main, *arquivos, "--saida-perfil", tmp_path / "sem.json",
                     "--perfil-base", "scripts/sondas/cadeia_tensao_312k.json")
    so = json.loads((tmp_path / "sem.json").read_text(encoding="utf-8"))["resposta_fase"]["segunda_ordem"]
    assert rc == 0 and "→ COM o polo" in out and so["polo_real_hz"] == pytest.approx(BORDA_HZ, rel=0.05)
    rc, out, err = cli(main, *arquivos, "--entrada", *refs, "--csv", tmp_path / "fase.csv",
                       "--saida-perfil", tmp_path / "com.json", "--perfil-base", "scripts/sondas/cadeia_tensao_312k.json")
    assert rc == 0, err
    assert "→ sem o polo" in out and "contra a quadrada ideal" in out and "÷ ref_quadrada1280Hz.m" in out
    perfil = json.loads((tmp_path / "com.json").read_text(encoding="utf-8"))
    so = perfil["resposta_fase"]["segunda_ordem"]
    assert so["f0_hz"] == pytest.approx(F0, rel=2e-3) and so["q"] == pytest.approx(Q, rel=3e-3)
    assert "polo_real_hz" not in so and "osciloscópio" in perfil["calibracao_adc"]["modo_referencia"]
    assert {c["entrada"] for c in perfil["resposta_fase"]["capturas"]} == {r.name for r in refs}
    linhas = list(csv.DictReader(open(tmp_path / "fase.csv", encoding="utf-8")))
    assert {(linha["arquivo"], linha["entrada"]) for linha in linhas} == {(a.name, r.name) for a, r in zip(arquivos, refs)}


def test_medir_fase_casa_as_variantes_pelo_nome_e_pede_a_entrada_de_cada_captura(cli, tmp_path):
    a = gravar(tmp_path, "F_cspadrao_312500_quadrada1280Hz_30s.bin", 312_500, 1280.0, seed=1)
    b = gravar(tmp_path, "F_cspadrao_312500_quadrada1280Hz10Vpp_30s.bin", 312_500, 1280.0, seed=2, amplitude_lsb=3300.0)
    c = gravar(tmp_path, "F_cspadrao_312500_quadrada6400Hz_30s.bin", 312_500, 6400.0, seed=3)
    ra = gravar_entrada(tmp_path, "ref_quadrada1280Hz.m", 1280.0, borda_hz=1e12, seed=11)
    rb = gravar_entrada(tmp_path, "ref_quadrada1280Hz10Vpp.m", 1280.0, borda_hz=1e12, seed=12)
    rc, _, err = cli(main, a, b, c, "--entrada", ra, rb)
    assert rc == 1 and "quadrada6400Hz" in err and "não tem a entrada medida" in err
    rc, out, err = cli(main, a, b, "--entrada", ra, rb)
    assert rc == 0, err
    assert f"{a.name} (312.5 kS/s, ÷ {ra.name})" in out and f"{b.name} (312.5 kS/s, ÷ {rb.name})" in out
    sem_nome = gravar_entrada(tmp_path, "outra_1280Hz.m", 1280.0, borda_hz=1e12, seed=13)
    rc, _, err = cli(main, a, "--entrada", rb, sem_nome)
    assert rc == 1 and "nomeie cada uma ref_<entrada>" in err


def test_canal_de_corrente_sem_entrada_avisa(cli, tmp_path):
    x = quadrada_pela_cadeia(312_500.0, 1280.0, 0.3, seed=5)
    corrente = tmp_path / "F_corrente.bin"
    corrente.write_bytes(montar_cabecalho(len(x), (1,), (1,), ("",), 312_500, versao=7, descricao="quadrada f=1280Hz",
                                          spi=(0, 0, 0)) + x.tobytes())
    rc, _, err = cli(main, corrente, gravar(tmp_path, "F_6400.bin", 312_500, 6400.0, seed=6))
    assert rc == 0 and "CORRENTE sem --entrada" in err and "passa-alta" in err
