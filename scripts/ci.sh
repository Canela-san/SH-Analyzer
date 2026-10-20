#!/usr/bin/env bash
# Roda localmente EXATAMENTE o que a CI do GitHub roda: o .github/workflows/ci.yml chama este script, então os
# comandos e as versões das ferramentas vivem num lugar só. Rode da raiz do repositório (ou de qualquer lugar).
#
#   scripts/ci.sh                  tudo: ruff + pytest em Python 3.10 e 3.13, e o firmware (~3 min)
#   scripts/ci.sh rapido           ruff + pytest sem os e2e (Python 3.13) + firmware: antes de cada commit (~30 s)
#   scripts/ci.sh testes [VERSAO]  ruff + pytest completo numa versão do Python (padrão 3.13)
#   scripts/ci.sh firmware         gcc -Werror no ler_adc.c e shellcheck nos scripts de shell
#
# Precisa do uv (que baixa sozinho as versões do Python e o shellcheck) e do gcc. Sem o zpaq, os testes do
# compactar_amostras são pulados (a CI os roda: sudo apt install zpaq).
set -euo pipefail

readonly VERSOES_PYTHON=(3.10 3.13)            # a matriz da CI: o mínimo do pyproject.toml e a mais nova
readonly SHELLCHECK="shellcheck-py==0.11.0.1"  # versão FIXA: a do Ubuntu da CI (0.9) acusava o que a local não via

cd "$(dirname "${BASH_SOURCE[0]}")/.."

etapa() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }

testes() {   # $1 = versão do Python; o resto vai para o pytest
    local py="$1"
    shift
    etapa "ruff (Python ${py})"
    uv run --python "$py" --extra dev ruff check .
    etapa "pytest (Python ${py}) $*"
    uv run --python "$py" --extra dev pytest "$@"
}

firmware() {
    etapa "gcc -Werror: firmware/ler_adc.c (o clpru da PRU é proprietário e fica de fora)"
    gcc -std=gnu11 -Wall -Wextra -Werror -fsyntax-only firmware/ler_adc.c
    etapa "shellcheck (${SHELLCHECK}): firmware/*.sh scripts/*.sh"
    uvx --quiet --from "$SHELLCHECK" shellcheck firmware/*.sh scripts/*.sh
}

command -v zpaq > /dev/null || echo "Aviso: sem o zpaq, os testes do compactar_amostras são pulados (sudo apt install zpaq)." >&2

case "${1:-tudo}" in
    tudo)      for py in "${VERSOES_PYTHON[@]}"; do testes "$py"; done; firmware ;;
    rapido)    testes 3.13 -m "not e2e"; firmware ;;
    testes)    testes "${2:-3.13}" ;;
    firmware)  firmware ;;
    -h|--help) sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *)         echo "Uso: scripts/ci.sh [tudo | rapido | testes [VERSAO] | firmware]  (--help para detalhes)" >&2; exit 2 ;;
esac
etapa "tudo certo"
