#!/usr/bin/env bash
# ==============================================================================
# BeagleBone_Setup.sh -- a interface entre o computador e a BeagleBone do SH-Analyzer.
#
# Um comando para cada coisa que se faz com a placa, do computador (rode sem argumentos para ver o estado
# dela, e com 'ajuda' para a lista):
#
#   status       conexão, relógio, firmware lá x repositório, PRU, disco, capturas e montagem (o padrão)
#   preparar     começar o dia: hora + enviar + setup, numa tacada
#   hora         acerta o relógio da BeagleBone pelo do computador (ela não tem bateria de RTC)
#   enviar       leva firmware/ (só ele), com a versão, e guarda o firmware anterior (plano B)
#   setup        roda o setup.sh lá: pinos, compilação e carga da PRU
#   ssh          terminal na pasta do firmware, com o sudo já liberado (ou roda um comando lá)
#   trazer       copia capturas para o computador
#   montar       monta o home da BeagleBone numa pasta do computador (sshfs)
#   desmontar    desmonta
#   configurar   grava IP, usuário e senha, para não informar de novo
#
# ACESSO (informado uma vez): o IP, o usuário e a senha vêm, nesta ordem de prioridade, das opções (--ip,
# --usuario), das variáveis BBB_IP, BBB_USER, BBB_SENHA e BBB_SENHA_SUDO, do arquivo gravado pelo 'configurar'
# (~/.config/sh-analyzer/beaglebone.conf, legível só por você) e dos padrões da imagem Debian da BeagleBone:
# debian@192.168.6.2, senha temppwd. A senha nunca vai na linha de comando (onde 'ps' a mostraria):
#   * login SSH: o próprio script responde ao ssh como SSH_ASKPASS (OpenSSH >= 8.4); com uma chave SSH
#     autorizada (ssh-copy-id), nenhuma senha é usada;
#   * sudo na BeagleBone: a senha vai pelo stdin para um arquivo em /dev/shm (RAM), só do usuário, que o
#     'sudo -A' lê (SUDO_ASKPASS) e que é apagado no fim do comando ou da sessão;
#   * uma conexão SSH é reaproveitada pelos comandos seguintes por 2 minutos (ControlMaster): a placa é
#     lenta para abrir conexões, e o 'preparar' faz várias.
#
# POR QUE SÓ firmware/ VAI PARA A PLACA: ela compila e roda o ler_adc, o código da PRU, o setup.sh e o
# calibrar_sonda.sh; a análise roda no computador. O repositório inteiro (e o .git) só ocuparia o espaço das
# capturas. O que a placa não tem, sem o .git, é a VERSÃO do código, que o ler_adc grava em cada captura
# (cabeçalho v5): o 'enviar' a escreve em firmware/VERSAO, a partir do 'git describe'.
# ==============================================================================

set -euo pipefail

# Modo SSH_ASKPASS: o ssh chama este mesmo arquivo para pedir a senha do login. Responde só a pedidos de
# senha (uma pergunta de outro tipo, como a frase de uma chave, é recusada e o ssh segue sem ela).
if [ -n "${_SH_ANALYZER_ASKPASS:-}" ]; then
    case "${1:-}" in
        *assword*) printf '%s\n' "${_SH_ANALYZER_SENHA:-}"; exit 0 ;;
        *) exit 1 ;;
    esac
fi

SCRIPT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/$(basename "${BASH_SOURCE[0]}")"
RAIZ="$(cd "$(dirname "$SCRIPT")/.." && pwd)"
NOME="scripts/$(basename "$SCRIPT")"
CONFIG="${XDG_CONFIG_HOME:-$HOME/.config}/sh-analyzer/beaglebone.conf"

# ------------------------------------------------------------------------------
# Aparência: cores só num terminal (e nunca com NO_COLOR)
# ------------------------------------------------------------------------------
if [ -t 1 ] && [ -z "${NO_COLOR:-}" ] && [ "${TERM:-}" != dumb ]; then
    N=$'\e[1m' F=$'\e[2m' R=$'\e[0m' VERDE=$'\e[32m' AMARELO=$'\e[33m' VERMELHO=$'\e[31m' CIANO=$'\e[36m'
else
    N='' F='' R='' VERDE='' AMARELO='' VERMELHO='' CIANO=''
fi

titulo() { printf '\n  %s◆ SH-Analyzer%s %s· BeagleBone%s   %s%s%s\n' "$N$CIANO" "$R" "$N" "$R" "$F" "$*" "$R"; }
etapa() { printf '\n  %s▸ %s%s\n' "$N$CIANO" "$*" "$R"; }
ok() { printf '    %s✓%s %s\n' "$VERDE" "$R" "$*"; }
info() { printf '    %s·%s %s\n' "$F" "$R" "$*"; }
aviso() { printf '    %s!%s %s\n' "$AMARELO" "$R" "$*" >&2; }
erro() { printf '    %s✗ %s%s\n' "$VERMELHO" "$*" "$R" >&2; }
falha() { erro "$*"; exit 1; }
dica() { printf '      %s%s%s\n' "$F" "$*" "$R" >&2; }   # junto de um erro
proximo() { printf '      %s%s%s\n' "$F" "$*" "$R"; }       # o passo seguinte, na saída normal
campo() {   # rótulo alinhado + valor (o printf conta bytes, e "Relógio" tem um acento: conta-se à mão)
    printf '    %s%s%*s%s %s\n' "$F" "$1" $((11 - ${#1})) '' "$R" "$2"
}
recuar() {   # a saída da BeagleBone, recuada atrás de uma barra (o \r de um terminal remoto sai)
    local linha
    while IFS= read -r linha || [ -n "$linha" ]; do
        printf '    %s│%s %s\n' "$F" "$R" "${linha%$'\r'}"
    done
}

# ------------------------------------------------------------------------------
# Acesso: padrões < arquivo do 'configurar' < variáveis de ambiente < opções
# ------------------------------------------------------------------------------
IP=192.168.6.2 USUARIO=debian SENHA=temppwd SENHA_SUDO='' PASTA=firmware MONTAGEM="$HOME/BeagleBone"
if [ -r "$CONFIG" ]; then
    while IFS='=' read -r chave valor || [ -n "$chave" ]; do   # lido como dados, nunca executado
        case "$chave" in
            ip) IP=$valor ;; usuario) USUARIO=$valor ;; senha) SENHA=$valor ;; senha_sudo) SENHA_SUDO=$valor ;;
            pasta) PASTA=$valor ;; montagem) MONTAGEM=$valor ;;
        esac
    done < "$CONFIG"
fi
IP=${BBB_IP:-$IP} USUARIO=${BBB_USER:-$USUARIO} SENHA=${BBB_SENHA:-$SENHA}
SENHA_SUDO=${BBB_SENHA_SUDO:-$SENHA_SUDO} PASTA=${BBB_PASTA:-$PASTA} MONTAGEM=${BBB_MONTAGEM:-$MONTAGEM}

uso() {
    cat <<EOF

  ${N}${CIANO}◆ SH-Analyzer${R} ${N}· BeagleBone${R}   ${F}a interface entre o computador e a placa${R}

  ${N}Uso:${R} $NOME [opções] [comando] [argumentos]

  ${N}Comandos${R}
    ${N}status${R}                      conexão, relógio, firmware, PRU, disco e capturas ${F}(o padrão)${R}
    ${N}preparar${R}                    começar o dia: hora + enviar + setup
    ${N}hora${R}                        acerta o relógio da BeagleBone pelo do computador
    ${N}enviar${R} [--setup]            leva firmware/ com a versão e guarda o anterior (plano B)
           [--forcar]            ${F}envia com mudanças não commitadas (a versão ganha "-dirty")${R}
           [--simular]           ${F}só mostra o que faria${R}
    ${N}setup${R}                       pinos, compilação e carga da PRU (o setup.sh, lá)
    ${N}ssh${R} [comando]               terminal na pasta do firmware, sudo sem senha; com comando, só o roda
    ${N}trazer${R} [padrão] [destino]   copia capturas e pastas ${F}(padrão '*.bin'; destino \$DIA ou a pasta atual)${R}
    ${N}montar${R} [pasta] [--forcar]   monta o home da BeagleBone no computador ${F}(sshfs; padrão ~/BeagleBone)${R}
    ${N}desmontar${R} [pasta] [--forcar] desmonta ${F}(--forcar: mesmo com arquivos abertos)${R}
    ${N}configurar${R}                  grava IP, usuário e senha para não informar de novo

  ${N}Opções${R}
    --ip IP          endereço ${F}(padrão 192.168.6.2; em alguns sistemas, 192.168.7.2)${R}
    --usuario NOME   usuário ${F}(padrão debian)${R}
    --pasta PASTA    pasta do firmware na BeagleBone, relativa ao home ${F}(padrão firmware)${R}

  ${N}Agora:${R} ${USUARIO}@${IP}, pasta ~/${PASTA#\~/}$([ -r "$CONFIG" ] && printf ' %s(de %s)%s' "$F" "${CONFIG/#$HOME/\~}" "$R")
  ${F}Senha: BBB_SENHA, a do 'configurar' ou a padrão da imagem Debian (temppwd). O sudo usa a mesma,
  a não ser que BBB_SENHA_SUDO (ou senha_sudo no arquivo) diga outra.${R}

  ${N}Exemplos${R}
    $NOME preparar                                  ${F}# hora, firmware novo e PRU carregada${R}
    $NOME ssh                                       ${F}# e lá: sudo ./ler_adc 100000 1 --blocos 3${R}
    $NOME ssh 'sudo ./ler_adc 100000 1 --blocos 3 -o T7a.bin -t "T7a 100k"'
    $NOME trazer 'T7*.bin' \$DIA
    $NOME --ip 192.168.7.2 status

EOF
}

# ------------------------------------------------------------------------------
# Linha de comando: opções globais em qualquer posição antes do comando
# ------------------------------------------------------------------------------
COMANDO=''
ARGS=()
while [ $# -gt 0 ]; do
    case "$1" in
        --ip) [ $# -ge 2 ] || falha "--ip precisa de um endereço."; IP=$2; shift ;;
        --usuario) [ $# -ge 2 ] || falha "--usuario precisa de um nome."; USUARIO=$2; shift ;;
        --pasta) [ $# -ge 2 ] || falha "--pasta precisa de um caminho."; PASTA=$2; shift ;;
        -h|--help|ajuda) uso; exit 0 ;;
        -*) if [ -z "$COMANDO" ]; then falha "opção desconhecida: '$1' (veja $NOME ajuda)."; fi
            ARGS+=("$1") ;;
        *) if [ -z "$COMANDO" ]; then COMANDO=$1; else ARGS+=("$1"); fi ;;
    esac
    shift
    if [ "$COMANDO" = ssh ]; then ARGS+=("$@"); break; fi   # o resto é o comando remoto, como no ssh
done
COMANDO=${COMANDO:-status}

# A pasta remota é relativa ao home (o padrão do ssh); '~/' na frente é aceito e removido, porque o shell
# remoto receberia o '~' protegido por aspas e criaria uma pasta chamada '~'.
PASTA="${PASTA#\~/}"
case "$PASTA" in
    ''|*' '*) falha "pasta remota inválida: '${PASTA}' (sem espaços; ex.: firmware ou sh-analyzer/firmware)." ;;
esac
SENHA_SUDO=${SENHA_SUDO:-$SENHA}
ALVO="${USUARIO}@${IP}"

# ------------------------------------------------------------------------------
# SSH: senha pelo SSH_ASKPASS (este arquivo) e uma conexão reaproveitada
# ------------------------------------------------------------------------------
CONTROLE="${XDG_RUNTIME_DIR:-${TMPDIR:-/tmp}}/sh-analyzer-ssh-%C"
SSH_BASE=(-o StrictHostKeyChecking=accept-new -o ConnectTimeout=8 -o NumberOfPasswordPrompts=1
          -o ServerAliveInterval=15 -o ServerAliveCountMax=8 -o LogLevel=ERROR)   # 2 min sem resposta para desistir
SSH_OPCOES=("${SSH_BASE[@]}" -o ControlMaster=auto -o "ControlPath=$CONTROLE" -o ControlPersist=120)
if [ -x "$SCRIPT" ]; then
    export SSH_ASKPASS="$SCRIPT" SSH_ASKPASS_REQUIRE=force _SH_ANALYZER_ASKPASS=1 _SH_ANALYZER_SENHA="$SENHA"
fi

remoto() { ssh "${SSH_OPCOES[@]}" -T "$ALVO" "$@"; }

# Monta 'bash -c <script> _ <args>' para o shell remoto, com tudo protegido por %q.
comando_remoto() {   # $1 = script; o resto, os argumentos dele ($1, $2... lá)
    local script=$1
    shift
    printf 'bash -c %q _' "$script"
    [ $# -eq 0 ] || printf ' %q' "$@"
}

# Abre (ou reaproveita) a conexão. Sem ela, diz o motivo provável e para.
conectar() {
    local saida
    if saida=$(ssh "${SSH_OPCOES[@]}" -T "$ALVO" true 2>&1 </dev/null); then
        return 0
    fi
    erro "não consegui entrar em ${ALVO}."
    case "$saida" in
        *"HOST IDENTIFICATION HAS CHANGED"*)
            dica "A chave da placa mudou (a imagem foi regravada?). Se for a sua BeagleBone, esqueça a antiga:"
            dica "  ssh-keygen -R ${IP}" ;;
        *"Permission denied"*)
            dica "Senha recusada. Grave a certa com: $NOME configurar  (ou BBB_SENHA=... na frente do comando)" ;;
        *"Connection refused"*)
            dica "A placa respondeu, mas o ssh dela ainda não subiu: espere uns segundos e tente de novo." ;;
        *)
            dica "Sem resposta de ${IP}. A placa ligou (LEDs piscando)? O cabo USB é de dados?"
            dica "Em alguns sistemas o endereço é 192.168.7.2:  $NOME --ip 192.168.7.2 ${COMANDO}" ;;
    esac
    [ -z "$saida" ] || dica "ssh: ${saida//$'\n'/ }"
    exit 1
}

# Deixa na BeagleBone um "askpass" do sudo com a senha (em /dev/shm, RAM, só do usuário) e imprime a pasta
# dele. A senha vai pelo stdin. Quem usa a pasta a apaga no fim (trap); se a conexão cair antes, ela some
# no próximo boot. (SH_ANALYZER_RAM troca a /dev/shm só nos testes, em que o "remoto" roda aqui mesmo.)
# shellcheck disable=SC2016  # as variáveis são do shell REMOTO: as aspas simples são de propósito
PREPARA_SUDO='umask 077
d=$(mktemp -d "${SH_ANALYZER_RAM:-/dev/shm}/sh-analyzer.XXXXXX" 2>/dev/null || mktemp -d) || exit 1
IFS= read -r s || true
printf "%s\n" "$s" > "$d/senha"
printf "#!/bin/sh\nexec cat \"%s/senha\"\n" "$d" > "$d/askpass"
chmod 700 "$d/askpass"
printf "%s\n" "$d"'
preparar_sudo() {
    printf '%s\n' "$SENHA_SUDO" | remoto "$(comando_remoto "$PREPARA_SUDO")"
}

# Formata um intervalo em segundos (com sinal ignorado): "0,4 s", "12 s", "3 min", "2 h 05 min", "3 dias".
duracao() {
    awk -v s="$1" 'BEGIN { if (s < 0) s = -s
        if (s < 10) { t = sprintf("%.1f s", s); gsub(/\./, ",", t); print t }
        else if (s < 120) printf "%d s\n", s
        else if (s < 7200) printf "%d min\n", s / 60
        else if (s < 172800) printf "%d h %02d min\n", s / 3600, (s % 3600) / 60
        else printf "%d dias\n", s / 86400 }'
}

# ==============================================================================
# hora: o relógio da BeagleBone pelo do computador
# ==============================================================================
# Parte que roda como root ($1 = hora enviada, $2 = uptime no início da sessão, antes do sudo): soma o tempo
# gasto até o sudo e acerta o relógio. 'fake-hwclock save' guarda a hora para o próximo boot (existe nas
# imagens Debian da BeagleBone). Imprime o erro que o relógio tinha.
# shellcheck disable=SC2016
HORA_ROOT='antes=$(date -u +%s.%N); t1=$(cut -d" " -f1 /proc/uptime)
novo=$(awk -v e="$1" -v a="$2" -v b="$t1" "BEGIN { printf \"%.3f\", e + b - a }")
date -u -s "@$novo" >/dev/null || exit 1
{ command -v fake-hwclock >/dev/null && fake-hwclock save; } >/dev/null 2>&1 || true
awk -v x="$antes" -v y="$novo" "BEGIN { printf \"erro=%.3f\\n\", x - y }"
date "+agora=%Y-%m-%d %H:%M:%S %Z"'
# shellcheck disable=SC2016
HORA_REMOTO='d=$1; export SUDO_ASKPASS="$d/askpass"; trap '\''rm -rf "$d"'\'' EXIT
t0=$(cut -d" " -f1 /proc/uptime)
sudo -A bash -c "$3" _ "$2" "$t0"'

cmd_hora() {
    etapa "Relógio"
    local d agora saida erro_s=''
    d=$(preparar_sudo)
    # O instante vai como segundos desde 1970 (UTC, com fração): vale qualquer que seja o fuso da placa.
    agora="$(date -u +%s.%N)"
    case "$agora" in *N) agora="$(date -u +%s)" ;; esac   # date sem %N (não GNU): segundos inteiros
    if ! saida=$(remoto "$(comando_remoto "$HORA_REMOTO" "$d" "$agora" "$HORA_ROOT")" 2>&1 </dev/null); then
        falha "não consegui acertar o relógio (a senha do sudo está certa?): ${saida//$'\n'/ }"
    fi
    while IFS='=' read -r chave valor; do
        case "$chave" in erro) erro_s=$valor ;; agora) ok "acertado: $valor" ;; esac
    done <<< "$saida"
    if [ -n "$erro_s" ]; then
        if awk -v e="$erro_s" 'BEGIN { exit !(e > -1 && e < 1) }'; then
            info "já estava certo (diferença de $(duracao "$erro_s"))"
        elif awk -v e="$erro_s" 'BEGIN { exit !(e < 0) }'; then
            info "estava $(duracao "$erro_s") atrasado"
        else
            info "estava $(duracao "$erro_s") adiantado"
        fi
    fi
}

# ==============================================================================
# enviar: só firmware/, com a versão e um plano B do que estava lá
# ==============================================================================
# $1 = pasta, $2 = carimbo, o resto = os arquivos enviados. O tar do código novo chega pelo stdin.
# shellcheck disable=SC2016
ENVIO_REMOTO='set -eu
pasta=$1; carimbo=$2; shift 2
mkdir -p -- "$pasta"
if [ -e "$pasta/ler_adc.c" ]; then
    antiga=$(head -c 64 "$pasta/VERSAO" 2>/dev/null | tr -cd "A-Za-z0-9._-" || true)
    [ -n "$antiga" ] || antiga=sem-versao
    destino="$pasta-anteriores/${carimbo}_$antiga"
    mkdir -p -- "$destino"
    for f in "$@" ler_adc fw_pru.out; do
        if [ -e "$pasta/$f" ]; then cp -p -- "$pasta/$f" "$destino/"; fi
    done
    echo "plano B (o firmware que estava lá, só o código): ~/$destino"
else
    echo "primeira cópia nesta pasta: não há firmware anterior para guardar"
fi
tar -C "$pasta" -xf -
echo "copiado: $# arquivo(s) em ~/$pasta"'

cmd_enviar() {
    local forcar=0 setup=0 simular=0 a
    for a in "${ARGS[@]+"${ARGS[@]}"}"; do
        case "$a" in
            --forcar) forcar=1 ;; --setup) setup=1 ;; --simular) simular=1 ;;
            *) falha "opção desconhecida para enviar: '$a' (use --setup, --forcar ou --simular)." ;;
        esac
    done
    etapa "Firmware"
    command -v git >/dev/null 2>&1 || falha "'git' não encontrado."
    git -C "$RAIZ" rev-parse --is-inside-work-tree >/dev/null 2>&1 || falha "${RAIZ} não é um repositório git."

    # Recusa se o firmware tem mudanças não commitadas: a versão gravada em cada captura tem de apontar para
    # um código que existe.
    local versao mudancas carimbo
    local -a arquivos
    versao="$(git -C "$RAIZ" describe --always)"
    mudancas="$(git -C "$RAIZ" status --porcelain -- firmware ':!firmware/VERSAO')"
    if [ -n "$mudancas" ]; then
        if [ "$forcar" -eq 0 ]; then
            erro "firmware/ tem mudanças não commitadas:"
            printf '%s\n' "$mudancas" | recuar >&2
            dica "Commite antes de enviar (a versão gravada em cada captura tem de apontar para um código que existe),"
            dica "ou use --forcar para enviar assim mesmo, com \"-dirty\" na versão."
            exit 1
        fi
        versao="${versao}-dirty"
        aviso "enviando com mudanças não commitadas: versão ${versao}"
    fi
    mapfile -t arquivos < <(git -C "$RAIZ" ls-files firmware | sed 's|^firmware/||')
    [ "${#arquivos[@]}" -gt 0 ] || falha "git ls-files não achou nada em firmware/."
    arquivos+=(VERSAO)
    carimbo="$(date +%Y-%m-%d_%H%M%S)"   # o relógio do PC: o da BeagleBone pode estar errado (sem RTC)

    info "versão ${N}${versao}${R} → ${ALVO}:~/${PASTA} ${F}(${#arquivos[@]} arquivos)${R}"
    if [ "$simular" -eq 1 ]; then
        info "arquivos: ${F}${arquivos[*]}${R}"
        info "--simular: nada foi escrito nem enviado (o plano B iria para ~/${PASTA}-anteriores/${carimbo}_<versão antiga>/)"
        return 0
    fi
    conectar
    printf '%s\n' "$versao" > "$RAIZ/firmware/VERSAO"
    # shellcheck disable=SC2029  # o comando remoto é montado aqui, protegido com %q
    tar -C "$RAIZ/firmware" -cf - "${arquivos[@]}" \
        | remoto "$(comando_remoto "$ENVIO_REMOTO" "$PASTA" "$carimbo" "${arquivos[@]}")" 2>&1 | recuar \
        || falha "o envio para ${ALVO} falhou (confira o espaço livre: $NOME status)."
    ok "firmware ${versao} na BeagleBone"
    if [ "$setup" -eq 1 ]; then
        cmd_setup
    else
        proximo "Próximo passo: $NOME setup"
    fi
}

# ==============================================================================
# setup: o setup.sh na BeagleBone (pinos, compilação, carga da PRU), sem pedir senha
# ==============================================================================
# O ambiente do terminal do ssh, onde a compilação funciona: um "ssh comando" não lê o /etc/profile, o ~/.profile nem o
# ~/.bashrc, e a imagem da BeagleBone põe num deles o caminho do compilador da PRU (PRU_CGT, PRU_C_DIR ou C_DIR). Os
# perfis são lidos aqui; as variáveis que só o shell interativo define vêm de um 'bash -i' sem terminal (a linha
# marcada separa o valor de qualquer coisa que o ~/.bashrc imprima). O Makefile também procura a instalação sozinho.
SETUP_REMOTO=$(cat <<'FIM'
d=$1; pasta=$2; export SUDO_ASKPASS="$d/askpass"; trap 'rm -rf "$d"' EXIT
for f in /etc/profile "$HOME/.profile"; do if [ -r "$f" ]; then . "$f" >/dev/null 2>&1; fi; done
linha=$(bash -ic 'printf "\nSH-ANALYZER|%s|%s|%s\n" "${PRU_CGT:-}" "${PRU_C_DIR:-}" "${C_DIR:-}"' 2>/dev/null </dev/null \
        | grep '^SH-ANALYZER|' | tail -n 1)
IFS='|' read -r _ i_cgt i_cdir i_c <<< "$linha"
if [ -z "${PRU_CGT:-}" ] && [ -n "$i_cgt" ]; then export PRU_CGT="$i_cgt"; fi
if [ -z "${PRU_C_DIR:-}" ] && [ -n "$i_cdir" ]; then export PRU_C_DIR="$i_cdir"; fi
if [ -z "${C_DIR:-}" ] && [ -n "$i_c" ]; then export C_DIR="$i_c"; fi
cd -- "$pasta" 2>/dev/null || { echo "a pasta ~/$pasta não existe: envie o firmware antes" >&2; exit 1; }
[ -x ./setup.sh ] || { echo "~/$pasta/setup.sh não existe: envie o firmware antes" >&2; exit 1; }
./setup.sh
FIM
)

cmd_setup() {
    etapa "Compilação e PRU ${F}(setup.sh)${R}"
    conectar
    local d
    d=$(preparar_sudo)
    remoto "$(comando_remoto "$SETUP_REMOTO" "$d" "$PASTA")" 2>&1 </dev/null | recuar \
        || falha "o setup.sh falhou: veja as mensagens acima. Plano B: o firmware anterior, em ~/${PASTA}-anteriores/."
    ok "firmware compilado e PRU0 rodando"
    proximo "Confira na largada do ler_adc a linha \"Firmware: $(cat "$RAIZ/firmware/VERSAO" 2>/dev/null || echo '...')\"."
}

# ==============================================================================
# ssh: terminal (ou um comando) na pasta do firmware, com o sudo liberado
# ==============================================================================
# Sessão interativa: um bash cujo rc carrega o ~/.bashrc, faz 'sudo' usar o askpass (sem perguntar) e apaga
# a senha ao sair. Com comando: roda-o com o mesmo 'sudo', na pasta do firmware.
# shellcheck disable=SC2016
SSH_REMOTO='d=$1; pasta=$2; shift 2
export SUDO_ASKPASS="$d/askpass"
cd -- "$pasta" 2>/dev/null || echo "(a pasta ~/$pasta não existe: abrindo no home)"
if [ $# -eq 0 ]; then
    cat > "$d/bashrc" <<FIM
[ -f ~/.bashrc ] && . ~/.bashrc
sudo() { command sudo -A "\$@"; }
trap '\''rm -rf "$d"'\'' EXIT
command sudo -A -v 2>/dev/null || echo "aviso: a senha do sudo foi recusada; ele vai pedir a senha normalmente." >&2
FIM
    exec bash --rcfile "$d/bashrc" -i
fi
trap '\''rm -rf "$d"'\'' EXIT
sudo() { command sudo -A "$@"; }
eval "$*"'

cmd_ssh() {
    conectar
    local d tty=-T
    d=$(preparar_sudo)
    if [ -t 0 ] && [ -t 1 ]; then tty=-t; fi
    if [ "${#ARGS[@]}" -eq 0 ]; then
        printf '\n  %s◆%s %s%s%s  %s~/%s · sudo sem senha · saia com exit ou Ctrl+D%s\n\n' \
            "$N$CIANO" "$R" "$N" "$ALVO" "$R" "$F" "$PASTA" "$R"
        tty=-t
    fi
    local -a remoto_args=("$d" "$PASTA")
    [ "${#ARGS[@]}" -eq 0 ] || remoto_args+=("${ARGS[*]}")   # como no ssh: as palavras juntas, para o shell de lá
    local st=0
    # shellcheck disable=SC2029  # o comando remoto é montado aqui, protegido com %q
    ssh "${SSH_OPCOES[@]}" "$tty" "$ALVO" "$(comando_remoto "$SSH_REMOTO" "${remoto_args[@]}")" || st=$?
    [ "${#ARGS[@]}" -gt 0 ] || printf '\n  %s◆%s sessão encerrada\n' "$N$CIANO" "$R"
    return "$st"
}

# ==============================================================================
# trazer: capturas da BeagleBone para o computador
# ==============================================================================
cmd_trazer() {
    local padrao=${ARGS[0]:-*.bin} destino=${ARGS[1]:-${DIA:-.}}
    etapa "Trazer ${padrao}"
    [ -d "$destino" ] || mkdir -p -- "$destino" || falha "não consegui criar ${destino}."
    conectar
    info "de ${ALVO}:~/${PASTA}/ para ${destino/#$HOME/\~}/"
    scp -rp "${SSH_OPCOES[@]}" "${ALVO}:${PASTA}/${padrao}" "${destino}/" \
        || falha "a cópia falhou (nenhum arquivo com '${padrao}' em ~/${PASTA}?)."
    ok "copiado para ${destino/#$HOME/\~}"
}

# ==============================================================================
# montar / desmontar: o home da BeagleBone numa pasta do computador (sshfs)
# ==============================================================================
# Opções, além das que você já usava (reconnect e os ServerAlive*):
#   idmap=user           os arquivos da placa aparecem como seus (o uid de lá pode ser outro);
#   follow_symlinks      atalhos da placa se comportam como no terminal de lá;
#   dcache_timeout=2     uma captura nova aparece na listagem em 2 s, não em 20 (o padrão);
#   auto_cache           um arquivo que mudou lá (uma captura crescendo) não é lido do cache velho;
#   ControlMaster=no     o sshfs usa uma conexão só dele, que o 'reconnect' pode refazer sozinho;
#   SSH_ASKPASS          a senha vai pelo mesmo caminho do resto do script: o 'reconnect' funciona mesmo
#                        com login por senha (com '-o password_stdin', a reconexão não teria a senha).
SSHFS_OPCOES="reconnect,ServerAliveInterval=15,ServerAliveCountMax=3,idmap=user,follow_symlinks,dcache_timeout=2,auto_cache"
SSHFS_OPCOES+=",ConnectTimeout=8,StrictHostKeyChecking=accept-new,NumberOfPasswordPrompts=1,ControlMaster=no,ControlPath=none"

absoluto() {   # caminho absoluto, mesmo que ainda não exista (sem readlink -m, que o macOS não tem)
    case "$1" in
        /*) printf '%s\n' "$1" ;;
        \~|\~/*) printf '%s\n' "$HOME${1#\~}" ;;
        *) printf '%s/%s\n' "$PWD" "${1#./}" ;;
    esac
}

montado() {   # $1 = pasta absoluta
    if command -v mountpoint >/dev/null 2>&1; then
        mountpoint -q -- "$1"
    else
        mount | grep -q " on $1 "
    fi
}

cmd_montar() {
    local forcar=0 ponto="" a
    for a in "${ARGS[@]+"${ARGS[@]}"}"; do
        case "$a" in --forcar) forcar=1 ;; -*) falha "opção desconhecida para montar: '$a'." ;; *) ponto=$a ;; esac
    done
    ponto=$(absoluto "${ponto:-$MONTAGEM}")
    etapa "Montar o home da BeagleBone"
    command -v sshfs >/dev/null 2>&1 || falha "'sshfs' não encontrado. Instale com: sudo apt install sshfs"
    if montado "$ponto"; then
        ok "já está montado em ${ponto/#$HOME/\~}"
        case "$ponto/" in
            "$RAIZ"/*) aviso "a montagem fica dentro do repositório: um 'git clean -xfd' apagaria arquivos da placa."
                       dica "Prefira uma pasta fora dele: $NOME desmontar ${ponto/#$HOME/\~} && $NOME montar" ;;
        esac
        return 0
    fi
    # Dentro do repositório, um 'git clean -xfd' entraria na montagem e apagaria arquivos DA PLACA (as
    # capturas inclusive), e o git, o editor e o ruff varreriam a placa pela rede.
    case "$ponto/" in
        "$RAIZ"/*)
            if [ "$forcar" -eq 0 ]; then
                erro "${ponto} fica dentro do repositório."
                dica "Lá dentro, um 'git clean -xfd' apagaria arquivos da BeagleBone pela montagem, e o git e o"
                dica "editor varreriam a placa pela rede. Use uma pasta fora dele (o padrão é ~/BeagleBone),"
                dica "ou --forcar se tiver certeza."
                exit 1
            fi
            aviso "montando dentro do repositório (--forcar): cuidado com 'git clean -x'." ;;
    esac
    mkdir -p -- "$ponto"
    if [ -n "$(ls -A -- "$ponto" 2>/dev/null)" ]; then
        falha "${ponto} não está vazia: o sshfs esconderia o que há nela. Use uma pasta vazia."
    fi
    sshfs "${ALVO}:" "$ponto" -o "$SSHFS_OPCOES" \
        || falha "o sshfs não montou (rode '$NOME status' para ver se a placa responde)."
    ok "home de ${ALVO} montado em ${N}${ponto/#$HOME/\~}${R}"
    info "o firmware está em ${ponto/#$HOME/\~}/${PASTA}"
    proximo "Para desmontar: $NOME desmontar"
}

cmd_desmontar() {
    local forcar=0 ponto="" a
    for a in "${ARGS[@]+"${ARGS[@]}"}"; do
        case "$a" in --forcar) forcar=1 ;; -*) falha "opção desconhecida para desmontar: '$a'." ;; *) ponto=$a ;; esac
    done
    ponto=$(absoluto "${ponto:-$MONTAGEM}")
    etapa "Desmontar"
    if ! montado "$ponto"; then
        ok "${ponto/#$HOME/\~} não está montado"
        return 0
    fi
    local -a desmonta
    if command -v fusermount3 >/dev/null 2>&1; then desmonta=(fusermount3 -u)
    elif command -v fusermount >/dev/null 2>&1; then desmonta=(fusermount -u)
    else desmonta=(umount); fi
    if [ "$forcar" -eq 1 ] && [ "${desmonta[0]}" != umount ]; then desmonta+=(-z); fi   # -z: assim que soltarem
    if ! "${desmonta[@]}" "$ponto" 2>/dev/null; then
        erro "${ponto} está em uso (um terminal ou um programa com algo aberto lá dentro?)."
        dica "Feche-o, ou use: $NOME desmontar --forcar"
        exit 1
    fi
    rmdir -- "$ponto" 2>/dev/null || true
    ok "desmontado"
}

# ==============================================================================
# configurar: IP, usuário e senha gravados para as próximas vezes
# ==============================================================================
cmd_configurar() {
    titulo "configurar o acesso"
    printf '\n  %sEnter mantém o valor entre colchetes. Fica em %s (só você lê).%s\n\n' "$F" "${CONFIG/#$HOME/\~}" "$R"
    local v
    read -r -p "    IP da BeagleBone [${IP}]: " v; IP=${v:-$IP}
    read -r -p "    Usuário [${USUARIO}]: " v; USUARIO=${v:-$USUARIO}
    read -r -s -p "    Senha [a atual]: " v; printf '\n'; SENHA=${v:-$SENHA}
    read -r -s -p "    Senha do sudo [a mesma]: " v; printf '\n'; SENHA_SUDO=${v:-$SENHA}
    read -r -p "    Pasta do firmware lá, relativa ao home [${PASTA}]: " v; PASTA=${v:-$PASTA}
    read -r -p "    Pasta para montar a placa no computador [${MONTAGEM}]: " v; MONTAGEM=${v:-$MONTAGEM}
    mkdir -p -- "$(dirname "$CONFIG")"
    (
        umask 077
        {
            printf '# SH-Analyzer: acesso à BeagleBone (gravado por %s configurar)\n' "$NOME"
            printf 'ip=%s\nusuario=%s\nsenha=%s\n' "$IP" "$USUARIO" "$SENHA"
            [ "$SENHA_SUDO" = "$SENHA" ] || printf 'senha_sudo=%s\n' "$SENHA_SUDO"
            printf 'pasta=%s\nmontagem=%s\n' "${PASTA#\~/}" "$MONTAGEM"
        } > "$CONFIG"
    )
    chmod 600 "$CONFIG"
    ALVO="${USUARIO}@${IP}"
    export _SH_ANALYZER_SENHA="$SENHA"
    ok "gravado em ${CONFIG/#$HOME/\~}"
    cmd_status
}

# ==============================================================================
# status: o painel
# ==============================================================================
# Uma conexão só, que devolve chave=valor. $1 = pasta do firmware.
# shellcheck disable=SC2016
STATUS_REMOTO='p=$1
printf "data=%s\n" "$(date -u +%s.%N)"
printf "versao=%s\n" "$(head -c 64 "$p/VERSAO" 2>/dev/null | tr -cd "A-Za-z0-9._-")"
[ -d "$p" ] && echo pasta=1 || echo pasta=0
[ -x "$p/ler_adc" ] && echo compilado=1 || echo compilado=0
printf "pru=%s\n" "$(cat /sys/class/remoteproc/remoteproc1/state 2>/dev/null || echo desconhecido)"
df -Pk "$HOME" 2>/dev/null | awk "NR == 2 { print \"livre_kb=\" \$4; print \"total_kb=\" \$2 }"
n=0; kb=0
for f in "$p"/*.bin; do [ -e "$f" ] || continue; n=$((n + 1)); kb=$((kb + $(du -k "$f" | cut -f1))); done
printf "capturas=%s\ncapturas_kb=%s\n" "$n" "$kb"
printf "ligada=%s\n" "$(cut -d" " -f1 /proc/uptime)"'

kb_legivel() {   # 1234567 -> "1,2 GB"
    awk -v k="$1" 'BEGIN { split("kB MB GB TB", u, " "); i = 1; while (k >= 1024 && i < 4) { k /= 1024; i++ }
        t = (k < 10 && i > 1) ? sprintf("%.1f %s", k, u[i]) : sprintf("%d %s", k + 0.5, u[i]); gsub(/\./, ",", t); print t }'
}

cmd_status() {
    titulo "${ALVO} · ~/${PASTA}"
    printf '\n'
    local t_ini saida t_fim
    t_ini=$(date -u +%s.%N)
    if ! saida=$(ssh "${SSH_OPCOES[@]}" -T "$ALVO" "$(comando_remoto "$STATUS_REMOTO" "$PASTA")" 2>/dev/null </dev/null); then
        campo "Conexão" "${VERMELHO}✗ sem acesso${R}"
        conectar   # diz o motivo e sai
    fi
    t_fim=$(date -u +%s.%N)
    local data='' versao='' pasta=0 compilado=0 pru='' livre_kb=0 total_kb=0 capturas=0 capturas_kb=0 ligada=0
    local chave valor
    while IFS='=' read -r chave valor; do
        case "$chave" in
            data) data=$valor ;; versao) versao=$valor ;; pasta) pasta=$valor ;;
            compilado) compilado=$valor ;; pru) pru=$valor ;; livre_kb) livre_kb=$valor ;; total_kb) total_kb=$valor ;;
            capturas) capturas=$valor ;; capturas_kb) capturas_kb=$valor ;; ligada) ligada=$valor ;;
        esac
    done <<< "$saida"

    campo "Conexão" "${VERDE}✓${R} ligada há $(duracao "$ligada") ${F}(resposta em $(duracao "$(awk -v a="$t_ini" -v b="$t_fim" 'BEGIN { print b - a }')"))${R}"

    # Relógio: a hora da placa contra o meio do intervalo da consulta.
    local diferenca
    diferenca=$(awk -v d="$data" -v a="$t_ini" -v b="$t_fim" 'BEGIN { printf "%.3f", d - (a + b) / 2 }')
    local hora_placa
    hora_placa=$(date -d "@${data%%.*}" '+%Y-%m-%d %H:%M:%S %Z' 2>/dev/null || date -r "${data%%.*}" '+%Y-%m-%d %H:%M:%S %Z')
    if awk -v e="$diferenca" 'BEGIN { exit !(e > -2 && e < 2) }'; then
        campo "Relógio" "${VERDE}✓${R} ${hora_placa} ${F}(certo)${R}"
    else
        local sentido=adiantado
        awk -v e="$diferenca" 'BEGIN { exit !(e < 0) }' && sentido=atrasado
        campo "Relógio" "${AMARELO}!${R} ${hora_placa} ${AMARELO}$(duracao "$diferenca") ${sentido}${R} ${F}→${R} ${N}hora${R}"
    fi

    # Firmware: o que está na placa contra o que o 'enviar' mandaria agora.
    local local_versao=''
    local_versao=$(git -C "$RAIZ" describe --always 2>/dev/null || true)
    if [ "$pasta" != 1 ]; then
        campo "Firmware" "${AMARELO}!${R} ~/${PASTA} não existe ${F}→${R} ${N}enviar --setup${R}"
    elif [ -z "$versao" ]; then
        campo "Firmware" "${AMARELO}!${R} sem VERSAO (anterior ao envio padronizado) ${F}→${R} ${N}enviar --setup${R}"
    elif [ -n "$local_versao" ] && [ "$versao" != "$local_versao" ]; then
        if git -C "$RAIZ" rev-parse -q --verify "${versao%-dirty}^{commit}" >/dev/null 2>&1 \
            && git -C "$RAIZ" diff --quiet "${versao%-dirty}" HEAD -- firmware 2>/dev/null; then
            campo "Firmware" "${VERDE}✓${R} ${versao} ${F}(o firmware é o mesmo do repositório, ${local_versao})${R}"
        else
            campo "Firmware" "${AMARELO}!${R} ${versao} ${AMARELO}(o repositório tem outro: ${local_versao})${R} ${F}→${R} ${N}enviar --setup${R}"
        fi
    else
        campo "Firmware" "${VERDE}✓${R} ${versao} ${F}(o mesmo do repositório)${R}"
    fi
    if [ "$pasta" = 1 ] && [ "$compilado" != 1 ]; then
        campo "" "${AMARELO}!${R} ler_adc não compilado ${F}→${R} ${N}setup${R}"
    fi

    case "$pru" in
        running) campo "PRU0" "${VERDE}✓${R} rodando" ;;
        desconhecido) campo "PRU0" "${AMARELO}!${R} sem remoteproc1 (o overlay da PRU está ativo?)" ;;
        *) campo "PRU0" "${AMARELO}!${R} ${pru} ${F}→${R} ${N}setup${R}" ;;
    esac

    local livre_txt
    livre_txt="$(kb_legivel "$livre_kb") livres de $(kb_legivel "$total_kb")"
    if [ "$livre_kb" -lt 524288 ]; then
        campo "Disco" "${AMARELO}!${R} ${livre_txt} ${F}(menos de 512 MB: traga as capturas e apague-as lá)${R}"
    else
        # 100 kS/s = 200 kB/s = 11 719 kB por minuto
        campo "Disco" "${VERDE}✓${R} ${livre_txt} ${F}(~$(duracao $(( livre_kb * 60 / 11719 ))) de captura a 100 kS/s)${R}"
    fi
    if [ "$capturas" -gt 0 ]; then
        campo "Capturas" "${capturas} arquivo(s) .bin em ~/${PASTA} ($(kb_legivel "$capturas_kb")) ${F}→${R} ${N}trazer${R}"
    else
        campo "Capturas" "${F}nenhum .bin em ~/${PASTA}${R}"
    fi

    local ponto
    ponto=$(absoluto "$MONTAGEM")
    if montado "$ponto"; then
        campo "Montagem" "${VERDE}✓${R} ${ponto/#$HOME/\~}"
    else
        campo "Montagem" "${F}não montada →${R} ${N}montar${R}"
    fi
    printf '\n'
}

# ==============================================================================
# preparar: tudo para começar o dia
# ==============================================================================
cmd_preparar() {
    titulo "preparar: hora, firmware e PRU"
    conectar
    cmd_hora
    ARGS=(--setup)
    cmd_enviar
    cmd_status
    printf '  %sPronto.%s Para capturar: %s%s ssh%s\n\n' "$N$VERDE" "$R" "$N" "$NOME" "$R"
}

case "$COMANDO" in
    status) cmd_status ;;
    preparar) cmd_preparar ;;
    hora) titulo "$ALVO"; conectar; cmd_hora; printf '\n' ;;
    enviar) titulo "$ALVO"; cmd_enviar; printf '\n' ;;
    setup) titulo "$ALVO"; cmd_setup; printf '\n' ;;
    ssh) cmd_ssh ;;
    trazer) titulo "$ALVO"; cmd_trazer; printf '\n' ;;
    montar) titulo "$ALVO"; cmd_montar; printf '\n' ;;
    desmontar) titulo "$ALVO"; cmd_desmontar; printf '\n' ;;
    configurar) cmd_configurar ;;
    *) falha "comando desconhecido: '${COMANDO}' (veja $NOME ajuda)." ;;
esac
