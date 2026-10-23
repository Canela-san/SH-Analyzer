#!/bin/bash
# ==============================================================================
# coletar.sh -- as coletas de dados do SH-Analyzer, na BeagleBone (na pasta do firmware, ao lado do ler_adc).
#
# Cada modo chama o ler_adc do jeito certo para uma finalidade, grava as capturas numa pasta própria (aqui, onde o
# 'lab trazer' as busca), confere cada uma e diz, no fim, o comando de análise no computador. Os modos estão em
# coleta/ (sonda.sh, campanha.sh, teto.sh, conferir.sh; o que eles compartilham, em coleta/comum.sh).
# ==============================================================================

set -uo pipefail
DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

ajuda() {
    cat <<'FIM'
Uso: ./coletar.sh MODO [opções]          ./coletar.sh MODO --help: as opções de cada modo

As coletas de dados do SH-Analyzer. Sem opções, cada modo usa a configuração que dá uma boa análise depois.

Modos
  conferir   ~10 s: o firmware, os pinos e o ADC respondendo; nível, offset e ruído do sinal e a faixa
             certa para ele. Rode antes de uma série de capturas e depois de mexer na bancada.
  sonda      a calibração de uma sonda por senoides, ponto a ponto (o antigo calibrar_sonda.sh)
  cadeia     a resposta da cadeia, magnitude e fase, por ondas quadradas (o antigo varrer_taxa.sh --fase)
  aliasing   o mesmo sinal em 3 taxas, para separar componentes reais de imagens (adc_tool.py aliasing)
  ruido      o piso de ruído com a entrada em curto, nas 3 faixas do ADC
  teto       a maior taxa com toda amostra na grade, por varredura em frequência, e a taxa de trabalho
  bancada    as varreduras de hardware do T7: esperas do CS, taxa, grade, SPI (o antigo varrer_taxa.sh)

Exemplos
  ./coletar.sh conferir --faixa 5.12 --esperado-vpp 0.83
  ./coletar.sh sonda --taxa 400000 --canal-sonda 0 --pontos 32 --sonda sct013_100a_sn001 --ref-externa
  ./coletar.sh cadeia --faixa 20.48
  ./coletar.sh aliasing --canais 1 --grandeza 1:tensao --sonda 1:cadeia_tensao_fase
  ./coletar.sh ruido
  ./coletar.sh teto
  ./coletar.sh bancada --grade --simular

Os modos que capturam em lote (cadeia, aliasing, ruido, bancada) gravam uma pasta com as capturas, o log.txt e o
resumo.csv e retomam de onde pararam com --continuar; --simular mostra o plano sem capturar.
FIM
}

MODO=${1:-}
case "$MODO" in
    ''|-h|--help|ajuda) ajuda; exit 0 ;;
esac
shift
case "$MODO" in
    sonda)
        # A calibração roda inteira como root (o ler_adc e a pasta capturas/). Sem sudo, ela se chama de novo com
        # ele (com um ler_adc falso, nos testes, não).
        if [ "$(id -u)" -ne 0 ] && [ -z "${SH_LER_ADC:-}" ] && [ "${1:-}" != -h ] && [ "${1:-}" != --help ]; then
            if [ -n "${SUDO_ASKPASS:-}" ]; then
                exec sudo -A bash "$DIR/coleta/sonda.sh" "$@"
            fi
            exec sudo bash "$DIR/coleta/sonda.sh" "$@"
        fi
        exec bash "$DIR/coleta/sonda.sh" "$@" ;;
    cadeia|aliasing|ruido|bancada) exec bash "$DIR/coleta/campanha.sh" "$MODO" "$@" ;;
    teto) exec bash "$DIR/coleta/teto.sh" "$@" ;;
    conferir) exec bash "$DIR/coleta/conferir.sh" "$@" ;;
    *) printf 'Erro: modo desconhecido: %s (os modos: conferir, sonda, cadeia, aliasing, ruido, teto, bancada; veja --help).\n' \
           "$MODO" >&2
       exit 2 ;;
esac
