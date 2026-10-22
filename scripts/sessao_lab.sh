#!/usr/bin/env bash
# ==============================================================================
# sessao_lab.sh -- começa (e acompanha) uma sessão de testes no laboratório, do computador.
#
# Feito para um alias, o mesmo no fish e no bash (o ~/.canela.profile é lido pelos dois):
#   alias lab='eval "$(/caminho/do/repo/scripts/sessao_lab.sh --variaveis)" && /caminho/do/repo/scripts/sessao_lab.sh'
#
#   lab                a sessão do dia: DADOS, DIA e a pasta do repositório no terminal, a pasta do dia com o
#                      caderno, e o estado de tudo (código, placa, montagem, disco, notebook). Pode repetir.
#   lab preparar       e então o 'preparar' da placa: relógio, firmware, compilação e PRU
#   lab ssh            e então o terminal da placa, gravado em $DIA/terminal_bbb.txt
#   lab trazer 'T7*'   e então as capturas da placa para $DIA
#   lab notas          e então o caderno ($DIA/anotacoes.md) no editor
#   lab pasta          e então $DIA no gerenciador de arquivos
#   lab <comando>      e então qualquer outro comando do BeagleBone_Setup.sh (status, hora, montar, desmontar...)
#
# POR QUE DUAS CHAMADAS: um programa não muda as variáveis nem a pasta do terminal que o chamou. A 1ª chamada
# (--variaveis) cria a pasta e o caderno e ESCREVE os comandos (export ... e cd ...) que o eval do alias roda no
# próprio terminal; 'export X=...' e 'cd' valem igual no fish e no bash. A 2ª, já com as variáveis, recebe os
# argumentos do alias e faz o resto.
#
# AS VARIÁVEIS:
#   DADOS        onde ficam as capturas: a que já estiver no ambiente, senão ~/Documents/sh-analyzer-data
#   DIA          $DADOS/lab/AAAA-MM-DD, a pasta da sessão. É a de hoje, a não ser que o terminal já tenha um DIA
#                com arquivos mexidos nas últimas 6 h (uma sessão que passou da meia-noite continua na mesma
#                pasta). Para outra: export DIA=... (ou set -gx DIA ... no fish) antes do lab.
#   SH_ANALYZER  a raiz deste repositório
#
# PARA OUTRO PROJETO: copie o arquivo e troque o bloco "O projeto", logo abaixo.
# ==============================================================================

set -uo pipefail

# ------------------------------------------------------------------------------
# O projeto
# ------------------------------------------------------------------------------
RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
NOME_PROJETO="SH-Analyzer"
VARIAVEL_RAIZ="SH_ANALYZER"                                   # a variável exportada com a raiz do repositório
DADOS_PADRAO="$HOME/Documents/sh-analyzer-data"
MODELO_CADERNO="$RAIZ/docs/lab-notes-template.md"
PLACA="$RAIZ/scripts/BeagleBone_Setup.sh"                     # a ferramenta da placa; os comandos desconhecidos vão para ela
CONFIG_PLACA="${XDG_CONFIG_HOME:-$HOME/.config}/sh-analyzer/beaglebone.conf"   # o ip=... gravado pelo 'configurar'
IP_PADRAO=192.168.6.2
ESPACO_MINIMO_MB=3072                                         # uma ida ao laboratório chega a ~1,5 GB de capturas

# ------------------------------------------------------------------------------
# Aparência (as mensagens da 1ª chamada vão para o stderr: o stdout é do eval)
# ------------------------------------------------------------------------------
cores() {   # $1 = o descritor em que as mensagens saem
    if [ -t "$1" ] && [ -z "${NO_COLOR:-}" ] && [ "${TERM:-}" != dumb ]; then
        N=$'\e[1m' F=$'\e[2m' R=$'\e[0m' AMARELO=$'\e[33m' VERMELHO=$'\e[31m' CIANO=$'\e[36m'
    else
        N='' F='' R='' AMARELO='' VERMELHO='' CIANO=''
    fi
}
campo() {   # rótulo alinhado + valor
    printf '    %s%s%*s%s %s\n' "$F" "$1" $((10 - ${#1})) '' "$R" "$2"
}
alerta() {  # rótulo alinhado + aviso em amarelo
    printf '    %s%s%*s%s %s! %s%s\n' "$F" "$1" $((10 - ${#1})) '' "$R" "$AMARELO" "$2" "$R"
}
curto() { printf '%s' "${1/#$HOME/\~}"; }

# ------------------------------------------------------------------------------
# 1ª chamada: a pasta do dia, o caderno e os comandos para o terminal
# ------------------------------------------------------------------------------
if [ "${1:-}" = --variaveis ]; then
    cores 2
    exec 3>&1 1>&2                    # daqui em diante, o que for impresso vai para o terminal; só o fd 3 é do eval
    desistir() { printf '    %s✗ %s%s\n' "$VERMELHO" "$*" "$R"; echo false >&3; exit 1; }   # o eval devolve erro: o alias para

    DADOS=${DADOS:-$DADOS_PADRAO}
    hoje="$DADOS/lab/$(date +%F)"
    dia=$hoje
    origem="nova"
    if [ -n "${DIA:-}" ] && [ "$DIA" != "$hoje" ] && [ -d "$DIA" ] \
       && [ -n "$(find "$DIA" -maxdepth 2 -newermt '6 hours ago' -print -quit 2>/dev/null)" ]; then
        dia=$DIA
        origem="a da sessão em andamento (mexida nas últimas 6 h)"
    elif [ -d "$hoje" ]; then
        origem="já existia"
    fi
    for valor in "$DADOS" "$dia" "$RAIZ"; do
        case "$valor" in *"'"*) desistir "o caminho '$valor' tem um apóstrofo: o eval do fish e o do bash não o leem igual." ;; esac
    done
    mkdir -p "$dia/fotos" || desistir "não consegui criar $(curto "$dia")."

    caderno="$dia/anotacoes.md"
    if [ -e "$caderno" ]; then
        estado_caderno="já existia"
    elif [ -r "$MODELO_CADERNO" ]; then
        sed "s/AAAA-MM-DD/$(basename "$dia")/" "$MODELO_CADERNO" > "$caderno" || desistir "não consegui criar $(curto "$caderno")."
        estado_caderno="criado do modelo: preencha durante a sessão"
    else
        estado_caderno="sem o modelo ($(curto "$MODELO_CADERNO")): crie o seu"
    fi

    printf '\n  %s◆ %s%s %s· sessão de laboratório%s   %s%s%s\n' "$N$CIANO" "$NOME_PROJETO" "$R" "$N" "$R" "$F" \
        "$(date '+%a %d/%m/%Y %H:%M')" "$R"
    arquivos=$(find "$dia" -type f ! -name anotacoes.md | wc -l)
    campo "DIA" "$(curto "$dia")  ${F}($origem$( [ "$arquivos" -eq 0 ] || echo ", $arquivos arquivo(s)"))${R}"
    campo "caderno" "anotacoes.md  ${F}($estado_caderno)${R}"

    printf "export DADOS='%s'\nexport DIA='%s'\nexport %s='%s'\ncd '%s'\n" "$DADOS" "$dia" "$VARIAVEL_RAIZ" "$RAIZ" "$RAIZ" >&3
    exit 0
fi

# ------------------------------------------------------------------------------
# 2ª chamada: o estado da sessão, ou o comando pedido
# ------------------------------------------------------------------------------
cores 1
if [ -z "${DIA:-}" ]; then
    printf '    %s✗ DIA não está definida: rode pelo alias (veja o topo de %s).%s\n' "$VERMELHO" "${BASH_SOURCE[0]}" "$R" >&2
    exit 1
fi

ip_da_placa() {   # BBB_IP > o ip= do 'configurar' (lido como dado) > o padrão da imagem
    local ip=$IP_PADRAO chave valor
    if [ -r "$CONFIG_PLACA" ]; then
        while IFS='=' read -r chave valor || [ -n "$chave" ]; do
            [ "$chave" != ip ] || ip=$valor
        done < "$CONFIG_PLACA"
    fi
    printf '%s' "${BBB_IP:-$ip}"
}

estado() {
    local versao ramo enviar ip montagens ponto livre online bateria fonte

    # O código: a versão que o 'enviar' grava em firmware/VERSAO e que vai para cada captura. Só comandos que olham os
    # arquivos versionados (nada de 'git status': ele encostaria na montagem da placa, que pode estar pendurada).
    if versao=$(timeout 5 git -C "$RAIZ" describe --always --dirty 2>/dev/null); then
        ramo=$(timeout 5 git -C "$RAIZ" rev-parse --abbrev-ref HEAD 2>/dev/null)
        enviar=$(timeout 5 git -C "$RAIZ" rev-list --count '@{u}..HEAD' 2>/dev/null || echo 0)
        if [ "${versao%-dirty}" != "$versao" ]; then
            alerta "código" "$versao ($ramo): há alterações não commitadas, e as capturas sairão marcadas -dirty"
        else
            campo "código" "$versao  ${F}($ramo$( [ "${enviar:-0}" -eq 0 ] || echo "; $enviar commit(s) ainda não enviados ao GitHub"))${R}"
        fi
    else
        alerta "código" "$(curto "$RAIZ") não é um repositório git: as capturas sairão sem a versão do código"
    fi

    # A placa: a porta do ssh responde?
    ip=$(ip_da_placa)
    online=0
    if timeout 1 bash -c "exec 3<>/dev/tcp/$ip/22" 2>/dev/null; then
        online=1
        campo "placa" "$ip responde  ${F}(lab status: firmware, relógio, PRU e disco de lá)${R}"
    else
        alerta "placa" "$ip não responde: ligue o USB da BeagleBone (ela leva ~1 min para subir)"
    fi

    # Montagens sshfs da placa: com ela fora, travam quem encostar nelas (o pytest e o 'ls' do repositório).
    # Lidas de /proc/mounts, sem tocar no ponto de montagem.
    montagens=$(awk -v ip="@$ip:" '$3 == "fuse.sshfs" && index($1, ip) { print $2 }' /proc/mounts 2>/dev/null)
    while IFS= read -r ponto; do
        [ -n "$ponto" ] || continue
        ponto=$(printf '%b' "$ponto")                             # /proc/mounts escreve o espaço como \040
        if [ "$online" -eq 1 ]; then
            campo "montagem" "$(curto "$ponto")"
        else
            alerta "montagem" "$(curto "$ponto") montada com a placa fora: trava quem encostar nela. lab desmontar '$ponto' --forcar"
        fi
    done <<< "$montagens"

    # O espaço no computador para as capturas
    livre=$(df -Pk "$DADOS" 2>/dev/null | awk 'NR == 2 { print int($4 / 1024) }')
    if [ -n "$livre" ] && [ "$livre" -lt "$ESPACO_MINIMO_MB" ]; then
        alerta "disco" "só $((livre / 1024)) GB livres em $(curto "$DADOS") (uma sessão chega a ~1,5 GB)"
    elif [ -n "$livre" ]; then
        campo "disco" "$((livre / 1024)) GB livres em $(curto "$DADOS")"
    fi

    # O relógio do computador vai para a placa ('hora') e, dela, para cada captura
    if [ "$(timedatectl show -p NTPSynchronized --value 2>/dev/null)" = no ]; then
        alerta "relógio" "o do computador não está sincronizado (NTP): a hora das capturas vem dele"
    fi

    # O notebook na bateria ou no carregador muda a interferência da rede na bancada: vai para o caderno
    fonte=''
    for ac in /sys/class/power_supply/{AC,ADP,ACAD}*/online; do
        [ -r "$ac" ] || continue
        if [ "$(cat "$ac")" = 1 ]; then fonte="no carregador"; else fonte="na bateria"; fi
        break
    done
    for bat in /sys/class/power_supply/BAT*/capacity; do
        [ -r "$bat" ] && bateria=$(cat "$bat") && fonte="${fonte:-com bateria}, ${bateria} %" && break
    done
    [ -z "$fonte" ] || campo "notebook" "$fonte  ${F}(anote no caderno: muda a interferência da rede)${R}"

    printf '\n  %s▸ Próximo%s\n' "$N$CIANO" "$R"
    printf '    %slab preparar%s       relógio, firmware, compilação e PRU da placa\n' "$N" "$R"
    printf '    %slab ssh%s            o terminal da placa, gravado em %s\n' "$N" "$R" "$(curto "$DIA")/terminal_bbb.txt"
    printf "    %slab trazer 'T7*'%s   no fim: as capturas da placa para o DIA\n" "$N" "$R"
    printf '    %slab notas · lab pasta · lab status · lab ajuda%s\n\n' "$F" "$R"
}

uso() {
    sed -n '/^#   lab  /,/^#   lab <comando>/p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
}

case "${1:-}" in
    '') estado ;;
    ajuda|-h|--help) uso ;;
    ssh)
        shift
        # O 'script' roda o comando com o $SHELL -c (o fish, aqui): com o /bin/sh, a linha vale em qualquer um.
        SHELL=/bin/sh exec script -q -a "$DIA/terminal_bbb.txt" -c "'$PLACA' ssh $*" ;;
    notas)
        editor=${VISUAL:-${EDITOR:-nvim}}
        command -v "$editor" > /dev/null || editor=xdg-open
        exec "$editor" "$DIA/anotacoes.md" ;;
    pasta) xdg-open "$DIA" > /dev/null 2>&1 & ;;
    *) exec "$PLACA" "$@" ;;
esac
