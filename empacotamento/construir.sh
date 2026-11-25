#!/usr/bin/env bash
# Constrói o aplicativo empacotado (o PyInstaller, numa pasta) e confere o pacote pronto (F7.12 em
# docs/gui-progress.md, 4h). O mesmo no computador de quem desenvolve e na CI dos instaladores
# (.github/workflows/instaladores.yml), no Linux e no Windows (no Git Bash).
#
#   empacotamento/construir.sh PASTA        constrói em PASTA/dist/sh-analyzer-gui e confere
#   empacotamento/construir.sh PASTA --so-conferir
#
# PASTA fica fora do repositório (a construção tem ~400 MB). O ambiente é o .venv-ci/empacotar-<versão do Python>,
# com os extras gui e placa e o PyInstaller na versão fixa abaixo: o .venv de quem desenvolve não é tocado.
# As conferências: a versão (--versao); a janela que abre e pinta o primeiro quadro, sem tela (--sair-ao-abrir); e o
# empacotamento/conferir_pacote.py rodado pelo próprio executável (os módulos, os dados, o agente, o exemplo e a
# placa simulada). As pastas de configuração, cache e dados das conferências são temporárias, e o cofre de senhas é
# o que recusa tudo: nada do usuário muda.
set -euo pipefail

readonly PYINSTALLER="pyinstaller==6.16.0"     # versão FIXA: a troca muda o pacote sem aviso
readonly PYTHON="${SH_PYTHON:-3.13}"

[[ $# -ge 1 ]] || { sed -n '2,14p' "$0" | sed 's/^# \{0,1\}//'; exit 2; }
cd "$(dirname "${BASH_SOURCE[0]}")/.."
mkdir -p "$1"
pasta="$(cd "$1" && pwd)"
case "$pasta/" in "$PWD"/*) echo "PASTA fica fora do repositório: $pasta" >&2; exit 2 ;; esac

etapa() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }

if [[ ${2:-} != --so-conferir ]]; then
    etapa "PyInstaller (${PYINSTALLER}, Python ${PYTHON})"
    inicio=$SECONDS
    UV_PROJECT_ENVIRONMENT=".venv-ci/empacotar-${PYTHON}" uv run --exact --python "$PYTHON" --extra gui --extra placa \
        --with "$PYINSTALLER" pyinstaller empacotamento/sh-analyzer-gui.spec \
        --distpath "$pasta/dist" --workpath "$pasta/obra" --noconfirm --log-level WARN
    echo "construído em $((SECONDS - inicio)) s"
fi

app="$pasta/dist/sh-analyzer-gui"
exe="$app/sh-analyzer-gui"
[[ -x "$exe" ]] || exe="$app/sh-analyzer-gui.exe"
[[ -x "$exe" ]] || { echo "sem o executável em $app" >&2; exit 1; }

# Um usuário de mentira: a configuração, o cache, os dados e o log das conferências numa pasta que some no fim.
casa="$(mktemp -d)"
trap 'rm -rf "$casa"' EXIT
export XDG_CONFIG_HOME="$casa/config" XDG_CACHE_HOME="$casa/cache" XDG_DATA_HOME="$casa/dados" \
       XDG_STATE_HOME="$casa/estado" APPDATA="$casa/appdata" LOCALAPPDATA="$casa/localappdata" \
       QT_QPA_PLATFORM=offscreen PYTHON_KEYRING_BACKEND=keyring.backends.fail.Keyring

etapa "a versão"
"$exe" --versao

etapa "a janela abre e pinta o primeiro quadro (sem tela)"
inicio=$(date +%s%N)
"$exe" --sair-ao-abrir
echo "aberta e fechada em $(( ($(date +%s%N) - inicio) / 1000000 )) ms"

etapa "o pacote por dentro (empacotamento/conferir_pacote.py, no executável)"
SHAN_COMO_PYTHON=1 "$exe" empacotamento/conferir_pacote.py

etapa "o tamanho"
du -sh "$app" | cut -f1
etapa "pronto: $app"
