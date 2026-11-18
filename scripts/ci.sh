#!/usr/bin/env bash
# Roda localmente os mesmos testes da CI do GitHub: o .github/workflows/ci.yml chama este script, então os
# comandos e as versões das ferramentas vivem num lugar só. Rode da raiz do repositório (ou de qualquer lugar).
#
#   scripts/ci.sh                  tudo: o firmware e a suíte inteira em Python 3.13 (com a interface) e em 3.10 (sem o Qt)
#   scripts/ci.sh rapido           ruff + pytest sem os e2e e sem o Qt (Python 3.13) + firmware: antes de cada commit
#   scripts/ci.sh testes [VERSAO]  ruff + pytest sem o Qt numa versão do Python (padrão 3.13): o motor, o sh_placa e o agente
#   scripts/ci.sh firmware         gcc -Werror no ler_adc.c e shellcheck nos scripts de shell
#   scripts/ci.sh interface        os testes da interface gráfica (PySide6 e pytest-qt, sem tela)
#
# Precisa do uv (que baixa sozinho as versões do Python e o shellcheck) e do gcc. Sem o zpaq, os testes do
# compactar_amostras são pulados (a CI os roda: sudo apt install zpaq); sem o gcc-arm-linux-gnueabihf, o ler_adc.c
# não é compilado para o ARM de 32 bits (a CI compila). Os ambientes ficam em .venv-ci/<versão do Python>[-qt]: o .venv
# é o de quem desenvolve (a interface aberta por ele), e a CI nunca o troca de Python nem de pacotes.
set -euo pipefail

readonly SHELLCHECK="shellcheck-py==0.11.0.1"  # versão FIXA: a do Ubuntu da CI (0.9) acusava o que a local não via

cd "$(dirname "${BASH_SOURCE[0]}")/.."

etapa() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }

uvpy() {   # $1 = versão do Python; $2 = sem_qt | com_qt; o resto vai para o uv run
    # Um ambiente por versão do Python e por Qt, fora do .venv: o uv recriaria o .venv a cada troca de Python, e quem
    # abrisse a interface no meio da CI (ou depois de uma CI interrompida) a teria na versão que a CI deixou. --exact:
    # cada ambiente só com os extras dele (o sem_qt prova que o motor, o sh_placa e o agente rodam sem o PySide6), e
    # um ambiente para cada um não desinstala e reinstala o Qt a cada troca de etapa.
    local py="$1" qt="$2"
    shift 2
    local extras=(--extra dev --extra placa)
    [[ $qt == com_qt ]] && extras=(--extra gui-dev)   # o gui-dev traz o dev, o placa, o PySide6 e o pytest-qt
    UV_PROJECT_ENVIRONMENT=".venv-ci/${py}${qt/#com_qt/-qt}" uv run --exact --python "$py" "${extras[@]}" "$@"
}

suite() {   # $1 = versão do Python; $2 = sem_qt | com_qt; o resto vai para o pytest
    local py="$1" qt="$2"
    shift 2
    etapa "ruff (Python ${py})"
    # O agente da placa fica em firmware/ (que o ruff pula), mas é Python: confere nomeando o arquivo.
    uvpy "$py" "$qt" ruff check . firmware/agente/shan_agente.py
    local rotulo="sem o Qt"
    [[ $qt == com_qt ]] && rotulo="com a interface"
    etapa "pytest (Python ${py}, ${rotulo}) $*"
    # Uma rodada só, em paralelo (o -n auto do pyproject.toml): o motor, o sh_placa, o agente e, com o Qt, a
    # interface sem tela. Os testes da arquitetura conferem num processo novo que a rede e o Qt não vazam para o motor.
    QT_QPA_PLATFORM=offscreen uvpy "$py" "$qt" pytest "$@"
}

interface() {   # a interface sozinha (o job dela no GitHub, ao lado dos de testes)
    etapa "pytest da interface gráfica (PySide6, sem tela)"
    QT_QPA_PLATFORM=offscreen uvpy 3.13 com_qt pytest \
        tests/test_interface.py tests/test_gui_*.py tests/test_arquitetura.py tests/test_marca.py
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
    tudo)      firmware; suite 3.13 com_qt; suite 3.10 sem_qt ;;
    rapido)    suite 3.13 sem_qt -m "not e2e"; firmware ;;
    testes)    suite "${2:-3.13}" sem_qt ;;
    firmware)  firmware ;;
    interface) interface ;;
    -h|--help) sed -n '2,14p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *)         echo "Uso: scripts/ci.sh [tudo | rapido | testes [VERSAO] | firmware | interface]  (--help para detalhes)" >&2; exit 2 ;;
esac
etapa "tudo certo"
