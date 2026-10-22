"""Escrita do perfil de sonda: montagem do JSON, gravação segura e gráfico de diagnóstico.

Formato de saída: o consumido por ``sonda.carregar_perfil_sonda`` -- ver
``docs/probe-correction-design.md``. ``montar_perfil_json`` lê os atributos de
metadados do ``argparse.Namespace`` de ``cli_gerar_perfil.montar_parser``
(``id``, ``fabricante``, ``faixa``, ``ganho``, ``modo_referencia``...) e, quando existem, os
resumos preenchidos pelo ``cli_gerar_perfil``: ``referencia_resumo`` (de onde veio a grandeza
injetada) e ``resposta_resumo`` (queda de 3 dB, inclinação final do conjunto).

Depende de: ``calibracao_sonda``, ``canais``, ``sonda``, ``erros``;
``matplotlib`` só dentro de ``gerar_grafico``.
"""

import json
import logging
import math
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from .calibracao_sonda import PontoPerfil, ResumoResposta
from .canais import analisar_lista_calibracao
from .constantes import FAIXA_LEGADA_V
from .erros import ErroSHAN
from .fase_quadrada import PontosAbsolutos, RespostaCombinada, fase_do_modelo, h_segunda_ordem
from .sonda import PerfilSonda, carregar_perfil_sonda

log = logging.getLogger(__name__)


def montar_perfil_json(pontos: list[PontoPerfil], args) -> dict:
    pontos_ordenados = sorted(pontos, key=lambda p: p.freq_hz)
    perfil = {
        "id": args.id,
        "tipo": "resposta_frequencia",
        "data_calibracao": args.data_calibracao,
        # 'n' e 'desvio_pct' (repetições e dispersão relativa do ganho entre
        # elas) são só rastreabilidade: carregar_perfil_sonda() lê apenas
        # freq_hz/ganho e ignora os demais campos do ponto.
        "pontos": [
            {"freq_hz": round(p.freq_hz, 3), "ganho": round(p.ganho, 6),
             "n": p.n_amostras, "desvio_pct": round(p.desvio_pct, 3)}
            for p in pontos_ordenados
        ],
    }
    if args.fabricante:
        perfil["fabricante"] = args.fabricante
    if args.modelo:
        perfil["modelo"] = args.modelo
    if args.numero_serie:
        perfil["numero_serie"] = args.numero_serie
    if args.tipo_saida:
        perfil["tipo_saida"] = args.tipo_saida
    if args.incerteza_estimada_pct is not None:
        perfil["incerteza_estimada_pct"] = args.incerteza_estimada_pct
    if args.faixa_freq_valida:
        perfil["faixa_freq_valida_hz"] = list(args.faixa_freq_valida)
    else:
        perfil["faixa_freq_valida_hz"] = [
            round(pontos_ordenados[0].freq_hz, 3),
            round(pontos_ordenados[-1].freq_hz, 3),
        ]
    calibrado_com = args.calibrado_com or "cadeia completa SH-Analyzer (sonda + isolador + ADS8688)"
    perfil["calibrado_com"] = calibrado_com

    # Metadados de rastreabilidade -- NÃO lidos por adc_tool.py hoje, mas
    # registram sob qual --ganho (e demais calibração ADC) do canal da
    # sonda este perfil é válido (ver docstring do módulo, seção --ganho).
    # Sem isso, nada impediria alguém de usar este perfil com um --ganho
    # de produção diferente do usado aqui, o que reintroduziria erro
    # sistemático de escala.
    # --faixa: o que as capturas realmente usaram (preenchido por cli_gerar_perfil a
    # partir do cabeçalho v3 / --faixa), ou o --faixa digitado / padrão histórico
    # quando quem chama não resumiu isso. 'faixa_v_confiavel' = a faixa é a REAL do
    # ADC (veio do cabeçalho), e então uma produção em OUTRA faixa não invalida o
    # perfil (ver sonda.conferir_calibracao_perfil).
    resumo_faixas = getattr(args, "faixas_resumo", None)
    if resumo_faixas is not None:
        faixas = [resumo_faixas["referencia"], resumo_faixas["sonda"]]
    else:
        faixas = analisar_lista_calibracao(args.faixa if args.faixa is not None else str(FAIXA_LEGADA_V), 2, "--faixa")
    ganhos = analisar_lista_calibracao(args.ganho, 2, "--ganho")
    calibracao_adc = {
        "formato": args.formato,
        "faixa_v": {"referencia": faixas[0], "sonda": faixas[1]},
        "ganho": {"referencia": ganhos[0], "sonda": ganhos[1]},
        "modo_referencia": args.modo_referencia,
        "gerado_em": datetime.now(timezone.utc).isoformat(),
        "n_pontos": len(pontos_ordenados),
    }
    if resumo_faixas is not None:
        calibracao_adc["faixa_v_confiavel"] = {"referencia": resumo_faixas["referencia_confiavel"],
                                               "sonda": resumo_faixas["sonda_confiavel"]}
    if args.modo_referencia == "shunt":
        calibracao_adc["resistencia_shunt_ohms"] = args.resistencia_shunt
    elif args.modo_referencia == "externa":
        # referência lida no osciloscópio/multímetro (ver calibracao_sonda.ler_referencia_externa)
        if args.resistencia_shunt is not None:
            calibracao_adc["resistencia_shunt_ohms"] = args.resistencia_shunt
    referencia = getattr(args, "referencia_resumo", None)
    if referencia:
        calibracao_adc["referencia"] = referencia       # modos 'amplitude' e 'osciloscopio': de onde veio a grandeza injetada
    resposta: ResumoResposta | None = getattr(args, "resposta_resumo", None)
    if resposta is not None:
        calibracao_adc["resposta_conjunto"] = {
            "ganho_baixa_frequencia": round(resposta.ganho_baixa_frequencia, 6),
            "freq_menos3db_hz": None if resposta.freq_menos3db_hz is None else round(resposta.freq_menos3db_hz, 1),
            "inclinacao_db_por_oitava": None if resposta.inclinacao_db_oitava is None else round(resposta.inclinacao_db_oitava, 2),
            "ganho_na_maior_frequencia_db": round(resposta.ganho_final_db, 2),
        }
    perfil["calibracao_adc"] = calibracao_adc
    return perfil


def gravar_perfil_validado(perfil_dict: dict, caminho_saida: Path, n_pontos: int) -> PerfilSonda:
    """Grava o perfil com segurança: temporário -> validação -> cópia ``.bak`` -> troca atômica.

    Escrita em dois tempos: grava num arquivo temporário, valida o round-trip
    nele (recarrega pelo MESMO código que ``adc_tool`` vai usar em produção --
    pega qualquer erro de geração antes do operador descobrir isso no meio de
    uma análise) e SÓ ENTÃO substitui o perfil final. Um perfil ruim (ou uma
    recalibração com --ganho errado) nunca destrói o perfil bom já existente:
    se há um arquivo anterior, ele é copiado para ``<saida>.bak`` antes da
    troca. Devolve o perfil recarregado."""
    caminho_saida.parent.mkdir(parents=True, exist_ok=True)
    caminho_tmp = caminho_saida.with_name(caminho_saida.name + ".tmp")
    with open(caminho_tmp, "w", encoding="utf-8") as f:
        json.dump(perfil_dict, f, indent=2, ensure_ascii=False)
        f.write("\n")
    try:
        perfil_recarregado = carregar_perfil_sonda(caminho_tmp)
    except (ErroSHAN, ValueError) as e:
        caminho_tmp.unlink(missing_ok=True)
        raise ErroSHAN(
            f"o perfil gerado NÃO carrega de volta via adc_tool.py -- {e} "
            f"(o perfil anterior, se havia, foi mantido)."
        ) from e
    if caminho_saida.exists():
        caminho_bak = caminho_saida.with_name(caminho_saida.name + ".bak")
        shutil.copy2(caminho_saida, caminho_bak)
        log.warning(f"'{caminho_saida}' já existia -- será substituído; cópia do anterior em '{caminho_bak}'.")
    os.replace(caminho_tmp, caminho_saida)
    log.info(f"Perfil salvo em '{caminho_saida}'.")
    log.info(
        f"Validação: perfil recarregado com sucesso via adc_tool.carregar_perfil_sonda "
        f"('{perfil_recarregado.id}', {n_pontos} pontos)."
    )
    return perfil_recarregado


def gerar_grafico(pontos: list[PontoPerfil], perfil_dict: dict, caminho_saida: Path) -> None:
    import matplotlib.pyplot as plt  # só no uso de --plot

    freqs_pontos = np.array([p.freq_hz for p in pontos])
    ganhos_pontos = np.array([p.ganho for p in pontos])

    # Reaproveita a MESMA classe usada em produção (adc_tool.PerfilSonda)
    # p/ desenhar a curva interpolada exatamente como adc_tool.py vai
    # usá-la depois -- não uma reimplementação paralela da interpolação.
    perfil_tmp = PerfilSonda(
        id=perfil_dict["id"], tipo="resposta_frequencia", caminho=caminho_saida,
        pontos_freq_hz=freqs_pontos, pontos_ganho=ganhos_pontos,
    )
    # A grade da curva vai de min a max dos pontos; o erro de arredondamento de
    # 10**log10(x) pode deixar 1 ponto 1 ulp fora da faixa e disparar o aviso
    # de "fora da faixa calibrada" -- irrelevante aqui, só desenhamos.
    perfil_tmp.silenciar_aviso_fora_da_faixa()
    freqs_curva = np.logspace(np.log10(freqs_pontos.min()), np.log10(freqs_pontos.max()), 500)
    ganhos_curva = perfil_tmp.ganho_em(freqs_curva)

    fig, ax = plt.subplots(figsize=(9, 5))
    ax.semilogx(freqs_curva, ganhos_curva, "-", color="tab:blue", linewidth=1.2, label="Interpolação PCHIP (uso em produção)")
    ax.semilogx(freqs_pontos, ganhos_pontos, "o", color="tab:orange", markersize=6, label="Pontos medidos")
    ax.axhline(1.0, color="gray", linewidth=0.8, linestyle=":")
    ax.set_xlabel("Frequência (Hz)")
    ax.set_ylabel("Ganho (linear, adimensional)")
    ax.set_title(f"Perfil de sonda '{perfil_dict['id']}' -- {len(pontos)} ponto(s)")
    ax.grid(True, which="both", alpha=0.4)
    ax.legend()
    fig.tight_layout()
    fig.savefig(caminho_saida, dpi=150)
    plt.close(fig)     # o pyplot guarda toda figura aberta até ser fechada
    log.info(f"Gráfico de diagnóstico salvo em '{caminho_saida}'.")


def gerar_grafico_bode(absolutos: list[PontosAbsolutos], combinada: RespostaCombinada, rotulos: list[str], f0: float,
                       q: float, caminho_saida: Path, polo: float = math.inf) -> None:
    """O diagrama de Bode por ondas quadradas: os harmônicos de cada captura (claros, já costurados), a grade
    combinada (a média ponderada por faixa, com ±1σ) e o 2ª ordem ajustado (com o polo real a mais, se houver);
    embaixo de cada painel, os resíduos da grade contra ele."""
    import matplotlib.pyplot as plt  # só no uso de --plot

    fig, eixos = plt.subplots(4, 1, sharex=True, figsize=(9, 9.5), gridspec_kw={"height_ratios": [3, 1.3, 3, 1.3]})
    mag, res_mag, fase, res_fase = eixos
    fmin = float(min(a.freq_hz[0] for a in absolutos)) / 1.3
    fmax = float(max(a.freq_hz[-1] for a in absolutos)) * 1.15
    fm = np.geomspace(fmin, fmax, 500)
    hm = h_segunda_ordem(fm, f0, q, polo)
    texto_polo = f", polo real em {polo / 1e3:.0f} kHz" if math.isfinite(polo) else ""
    mag.semilogx(fm, 20 * np.log10(np.abs(hm)), "-", color="tab:blue", lw=1.0, alpha=0.8,
                 label=f"2ª ordem ajustado: f0 = {f0 / 1e3:.3f} kHz, Q = {q:.4f}{texto_polo}")
    fase.semilogx(fm, np.degrees(fase_do_modelo(fm, f0, q, polo)), "-", color="tab:blue", lw=1.0, alpha=0.8)
    db = 20 / np.log(10)
    # uma cor por f₁ (as variantes de amplitude/offset e as duas taxas juntas), na legenda uma vez só
    f1s = sorted({round(a.medida.f1_hz) for a in absolutos})
    taxas = sorted({rotulo for rotulo in rotulos})
    ja_na_legenda: set[int] = set()
    for a in sorted(absolutos, key=lambda a: a.medida.f1_hz):
        modelo = h_segunda_ordem(a.freq_hz, f0, q, polo)
        f1 = round(a.medida.f1_hz)
        kw = dict(ls="none", marker=".", ms=3, alpha=0.35, color=f"C{(f1s.index(f1) % 9) + 1}")
        rotulo_f1 = None if f1 in ja_na_legenda else f"f₁ = {f1} Hz"
        ja_na_legenda.add(f1)
        mag.semilogx(a.freq_hz, db * a.ln_ganho, label=rotulo_f1, **kw)
        fase.semilogx(a.freq_hz, np.degrees(a.fase_rad), **kw)
        res_mag.semilogx(a.freq_hz, db * (a.ln_ganho - np.log(np.abs(modelo))), **kw)
        res_fase.semilogx(a.freq_hz, np.degrees(a.fase_rad - fase_do_modelo(a.freq_hz, f0, q, polo)), **kw)
    c = combinada
    r_db = db * (c.ln_ganho - np.log(np.abs(h_segunda_ordem(c.freq_hz, f0, q, polo))))
    r_gr = np.degrees(c.fase_rad - fase_do_modelo(c.freq_hz, f0, q, polo))
    kw = dict(ls="none", marker="o", ms=3.5, color="black", ecolor="black", elinewidth=0.8, capsize=1.5, zorder=5)
    mag.errorbar(c.freq_hz, db * c.ln_ganho, yerr=db * c.sigma_ln, label="Combinada (média ponderada por faixa)", **kw)
    fase.errorbar(c.freq_hz, np.degrees(c.fase_rad), yerr=np.degrees(c.sigma_fase), **kw)
    res_mag.errorbar(c.freq_hz, r_db, yerr=db * c.sigma_ln, **kw)
    res_fase.errorbar(c.freq_hz, r_gr, yerr=np.degrees(c.sigma_fase), **kw)
    lim_db = max(0.02, 1.5 * float(np.max(np.abs(r_db) + db * c.sigma_ln)))
    lim_gr = max(0.1, 1.5 * float(np.max(np.abs(r_gr) + np.degrees(c.sigma_fase))))
    res_mag.set_ylim(-lim_db, lim_db)
    res_fase.set_ylim(-lim_gr, lim_gr)
    mag.set_ylabel("Ganho (dB, K = 1)")
    res_mag.set_ylabel("Resíduo (dB)")
    fase.set_ylabel("Fase (°)")
    res_fase.set_ylabel("Resíduo (°)")
    res_fase.set_xlabel("Frequência (Hz)")
    mag.set_title("Resposta da cadeia por ondas quadradas (fase a menos de um atraso puro, supondo fase mínima)\n"
                  f"{len(absolutos)} capturas ({', '.join(taxas)})", fontsize=10)
    for eixo in eixos:
        eixo.grid(True, which="both", alpha=0.4)
    for eixo in (res_mag, res_fase):
        eixo.axhline(0, color="tab:blue", lw=0.8)
    mag.legend(fontsize=7, loc="lower left", ncols=2)
    fig.tight_layout()
    fig.savefig(caminho_saida, dpi=150)
    plt.close(fig)
    log.info(f"Diagrama de Bode salvo em '{caminho_saida}'.")
