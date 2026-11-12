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
# compactar_amostras são pulados (a CI os roda: sudo apt install zpaq); sem o gcc-arm-linux-gnueabihf, o ler_adc.c
# não é compilado para o ARM de 32 bits (a CI compila).
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
    # --extra gui: o PyQt6, para os testes da interface gráfica (sem tela: QT_QPA_PLATFORM=offscreen, que o
    # tests/test_gui.py liga sozinho). Sem o extra, esses testes são pulados.
    etapa "pytest (Python ${py}) $*"
    uv run --python "$py" --extra dev --extra gui pytest "$@"
}

firmware() {
    etapa "gcc -Werror: firmware/ler_adc.c (o clpru da PRU é proprietário e fica de fora)"
    gcc -std=gnu11 -Wall -Wextra -Werror -fsyntax-only firmware/ler_adc.c
    # A BeagleBone é um ARM de 32 bits: tipos de outro tamanho (off_t, time_t, long) e o _Static_assert do off_t de
    # 64 bits só aparecem compilando para ela. Sem o compilador cruzado, só avisa (a CI do GitHub o instala).
    if command -v arm-linux-gnueabihf-gcc > /dev/null; then
        etapa "arm-linux-gnueabihf-gcc: firmware/ler_adc.c para o ARM de 32 bits da BeagleBone"
        arm-linux-gnueabihf-gcc -std=gnu11 -Wall -Wextra -fsyntax-only firmware/ler_adc.c
    else
        echo "Aviso: sem o arm-linux-gnueabihf-gcc, o ler_adc.c não é compilado para 32 bits (sudo apt install gcc-arm-linux-gnueabihf)." >&2
    fi
    etapa "shellcheck (${SHELLCHECK}): firmware/*.sh firmware/coleta/*.sh scripts/*.sh"
    uvx --quiet --from "$SHELLCHECK" shellcheck -x firmware/*.sh firmware/coleta/*.sh scripts/*.sh
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
