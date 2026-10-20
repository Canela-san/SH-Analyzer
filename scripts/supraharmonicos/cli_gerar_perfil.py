"""Linha de comando do ``gerar_perfil_sonda``: flags, orquestração e ``main()``.

Borda do programa (ver ``cli_adc_tool`` para a convenção): liga o logging,
traduz ``ErroUso`` -> ``parser.error`` (código 2) e ``ErroSHAN`` -> ``Erro: ...``
(código 1). Medição e agregação estão em ``calibracao_sonda``; escrita do JSON
em ``escrita_perfil``; amplitude com unidades e metadados em ``referencia``;
leitura do osciloscópio em ``osciloscopio``.

A referência da grandeza injetada (de onde vem a "verdade" do ganho) é uma de quatro:
amplitude conhecida (gravada nos metadados de cada captura ou constante), osciloscópio,
leituras anotadas (``referencia_externa.csv``) ou o canal de referência do ADC no shunt.
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
    RESOLUCAO_WELCH_CALIBRACAO_PADRAO,
    SNR_MINIMO_DB_PADRAO,
    SOBREPOSICAO_WELCH_CALIBRACAO_PADRAO,
    TOLERANCIA_FREQ_PCT_PADRAO,
    PontoMedido,
    ResumoResposta,
    agregar_por_frequencia,
    descobrir_capturas,
    identificar_captura,
    ler_referencia_externa,
    ler_status_manifesto,
    processar_captura,
    resumir_resposta,
)
from .canais import analisar_lista_calibracao
from .constantes import FAIXA_LEGADA_V
from .erros import ErroSHAN, ErroUso
from .escrita_perfil import gerar_grafico, gravar_perfil_validado, montar_perfil_json
from .osciloscopio import (
    adicionar_argumentos_osciloscopio,
    ler_forma_de_onda_dos_args,
    localizar_arquivo_osciloscopio,
    medir_senoide,
)
from .referencia import Amplitude, ReferenciaCaptura, analisar_amplitude, pico_fisico
from .registro import configurar_logging_cli
from .sonda import SONDAS_DIR_PADRAO

log = logging.getLogger(__name__)

FREQ_DIVERGENTE_FRACAO = 0.02   # metadado de frequência x frequência medida: acima disso, aviso


def montar_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gerar_perfil_sonda.py",
        description=(
            "Constrói o perfil de calibração (.json) da SONDA -- o conjunto sonda + frontend + ADS8688 (com o "
            "filtro passa-baixa interno dele), medido de ponta a ponta -- a partir das capturas de "
            "firmware/calibrar_sonda.sh. Mede frequência e amplitude de cada captura (não confia no nome do "
            "arquivo), calcula o ganho contra a grandeza que foi injetada e agrega repetições. A grandeza "
            "injetada vem de UMA destas fontes: a amplitude conhecida da senoide (gravada nos metadados de cada "
            "captura, ou --amplitude-referencia), o osciloscópio (--referencia-osciloscopio), leituras "
            "anotadas a cada ponto (--referencia-externa) ou um segundo canal do ADC no shunt (--resistencia-shunt)."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Exemplos:\n"
            "  # Amplitude gravada nos metadados de cada captura (calibrar_sonda.sh --amplitude 500mVpp):\n"
            "  uv run gerar_perfil_sonda.py capturas/fluke_i30_01 --plot\n"
            "  # Amplitude constante dada aqui (mesmo sinal em todas as capturas)\n"
            "  uv run gerar_perfil_sonda.py capturas/fluke_i30_01 --amplitude-referencia 500mVpp --plot\n"
            "  # Osciloscópio: um .m por captura, com o nome dela (calibracao_1000Hz_rep1.m ...)\n"
            "  uv run gerar_perfil_sonda.py capturas/fluke_i30_01 --referencia-osciloscopio --plot\n"
            "  # 1 canal, tensão RMS no shunt lida no osciloscópio e anotada (referencia_externa.csv da pasta)\n"
            "  uv run gerar_perfil_sonda.py capturas/fluke_i30_01 \\\n"
            "      --referencia-externa --resistencia-shunt 1.0 --ganho 10 --plot\n"
            "  # 2 canais (referência no ADC): corrente = V_shunt(canal de referência) / R\n"
            "  uv run gerar_perfil_sonda.py capturas/fluke_i30_01 \\\n"
            "      --resistencia-shunt 0.1 --ganho 1,10 --fabricante Fluke --modelo i30s --plot\n"
            "\n"
            "Amplitude: número + unidade + tipo, ex.: 500mVpp, 250mVpk, 176.8mVrms, 2Arms (um número puro vale\n"
            "como pico em A). Em V é a tensão no ponto onde o --ganho é aplicado; em A, a grandeza física.\n"
            "--faixa/--ganho/--offset: 1 valor (vale p/ os canais lidos) ou 'referencia,sonda'.\n"
            "--ganho do canal da sonda = 1/sensibilidade_nominal (sonda de 100 mV/A -> 10) e DEVE ser\n"
            "o mesmo usado depois em 'adc_tool.py --ganho' -- ver docstring do módulo."
        ),
    )
    parser.add_argument("pasta_capturas", type=Path, help="Pasta com os '.bin' de calibração (ex.: capturas/fluke_i30_01/).")

    grupo_ref = parser.add_argument_group(
        "Referência da grandeza injetada (escolha UMA fonte)",
        "Sem referência não há ganho. Sem nenhuma flag desta seção, vale a amplitude gravada nos metadados das "
        "capturas ('ref: amp=...', escrita por calibrar_sonda.sh --amplitude), se houver.",
    )
    grupo_ref.add_argument("--amplitude-referencia", type=str, default=None, metavar="AMPLITUDE",
                           help="Amplitude CONHECIDA da senoide injetada, igual em todas as capturas: número + unidade + tipo "
                                "(500mVpp, 250mVpk, 176.8mVrms, 2Arms; número puro = pico em A). Vence a gravada nos "
                                "metadados (e avisa se forem diferentes).")
    grupo_ref.add_argument("--referencia-osciloscopio", nargs="?", const="@pasta", default=None, type=str, metavar="PASTA",
                           help="A amplitude vem do osciloscópio: para cada captura 'X.bin', o arquivo 'X.m' (ou .mat/.csv/.txt) "
                                "com a forma de onda, na pasta de capturas (ou em PASTA). A senoide é medida por ajuste de "
                                "mínimos quadrados. Ver as opções --osc-*.")
    grupo_ref.add_argument("--resistencia-shunt", type=float, metavar="OHMS",
                           help="Resistência do shunt de precisão, em ohms. Sozinho: a corrente real é calculada por frequência a "
                                "partir do canal de referência da captura (2 canais). Com --referencia-externa: converte a tensão "
                                "RMS no shunt lida no osciloscópio em corrente.")
    grupo_ref.add_argument("--referencia-externa", nargs="?", const="@pasta", default=None, type=str, metavar="CSV",
                           help=f"Grandeza real lida num instrumento externo, anotada por captura em um CSV (colunas 'arquivo' e "
                                f"'v_shunt_rms_V' [tensão no shunt; precisa de --resistencia-shunt], 'corrente_rms_A' ou "
                                f"'tensao_rms_V' [tensão na entrada de uma cadeia de tensão]). Sem caminho: '{NOME_REFERENCIA_EXTERNA}' "
                                f"dentro da pasta de capturas (escrito por 'calibrar_sonda.sh --ref-externa'). As capturas têm 1 canal só (o da sonda).")
    adicionar_argumentos_osciloscopio(parser.add_argument_group(
        "Osciloscópio (com --referencia-osciloscopio)",
        "O leitor de .m/.mat/.csv é tolerante, mas não há formato único entre fabricantes: se ele não acertar a "
        "variável ou a taxa de amostragem, a mensagem de erro lista o que achou no arquivo e estas opções resolvem.",
    ))

    parser.add_argument("--id", type=str, default=None, help="Id da sonda no perfil de saída (padrão: nome da pasta).")
    parser.add_argument("-o", "--saida", type=Path, default=None, metavar="ARQUIVO.json",
                         help="Caminho do .json de saída (padrão: scripts/sondas/<id>.json, ao lado deste script).")

    parser.add_argument("--canal-referencia", type=int, default=None, metavar="N",
                         help="Força o número do canal de referência (padrão: detectado do cabeçalho v2). Só é lido com --resistencia-shunt sozinho.")
    parser.add_argument("--canal-sonda", type=int, default=None, metavar="N",
                         help="Força o número do canal da sonda (padrão: o único canal da captura, ou o de grandeza=corrente no cabeçalho v2).")

    parser.add_argument("--formato", choices=["int16", "uint16"], default="uint16",
                         help="Mesmo significado de adc_tool.py --formato (padrão: uint16).")
    parser.add_argument("--faixa", type=str, default=None, metavar="V[,V]",
                         help="Faixa (fundo de escala total) do ADC em Volts -- 1 valor ou 'referencia,sonda'. "
                              "Padrão: a faixa gravada no cabeçalho de cada captura (ler_adc --faixa-adc, cabeçalho v3); "
                              "capturas v1/v2, que não registram a faixa, assumem 10.24.")
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
    """Valida flags e preenche ``modo_referencia`` (``None`` = decidir pelos metadados das capturas),
    ``amplitude_constante`` e ``id`` (padrão: nome da pasta)."""
    fontes = [nome for nome, ativa in [
        ("--referencia-externa", args.referencia_externa is not None),
        ("--amplitude-referencia", args.amplitude_referencia is not None),
        ("--referencia-osciloscopio", args.referencia_osciloscopio is not None),
    ] if ativa]
    if len(fontes) > 1:
        raise ErroUso(f"{' e '.join(fontes)} não podem ser combinados: escolha uma só fonte de referência.")
    if args.amplitude_referencia is not None and args.resistencia_shunt is not None:
        raise ErroUso("--amplitude-referencia não pode ser combinado com --resistencia-shunt.")
    if args.referencia_osciloscopio is not None and args.resistencia_shunt is not None:
        raise ErroUso("--referencia-osciloscopio não usa --resistencia-shunt: para um osciloscópio ligado num shunt, "
                      "use --osc-escala (1/R) e --osc-unidade A.")
    if args.resistencia_shunt is not None and args.resistencia_shunt <= 0:
        raise ErroUso("--resistencia-shunt precisa ser positiva.")
    if args.resolucao_welch <= 0 or not 0.0 <= args.sobreposicao_welch < 1.0:
        raise ErroUso("--resolucao-welch precisa ser positiva e --sobreposicao-welch estar em [0, 1).")
    if args.tolerancia_freq_pct <= 0:
        raise ErroUso("--tolerancia-freq-pct precisa ser positiva.")
    if args.frequencia is not None and not (math.isfinite(args.frequencia) and args.frequencia > 0):
        raise ErroUso("-f/--frequencia precisa ser um número positivo (Hz).")

    args.amplitude_constante = None
    if args.referencia_externa is not None:
        args.modo_referencia = "externa"
    elif args.amplitude_referencia is not None:
        args.modo_referencia = "amplitude"
        try:
            args.amplitude_constante = analisar_amplitude(args.amplitude_referencia)
        except ErroSHAN as e:
            raise ErroUso(f"--amplitude-referencia: {e}") from None
    elif args.referencia_osciloscopio is not None:
        args.modo_referencia = "osciloscopio"
    elif args.resistencia_shunt is not None:
        args.modo_referencia = "shunt"
    else:
        args.modo_referencia = None        # decidido por _resolver_modo, olhando os metadados das capturas

    usou_osc = (args.osc_var is not None or args.osc_tempo is not None or args.osc_fs is not None
                or args.osc_escala != 1.0 or args.osc_unidade != "V")
    if usou_osc and args.modo_referencia != "osciloscopio":
        raise ErroUso("as opções --osc-* só valem com --referencia-osciloscopio.")

    if args.id is None:
        args.id = args.pasta_capturas.resolve().name
    if not re.match(r"^[a-z0-9_-]+$", args.id):
        log.warning(
            f"id '{args.id}' tem caracteres fora de [a-z0-9_-] -- "
            f"firmware/calibrar_sonda.sh só gera pastas já sanitizadas; se "
            f"esta pasta não veio de lá, considere renomear."
        )


def _resolver_modo(args: argparse.Namespace, identificacao: dict[Path, tuple[float | None, ReferenciaCaptura | None]]) -> None:
    """Sem flag de referência, vale a amplitude gravada nos metadados das capturas (se alguma tiver)."""
    if args.modo_referencia is not None:
        return
    com_amplitude = [c for c, (_, ref) in identificacao.items() if ref is not None and ref.amplitude is not None]
    if not com_amplitude:
        raise ErroUso(
            "informe a referência da grandeza injetada: --amplitude-referencia (amplitude conhecida, ex.: 500mVpp), "
            "--referencia-osciloscopio, --referencia-externa ou --resistencia-shunt (canal de referência no ADC). "
            "Nenhuma captura da pasta traz a amplitude nos metadados ('ref: amp=...')."
        )
    args.modo_referencia = "amplitude"
    log.info(f"referência: amplitude gravada nos metadados de {len(com_amplitude)} das {len(identificacao)} captura(s).")


def _caminho_referencia_externa(args: argparse.Namespace) -> Path:
    if args.referencia_externa == "@pasta":
        return args.pasta_capturas / NOME_REFERENCIA_EXTERNA
    return Path(args.referencia_externa)


def _pasta_osciloscopio(args: argparse.Namespace) -> Path | None:
    return None if args.referencia_osciloscopio == "@pasta" else Path(args.referencia_osciloscopio)


def _pico_amplitude_conhecida(args: argparse.Namespace, ponto: PontoMedido, ganho_sonda: float) -> float | None:
    """Pico (grandeza física) da amplitude conhecida: ``--amplitude-referencia`` vence os metadados da captura."""
    gravada = ponto.referencia_gravada.amplitude if ponto.referencia_gravada is not None else None
    constante: Amplitude | None = args.amplitude_constante
    if constante is not None:
        if gravada is not None and gravada.unidade == constante.unidade and abs(gravada.pico - constante.pico) > 0.01 * constante.pico:
            log.warning(f"'{ponto.arquivo.name}': os metadados dizem {gravada.texto}, mas --amplitude-referencia "
                        f"{constante.texto} vale para todas as capturas.")
        return pico_fisico(constante, ganho_sonda)
    if gravada is not None:
        return pico_fisico(gravada, ganho_sonda)
    return None


def _pico_osciloscopio(args: argparse.Namespace, ponto: PontoMedido, ganho_sonda: float) -> float | None:
    """Pico (grandeza física) medido no arquivo do osciloscópio irmão da captura; ``None`` (com aviso) se não deu."""
    arquivo = localizar_arquivo_osciloscopio(ponto.arquivo, _pasta_osciloscopio(args))
    if arquivo is None:
        log.warning(f"pulando '{ponto.arquivo.name}' -- sem arquivo do osciloscópio '{ponto.arquivo.stem}.m' "
                    f"(ou .mat/.csv/.txt) na pasta '{_pasta_osciloscopio(args) or ponto.arquivo.parent}'.")
        return None
    try:
        forma = ler_forma_de_onda_dos_args(arquivo, args)
        tom = medir_senoide(forma.valores, forma.fs, freq_dica=ponto.freq_medida_hz)
    except ErroSHAN as e:
        log.warning(f"pulando '{ponto.arquivo.name}' -- osciloscópio '{arquivo.name}': {e}")
        return None
    log.info(f"  {ponto.arquivo.name}: osciloscópio {tom.freq_hz:.4f} Hz, {tom.amplitude_pico_a_pico:.6g} {args.osc_unidade}pp "
             f"(ADC: {(ponto.freq_medida_hz / tom.freq_hz - 1) * 1e6:+.0f} ppm na frequência)")
    return pico_fisico(Amplitude(tom.amplitude_pico, args.osc_unidade, "pico", arquivo.name), ganho_sonda)


def _medir_capturas(args: argparse.Namespace, arquivos: list[Path], status_manifesto: dict[str, str],
                    identificacao: dict[Path, tuple[float | None, ReferenciaCaptura | None]]) -> list[PontoMedido]:
    """Mede cada captura; arquivos ruins são pulados com aviso (não derrubam o lote)."""
    pontos_medidos: list[PontoMedido] = []
    correntes_externas: dict[str, float] = {}
    if args.modo_referencia == "externa":
        correntes_externas = ler_referencia_externa(_caminho_referencia_externa(args), args.resistencia_shunt)
        log.info(f"{len(correntes_externas)} leitura(s) externa(s) lida(s) de '{_caminho_referencia_externa(args)}'.")
    ganho_sonda = analisar_lista_calibracao(args.ganho, 2, "--ganho")[1]
    for caminho in arquivos:
        freq_alvo_hz, referencia = identificacao[caminho]
        if freq_alvo_hz is None:
            log.warning(f"pulando '{caminho.name}' -- não sei a frequência injetada (nem pelo nome, nem por 'ref: f=' nos metadados).")
            continue

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
        if resultado is None:
            continue
        resultado.referencia_gravada = referencia
        if referencia is not None and referencia.freq_hz is not None \
                and abs(resultado.freq_medida_hz / referencia.freq_hz - 1.0) > FREQ_DIVERGENTE_FRACAO:
            log.warning(f"'{caminho.name}': o gerador estava em {referencia.freq_hz:g} Hz (metadados), mas a captura mede "
                        f"{resultado.freq_medida_hz:.1f} Hz ({(resultado.freq_medida_hz / referencia.freq_hz - 1) * 100:+.1f}%) "
                        f"-- confira o metadado e o ajuste do gerador.")

        if args.modo_referencia == "externa":
            corrente_rms = correntes_externas.get(caminho.name)
            if corrente_rms is None:
                log.warning(
                    f"pulando '{caminho.name}' -- sem leitura do instrumento externo em "
                    f"'{_caminho_referencia_externa(args).name}'. Anote o valor (ou refaça o ponto com "
                    f"'calibrar_sonda.sh --ref-externa --modo refazer')."
                )
                continue
            resultado.referencia_pico = math.sqrt(2.0) * corrente_rms  # RMS -> pico (tom senoidal)
        elif args.modo_referencia == "amplitude":
            resultado.referencia_pico = _pico_amplitude_conhecida(args, resultado, ganho_sonda)
            if resultado.referencia_pico is None:
                log.warning(f"pulando '{caminho.name}' -- sem amplitude conhecida: a captura não traz 'ref: amp=...' "
                            f"nos metadados e não há --amplitude-referencia.")
                continue
        elif args.modo_referencia == "osciloscopio":
            resultado.referencia_pico = _pico_osciloscopio(args, resultado, ganho_sonda)
            if resultado.referencia_pico is None:
                continue
        pontos_medidos.append(resultado)
    return pontos_medidos


def _resumir_referencia(args: argparse.Namespace, pontos: list[PontoMedido]) -> dict | None:
    """Bloco ``calibracao_adc.referencia`` do JSON: de onde veio a grandeza injetada (rastreabilidade)."""
    if args.modo_referencia == "osciloscopio":
        return {"origem": "osciloscopio", "escala": args.osc_escala, "unidade": args.osc_unidade}
    if args.modo_referencia != "amplitude":
        return None
    if args.amplitude_constante is not None:
        return {"origem": "constante", "amplitudes": [args.amplitude_constante.texto]}
    textos = sorted({p.referencia_gravada.amplitude.texto for p in pontos
                     if p.referencia_gravada is not None and p.referencia_gravada.amplitude is not None})
    return {"origem": "metadados", "amplitudes": textos}


def _resumir_faixas(pontos: list[PontoMedido]) -> dict:
    """``--faixa`` por papel que as capturas realmente usaram, para o bloco ``calibracao_adc`` do JSON.

    Com ``ler_adc --faixa-adc`` (cabeçalho v3) cada captura traz a faixa real do ADC e as capturas de um
    mesmo perfil PODEM diferir entre si (ex.: um tom fraco medido numa faixa menor) -- não é erro, porque
    cada uma foi convertida em Volts reais. O JSON registra a faixa da primeira captura e só marca a faixa
    como confiável se TODAS vieram do cabeçalho."""
    resumo: dict = {}
    for papel, campo, indice in (("referencia", "faixa_referencia", 0), ("sonda", "faixa_sonda", 1)):
        usadas = [getattr(p, campo) for p in pontos if getattr(p, campo) is not None]
        resumo[papel] = usadas[0] if usadas else FAIXA_LEGADA_V
        resumo[f"{papel}_confiavel"] = bool(usadas) and all(p.faixas_confiaveis[indice] for p in pontos
                                                            if getattr(p, campo) is not None)
        distintas = sorted(set(usadas))
        if len(distintas) > 1:
            log.info(f"as capturas usaram {len(distintas)} faixas de ADC diferentes no canal de {papel} "
                     f"({', '.join(f'{v:g} V' for v in distintas)}) -- ok quando vêm do cabeçalho (cada uma foi convertida em Volts reais).")
    return resumo


def _registrar_resumo_resposta(resumo: ResumoResposta | None) -> None:
    """Diz em palavras o que o perfil mostra do conjunto (queda de 3 dB, inclinação, ganho do ruído)."""
    if resumo is None:
        return
    log.info(f"Resposta do conjunto (sonda + frontend + ADC), relativa ao ganho de baixa frequência {resumo.ganho_baixa_frequencia:.4g}:")
    if resumo.freq_menos3db_hz is not None:
        log.info(f"  queda de 3 dB em ~{resumo.freq_menos3db_hz:.0f} Hz")
    else:
        log.info("  o ganho não cai 3 dB dentro da faixa medida")
    if resumo.inclinacao_db_oitava is not None:
        log.info(f"  inclinação final {resumo.inclinacao_db_oitava:.1f} dB/oitava (passa-baixa de 2ª ordem: -12; de 1ª ordem: -6)")
    if resumo.ganho_final_db <= -6.0:
        log.info(f"  em {resumo.freq_final_hz:.0f} Hz o ganho é {resumo.ganho_final_db:.1f} dB: a correção amplifica o sinal "
                 f"(e o ruído junto) {10 ** (-resumo.ganho_final_db / 20):.0f}x nessa frequência")


def executar_geracao(args: argparse.Namespace) -> None:
    """Fluxo completo: capturas -> medição -> agregação -> JSON validado (+ gráfico)."""
    _validar_e_completar_args(args)
    pasta = args.pasta_capturas
    caminho_saida = args.saida or (SONDAS_DIR_PADRAO / f"{args.id}.json")

    arquivos = descobrir_capturas(pasta)
    status_manifesto = ler_status_manifesto(pasta)
    identificacao = {c: identificar_captura(c) for c in arquivos}
    _resolver_modo(args, identificacao)
    log.info(f"{len(arquivos)} arquivo(s) de captura encontrado(s) em '{pasta}'.")
    if args.amplitude_constante is not None:
        log.info(f"referência: amplitude constante {args.amplitude_constante}.")

    pontos_medidos = _medir_capturas(args, arquivos, status_manifesto, identificacao)
    if len(pontos_medidos) < 2:
        raise ErroSHAN(
            f"só {len(pontos_medidos)} ponto(s) processado(s) com sucesso "
            f"-- são necessários pelo menos 2 para um perfil 'resposta_frequencia'. "
            f"Veja os avisos acima para o motivo de cada arquivo pulado."
        )

    pontos_perfil = agregar_por_frequencia(pontos_medidos, args.modo_referencia, args.resistencia_shunt)
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

    resumo = resumir_resposta(pontos_perfil)
    args.referencia_resumo = _resumir_referencia(args, pontos_medidos)
    args.faixas_resumo = _resumir_faixas(pontos_medidos)
    args.resposta_resumo = resumo
    perfil_dict = montar_perfil_json(pontos_perfil, args)
    gravar_perfil_validado(perfil_dict, caminho_saida, len(pontos_perfil))

    for p in sorted(pontos_perfil, key=lambda p: p.freq_hz):
        marcador = f" (desvio {p.desvio_pct:.1f}%, {p.n_amostras} rep.)" if p.n_amostras > 1 else ""
        log.info(f"  {p.freq_hz:10.2f} Hz -> ganho {p.ganho:.4f}{marcador}")
    _registrar_resumo_resposta(resumo)

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
