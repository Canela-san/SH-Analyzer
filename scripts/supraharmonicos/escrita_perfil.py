"""Escrita do perfil de sonda: montagem do JSON, gravação segura e gráfico de diagnóstico.

Formato de saída: o consumido por ``sonda.carregar_perfil_sonda`` -- ver
``docs/proposta_correcao_sonda.md``. ``montar_perfil_json`` lê os atributos de
metadados do ``argparse.Namespace`` de ``cli_gerar_perfil.montar_parser``
(``id``, ``fabricante``, ``faixa``, ``ganho``, ``modo_referencia``...) e, quando existem, os
resumos preenchidos pelo ``cli_gerar_perfil``: ``referencia_resumo`` (de onde veio a grandeza
injetada) e ``resposta_resumo`` (queda de 3 dB, inclinação final do conjunto).

Depende de: ``calibracao_sonda``, ``canais``, ``sonda``, ``erros``;
``matplotlib`` só dentro de ``gerar_grafico``.
"""

import json
import logging
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from .calibracao_sonda import PontoPerfil, ResumoResposta
from .canais import analisar_lista_calibracao
from .erros import ErroSHAN
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
    faixas = analisar_lista_calibracao(args.faixa, 2, "--faixa")
    ganhos = analisar_lista_calibracao(args.ganho, 2, "--ganho")
    calibracao_adc = {
        "formato": args.formato,
        "faixa_v": {"referencia": faixas[0], "sonda": faixas[1]},
        "ganho": {"referencia": ganhos[0], "sonda": ganhos[1]},
        "modo_referencia": args.modo_referencia,
        "gerado_em": datetime.now(timezone.utc).isoformat(),
        "n_pontos": len(pontos_ordenados),
    }
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
    log.info(f"Gráfico de diagnóstico salvo em '{caminho_saida}'.")
