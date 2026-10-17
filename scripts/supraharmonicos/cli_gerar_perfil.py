"""Linha de comando do ``gerar_perfil_sonda``: flags, orquestração e ``main()``.

Borda do programa (ver ``cli_adc_tool`` para a convenção): liga o logging,
traduz ``ErroUso`` -> ``parser.error`` (código 2) e ``ErroSHAN`` -> ``Erro: ...``
(código 1). Medição e agregação estão em ``calibracao_sonda``; escrita do JSON
em ``escrita_perfil``.
"""

import argparse
import logging
import math
import re
from datetime import date
from pathlib import Path

from .calibracao_sonda import (
    JANELA_CALIBRACAO_PADRAO,
    NOME_REFERENCIA_EXTERNA,
    PADRAO_NOME_CAPTURA,
    RESOLUCAO_WELCH_CALIBRACAO_PADRAO,
    SNR_MINIMO_DB_PADRAO,
    SOBREPOSICAO_WELCH_CALIBRACAO_PADRAO,
    TOLERANCIA_FREQ_PCT_PADRAO,
    PontoMedido,
    agregar_por_frequencia,
    descobrir_capturas,
    ler_referencia_externa,
    ler_status_manifesto,
    processar_captura,
)
from .erros import ErroSHAN, ErroUso
from .escrita_perfil import gerar_grafico, gravar_perfil_validado, montar_perfil_json
from .registro import configurar_logging_cli
from .sonda import SONDAS_DIR_PADRAO

log = logging.getLogger(__name__)


def montar_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gerar_perfil_sonda.py",
        description=(
            "Constrói o perfil de calibração (.json) de uma sonda de corrente "
            "a partir das capturas de firmware/calibrar_sonda.sh. Mede "
            "frequência e amplitude de cada captura (não confia no nome do "
            "arquivo), calcula o ganho contra uma referência de corrente "
            "real, e agrega repetições. A corrente real vem de UMA destas fontes: "
            "um segundo canal do ADC no shunt (--resistencia-shunt), leituras do "
            "osciloscópio anotadas a cada ponto (--referencia-externa) ou uma "
            "corrente constante (--amplitude-referencia)."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Exemplos:\n"
            "  # 2 canais (referência no ADC): corrente = V_shunt(canal de referência) / R\n"
            "  uv run gerar_perfil_sonda.py capturas/fluke_i30_01 \\\n"
            "      --resistencia-shunt 0.1 --ganho 1,10 --fabricante Fluke --modelo i30s --plot\n"
            "  # 1 canal (Nyquist 2x maior), corrente lida no osciloscópio (referencia_externa.csv da pasta)\n"
            "  uv run gerar_perfil_sonda.py capturas/fluke_i30_01 \\\n"
            "      --referencia-externa --resistencia-shunt 1.0 --ganho 10 --plot\n"
            "\n"
            "--faixa/--ganho/--offset: 1 valor (vale p/ os canais lidos) ou 'referencia,sonda'.\n"
            "--ganho do canal da sonda = 1/sensibilidade_nominal (sonda de 100 mV/A -> 10) e DEVE ser\n"
            "o mesmo usado depois em 'adc_tool.py --ganho' -- ver docstring do módulo."
        ),
    )
    parser.add_argument("pasta_capturas", type=Path, help="Pasta com os '.bin' de calibração (ex.: capturas/fluke_i30_01/).")

    grupo_ref = parser.add_argument_group(
        "Referência da corrente real (escolha UMA fonte)",
        "Sem referência não há ganho: --resistencia-shunt sozinho (canal de referência no ADC, 2 canais por captura), "
        "--referencia-externa (leituras do osciloscópio, 1 canal por captura) ou --amplitude-referencia (corrente constante).",
    )
    grupo_ref.add_argument("--resistencia-shunt", type=float, metavar="OHMS",
                           help="Resistência do shunt de precisão, em ohms. Sozinho: a corrente real é calculada por frequência a "
                                "partir do canal de referência da captura (2 canais). Com --referencia-externa: converte a tensão "
                                "RMS no shunt lida no osciloscópio em corrente.")
    grupo_ref.add_argument("--referencia-externa", nargs="?", const="@pasta", default=None, type=str, metavar="CSV",
                           help=f"Corrente real lida num instrumento externo, anotada por captura em um CSV (colunas 'arquivo' e "
                                f"'v_shunt_rms_V' -- ou 'corrente_rms_A'). Sem caminho: '{NOME_REFERENCIA_EXTERNA}' dentro da pasta "
                                f"de capturas (escrito por 'calibrar_sonda.sh --ref-externa'). As capturas têm 1 canal só (o da sonda).")
    grupo_ref.add_argument("--amplitude-referencia", type=float, metavar="A",
                           help="Corrente real CONSTANTE injetada em toda a varredura, em Amperes (amplitude de pico).")

    parser.add_argument("--id", type=str, default=None, help="Id da sonda no perfil de saída (padrão: nome da pasta).")
    parser.add_argument("-o", "--saida", type=Path, default=None, metavar="ARQUIVO.json",
                         help="Caminho do .json de saída (padrão: scripts/sondas/<id>.json, ao lado deste script).")

    parser.add_argument("--canal-referencia", type=int, default=None, metavar="N",
                         help="Força o número do canal de referência (padrão: detectado do cabeçalho v2). Só é lido com --resistencia-shunt sozinho.")
    parser.add_argument("--canal-sonda", type=int, default=None, metavar="N",
                         help="Força o número do canal da sonda (padrão: o único canal da captura, ou o de grandeza=corrente no cabeçalho v2).")

    parser.add_argument("--formato", choices=["int16", "uint16"], default="uint16",
                         help="Mesmo significado de adc_tool.py --formato (padrão: uint16).")
    parser.add_argument("--faixa", type=str, default="10.24", metavar="V[,V]",
                         help="Faixa do ADC em Volts -- 1 valor ou 'referencia,sonda' (padrão: 10.24).")
    parser.add_argument("--ganho", type=str, default="1.0", metavar="G[,G]",
                         help="Ganho ADC->grandeza física -- 1 valor ou 'referencia,sonda' (padrão: 1.0). "
                              "Para o canal da sonda, ver docstring do módulo (--ganho ANTES da correção de frequência).")
    parser.add_argument("--offset", type=str, default=None, metavar="V[,V]",
                         help="Offset DC -- padrão automático (faixa/2 p/ uint16), mesma regra de adc_tool.py.")

    parser.add_argument("--tolerancia-freq-pct", type=float, default=TOLERANCIA_FREQ_PCT_PADRAO, metavar="PCT",
                         help=f"Janela de busca do tom em torno da frequência-alvo nominal (padrão: {TOLERANCIA_FREQ_PCT_PADRAO:g}%%).")
    parser.add_argument("--resolucao-welch", type=float, default=RESOLUCAO_WELCH_CALIBRACAO_PADRAO, metavar="HZ",
                         help=f"Resolução espectral do Welch usado para medir cada tom (padrão: {RESOLUCAO_WELCH_CALIBRACAO_PADRAO:g} Hz).")
    parser.add_argument("--snr-minimo-db", type=float, default=SNR_MINIMO_DB_PADRAO, metavar="DB",
                         help=f"SNR mínimo (dB) do pico sobre o piso de ruído para aceitar um tom (padrão: {SNR_MINIMO_DB_PADRAO:g}). "
                              f"Abaixo disso o arquivo é pulado -- evita gravar no perfil o 'pico' de um canal só com ruído (ex.: sonda desconectada).")
    parser.add_argument("-f", "--frequencia", type=float, default=None, metavar="HZ",
                         help="Frequência de amostragem TOTAL, só p/ capturas legadas SEM cabeçalho (mesmo significado de adc_tool.py -f).")
    parser.add_argument("--sobreposicao-welch", type=float, default=SOBREPOSICAO_WELCH_CALIBRACAO_PADRAO, metavar="FRACAO",
                         help=f"Sobreposição entre segmentos do Welch (padrão: {SOBREPOSICAO_WELCH_CALIBRACAO_PADRAO:g}).")
    parser.add_argument("--janela", type=str, default=JANELA_CALIBRACAO_PADRAO, metavar="NOME",
                         help=f"Janela espectral (padrão: '{JANELA_CALIBRACAO_PADRAO}' -- recomendada p/ exatidão de amplitude; mesmas opções de adc_tool.py).")

    parser.add_argument("--fabricante", type=str, default=None)
    parser.add_argument("--modelo", type=str, default=None)
    parser.add_argument("--numero-serie", type=str, default=None)
    parser.add_argument("--tipo-saida", type=str, default=None, help="Ex.: 'mV/A'.")
    parser.add_argument("--incerteza-estimada-pct", type=float, default=None)
    parser.add_argument("--calibrado-com", type=str, default=None)
    parser.add_argument("--faixa-freq-valida", type=float, nargs=2, default=None, metavar=("MIN_HZ", "MAX_HZ"),
                         help="Override manual -- padrão: [menor, maior] frequência efetivamente medida.")
    parser.add_argument("--data-calibracao", type=str, default=str(date.today()), metavar="AAAA-MM-DD")

    parser.add_argument("--plot", action="store_true", help="Gera um '.png' de diagnóstico (pontos + curva interpolada) ao lado do '.json'.")

    return parser


def _validar_e_completar_args(args: argparse.Namespace) -> None:
    """Valida flags e preenche ``modo_referencia`` e ``id`` (padrão: nome da pasta)."""
    if args.referencia_externa is not None:
        args.modo_referencia = "externa"
    elif args.amplitude_referencia is not None:
        args.modo_referencia = "fixa"
    elif args.resistencia_shunt is not None:
        args.modo_referencia = "shunt"
    else:
        raise ErroUso(
            "informe a referência da corrente real: --resistencia-shunt (canal de referência no ADC), "
            "--referencia-externa (leituras do osciloscópio) ou --amplitude-referencia (corrente constante)."
        )
    if args.amplitude_referencia is not None and args.modo_referencia != "fixa":
        raise ErroUso("--amplitude-referencia não pode ser combinado com --referencia-externa.")
    if args.amplitude_referencia is not None and args.resistencia_shunt is not None:
        raise ErroUso("--amplitude-referencia não pode ser combinado com --resistencia-shunt.")
    if args.modo_referencia == "fixa" and args.amplitude_referencia <= 0:
        raise ErroUso("--amplitude-referencia precisa ser positiva.")
    if args.resistencia_shunt is not None and args.resistencia_shunt <= 0:
        raise ErroUso("--resistencia-shunt precisa ser positiva.")

    if args.id is None:
        args.id = args.pasta_capturas.resolve().name
    if not re.match(r"^[a-z0-9_-]+$", args.id):
        log.warning(
            f"id '{args.id}' tem caracteres fora de [a-z0-9_-] -- "
            f"firmware/calibrar_sonda.sh só gera pastas já sanitizadas; se "
            f"esta pasta não veio de lá, considere renomear."
        )


def _caminho_referencia_externa(args: argparse.Namespace) -> Path:
    if args.referencia_externa == "@pasta":
        return args.pasta_capturas / NOME_REFERENCIA_EXTERNA
    return Path(args.referencia_externa)


def _medir_capturas(args: argparse.Namespace, arquivos: list[Path],
                    status_manifesto: dict[str, str]) -> list[PontoMedido]:
    """Mede cada captura; arquivos ruins são pulados com aviso (não derrubam o lote)."""
    pontos_medidos: list[PontoMedido] = []
    correntes_externas: dict[str, float] = {}
    if args.modo_referencia == "externa":
        correntes_externas = ler_referencia_externa(_caminho_referencia_externa(args), args.resistencia_shunt)
        log.info(f"{len(correntes_externas)} leitura(s) externa(s) lida(s) de '{_caminho_referencia_externa(args)}'.")
    for caminho in arquivos:
        m = PADRAO_NOME_CAPTURA.match(caminho.name)
        freq_alvo_hz = float(m.group(1))

        status = status_manifesto.get(caminho.name)
        if status == "sem_arquivo":
            continue  # não deveria nem existir no disco, mas por garantia
        if status and status.startswith("aceito_com_erro"):
            log.warning(f"'{caminho.name}' foi aceito com erro na coleta ({status}) -- processando mesmo assim.")

        resultado = processar_captura(
            caminho, freq_alvo_hz, args.modo_referencia,
            args.canal_referencia, args.canal_sonda,
            args.formato, args.faixa, args.ganho, args.offset,
            args.tolerancia_freq_pct, args.janela, args.resolucao_welch, args.sobreposicao_welch,
            args.snr_minimo_db, args.frequencia,
        )
        if resultado is not None and args.modo_referencia == "externa":
            corrente_rms = correntes_externas.get(caminho.name)
            if corrente_rms is None:
                log.warning(
                    f"pulando '{caminho.name}' -- sem leitura do instrumento externo em "
                    f"'{_caminho_referencia_externa(args).name}'. Anote o valor (ou refaça o ponto com "
                    f"'calibrar_sonda.sh --ref-externa --modo refazer')."
                )
                continue
            resultado.corrente_externa_pico_a = math.sqrt(2.0) * corrente_rms  # RMS -> pico (tom senoidal)
        if resultado is not None:
            pontos_medidos.append(resultado)
    return pontos_medidos


def executar_geracao(args: argparse.Namespace) -> None:
    """Fluxo completo: capturas -> medição -> agregação -> JSON validado (+ gráfico)."""
    _validar_e_completar_args(args)
    pasta = args.pasta_capturas
    caminho_saida = args.saida or (SONDAS_DIR_PADRAO / f"{args.id}.json")

    arquivos = descobrir_capturas(pasta)
    status_manifesto = ler_status_manifesto(pasta)
    log.info(f"{len(arquivos)} arquivo(s) de captura encontrado(s) em '{pasta}'.")

    pontos_medidos = _medir_capturas(args, arquivos, status_manifesto)
    if len(pontos_medidos) < 2:
        raise ErroSHAN(
            f"só {len(pontos_medidos)} ponto(s) processado(s) com sucesso "
            f"-- são necessários pelo menos 2 para um perfil 'resposta_frequencia'. "
            f"Veja os avisos acima para o motivo de cada arquivo pulado."
        )

    pontos_perfil = agregar_por_frequencia(
        pontos_medidos, args.modo_referencia, args.amplitude_referencia, args.resistencia_shunt
    )
    log.info(f"{len(pontos_perfil)} ponto(s) de frequência únicos após agregação de repetições.")

    ganho_ref = min(pontos_perfil, key=lambda p: p.freq_hz).ganho
    if not (0.7 <= ganho_ref <= 1.3):
        log.warning(
            f"ganho no ponto de menor frequência ({ganho_ref:.3f}) está "
            f"longe de 1.0 -- se essa frequência é onde a sensibilidade "
            f"nominal da sonda foi especificada, o --ganho={args.ganho} "
            f"informado provavelmente não é o valor nominal correto (ver "
            f"docstring do módulo)."
        )

    perfil_dict = montar_perfil_json(pontos_perfil, args)
    gravar_perfil_validado(perfil_dict, caminho_saida, len(pontos_perfil))

    for p in sorted(pontos_perfil, key=lambda p: p.freq_hz):
        marcador = f" (desvio {p.desvio_pct:.1f}%, {p.n_amostras} rep.)" if p.n_amostras > 1 else ""
        log.info(f"  {p.freq_hz:10.2f} Hz -> ganho {p.ganho:.4f}{marcador}")

    if args.plot:
        gerar_grafico(pontos_perfil, perfil_dict, caminho_saida.with_suffix(".png"))


def main(argv: list[str] | None = None) -> int:
    """Ponto de entrada do ``gerar_perfil_sonda``. Devolve o código de saída do processo."""
    parser = montar_parser()
    args = parser.parse_args(argv)
    configurar_logging_cli()
    try:
        executar_geracao(args)
    except ErroUso as e:
        parser.error(str(e))
    except ErroSHAN as e:
        log.error(str(e))
        return 1
    return 0
