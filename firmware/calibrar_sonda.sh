#!/bin/bash
#
# calibrar_sonda.sh -- Coleta interativa de pontos de calibração de
# resposta em frequência para sondas de corrente do SH-Analyzer.
#
# Guia o operador na injeção manual de um sinal conhecido em várias
# frequências (via gerador de sinal de bancada), disparando o `ler_adc`
# para cada ponto e organizando as capturas resultantes em
# capturas/<sonda>/. Não calcula ganho nem faz nenhuma análise de
# amplitude -- isso é feito depois, em adc_tool.py (--fft/--welch/--picos
# sobre as capturas geradas aqui). Ver docs/proposta_correcao_sonda.md,
# seção 7, para a metodologia completa.
#
# Bancada esperada (ajustável nas constantes CANAL_REFERENCIA/CANAL_SONDA,
# logo abaixo): um resistor shunt de precisão em série com a sonda sob
# calibração, com o canal CANAL_REFERENCIA medindo a tensão sobre esse
# shunt (corrente real = V/R_shunt, calculada depois na análise -- este
# script só grava os dois canais brutos) e CANAL_SONDA lendo a saída da
# sonda sendo calibrada.
#
# Dois modos:
#   1) Novo perfil     -- gera N pontos log-espaçados entre freq_min/max.
#   2) Expandir perfil -- lê as frequências já capturadas em
#                         capturas/<sonda>/ e insere um novo ponto (média
#                         GEOMÉTRICA, não aritmética -- ver
#                         calcular_pontos_densificacao) entre cada par de
#                         frequências adjacentes, adensando a malha.
#
# Requisitos: bash 4.3+ (usa 'local -n', nameref), e os utilitários padrão
# bc (com a biblioteca matemática, flag -l), awk, sed, grep, find, df --
# presentes em qualquer instalação Debian/Ubuntu comum de BeagleBone.
# DE PROPÓSITO, nenhuma matemática de ponto flutuante roda em Python (ou
# qualquer outro interpretador externo) -- tudo aqui é feito com 'bc -l'
# (log-espaçamento, média geométrica, comparação de Nyquist).
#
# Uso: sudo ./calibrar_sonda.sh   (precisa de root, porque chama ./ler_adc,
#                                  que acessa /dev/mem)

# -----------------------------------------------------------------------
# Por que este script NÃO usa 'set -e' (errexit):
#
# O fluxo inteiro depende de checar explicitamente o código de saída de
# comandos que PODEM (e, no caso do ler_adc travando por SPI, DEVEM) falhar
# sem que isso encerre o script -- é exatamente disso que o menu de
# retentativa [C]/[R]/[A] trata. 'set -e' tem um comportamento notoriamente
# inconsistente dentro de funções usadas em condicionais e substituições de
# comando, e "esconder" uma falha esperada atrás dele tornaria o fluxo mais
# difícil de auditar, não mais seguro. Preferimos checar cada retorno que
# importa, explicitamente, com 'if'/'case'.
#
# 'set -u' (nounset) e 'pipefail' continuam ligados -- pegam variável não
# inicializada e falha silenciosa no meio de um pipe, que são bugs de
# verdade, não fluxo de controle esperado.
set -u
set -o pipefail

# -----------------------------------------------------------------------
# 0. Pré-checagem da versão do bash (nameref -- 'local -n' -- exige 4.3+)
# -----------------------------------------------------------------------
if [ -z "${BASH_VERSINFO:-}" ] || [ "${BASH_VERSINFO[0]}" -lt 4 ] || \
   { [ "${BASH_VERSINFO[0]}" -eq 4 ] && [ "${BASH_VERSINFO[1]}" -lt 3 ]; }; then
    echo "ERRO: este script precisa do bash 4.3 ou mais novo (usa" >&2
    echo "'local -n'/nameref). Versão detectada: ${BASH_VERSION:-desconhecida}." >&2
    exit 1
fi

# =========================================================================
# 1. Configuração
# =========================================================================
readonly PASTA_BASE="capturas"
readonly NOME_MANIFESTO="pontos_coletados.csv"
readonly ESPACO_MINIMO_MB=50

# Canais da bancada -- ver cabeçalho do arquivo para o racional.
readonly CANAL_REFERENCIA=0
readonly CANAL_SONDA=1

# Resolve o caminho do ler_adc relativo a ESTE script (não ao diretório
# corrente de quem chama) -- assim `sudo ./calibrar_sonda.sh` funciona
# não importa de onde for invocado, desde que o binário esteja ao lado
# deste script.
DIR_SCRIPT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly DIR_SCRIPT
readonly LER_ADC="${DIR_SCRIPT}/ler_adc"

REDUNDANCIA=1          # sobrescrito pela resposta do operador
SONDA_ID_SANITIZADO="" # idem

# =========================================================================
# 2. Cores ANSI e funções de saída
# =========================================================================
# Sem cores se a saída não for um terminal (ex.: redirecionada para um
# arquivo de log) -- evita poluir o log com códigos de escape.
if [ -t 1 ]; then
    COR_VERMELHO='\033[0;31m'; COR_VERDE='\033[0;32m'
    COR_AMARELO='\033[0;33m';  COR_AZUL='\033[0;34m'
    COR_NEGRITO='\033[1m';     COR_RESET='\033[0m'
else
    COR_VERMELHO=''; COR_VERDE=''; COR_AMARELO=''
    COR_AZUL='';     COR_NEGRITO=''; COR_RESET=''
fi

log_info()    { printf "%b\n" "${COR_AZUL}[INFO]${COR_RESET} $*" >&2; }
log_sucesso() { printf "%b\n" "${COR_VERDE}[OK]${COR_RESET} $*" >&2; }
log_aviso()   { printf "%b\n" "${COR_AMARELO}[ATENCAO]${COR_RESET} $*" >&2; }
log_erro()    { printf "%b\n" "${COR_VERMELHO}[ERRO]${COR_RESET} $*" >&2; }

erro_fatal() { log_erro "$*"; exit 1; }

separador() {
    printf "%b\n" "${COR_AZUL}────────────────────────────────────────────────────────────${COR_RESET}"
}

titulo_secao() {
    echo
    printf "%b\n" "${COR_NEGRITO}${COR_AZUL}=== $* ===${COR_RESET}"
}

# Ctrl+C em qualquer ponto do script deve avisar e sair limpo, em vez de
# deixar uma mensagem de erro genérica do bash.
trap 'echo; log_aviso "Interrompido (Ctrl+C). Nenhuma captura em andamento foi perdida -- as já concluídas continuam em '"'"'${PASTA_BASE}'"'"'."; exit 130' INT

# =========================================================================
# 3. Verificações de ambiente
# =========================================================================

# Confere se todos os utilitários externos usados pelo script existem --
# falha cedo e com uma mensagem clara, em vez de um erro obscuro de
# "comando não encontrado" no meio da coleta.
verificar_dependencias() {
    local faltando=() cmd
    for cmd in bc awk sed grep find df date; do
        command -v "$cmd" >/dev/null 2>&1 || faltando+=("$cmd")
    done
    if [ "${#faltando[@]}" -gt 0 ]; then
        erro_fatal "Ferramenta(s) obrigatória(s) não encontrada(s): ${faltando[*]}. Este script depende só de utilitários POSIX padrão -- confira a integridade do sistema."
    fi

    # bc precisa da biblioteca matemática (-l: funções l()/e(), log/exp
    # naturais) usada no espaçamento log e na média geométrica.
    if ! printf 'e(l(2))\n' | bc -l >/dev/null 2>&1; then
        erro_fatal "'bc -l' não respondeu como esperado -- confira se o 'bc' instalado suporta a biblioteca matemática (pacote 'bc' padrão do Debian suporta; um bc minimalista de outra distro pode não suportar)."
    fi

    if [ ! -e "$LER_ADC" ]; then
        erro_fatal "Não encontrei o executável 'ler_adc' em '${DIR_SCRIPT}'. Compile-o ('make' dentro de firmware/) e mantenha este script na mesma pasta do binário."
    fi
    if [ ! -x "$LER_ADC" ]; then
        erro_fatal "'${LER_ADC}' existe mas não é executável -- rode 'chmod +x ${LER_ADC}'."
    fi
}

verificar_root() {
    if [ "$(id -u)" -ne 0 ]; then
        erro_fatal "Este script precisa rodar como root (ele chama '${LER_ADC##*/}', que acessa /dev/mem) -- rode com 'sudo'."
    fi
}

# Confere o espaço livre (MB) na partição onde 'pasta' vive. A memória
# interna da BeagleBone é pequena -- isso evita descobrir no meio de uma
# sessão de bancada (com o operador longe do terminal) que o disco encheu
# e o '.bin' foi truncado sem aviso. NÃO aborta sozinho: pausa e deixa o
# operador liberar espaço (e conferir de novo) ou abortar por vontade
# própria.
verificar_espaco_disco() {
    local pasta="$1" livre_mb resposta
    while true; do
        livre_mb="$(df -Pm "$pasta" 2>/dev/null | awk 'NR==2 {print $4}')"
        if [ -z "${livre_mb:-}" ]; then
            log_aviso "Não consegui checar o espaço livre em '${pasta}' (saída inesperada de 'df') -- prosseguindo sem essa checagem."
            return 0
        fi
        if [ "$livre_mb" -ge "$ESPACO_MINIMO_MB" ]; then
            return 0
        fi
        log_erro "Espaço em disco CRÍTICO: só ${livre_mb} MB livres (mínimo configurado: ${ESPACO_MINIMO_MB} MB)."
        if ! read -r -p "$(printf "%b" "${COR_AMARELO}Libere espaço (ex.: copie capturas antigas para outro computador) e pressione ENTER para checar de novo, ou digite 'a' para abortar: ${COR_RESET}")" resposta; then
            erro_fatal "Entrada encerrada inesperadamente (EOF em stdin) -- abortando."
        fi
        if [ "${resposta,,}" = "a" ]; then
            erro_fatal "Abortado pelo operador por falta de espaço em disco."
        fi
    done
}

# =========================================================================
# 4. Entrada de dados do operador (validação)
# =========================================================================
readonly REGEX_INTEIRO_POSITIVO='^[0-9]+$'
readonly REGEX_FLOAT_POSITIVO='^[0-9]+(\.[0-9]+)?$'

# Lê um valor do operador, repetindo o prompt até bater com 'regex' (ERE).
# Aceita vírgula OU ponto como separador decimal (troca vírgula por ponto
# antes de validar -- conveniência de digitação em pt-BR; bc/awk exigem
# ponto). Define a variável cujo NOME é passado em $1 (nameref) em vez de
# devolver o valor via stdout -- evita qualquer ambiguidade entre o texto
# do prompt e o valor lido quando a função é chamada de dentro de outra
# lógica (nada de "$(ler_valor ...)").
#
# Uso: ler_valor NOME_DA_VARIAVEL "Mensagem do prompt: " "$REGEX"
ler_valor() {
    local -n _destino="$1"
    local mensagem="$2" regex="$3" entrada
    while true; do
        if ! read -r -p "$(printf "%b" "${COR_AMARELO}${mensagem}${COR_RESET}")" entrada; then
            erro_fatal "Entrada encerrada inesperadamente (EOF em stdin) -- abortando."
        fi
        entrada="${entrada//,/.}"
        entrada="$(printf '%s' "$entrada" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')"
        # [[ =~ ]] nativo do bash em vez de 'printf | grep -E': grep opera
        # por LINHA, e 'printf %s ""' (sem newline final, de propósito,
        # para não injetar espaço nenhum) produz ZERO linhas para uma
        # entrada vazia -- então um padrão como '^$' (usado para aceitar
        # "ENTER em branco = usar padrão") nunca bateria via grep, mesmo
        # sendo exatamente o caso que deveria casar. [[ =~ ]] compara a
        # STRING diretamente, sem essa pegadinha de linha/newline.
        if [[ "$entrada" =~ $regex ]]; then
            _destino="$entrada"
            return 0
        fi
        log_erro "Valor inválido: '${entrada}'. Tente de novo."
    done
}

# Pergunta S/n (padrão = sim quando ENTER vazio). Define $1 como "s" ou "n".
ler_confirmacao() {
    local -n _destino="$1"
    local mensagem="$2" entrada
    if ! read -r -p "$(printf "%b" "${COR_AMARELO}${mensagem} [S/n]: ${COR_RESET}")" entrada; then
        erro_fatal "Entrada encerrada inesperadamente (EOF em stdin) -- abortando."
    fi
    case "${entrada,,}" in
        n|nao|não) _destino="n" ;;
        *)         _destino="s" ;;
    esac
}

# Menu simples de escolha entre N opções numeradas. Define $1 com o índice
# escolhido (1-based). $2 é o título; os itens vêm depois, um por
# argumento.
ler_escolha_menu() {
    local -n _destino="$1"
    local titulo="$2"
    shift 2
    local -a itens=("$@")
    local i entrada
    echo "$titulo"
    for i in "${!itens[@]}"; do
        printf "  %d) %s\n" "$((i + 1))" "${itens[$i]}"
    done
    while true; do
        if ! read -r -p "$(printf "%b" "${COR_AMARELO}Escolha [1-${#itens[@]}]: ${COR_RESET}")" entrada; then
            erro_fatal "Entrada encerrada inesperadamente (EOF em stdin) -- abortando."
        fi
        if [[ "$entrada" =~ ^[0-9]+$ ]] && \
           [ "$entrada" -ge 1 ] && [ "$entrada" -le "${#itens[@]}" ]; then
            _destino="$entrada"
            return 0
        fi
        log_erro "Opção inválida."
    done
}

# Sanitiza um id de sonda em algo seguro para nome de pasta/arquivo:
# minúsculas, só [a-z0-9_-], sem espaços, sem repetição/sobra de '_'.
sanitizar_id() {
    local bruto="$1" limpo
    limpo="$(printf '%s' "$bruto" | tr '[:upper:]' '[:lower:]')"
    limpo="$(printf '%s' "$limpo" | sed -E 's/[^a-z0-9_-]+/_/g; s/_+/_/g; s/^[_-]+//; s/[_-]+$//')"
    printf '%s' "$limpo"
}

# =========================================================================
# 5. Matemática (bc -l -- sem Python)
# =========================================================================

# Confere Nyquist: freq_max PRECISA ser ESTRITAMENTE menor que taxa/2.
# Comparação feita em bc (não em bash/(( ))), porque taxa e freq_max podem
# não ser inteiros com quociente exato.
validar_nyquist() {
    local taxa="$1" freq_max="$2" ok nyquist
    nyquist="$(echo "scale=6; $taxa / 2" | bc -l)"
    ok="$(echo "$freq_max < ($taxa / 2)" | bc -l)"
    if [ "$ok" -ne 1 ]; then
        erro_fatal "Frequência máxima (${freq_max} Hz) precisa ser ESTRITAMENTE menor que metade da taxa de amostragem (${taxa} Hz / 2 = ${nyquist} Hz) -- viola o teorema de Nyquist. Reduza a frequência máxima ou aumente a taxa de amostragem."
    fi
}

# Gera N frequências espaçadas LOGARITMICAMENTE entre freq_min e freq_max
# (incluindo as duas pontas) -- mais denso nos extremos em termos
# relativos, a convenção padrão para caracterizar resposta em frequência
# (ver docs/proposta_correcao_sonda.md, seção 7). Uma frequência por linha
# em stdout.
calcular_pontos_log() {
    local freq_min="$1" freq_max="$2" n="$3"
    bc -l <<BC_EOF
scale = 10
lmin = l($freq_min)
lmax = l($freq_max)
passo = (lmax - lmin) / ($n - 1)
for (i = 0; i < $n; i++) {
    ponto = e(lmin + i * passo)
    print ponto, "\n"
}
BC_EOF
}

# Para cada par de frequências ADJACENTES em 'freqs' (lista de argumentos,
# já ordenada), calcula a média GEOMÉTRICA -- não a aritmética -- como
# novo ponto entre elas: é o ponto exatamente equidistante das duas em
# escala LOGARÍTMICA, consistente com o espaçamento log da malha original
# (calcular_pontos_log, acima). A média aritmética simples ((f1+f2)/2)
# ficaria enviesada para o lado de maior frequência quando vista em escala
# log -- por isso a troca em relação à sugestão original do "ponto médio"
# simples.
calcular_pontos_densificacao() {
    local -a freqs=("$@")
    local i
    for ((i = 0; i < ${#freqs[@]} - 1; i++)); do
        echo "sqrt(${freqs[i]} * ${freqs[i + 1]})" | bc -l
    done
}

# Lista as frequências (Hz, inteiras) já presentes nos nomes de arquivo em
# 'pasta', a partir do padrão 'calibracao_<FREQ>Hz_rep<N>.bin' -- únicas e
# ordenadas numericamente crescente, uma por linha. Vazio (sem erro) se a
# pasta não existir ou não tiver nada reconhecível.
extrair_frequencias_existentes() {
    local pasta="$1"
    [ -d "$pasta" ] || return 0
    find "$pasta" -maxdepth 1 -type f -name 'calibracao_*Hz_rep*.bin' -printf '%f\n' 2>/dev/null \
        | sed -nE 's/^calibracao_([0-9]+)Hz_rep[0-9]+\.bin$/\1/p' \
        | sort -n -u
}

# =========================================================================
# 6. Manifesto (CSV de acompanhamento -- insumo para o futuro
#    scripts/calibrar_sonda.py que calcula o ganho a partir das capturas)
# =========================================================================

inicializar_manifesto() {
    local caminho="$1"
    [ -f "$caminho" ] || echo "frequencia_hz,repeticao,arquivo,timestamp,status" > "$caminho"
}

registrar_manifesto() {
    local caminho="$1" freq="$2" rep="$3" arquivo="$4" status="$5" ts
    ts="$(date '+%Y-%m-%dT%H:%M:%S%z')"
    printf '%s,%s,%s,%s,%s\n' "$freq" "$rep" "$arquivo" "$ts" "$status" >> "$caminho"
}

# =========================================================================
# 7. Execução de uma medição
# =========================================================================

# Se 'caminho' já existe, devolve uma variante '_v2', '_v3', ... em vez de
# deixar o ler_adc sobrescrever silenciosamente uma captura anterior (pode
# acontecer ao rodar "Expandir" mais de uma vez sobre a mesma malha, ou ao
# repetir manualmente uma sessão). Avisa em amarelo quando isso acontece.
caminho_disponivel() {
    local caminho="$1" base="${1%.bin}" versao=2 candidato
    [ -e "$caminho" ] || { printf '%s' "$caminho"; return 0; }
    log_aviso "'${caminho}' já existe -- gravando como uma nova versão em vez de sobrescrever."
    while true; do
        candidato="${base}_v${versao}.bin"
        [ -e "$candidato" ] || { printf '%s' "$candidato"; return 0; }
        versao=$((versao + 1))
    done
}

# Monta e roda a chamada ao ler_adc para um ponto de calibração. Devolve o
# código de saída do ler_adc -- NÃO decide sozinha o que fazer com uma
# falha; isso é responsabilidade de quem chama (o menu de retentativa).
executar_medicao() {
    local taxa="$1" arquivo_saida="$2" titulo="$3"
    "$LER_ADC" "$taxa" "${CANAL_REFERENCIA},${CANAL_SONDA}" \
        --grandeza "${CANAL_SONDA}:corrente" \
        --sonda "${CANAL_SONDA}:${SONDA_ID_SANITIZADO}" \
        -o "$arquivo_saida" \
        -t "$titulo"
    return $?
}

# Processa 1 ponto de frequência: REDUNDANCIA repetições, cada uma com
# checagem de disco, pausa para o operador ajustar o gerador, chamada ao
# ler_adc e o menu [C]ontinuar/[R]efazer/[A]bortar.
processar_ponto() {
    local indice="$1" total="$2" freq="$3" taxa="$4" pasta_sonda="$5" manifesto="$6"
    local freq_exibicao freq_arquivo rep

    freq_exibicao="$(printf '%.2f' "$freq")"
    freq_arquivo="$(printf '%.0f' "$freq")"

    for ((rep = 1; rep <= REDUNDANCIA; rep++)); do
        separador
        printf "%b\n" "${COR_NEGRITO}Ponto ${indice} de ${total}  |  Frequência: ${freq_exibicao} Hz  |  Repetição ${rep} de ${REDUNDANCIA}${COR_RESET}"
        separador

        verificar_espaco_disco "$pasta_sonda"

        local resposta_pronto
        if ! read -r -p "$(printf "%b" "${COR_AMARELO}Ajuste o gerador de sinal para ${freq_exibicao} Hz, aguarde a estabilização e pressione ENTER para medir (ou 'a' para abortar): ${COR_RESET}")" resposta_pronto; then
            erro_fatal "Entrada encerrada inesperadamente (EOF em stdin) -- abortando."
        fi
        if [ "${resposta_pronto,,}" = "a" ]; then
            log_aviso "Abortado pelo operador antes da medição."
            exit 0
        fi

        local arquivo_alvo arquivo_saida titulo codigo_saida escolha sugestao
        arquivo_alvo="${pasta_sonda}/calibracao_${freq_arquivo}Hz_rep${rep}.bin"
        titulo="Calibracao ${freq_arquivo}Hz rep${rep} sonda=${SONDA_ID_SANITIZADO}"

        while true; do
            arquivo_saida="$(caminho_disponivel "$arquivo_alvo")"
            log_info "Medindo (${LER_ADC##*/} ${taxa} ${CANAL_REFERENCIA},${CANAL_SONDA} --grandeza ${CANAL_SONDA}:corrente --sonda ${CANAL_SONDA}:${SONDA_ID_SANITIZADO} -o $(basename "$arquivo_saida")) ..."
            executar_medicao "$taxa" "$arquivo_saida" "$titulo"
            codigo_saida=$?

            if [ "$codigo_saida" -eq 0 ]; then
                log_sucesso "Medição concluída: $(basename "$arquivo_saida")"
                sugestao="C"
            else
                log_erro "ler_adc terminou com código ${codigo_saida} -- provável falha de hardware/SPI, ou captura incompleta."
                sugestao="R"
            fi

            echo
            echo "  [C] Continuar        -- aceita esta medição e segue em frente"
            echo "  [R] Refazer          -- descarta o arquivo e repete este mesmo ponto"
            echo "  [A] Abortar          -- encerra o script agora"

            # Laço INTERNO só para validar a escolha -- uma resposta
            # inválida (nem c/r/a) deve voltar a perguntar, NUNCA disparar
            # outra medição. Só 'r' sai deste laço interno de volta para o
            # laço externo (que remede); 'c' sai dos DOIS laços de uma vez
            # ('break 2').
            while true; do
                read -r -p "$(printf "%b" "${COR_AMARELO}Escolha (sugestão: ${sugestao}): ${COR_RESET}")" escolha || {
                    erro_fatal "Entrada encerrada inesperadamente (EOF em stdin) -- abortando."
                }
                case "${escolha,,}" in
                    c)
                        local status_manifesto
                        if [ ! -e "$arquivo_saida" ]; then
                            log_erro "Escolhido continuar, mas '$(basename "$arquivo_saida")' não existe em disco (o ler_adc provavelmente falhou antes de gravar qualquer coisa) -- o manifesto vai registrar isso como 'sem_arquivo', não 'ok'. Considere [R]efazer em vez de continuar."
                            status_manifesto="sem_arquivo"
                        elif [ "$codigo_saida" -eq 0 ]; then
                            status_manifesto="ok"
                        else
                            status_manifesto="aceito_com_erro_${codigo_saida}"
                        fi
                        registrar_manifesto "$manifesto" "$freq_exibicao" "$rep" "$(basename "$arquivo_saida")" "$status_manifesto"
                        break 2
                        ;;
                    r)
                        log_aviso "Descartando '$(basename "$arquivo_saida")' e repetindo esta medição."
                        rm -f "$arquivo_saida"
                        break
                        ;;
                    a)
                        log_aviso "Abortado pelo operador."
                        rm -f "$arquivo_saida" 2>/dev/null
                        exit 0
                        ;;
                    *)
                        log_erro "Opção inválida -- digite C, R ou A."
                        ;;
                esac
            done
        done
    done
}

# =========================================================================
# 8. Fluxo principal
# =========================================================================

banner() {
    printf "%b\n" "${COR_NEGRITO}${COR_AZUL}"
    cat <<'EOF'
╔══════════════════════════════════════════════════════════════╗
║       SH-Analyzer -- Coleta de calibração de sonda            ║
╚══════════════════════════════════════════════════════════════╝
EOF
    printf "%b\n" "${COR_RESET}"
}

coletar_parametros_comuns() {
    # Preenche, via nameref, as variáveis cujos NOMES são passados: taxa,
    # sonda_bruta, redundancia.
    local -n _taxa="$1" _sonda_bruta="$2" _redundancia="$3"
    ler_valor _taxa "Taxa de amostragem TOTAL do sistema, em Hz (ex.: 102400): " "$REGEX_INTEIRO_POSITIVO"
    ler_valor _sonda_bruta "Identificador da sonda (ex.: fluke_i30_sn0001): " '^.+$'
    ler_valor _redundancia "Fator de redundância -- repetições por frequência [padrão 1]: " "${REGEX_INTEIRO_POSITIVO}|^$"
    [ -z "$_redundancia" ] && _redundancia=1
}

fluxo_novo_perfil() {
    local taxa sonda_bruta redundancia freq_min freq_max num_pontos
    coletar_parametros_comuns taxa sonda_bruta redundancia

    ler_valor freq_min "Frequência MÍNIMA da faixa, em Hz (ex.: 50): " "$REGEX_FLOAT_POSITIVO"
    ler_valor freq_max "Frequência MÁXIMA da faixa, em Hz (ex.: 100000): " "$REGEX_FLOAT_POSITIVO"
    ler_valor num_pontos "Número total de pontos de calibração (mínimo 2): " "$REGEX_INTEIRO_POSITIVO"

    if [ "$num_pontos" -lt 2 ]; then
        erro_fatal "São necessários pelo menos 2 pontos para definir uma faixa."
    fi
    if [ "$(echo "$freq_min >= $freq_max" | bc -l)" -eq 1 ]; then
        erro_fatal "Frequência mínima (${freq_min} Hz) precisa ser menor que a máxima (${freq_max} Hz)."
    fi
    validar_nyquist "$taxa" "$freq_max"

    local -a pontos=()
    while IFS= read -r linha; do
        pontos+=("$linha")
    done < <(calcular_pontos_log "$freq_min" "$freq_max" "$num_pontos")

    iniciar_coleta "$taxa" "$sonda_bruta" "$redundancia" pontos
}

fluxo_expandir_perfil() {
    local taxa sonda_bruta redundancia sonda_sanitizada pasta_sonda
    coletar_parametros_comuns taxa sonda_bruta redundancia
    sonda_sanitizada="$(sanitizar_id "$sonda_bruta")"
    pasta_sonda="${PASTA_BASE}/${sonda_sanitizada}"

    local -a existentes=()
    while IFS= read -r linha; do
        [ -n "$linha" ] && existentes+=("$linha")
    done < <(extrair_frequencias_existentes "$pasta_sonda")

    if [ "${#existentes[@]}" -lt 2 ]; then
        erro_fatal "Encontrei ${#existentes[@]} frequência(s) já capturada(s) em '${pasta_sonda}' -- são necessárias pelo menos 2 (em captura(s) anteriores, nomeadas 'calibracao_<FREQ>Hz_rep<N>.bin') para calcular pontos de adensamento entre elas."
    fi

    log_info "Frequências já capturadas em '${pasta_sonda}': ${existentes[*]} Hz"

    local -a pontos=()
    while IFS= read -r linha; do
        pontos+=("$linha")
    done < <(calcular_pontos_densificacao "${existentes[@]}")

    log_info "$(( ${#existentes[@]} - 1 )) novo(s) ponto(s) de adensamento (1 entre cada par adjacente, média geométrica)."

    validar_nyquist "$taxa" "$(printf '%s\n' "${pontos[@]}" | sort -n | tail -1)"

    iniciar_coleta "$taxa" "$sonda_bruta" "$redundancia" pontos
}

# Etapa comum aos dois modos: mostra o plano de coleta, pede confirmação,
# cria a pasta/manifesto e processa cada ponto em sequência.
iniciar_coleta() {
    local taxa="$1" sonda_bruta="$2" redundancia="$3"
    local -n _pontos="$4"

    SONDA_ID_SANITIZADO="$(sanitizar_id "$sonda_bruta")"
    if [ -z "$SONDA_ID_SANITIZADO" ]; then
        erro_fatal "O identificador de sonda '${sonda_bruta}' não sobrou com nenhum caractere válido depois de sanitizado -- use letras, números, '-' ou '_'."
    fi
    if [ "$SONDA_ID_SANITIZADO" != "$sonda_bruta" ]; then
        log_aviso "Identificador de sonda normalizado para '${SONDA_ID_SANITIZADO}' (era '${sonda_bruta}') -- use exatamente esse valor no perfil .json e em --sonda-perfil/adc_tool.py depois."
    fi

    REDUNDANCIA="$redundancia"
    local pasta_sonda="${PASTA_BASE}/${SONDA_ID_SANITIZADO}"
    local manifesto="${pasta_sonda}/${NOME_MANIFESTO}"
    local total="${#_pontos[@]}"
    local total_medicoes="$((total * REDUNDANCIA))"

    titulo_secao "Plano de coleta"
    echo "Sonda:                ${SONDA_ID_SANITIZADO}"
    echo "Taxa de amostragem:   ${taxa} Hz total (canais ${CANAL_REFERENCIA},${CANAL_SONDA} -- referência,sonda)"
    echo "Pontos de frequência: ${total}"
    echo "Redundância:          ${REDUNDANCIA}x por ponto"
    echo "Total de medições:    ${total_medicoes}"
    echo "Pasta de saída:       ${pasta_sonda}/"
    echo
    echo "Frequências (Hz):"
    printf '  %.2f\n' "${_pontos[@]}"
    echo

    local confirmar
    ler_confirmacao confirmar "Iniciar a coleta?"
    if [ "$confirmar" = "n" ]; then
        log_aviso "Cancelado pelo operador antes de iniciar."
        exit 0
    fi

    mkdir -p "$pasta_sonda"
    inicializar_manifesto "$manifesto"

    local i=0
    for freq in "${_pontos[@]}"; do
        i=$((i + 1))
        processar_ponto "$i" "$total" "$freq" "$taxa" "$pasta_sonda" "$manifesto"
    done

    separador
    log_sucesso "Coleta concluída: ${total_medicoes} medição/medições em '${pasta_sonda}/'."
    log_info "Manifesto: ${manifesto}"
    log_info "Próximo passo: extrair a amplitude de cada captura (ex.: adc_tool.py --fft --picos ou --welch) e montar o perfil scripts/sondas/${SONDA_ID_SANITIZADO}.json -- ver docs/proposta_correcao_sonda.md, seção 7.1."
}

main() {
    banner
    verificar_dependencias
    verificar_root

    local escolha_modo
    ler_escolha_menu escolha_modo "Modo de operação:" \
        "Novo perfil (gerar pontos log-espaçados do zero)" \
        "Expandir perfil existente (adensar malha de um perfil já iniciado)"

    case "$escolha_modo" in
        1) fluxo_novo_perfil ;;
        2) fluxo_expandir_perfil ;;
    esac
}

main "$@"
