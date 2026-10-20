"""Linha de comando do ``adc_tool``: definição das flags e ``main()``.

Esta é a BORDA do programa -- o único lugar (junto com ``cli_gerar_perfil``)
que liga o logging ao console, lê ``sys.argv`` e traduz exceções em código de
saída:

* ``ErroUso``  -> ``parser.error`` (mensagem de uso + código 2);
* ``ErroSHAN`` -> ``Erro: <mensagem>`` no stderr + código 1;
* sucesso      -> código 0.

A lógica de cada modo está em ``modos`` (e nas camadas abaixo dele); aqui só
se declara o parser. Para acrescentar uma flag: declare-a em ``montar_parser``,
leia-a em ``modos``/``contexto`` e, se ela for compartilhada com o firmware,
atualize ``constantes`` e o teste de contrato.
"""

import argparse
import logging
import math
from pathlib import Path

from .constantes import (
    CANAL_PADRAO,
    CORTE_SUPRAHARMONICOS_PADRAO,
    DISTANCIA_MINIMA_PICOS_PADRAO,
    JANELA_PADRAO_FFT,
    JANELA_PADRAO_WELCH,
    ORDEM_FILTRO_MAXIMA,
    ORDEM_FILTRO_MINIMA,
    ORDEM_FILTRO_PADRAO,
    RESOLUCAO_WELCH_PADRAO,
    SOBREPOSICAO_WELCH_PADRAO,
    TAMANHO_CHUNK_PADRAO,
)
from .contexto import anunciar_cabecalho, resolver_contexto
from .erros import ErroSHAN, ErroUso
from .modos import executar_conversao, executar_exportacao_hdf5, executar_plotagem
from .registro import configurar_logging_cli

log = logging.getLogger(__name__)


def montar_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="adc_tool.py",
        description=(
            "Ferramenta de linha de comando do SH-Analyzer para dados brutos "
            "do ADS8688. Dois modos: (1) CONVERSÃO (-c/--converter + "
            "-o/--saida), '.bin' <-> '.csv'; (2) PLOTAGEM (padrão), forma de "
            "onda e, opcionalmente, espectro via --fft (ciclo-sincronizado, "
            "ideal para fundamental/harmônicos) e/ou --welch (segmentado e "
            "médio, ideal para supraharmônicos). Suporta 1 ou vários canais "
            "intercalados (grupo 'Captura multi-canal')."
        ),
        epilog=(
            "Exemplos:\n"
            "  # Plotar com FFT ciclo-sincronizada (fundamental/harmônicos)\n"
            "  %(prog)s captura.bin -f 102400 --fft\n"
            "\n"
            "  # Espectro médio (Welch) para conteúdo de banda larga\n"
            "  %(prog)s captura.bin -f 102400 --welch --modo-espectro ruido "
            "--filtro-passa-alta 2000\n"
            "\n"
            "  # Agrupar em bandas de 200 Hz e reportar picos acima de -60 dB\n"
            "  %(prog)s captura.bin -f 102400 --welch --agrupar-bandas 200 "
            "--picos -60\n"
            "\n"
            "  # FFT de alta resolução temporal (só 10 ciclos, distúrbio)\n"
            "  %(prog)s captura.bin -f 102400 --inicio 50000 --fft 10\n"
            "\n"
            "  # Converter .bin -> .csv\n"
            "  %(prog)s -c captura.bin -o captura.csv\n"
            "\n"
            "  # Exportar para HDF5 (canais/frequência do cabeçalho, se houver)\n"
            "  %(prog)s captura.bin --export-hdf5 captura.h5 --incluir-tensao\n"
            "\n"
            "  # Multi-canal: 3 canais, ganho por canal, FFT independente\n"
            "  %(prog)s captura.bin -f 102400 --canais 0,1,3 --ganho "
            "19.53,0.1,1.0 --fft\n"
            "\n"
            "  # Canal 1 = corrente com sonda registrada no cabeçalho (correção\n"
            "  # automática via scripts/sondas/<id>.json); canal 0 = tensão\n"
            "  %(prog)s captura.bin --fft --welch\n"
            "\n"
            "  # Mesma ideia, mas sem cabeçalho / sonda diferente da gravada\n"
            "  %(prog)s captura.bin -f 102400 --canais 0,1 "
            "--grandeza 0:tensao,1:corrente --sonda-perfil 1:sondas/outra_sonda.json --welch\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "arquivo", type=Path, nargs="?", default=None,
        help="[PLOTAGEM] Caminho do arquivo a plotar ('.bin' via memory-map "
             "ou '.csv' com coluna 'valor_bruto'). Obrigatório nesse modo; "
             "não usado com -c/--converter."
    )
    parser.add_argument(
        "-f", "--frequencia", type=float, default=None, metavar="HZ",
        help="[PLOTAGEM/HDF5] Frequência de amostragem TOTAL da captura, em "
             "Hz. Com N canais em --canais, a frequência EFETIVA por canal é "
             "esse valor / N. Sem esta flag: usa a frequência registrada no "
             "cabeçalho do '.bin' (se houver); senão, é obrigatória no modo "
             "de plotagem."
    )

    grupo_multicanal = parser.add_argument_group(
        "Captura multi-canal",
        "Uma captura com mais de 1 canal grava as amostras intercaladas "
        "(round-robin) num único arquivo -- estas flags dizem como "
        "desintercalar. Válidas na plotagem e na conversão '.bin'->'.csv'.",
    )
    grupo_multicanal.add_argument(
        "--canais", type=str, default=None, metavar="LISTA",
        help="Canais no arquivo, separados por vírgula, na ordem impressa "
             "por `ler_adc` durante a captura (ex.: '0,1,3'). Sem esta "
             "flag: usa os canais registrados no cabeçalho do '.bin' "
             f"(se houver); senão, padrão histórico '{CANAL_PADRAO}'."
    )
    grupo_multicanal.add_argument(
        "--canais-exibir", type=str, default=None, metavar="LISTA",
        help="Subconjunto de --canais a efetivamente plotar/analisar "
             "(padrão: todos)."
    )
    grupo_multicanal.add_argument(
        "--layout-canais", choices=["separados", "sobrepostos"], default="separados",
        help="[PLOTAGEM, >1 canal] 'separados' (padrão): 1 subplot por "
             "canal. 'sobrepostos': todos no mesmo eixo, com legenda."
    )

    grupo_sonda = parser.add_argument_group(
        "Grandeza física e correção de sonda",
        "[PLOTAGEM] Corrente atenua de forma diferente em cada frequência "
        "(ao contrário de tensão, que usa só --ganho escalar) -- estas "
        "flags dizem qual grandeza cada canal mede e qual sonda usar para "
        "corrigir isso antes de --fft/--welch/plot (canal de corrente, ou "
        "de tensão com sonda registrada). A correção restaura a AMPLITUDE "
        "por frequência, não a fase. O perfil só vale com o mesmo --ganho/"
        "--formato da sua geração -- e com a mesma --faixa, a menos que "
        "ambos venham da faixa gravada no cabeçalho v3 (conferido, com aviso). Ver "
        "docs/probe-correction-design.md e docs/probe-profile-audit.md.",
    )
    grupo_sonda.add_argument(
        "--grandeza", type=str, default=None, metavar="C:G[,...]",
        help="Grandeza física de cada canal, no formato 'canal:grandeza' "
             "(ex.: '0:tensao,1:corrente'). Valores aceitos: 'tensao' "
             "(padrão), 'corrente', 'temperatura'. Sem esta flag: usa a "
             "grandeza registrada no cabeçalho da captura (se houver, "
             "cabeçalho versão 2+); senão, assume tensão em todo canal "
             "(comportamento histórico)."
    )
    grupo_sonda.add_argument(
        "--sondas-dir", type=Path, default=None, metavar="DIR",
        help="Pasta onde procurar o perfil de uma sonda pelo id gravado no "
             "cabeçalho da captura (arquivo '<id>.json' dentro de DIR; o id "
             "só pode ter letras, dígitos, '_', '-' e '.'). "
             "Padrão: a pasta 'sondas' ao lado deste script "
             "(scripts/sondas/)."
    )
    grupo_sonda.add_argument(
        "--sonda-perfil", type=str, default=None, metavar="C:ARQUIVO[,...]",
        help="Aponta diretamente para o arquivo de perfil (.json) de um "
             "canal, no formato 'canal:arquivo' -- maior prioridade que o "
             "id gravado no cabeçalho + --sondas-dir. Use quando o "
             "cabeçalho não tem sonda registrada (captura antiga, ou sem "
             "cabeçalho) ou para testar um perfil diferente do gravado."
    )
    grupo_sonda.add_argument(
        "--sem-correcao-sonda", action="store_true",
        help="Desliga a correção por frequência (canais de corrente, ou de "
             "tensão com sonda registrada; fica só a calibração --ganho escalar) -- útil para comparar "
             "o espectro corrigido com o bruto, ou depurar um perfil "
             "suspeito."
    )

    grupo_conversao = parser.add_argument_group(
        "Modo de conversão (.bin <-> .csv)",
        "Ativado por -c/--converter; nesse modo 'arquivo' e -f são "
        "ignorados. Direção detectada pelas extensões de -c e -o.",
    )
    grupo_conversao.add_argument(
        "-c", "--converter", type=Path, default=None, metavar="ARQUIVO_ENTRADA",
        help="Ativa o modo de conversão: converte ARQUIVO_ENTRADA para "
             "-o/--saida (obrigatório junto com esta flag)."
    )
    grupo_conversao.add_argument(
        "--incluir-tensao", action="store_true",
        help="Só em '.bin'->'.csv': acrescenta a coluna 'tensao_v' (só "
             "informativa -- ignorada na reconstrução de volta para '.bin')."
    )
    grupo_conversao.add_argument(
        "--tamanho-chunk", type=int, default=TAMANHO_CHUNK_PADRAO, metavar="N",
        help=f"Amostras por bloco na conversão (padrão: {TAMANHO_CHUNK_PADRAO})."
    )

    grupo_hdf5 = parser.add_argument_group(
        "Modo de exportação HDF5",
        "Ativado por --export-hdf5; usa o argumento posicional 'arquivo' "
        "como entrada (um '.bin'). Sempre grava em blocos sobre o memmap -- "
        "nunca carrega a captura inteira na RAM. Ignora --fft/--welch/"
        "--picos/--agrupar-bandas/--canais-exibir (só se aplicam ao modo de "
        "plotagem).",
    )
    grupo_hdf5.add_argument(
        "--export-hdf5", type=Path, default=None, metavar="ARQUIVO.h5",
        dest="export_hdf5",
        help="Converte 'arquivo' ('.bin') para HDF5 em ARQUIVO.h5. Grava "
             "/amostras (códigos brutos do ADC, 2D: amostras_por_canal x "
             "num_canais) e, com --incluir-tensao, também /tensao_v "
             "(calibrado, float32). O cabeçalho da captura (se houver) e os "
             "parâmetros de calibração são gravados como atributos na raiz. "
             "Requer 'h5py' instalado (ou rodar via 'uv run', que já "
             "declara a dependência)."
    )

    grupo_filtro = parser.add_argument_group(
        "Filtragem digital (Butterworth, fase zero)",
        "[PLOTAGEM] Aplicado a cada canal, em Volts, ANTES do recorte em "
        "ciclos inteiros, de --fft/--welch e da plotagem no tempo.",
    )
    grupo_filtro.add_argument(
        "--filtro-passa-baixa", type=float, default=None, metavar="HZ",
        help="Corte (Hz) de um passa-baixa Butterworth de fase zero. "
             "Precisa ser menor que a Nyquist efetiva do canal. Pode ser "
             "combinado com --filtro-passa-alta (passa-alta primeiro)."
    )
    grupo_filtro.add_argument(
        "--filtro-passa-alta", type=float, default=None, metavar="HZ",
        help="Corte (Hz) de um passa-alta Butterworth de fase zero -- útil "
             "para remover deriva de DC/nível, ou o resíduo da fundamental "
             "antes de --welch/--picos na faixa de supraharmônicos."
    )
    grupo_filtro.add_argument(
        "--ordem-filtro", type=int, default=ORDEM_FILTRO_PADRAO,
        choices=range(ORDEM_FILTRO_MINIMA, ORDEM_FILTRO_MAXIMA + 1),
        metavar=f"[{ORDEM_FILTRO_MINIMA}-{ORDEM_FILTRO_MAXIMA}]",
        help=f"Ordem do(s) filtro(s) acima (padrão: {ORDEM_FILTRO_PADRAO}). "
             f"Implementado em SOS para permanecer estável nas ordens mais altas."
    )

    parser.add_argument(
        "-o", "--saida", "--salvar", dest="saida", type=Path, default=None, metavar="ARQUIVO",
        help="[CONVERSÃO] arquivo de saída ('.csv' ou '.bin', obrigatório "
             "com -c). [PLOTAGEM] caminho de imagem para salvar o gráfico "
             "em vez de abrir a janela interativa (opcional)."
    )
    parser.add_argument(
        "--sem-grafico", action="store_true",
        help="[PLOTAGEM] Só os números (console e exportações), sem gráfico e sem carregar o matplotlib: para "
             "análise em lote, por SSH ou num servidor. Sem tela e sem -o, o gráfico é pulado sozinho (com aviso)."
    )
    parser.add_argument(
        "--inicio", type=int, default=0, metavar="N",
        help="Primeira amostra a usar, 0-based (padrão: 0)."
    )
    parser.add_argument(
        "--fim", type=int, default=None, metavar="N",
        help="Última amostra (exclusive) a usar (padrão: até o fim do arquivo)."
    )
    parser.add_argument(
        "--fft", nargs="?", type=int, const=0, default=None, metavar="N_CICLOS",
        help="[PLOTAGEM] Espectro por FFT única, sincronizada em ciclos "
             "inteiros da fundamental -- ideal para a fundamental e "
             "harmônicos de baixa ordem. Sem número: todos os ciclos "
             "completos da janela. Com N: só os N primeiros (distúrbios "
             "momentâneos). Pode ser combinado com --welch."
    )
    parser.add_argument(
        "--freq-min", type=float, default=45.0, metavar="HZ",
        help="[--fft] Limite inferior de busca da fundamental (padrão: 45)."
    )
    parser.add_argument(
        "--freq-max", type=float, default=65.0, metavar="HZ",
        help="[--fft] Limite superior de busca da fundamental (padrão: 65)."
    )
    parser.add_argument(
        "--janela", type=str, default=None, metavar="NOME",
        help=f"[--fft/--welch] Janela espectral. Padrão: '{JANELA_PADRAO_FFT}' na --fft (sincronizada em ciclos "
             f"inteiros, não vaza para a fundamental e os harmônicos, como na IEC 61000-4-7) e '{JANELA_PADRAO_WELCH}' "
             "no --welch (o segmento não é síncrono com nada). Dada, vale para os dois. Opções: 'retangular'/'boxcar', "
             "'hann'/'hanning', "
             "'blackmanharris'/'blackman-harris' (lóbulos laterais muito "
             "baixos, útil para separar um supraharmônico fraco perto de "
             "uma fundamental forte), 'flattop'/'flat-top' (melhor exatidão "
             "de amplitude, pior resolução), 'kaiser' (+ --kaiser-beta)."
    )
    parser.add_argument(
        "--kaiser-beta", type=float, default=8.6, metavar="BETA",
        help="[--janela kaiser] beta≈5 ~ Hamming, beta≈6 ~ Hann, beta≈8.6 ~ "
             "Blackman (padrão), beta≈14: lóbulos laterais muitíssimo baixos."
    )

    grupo_espectro = parser.add_argument_group(
        "Análise espectral avançada (Welch, bandas, picos)",
        "Complementa --fft (sincronizado no ciclo da fundamental) com um "
        "caminho pensado para supraharmônicos: ruído de conversores "
        "chaveados não tem relação de fase com o ciclo da rede, então --fft "
        "não elimina o vazamento desse conteúdo por corte de ciclo -- "
        "--welch ataca o problema por segmentação + média (Welch), em vez "
        "de sincronismo de ciclo.",
    )
    grupo_espectro.add_argument(
        "--welch", action="store_true",
        help="[PLOTAGEM] Espectro médio por segmentação: o sinal é dividido "
             "em blocos de --resolucao-welch Hz de resolução, cada um "
             "janelado e transformado, e os periodogramas resultantes são "
             "MEDIADOS -- reduz variância e é robusto a ruído de banda "
             "larga e deriva de frequência de chaveamento (dithering), ao "
             "custo de resolução fixa em frequência. Pode ser combinado com "
             "--fft (cada um plota sua própria curva)."
    )
    grupo_espectro.add_argument(
        "--resolucao-welch", type=float, default=RESOLUCAO_WELCH_PADRAO, metavar="HZ",
        help=f"[--welch] Resolução de cada segmento em Hz -- define o "
             f"tamanho do segmento como fs_efetiva/HZ amostras (padrão: "
             f"{RESOLUCAO_WELCH_PADRAO:g}). Menor = mais segmentos médios "
             f"(menos variância), resolução mais grossa."
    )
    grupo_espectro.add_argument(
        "--sobreposicao-welch", type=float, default=SOBREPOSICAO_WELCH_PADRAO, metavar="FRACAO",
        help=f"[--welch] Fração de sobreposição entre segmentos, em [0, 1) "
             f"(padrão: {SOBREPOSICAO_WELCH_PADRAO:g})."
    )
    grupo_espectro.add_argument(
        "--modo-espectro", choices=["tom", "ruido"], default="tom",
        help="Normalização usada por --fft e --welch: 'tom' (padrão) "
             "reporta amplitude corrigida pelo ganho coerente da janela -- "
             "correta para um tom discreto. 'ruido' reporta densidade "
             "espectral de potência (PSD, V²/Hz), normalizada pelo ganho "
             "incoerente/ENBW -- correta para conteúdo de banda larga, onde "
             "'tom' mudaria artificialmente com o tamanho da FFT/segmento "
             "para o mesmo ruído físico."
    )
    grupo_espectro.add_argument(
        "--agrupar-bandas", type=float, default=None, metavar="HZ",
        help="Agrupa o(s) espectro(s) em bandas de largura HZ (ex.: 200), "
             "reportando o nível RMS de cada banda em vez do valor bin a "
             "bin -- convenção da literatura de supraharmônicos, torna o "
             "resultado comparável entre capturas com resoluções "
             "diferentes. Sem esta flag, mostra o espectro fino. Requer "
             "--fft e/ou --welch."
    )
    grupo_espectro.add_argument(
        "--picos", type=float, default=None, metavar="LIMIAR_DB",
        help="Reporta no console os picos espectrais (frequência e "
             "amplitude, refinados por interpolação parabólica) acima de "
             "LIMIAR_DB dentro de [--freq-min-picos, --freq-max-picos] -- "
             "extração quantitativa de componentes supraharmônicas "
             "individuais. Requer --fft e/ou --welch; usa o espectro FINO "
             "(antes de --agrupar-bandas)."
    )
    grupo_espectro.add_argument(
        "--freq-min-picos", type=float, default=CORTE_SUPRAHARMONICOS_PADRAO, metavar="HZ",
        help=f"[--picos] Limite inferior da busca (padrão: "
             f"{CORTE_SUPRAHARMONICOS_PADRAO:g} Hz -- início convencional "
             f"da faixa de supraharmônicos, IEC 61000-4-7). Independente de "
             f"--freq-min/--freq-max, que buscam a fundamental."
    )
    grupo_espectro.add_argument(
        "--freq-max-picos", type=float, default=None, metavar="HZ",
        help="[--picos] Limite superior da busca (padrão: Nyquist efetiva)."
    )
    grupo_espectro.add_argument(
        "--distancia-minima-picos", type=float, default=DISTANCIA_MINIMA_PICOS_PADRAO, metavar="HZ",
        help=f"[--picos] Distância mínima entre dois picos reportados, para "
             f"não contar o mesmo lóbulo várias vezes (padrão: "
             f"{DISTANCIA_MINIMA_PICOS_PADRAO:g} Hz)."
    )

    grupo_pesquisa = parser.add_argument_group(
        "Análise para pesquisa e exportação",
        "Ferramentas de análise de qualidade de energia e de supraharmônicos, e a exportação de todo resultado com os "
        "parâmetros que o produziram (para reproduzir, publicar ou continuar no MATLAB/Python). Todas trabalham sobre o "
        "sinal já calibrado, corrigido pela sonda e filtrado, como o resto da análise.",
    )
    grupo_pesquisa.add_argument(
        "--harmonicos", type=int, default=None, metavar="N",
        help="[--fft] Tabela dos harmônicos 1..N: frequência, valor RMS da componente e do grupo harmônico "
             "(IEC 61000-4-7), %% da fundamental e fase relativa à fundamental (referencial seno), mais THD e THDG. "
             "Usa o trecho sincronizado em ciclos inteiros da --fft (sem vazamento entre harmônicos)."
    )
    grupo_pesquisa.add_argument(
        "--bandas-iec", action="store_true",
        help="Bandas de supraharmônicos pelo método da IEC 61000-4-7, anexo B (e IEC 61000-4-30, anexo C): janelas "
             "de 200 ms sem lacunas, bins de 5 Hz, bandas de 200 Hz centradas em 2100, 2300... Hz. Para cada banda, "
             "a série no tempo e as estatísticas: RMS das janelas, máximo, percentil 95 (CP95) e mínimo."
    )
    grupo_pesquisa.add_argument(
        "--bandas-iec-min", type=float, default=2000.0, metavar="HZ",
        help="[--bandas-iec] Início da primeira banda (padrão: 2000 Hz, a primeira centrada em 2100 Hz)."
    )
    grupo_pesquisa.add_argument(
        "--bandas-iec-max", type=float, default=None, metavar="HZ",
        help="[--bandas-iec] Fim da última banda (padrão: a Nyquist do canal; a norma de 2 a 9 kHz para em 9000)."
    )
    grupo_pesquisa.add_argument(
        "--espectrograma", action="store_true",
        help="Espectro ao longo do tempo (STFT), com os segmentos do Welch (--resolucao-welch, --sobreposicao-welch, "
             "janela Hann por padrão) reunidos em até 600 colunas: mostra quando cada supraharmônico aparece, "
             "some ou muda de frequência. Figura à parte (com -o: <saida>_espectrograma.png)."
    )
    grupo_pesquisa.add_argument(
        "--exportar", type=Path, default=None, metavar="PREFIXO",
        help="Grava os resultados em CSV (um arquivo por resultado e por canal: PREFIXO_canal1_welch.csv, "
             "..._harmonicos.csv, ..._bandas_iec.csv, ..._espectrograma.csv, PREFIXO_picos.csv) e os metadados em "
             "PREFIXO_metadados.json: captura, calibração de cada canal, janela, resolução, ENBW, filtros, correção de "
             "sonda, versões e o comando exato."
    )
    grupo_pesquisa.add_argument(
        "--exportar-mat", type=Path, default=None, metavar="ARQUIVO.mat",
        help="Os mesmos resultados numa estrutura 'sh' do MATLAB/Octave (load('ARQUIVO.mat'); sh.canal1.welch.f, "
             "sh.canal1.harmonicos.thd_pct, sh.metadados...)."
    )

    parser.add_argument(
        "--formato", choices=["int16", "uint16"], default="uint16",
        help="Como interpretar o código de 16 bits do ADC: 'uint16' (padrão; binário deslocado, o que o "
             "ADS8688 entrega: 0 = -fundo de escala, 32768 = 0 V) ou 'int16' (complemento de dois)."
    )
    parser.add_argument(
        "--faixa", type=str, default=None, metavar="VOLTS",
        help="Fundo de escala TOTAL do ADC em Volts (±10.24 V = 20.48; ±5.12 V = 10.24; ±2.56 V = 5.12, "
             "com --formato uint16). Um valor único (todos os canais) ou lista por canal, na "
             "ordem de --canais. Padrão: a faixa que o firmware gravou no cabeçalho da captura "
             "(ler_adc --faixa-adc, cabeçalho v3), canal a canal; capturas mais antigas (v1/v2), "
             "que não registram a faixa, usam a de reset do ADC, 20.48 (±10,24 V)."
    )
    parser.add_argument(
        "--ganho", type=str, default="1.0", metavar="FATOR",
        help="Ganho do sensor/PCB (padrão: 1.0). Um valor ou lista por canal."
    )
    parser.add_argument(
        "--offset", type=str, default=None, metavar="VOLTS",
        help="Deslocamento DC subtraído antes do ganho (padrão automático: "
             "faixa/2 para uint16, 0.0 para int16, por canal). Um valor ou "
             "lista por canal."
    )

    return parser


def _validar_flags_numericas(args: argparse.Namespace) -> None:
    """Valores que o argparse aceita mas que derrubariam o programa com um traceback lá na frente
    (divisão por zero, ``range`` com passo 0) ou dariam lixo em silêncio (NaN)."""
    if args.frequencia is not None and not (math.isfinite(args.frequencia) and args.frequencia > 0):
        raise ErroUso("-f/--frequencia precisa ser um número positivo (Hz).")
    if args.tamanho_chunk < 1:
        raise ErroUso("--tamanho-chunk precisa ser >= 1.")
    if args.distancia_minima_picos <= 0:
        raise ErroUso("--distancia-minima-picos precisa ser positiva.")


def main(argv: list[str] | None = None) -> int:
    """Ponto de entrada do ``adc_tool``. Devolve o código de saída do processo."""
    parser = montar_parser()
    args = parser.parse_args(argv)
    configurar_logging_cli()

    try:
        if args.export_hdf5 is not None and args.converter is not None:
            raise ErroUso("--export-hdf5 e -c/--converter não podem ser usados juntos -- escolha um modo.")
        _validar_flags_numericas(args)

        ctx = resolver_contexto(args)
        anunciar_cabecalho(ctx, args.formato)

        if args.export_hdf5 is not None:
            executar_exportacao_hdf5(args, ctx)
        elif args.converter is not None:
            executar_conversao(args, ctx)
        else:
            executar_plotagem(args, ctx)
    except ErroUso as e:
        parser.error(str(e))  # imprime o uso + a mensagem e sai com código 2
    except ErroSHAN as e:
        log.error(str(e))
        return 1
    return 0
