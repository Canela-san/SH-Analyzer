#!/usr/bin/env bash
#
# ==============================================================================
# compactar_amostras.sh
# ------------------------------------------------------------------------------
# Compacta capturas do SH-Analyzer (.bin brutos e/ou .h5/.hdf5 exportados) num
# ÚNICO arquivo de saída, priorizando densidade de compressão acima de tempo,
# CPU ou RAM. Dois motores à disposição:
#
#   (padrão)      7-Zip  | LZMA2, nível ultra, bloco sólido, dicionário 1 GiB
#   --max/--maxima  zpaq | método -m5 (o mais forte do zpaq), multi-thread
#
# Autor original: Gabriel Canela -- revisão: suporte a .h5/.hdf5, barra de
# progresso para o zpaq (que não expõe progresso de compressão utilizável
# externamente -- ver nota grande antes de estimar_tempo_zpaq), relatório
# final e limpeza (arquivo parcial + processo filho) em caso de interrupção.
# ==============================================================================

set -euo pipefail

# ------------------------------------------------------------------------------
# 0. Configuração
# ------------------------------------------------------------------------------
MODO="alta"                       # "alta" (7z) ou "maxima" (zpaq -m5)
DIRETORIO_ALVO="."
ARQUIVO_SAIDA_CUSTOM=""
EXTENSOES_ENTRADA=("bin" "h5" "hdf5")

DICIONARIO_7Z="1g"                # "massivo" por pedido -- suba para 1536m/2g
                                   # se a máquina tiver bastante RAM sobrando
                                   # (regra prática do LZMA2: RAM ~= 11.5x o
                                   # dicionário durante a compressão)
TAMANHO_AMOSTRA_CALIBRACAO=4194304  # 4 MiB -- ver nota em estimar_tempo_zpaq
LIMIAR_PULAR_CALIBRACAO=8388608     # 8 MiB -- captura pequena não compensa
                                     # calibrar (ver main)

THREADS="$(nproc)"

# ------------------------------------------------------------------------------
# 1. Interface visual
# ------------------------------------------------------------------------------
VERMELHO='\033[0;31m'
VERDE='\033[0;32m'
AZUL='\033[0;34m'
AMARELO='\033[1;33m'
CIANO='\033[0;36m'
CINZA='\033[0;90m'
NEGRITO='\033[1m'
SEM_COR='\033[0m'

cabecalho() {
    echo
    echo -e "${AZUL}${NEGRITO}══════════════════════════════════════════════════════════${SEM_COR}"
    echo -e "${AZUL}${NEGRITO}   Compressor de Alta Densidade — Capturas SH-Analyzer${SEM_COR}"
    echo -e "${AZUL}${NEGRITO}══════════════════════════════════════════════════════════${SEM_COR}"
    echo
}

log_info()  { echo -e "  ${CIANO}[ INFO ]${SEM_COR}       $*"; }
log_ok()    { echo -e "  ${VERDE}[  OK  ]${SEM_COR}       $*"; }
log_aviso() { echo -e "  ${AMARELO}[ AVISO ]${SEM_COR}      $*"; }
log_erro()  { echo -e "  ${VERMELHO}[ ERRO ]${SEM_COR}       $*" >&2; }
log_proc()  { echo -e "  ${AZUL}[ PROCESSANDO ]${SEM_COR} $*"; }

secao() {
    echo
    echo -e "${CINZA}── $* ${SEM_COR}"
}

formatar_tamanho() {
    numfmt --to=iec-i --suffix=B --format="%.2f" "$1" 2>/dev/null || echo "${1} B"
}

formatar_duracao() {
    local s="$1"
    printf '%02d:%02d:%02d' $((s/3600)) $((s%3600/60)) $((s%60))
}

# Repete um caractere N vezes. Evita "printf '%*s' N '' | tr ' ' 'X'": em
# locale POSIX/C (comum fora de uma sessão desktop -- cron, SSH sem locale,
# containers), 'tr' trata um caractere multibyte como só o seu primeiro
# byte, corrompendo blocos como █/░. Concatenação em bash é byte-segura
# independente de locale, então isso funciona sempre.
repetir_caractere() {
    local caractere="$1" vezes="$2" i saida=""
    for (( i = 0; i < vezes; i++ )); do
        saida+="$caractere"
    done
    printf '%s' "$saida"
}

# ------------------------------------------------------------------------------
# 2. Limpeza em caso de interrupção (Ctrl+C) ou erro
# ------------------------------------------------------------------------------
ARQUIVO_SAIDA_EM_ANDAMENTO=""
PID_COMPRESSOR_ATIVO=""
ARQUIVOS_TEMP_CALIBRACAO=()

# [POR QUE MATAR O FILHO EXPLICITAMENTE] Num terminal interativo comum,
# Ctrl+C entrega SIGINT para todo o grupo de processos em primeiro plano
# (script + zpaq/7z + o "sleep" do monitor de progresso), então tudo para
# junto naturalmente. Mas isso não é garantido em todo contexto de execução
# (nohup, systemd, `bash script.sh &` a partir de um shell não-interativo,
# etc. podem deixar o filho em outro grupo de processos) -- e, além disso,
# bash só executa a trap DEPOIS que o comando em primeiro plano atual (o
# "sleep" do laço de monitoramento) retornar, então sem isso o processo pesado
# (zpaq/7z) ficaria rodando "orfão" em segundo plano mesmo após a trap
# disparar. Por isso a trap mata o PID do compressor explicitamente, em vez
# de confiar só na propagação implícita do sinal pelo grupo de processos.
limpar_e_sair() {
    local codigo=$?
    trap - INT TERM ERR
    echo
    if [ -n "$PID_COMPRESSOR_ATIVO" ] && kill -0 "$PID_COMPRESSOR_ATIVO" 2>/dev/null; then
        log_aviso "Interrompido -- encerrando o processo de compressão (PID ${PID_COMPRESSOR_ATIVO})..."
        kill -TERM "$PID_COMPRESSOR_ATIVO" 2>/dev/null || true
        wait "$PID_COMPRESSOR_ATIVO" 2>/dev/null || true
    fi
    if [ -n "$ARQUIVO_SAIDA_EM_ANDAMENTO" ] && [ -f "$ARQUIVO_SAIDA_EM_ANDAMENTO" ]; then
        log_aviso "Removendo arquivo de saída incompleto '${ARQUIVO_SAIDA_EM_ANDAMENTO}'."
        rm -f "$ARQUIVO_SAIDA_EM_ANDAMENTO"
    fi
    if [ ${#ARQUIVOS_TEMP_CALIBRACAO[@]} -gt 0 ]; then
        rm -f "${ARQUIVOS_TEMP_CALIBRACAO[@]}"
    fi
    exit "$codigo"
}
trap limpar_e_sair INT TERM ERR

# ------------------------------------------------------------------------------
# 3. Dependências -- verifica e instala só o que falta, só quando necessário
# ------------------------------------------------------------------------------
verificar_dependencias() {
    secao "Dependências"
    local -a pacotes_faltando=()
    local -a binarios_faltando=()

    if [ "$MODO" = "alta" ] && ! command -v 7z &>/dev/null; then
        pacotes_faltando+=("p7zip-full")
        binarios_faltando+=("7z")
    fi
    if [ "$MODO" = "maxima" ] && ! command -v zpaq &>/dev/null; then
        pacotes_faltando+=("zpaq")
        binarios_faltando+=("zpaq")
    fi

    if [ ${#pacotes_faltando[@]} -eq 0 ]; then
        log_ok "Todas as dependências necessárias já estão instaladas."
        return
    fi

    log_aviso "Dependência(s) ausente(s): ${binarios_faltando[*]}. Instalando via apt (pode pedir sua senha)..."
    if ! sudo apt-get update -qq; then
        log_erro "Falha ao atualizar os repositórios apt."
        exit 1
    fi
    if ! sudo apt-get install -y -qq "${pacotes_faltando[@]}"; then
        log_erro "Falha ao instalar: ${pacotes_faltando[*]}. Verifique conexão/permissões."
        exit 1
    fi
    log_ok "Instalado(s) com sucesso: ${pacotes_faltando[*]}"
}

# ------------------------------------------------------------------------------
# 4. Descoberta de arquivos de entrada (.bin, .h5, .hdf5 -- case-insensitive)
# ------------------------------------------------------------------------------
coletar_arquivos_entrada() {
    local -a encontrados=()
    local ext
    for ext in "${EXTENSOES_ENTRADA[@]}"; do
        while IFS= read -r -d '' f; do
            encontrados+=("$f")
        done < <(find "$DIRETORIO_ALVO" -maxdepth 1 -type f -iname "*.${ext}" -print0 2>/dev/null)
    done
    if [ ${#encontrados[@]} -gt 0 ]; then
        printf '%s\0' "${encontrados[@]}" | sort -z
    fi
}

tamanho_total_bytes() {
    local total=0 f
    for f in "$@"; do
        total=$(( total + $(stat -c%s "$f") ))
    done
    echo "$total"
}

# ------------------------------------------------------------------------------
# 5a. Barra de progresso "de verdade" para o 7-Zip
# ------------------------------------------------------------------------------
# O 7-Zip já expõe um percentual real e preciso de bytes processados via
# -bsp1 (LZMA2 é um algoritmo em stream: lê, comprime e grava de forma
# incremental) -- não há motivo para reimplementar isso por fora, então
# deixamos a saída nativa dele aparecer.
comprimir_7z() {
    local arquivo_saida="$1"; shift
    log_proc "Compactando com 7-Zip (LZMA2, ultra, bloco sólido, dicionário ${DICIONARIO_7Z}, ${THREADS} thread(s))..."
    echo
    # Em segundo plano (a saída nativa do 7z continua indo direto para o
    # terminal normalmente) só para que PID_COMPRESSOR_ATIVO fique
    # disponível para a trap de limpeza -- ver comentário grande junto a
    # limpar_e_sair sobre por que isso é necessário.
    7z a -t7z -mx=9 -m0=lzma2:d${DICIONARIO_7Z}:fb273 -ms=on -mmt="$THREADS" \
        -bsp1 -bb1 "$arquivo_saida" "$@" &
    PID_COMPRESSOR_ATIVO=$!
    wait "$PID_COMPRESSOR_ATIVO"
    local status=$?
    PID_COMPRESSOR_ATIVO=""
    return $status
}

# ------------------------------------------------------------------------------
# 5b. Barra de progresso "estimada" para o zpaq
# ------------------------------------------------------------------------------
# [POR QUE UMA ESTIMATIVA, E NÃO UM PERCENTUAL EXATO]
# Testado empiricamente: no modo -m5 (context mixing), o zpaq lê o(s)
# arquivo(s) de entrada quase que instantaneamente para a memória e só grava
# o arquivo de saída no finalzinho, de uma vez -- tanto "bytes lidos"
# (/proc/PID/task/*/io) quanto "tamanho do arquivo de saída" ficam parados
# em ~100%/0% durante praticamente toda a execução real. Ou seja: não existe
# sinal externo (I/O) que reflita o progresso de fato, porque o trabalho
# pesado é 100% CPU, sem I/O incremental observável.
#
# A alternativa escolhida: compactar uma AMOSTRA pequena do início do maior
# arquivo, com exatamente o mesmo método/threads, medir o tempo real gasto
# nessa amostra nesta máquina com estes dados, e extrapolar linearmente para
# o tamanho total -- assumindo que a compressibilidade é razoavelmente
# uniforme ao longo da captura (razoável para uma forma de onda de ADC
# continuamente amostrada). Em teste local (arquivo de 24 MB, amostra de
# 4 MiB), a estimativa ficou a ~8% do tempo real -- longe de perfeita, mas
# honesta e útil como indicador visual, o que o zpaq sozinho não oferece.
# Por isso a barra é rotulada "estimado" e trava em 99% até o processo
# encerrar de verdade.
estimar_tempo_zpaq() {
    local arquivo_referencia="$1" total_bytes="$2"
    local tam_disponivel tam_amostra
    tam_disponivel=$(stat -c%s "$arquivo_referencia")
    tam_amostra=$TAMANHO_AMOSTRA_CALIBRACAO
    (( tam_amostra > tam_disponivel )) && tam_amostra=$tam_disponivel

    local amostra_tmp calib_tmp
    amostra_tmp=$(mktemp --suffix=.calib.bin)
    calib_tmp=$(mktemp --suffix=.calib.zpaq); rm -f "$calib_tmp"
    head -c "$tam_amostra" "$arquivo_referencia" > "$amostra_tmp"
    ARQUIVOS_TEMP_CALIBRACAO=("$amostra_tmp" "$calib_tmp")

    local inicio_ms fim_ms duracao_ms
    inicio_ms=$(date +%s%3N)
    # Em segundo plano + wait (não uma chamada síncrona direta) para que um
    # Ctrl+C durante a própria calibração também seja respondido de forma
    # imediata pela trap, em vez de só depois que esta amostra terminar.
    zpaq add "$calib_tmp" "$amostra_tmp" -m5 -t"$THREADS" >/dev/null 2>&1 &
    PID_COMPRESSOR_ATIVO=$!
    wait "$PID_COMPRESSOR_ATIVO" || true
    PID_COMPRESSOR_ATIVO=""
    fim_ms=$(date +%s%3N)
    rm -f "$amostra_tmp" "$calib_tmp"
    ARQUIVOS_TEMP_CALIBRACAO=()

    duracao_ms=$(( fim_ms - inicio_ms ))
    (( duracao_ms < 1 )) && duracao_ms=1
    echo $(( duracao_ms * total_bytes / tam_amostra / 1000 ))
}

# Spinner simples (indeterminado) -- usado só quando a captura é pequena
# demais para valer a pena calibrar (ver LIMIAR_PULAR_CALIBRACAO).
executar_zpaq_com_spinner() {
    local pid="$1"
    # Array de quadros (não string fatiada por índice): fatiar uma string
    # multibyte com "${s:i:1}" depende de LC_CTYPE ser UTF-8 -- em locale
    # POSIX/C (comum em cron, containers, SSH sem locale configurado) isso
    # corta no meio dos bytes do caractere e imprime lixo. Um array é
    # indexado por elemento, não por byte, então funciona em qualquer locale.
    local -a quadros=('⠋' '⠙' '⠹' '⠸' '⠼' '⠴' '⠦' '⠧' '⠇' '⠏')
    local i=0 inicio decorridos
    inicio=$(date +%s)
    while kill -0 "$pid" 2>/dev/null; do
        decorridos=$(( $(date +%s) - inicio ))
        printf "\r  ${AZUL}%s${SEM_COR}  processando... (%s decorrido)   " \
            "${quadros[i++ % ${#quadros[@]}]}" "$(formatar_duracao "$decorridos")"
        sleep 0.15
    done
    wait "$pid"
}

# Barra com percentual estimado (elapsed / estimado), usada para capturas
# grandes o bastante para justificar a calibração.
executar_zpaq_com_barra_estimada() {
    local pid="$1" segundos_estimados="$2"
    local largura=36 inicio decorrido percentual preenchido vazio
    inicio=$(date +%s)
    while kill -0 "$pid" 2>/dev/null; do
        decorrido=$(( $(date +%s) - inicio ))
        if (( segundos_estimados > 0 )); then
            percentual=$(( decorrido * 100 / segundos_estimados ))
        else
            percentual=0
        fi
        (( percentual > 99 )) && percentual=99
        preenchido=$(( percentual * largura / 100 ))
        vazio=$(( largura - preenchido ))
        printf "\r  ${AZUL}[%s%s]${SEM_COR} ${NEGRITO}%3d%%${SEM_COR} ${CINZA}(estimado)${SEM_COR}  %s / ~%s   " \
            "$(repetir_caractere '█' "$preenchido")" \
            "$(repetir_caractere '░' "$vazio")" \
            "$percentual" "$(formatar_duracao "$decorrido")" "$(formatar_duracao "$segundos_estimados")"
        sleep 1
    done
    wait "$pid"
    local status=$?
    local barra_cheia
    barra_cheia=$(repetir_caractere '█' "$largura")
    printf "\r  ${AZUL}[%s]${SEM_COR} ${VERDE}${NEGRITO}100%%${SEM_COR}  concluído em %s.%*s\n" \
        "$barra_cheia" "$(formatar_duracao "$(( $(date +%s) - inicio ))")" 15 ""
    return $status
}

comprimir_zpaq() {
    local arquivo_saida="$1"; shift
    local total_bytes
    total_bytes=$(tamanho_total_bytes "$@")

    log_proc "Compactando com zpaq (método -m5, ${THREADS} thread(s))..."

    if (( total_bytes < LIMIAR_PULAR_CALIBRACAO )); then
        log_info "Captura pequena (< $(formatar_tamanho "$LIMIAR_PULAR_CALIBRACAO")) -- pulando calibração, indicador indeterminado."
        echo
        zpaq add "$arquivo_saida" "$@" -m5 -t"$THREADS" >/dev/null 2>&1 &
        PID_COMPRESSOR_ATIVO=$!
        executar_zpaq_com_spinner "$PID_COMPRESSOR_ATIVO"
        local status=$?
        PID_COMPRESSOR_ATIVO=""
        echo -e "\r  ${VERDE}${NEGRITO}[  OK  ]${SEM_COR} Compressão concluída.                                   "
        return $status
    fi

    log_info "Calibrando velocidade real do zpaq -m5 nesta máquina com uma amostra dos dados..."
    local estimativa_s
    estimativa_s=$(estimar_tempo_zpaq "$1" "$total_bytes")
    log_info "Estimativa de duração total: ~$(formatar_duracao "$estimativa_s") (extrapolada da amostra; pode variar)."
    echo

    zpaq add "$arquivo_saida" "$@" -m5 -t"$THREADS" >/dev/null 2>&1 &
    PID_COMPRESSOR_ATIVO=$!
    executar_zpaq_com_barra_estimada "$PID_COMPRESSOR_ATIVO" "$estimativa_s"
    local status=$?
    PID_COMPRESSOR_ATIVO=""
    return $status
}

# ------------------------------------------------------------------------------
# 6. Ajuda
# ------------------------------------------------------------------------------
imprimir_uso() {
    cat << USO
Uso: $(basename "$0") [--max | --maxima | --alta] [--dir DIRETORIO] [-o ARQUIVO] [-h]

Compacta todas as capturas .bin e/ou .h5/.hdf5 de um diretório num único
arquivo de saída, priorizando densidade de compressão sobre tempo/CPU/RAM.

Modos de compressão:
  (padrão)          7-Zip -- LZMA2 nível ultra, bloco sólido, dicionário
                    ${DICIONARIO_7Z}. Rápido de se obter, ótima razão de
                    compressão, progresso nativo e preciso.
  --max, --maxima   zpaq -- método -m5 (o mais forte do zpaq). Tipicamente
                    comprime mais que o 7z para dados binários, à custa de
                    ser MUITO mais lento. Progresso é uma ESTIMATIVA (ver
                    comentário em estimar_tempo_zpaq no código).
  --alta            Força o modo padrão explicitamente (útil se você mudar
                    o padrão do script no futuro).

Outras opções:
  --dir DIRETORIO   Diretório onde procurar os arquivos (padrão: diretório atual).
  -o, --saida ARQ   Nome do arquivo de saída (padrão: gerado com timestamp).
  -h, --help        Mostra esta ajuda e sai.

Exemplos:
  $(basename "$0")                         # 7z ultra, tudo no diretório atual
  $(basename "$0") --max                   # zpaq -m5, máxima compressão possível
  $(basename "$0") --dir ~/capturas -o ensaio_bancada.7z
USO
}

# ------------------------------------------------------------------------------
# 7. Parsing de argumentos
# ------------------------------------------------------------------------------
while [ $# -gt 0 ]; do
    case "$1" in
        --max|--maxima)
            MODO="maxima"; shift ;;
        --alta)
            MODO="alta"; shift ;;
        --dir)
            [ $# -ge 2 ] || { log_erro "--dir precisa de um valor."; exit 1; }
            DIRETORIO_ALVO="$2"; shift 2 ;;
        -o|--saida)
            [ $# -ge 2 ] || { log_erro "-o/--saida precisa de um valor."; exit 1; }
            ARQUIVO_SAIDA_CUSTOM="$2"; shift 2 ;;
        -h|--help)
            imprimir_uso; exit 0 ;;
        *)
            log_erro "Opção desconhecida: '$1'. Use -h para ajuda."
            exit 1 ;;
    esac
done

if [ ! -d "$DIRETORIO_ALVO" ]; then
    log_erro "Diretório '${DIRETORIO_ALVO}' não existe."
    exit 1
fi

# ------------------------------------------------------------------------------
# 8. Main
# ------------------------------------------------------------------------------
cabecalho

secao "Arquivos de entrada"
mapfile -d '' -t ARQUIVOS < <(coletar_arquivos_entrada)

if [ ${#ARQUIVOS[@]} -eq 0 ]; then
    log_erro "Nenhum arquivo .bin/.h5/.hdf5 encontrado em '${DIRETORIO_ALVO}'."
    exit 1
fi

TOTAL_ENTRADA=$(tamanho_total_bytes "${ARQUIVOS[@]}")
log_ok "${#ARQUIVOS[@]} arquivo(s) encontrado(s), $(formatar_tamanho "$TOTAL_ENTRADA") no total:"
for f in "${ARQUIVOS[@]}"; do
    echo -e "    ${CINZA}•${SEM_COR} $f  ${CINZA}($(formatar_tamanho "$(stat -c%s "$f")"))${SEM_COR}"
done

verificar_dependencias

secao "Compressão"
DATA_ATUAL=$(date +"%Y%m%d_%H%M%S")
if [ -n "$ARQUIVO_SAIDA_CUSTOM" ]; then
    ARQUIVO_SAIDA="$ARQUIVO_SAIDA_CUSTOM"
elif [ "$MODO" = "maxima" ]; then
    ARQUIVO_SAIDA="amostragens_adc_maxima_${DATA_ATUAL}.zpaq"
else
    ARQUIVO_SAIDA="amostragens_adc_alta_${DATA_ATUAL}.7z"
fi

if [ -e "$ARQUIVO_SAIDA" ]; then
    log_erro "'${ARQUIVO_SAIDA}' já existe -- escolha outro nome com -o/--saida."
    exit 1
fi

ARQUIVO_SAIDA_EM_ANDAMENTO="$ARQUIVO_SAIDA"
INICIO_TOTAL=$(date +%s)

if [ "$MODO" = "maxima" ]; then
    comprimir_zpaq "$ARQUIVO_SAIDA" "${ARQUIVOS[@]}"
else
    comprimir_7z "$ARQUIVO_SAIDA" "${ARQUIVOS[@]}"
fi

ARQUIVO_SAIDA_EM_ANDAMENTO=""   # sucesso -- não apagar mais em caso de sinal
DURACAO_TOTAL=$(( $(date +%s) - INICIO_TOTAL ))

# ------------------------------------------------------------------------------
# 9. Relatório final
# ------------------------------------------------------------------------------
TAMANHO_SAIDA=$(stat -c%s "$ARQUIVO_SAIDA")
RAZAO=$(( TOTAL_ENTRADA > 0 ? 100 - (TAMANHO_SAIDA * 100 / TOTAL_ENTRADA) : 0 ))

secao "Resultado"
echo -e "  ${NEGRITO}Arquivo gerado:${SEM_COR}     $ARQUIVO_SAIDA"
echo -e "  ${NEGRITO}Tamanho original:${SEM_COR}   $(formatar_tamanho "$TOTAL_ENTRADA")  (${#ARQUIVOS[@]} arquivo(s))"
echo -e "  ${NEGRITO}Tamanho final:${SEM_COR}      $(formatar_tamanho "$TAMANHO_SAIDA")"
echo -e "  ${NEGRITO}Redução:${SEM_COR}            ${RAZAO}%"
echo -e "  ${NEGRITO}Tempo total:${SEM_COR}        $(formatar_duracao "$DURACAO_TOTAL")"
echo
log_ok "Compressão concluída com sucesso."
echo