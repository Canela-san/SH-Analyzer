#!/usr/bin/env bash
# O pacote .deb num sistema limpo (roda DENTRO de um contêiner Debian ou Ubuntu, como root; a CI dos instaladores e
# a do apt o chamam com `docker run`):
#
#   testar_no_conteiner.sh deb ARQUIVO.deb         instala o .deb, abre sem tela e no X (xvfb), remove
#   testar_no_conteiner.sh atualizar REPO1 REPO2   o repositório REPO1 (pastas montadas), instala, troca para o REPO2
#                                                  e confere que o upgrade traz a versão nova
#   testar_no_conteiner.sh repositorio URL         os comandos do README contra o repositório publicado
#
# Abrir de verdade confere as dependências do pacote: o que faltar (uma biblioteca do xcb, o fontconfig) aparece aqui,
# e não no computador de quem instala.
set -euo pipefail

export DEBIAN_FRONTEND=noninteractive LANG=C.UTF-8
etapa() { printf '\n==> %s\n' "$*"; }

apt_get() {   # o apt calado, com o log inteiro se falhar
    if ! apt-get "$@" >/tmp/apt.log 2>&1; then
        cat /tmp/apt.log
        return 1
    fi
}

abrir() {   # o aplicativo instalado abre e fecha sozinho, sem tela e no X
    local casa
    casa=$(mktemp -d)
    etapa "abrir ($(sh-analyzer --versao))"
    env HOME="$casa" XDG_CONFIG_HOME="$casa/config" XDG_CACHE_HOME="$casa/cache" XDG_DATA_HOME="$casa/dados" \
        PYTHON_KEYRING_BACKEND=keyring.backends.fail.Keyring QT_QPA_PLATFORM=offscreen \
        timeout 180 sh-analyzer --sair-ao-abrir
    apt_get install -y --no-install-recommends xvfb xauth
    env HOME="$casa" XDG_CONFIG_HOME="$casa/config" XDG_CACHE_HOME="$casa/cache" XDG_DATA_HOME="$casa/dados" \
        PYTHON_KEYRING_BACKEND=keyring.backends.fail.Keyring QT_QPA_PLATFORM=xcb \
        timeout 180 xvfb-run -a sh-analyzer --sair-ao-abrir
    echo "abriu sem tela e no X"
}

instalado() { dpkg-query -W -f '${Version}' sh-analyzer; }

conferir_arquivos() {
    test -x /usr/bin/sh-analyzer
    test -f /usr/share/applications/sh-analyzer.desktop
    test -f /usr/share/mime/packages/sh-analyzer.xml
    test -f /usr/share/icons/hicolor/scalable/apps/sh-analyzer.svg
    test -f /usr/share/keyrings/sh-analyzer.gpg
    test -f /etc/apt/sources.list.d/sh-analyzer.sources
    echo "o atalho, o tipo dos projetos, o ícone e a fonte do apt estão no lugar"
}

remover() {
    etapa "remover"
    apt_get purge -y sh-analyzer
    test ! -e /opt/sh-analyzer && test ! -e /usr/bin/sh-analyzer && test ! -e /etc/apt/sources.list.d/sh-analyzer.sources
    echo "removido sem sobras"
}

case "${1:-}" in
    deb)
        etapa "instalar $(basename "$2") em $(. /etc/os-release && echo "$PRETTY_NAME")"
        apt_get update
        apt_get install -y "$2"
        conferir_arquivos
        abrir
        remover
        ;;
    atualizar)
        etapa "o repositório local, a instalação e o upgrade"
        # As fontes do sistema (as dependências) mais a de teste, numa pasta à parte: a fonte que o pacote instala
        # aponta para o repositório publicado, que aqui fica de fora.
        mkdir -p /tmp/fontes
        cp /etc/apt/sources.list.d/*.sources /tmp/fontes/ 2>/dev/null || true
        ln -sfn "$2" /repo
        cp /repo/sh-analyzer.gpg /usr/share/keyrings/sh-analyzer-teste.gpg
        printf 'Types: deb\nURIs: file:/repo\nSuites: stable\nComponents: main\nSigned-By: %s\n' \
            /usr/share/keyrings/sh-analyzer-teste.gpg > /tmp/fontes/teste.sources
        so_estas=(-o Dir::Etc::sourceparts=/tmp/fontes)
        apt_get update "${so_estas[@]}"
        apt_get install -y "${so_estas[@]}" sh-analyzer
        antes=$(instalado)
        ln -sfn "$3" /repo
        apt_get update "${so_estas[@]}"
        apt_get upgrade -y "${so_estas[@]}"
        depois=$(instalado)
        echo "instalado: $antes; depois do upgrade: $depois"
        dpkg --compare-versions "$depois" gt "$antes"
        ;;
    repositorio)
        etapa "os comandos do README contra $2 em $(. /etc/os-release && echo "$PRETTY_NAME")"
        apt_get update
        apt_get install -y --no-install-recommends wget ca-certificates
        wget -qO /usr/share/keyrings/sh-analyzer.gpg "$2/sh-analyzer.gpg"
        wget -qO /etc/apt/sources.list.d/sh-analyzer.sources "$2/sh-analyzer.sources"
        apt_get update
        apt_get install -y sh-analyzer
        echo "instalado pelo repositório: $(instalado)"
        conferir_arquivos
        abrir
        ;;
    *)
        sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//'
        exit 2
        ;;
esac
