"""Porta de entrada única do SH-Analyzer: ``adc_tool.py [SUBCOMANDO] ...``.

Cada subcomando é uma das CLIs do pacote, carregada só quando pedida -- ``adc_tool.py info`` não carrega o SciPy
nem o matplotlib, e ``adc_tool.py compactar`` é o único que carrega o ``rich``. Sem subcomando (o primeiro argumento
é um arquivo ou uma opção), é a análise, como sempre foi: ``adc_tool.py captura.bin --fft`` continua valendo.

Os scripts antigos (``medir_captura.py``, ``gerar_perfil_sonda.py``, ``compactar_amostras.py``) continuam
funcionando e chamam as mesmas CLIs: os comandos do roteiro de laboratório não mudam.

Depende de: todas as ``cli_*`` (é o único módulo que pode importá-las; ver tests/test_arquitetura.py)."""

import logging
import sys
from collections.abc import Callable

from .registro import configurar_logging_cli

log = logging.getLogger(__name__)


def _analisar(argv: list[str]) -> int:
    from .cli_adc_tool import main
    return main(argv)


def _info(argv: list[str]) -> int:
    from .cli_info import main
    return main(argv)


def _medir(argv: list[str]) -> int:
    from .cli_medir_captura import main
    return main(argv)


def _perfil(argv: list[str]) -> int:
    from .cli_gerar_perfil import main
    return main(argv)


def _compactar(argv: list[str]) -> int:
    from .cli_compactar import main
    return main(argv)


def _aliasing(argv: list[str]) -> int:
    from .cli_aliasing import main
    return main(argv)


SUBCOMANDOS: dict[str, tuple[Callable[[list[str]], int], str]] = {
    "analisar": (_analisar, "(o padrão) forma de onda, FFT, Welch, harmônicos, bandas IEC, espectrograma, picos e "
                            "exportação (CSV/JSON/MATLAB) de uma captura"),
    "info": (_info, "o que cada captura é: cabeçalho, canais, faixa, integridade e, com --estatisticas, média, "
                    "RMS, extremos e saturação por canal"),
    "medir": (_medir, "métricas de bancada de uma ou várias capturas (ruído, THD, SINAD, ENOB, SFDR, continuidade, "
                      "diafonia, erro contra um instrumento), em tabela e CSV -- o mesmo que medir_captura.py"),
    "perfil": (_perfil, "gera o perfil de resposta em frequência de uma sonda a partir das capturas do "
                        "calibrar_sonda.sh -- o mesmo que gerar_perfil_sonda.py"),
    "compactar": (_compactar, "arquiva capturas sem perdas (.zpaq.tar, conferido bit a bit) e extrai, lista ou "
                              "verifica pacotes -- o mesmo que compactar_amostras.py"),
    "aliasing": (_aliasing, "separa componentes reais de imagens de aliasing com duas capturas do mesmo sinal em "
                            "taxas diferentes"),
}


def texto_subcomandos() -> str:
    linhas = ["Subcomandos (adc_tool.py SUBCOMANDO --help para as opções de cada um):"]
    linhas += [f"  {nome:<10} {descricao}" for nome, (_, descricao) in SUBCOMANDOS.items()]
    linhas.append("Sem subcomando, é a análise: 'adc_tool.py captura.bin --fft' = 'adc_tool.py analisar captura.bin --fft'.")
    return "\n".join(linhas)


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else list(argv)
    if argv and argv[0] in ("-h", "--help"):
        configurar_logging_cli()
        log.info(texto_subcomandos() + "\n\nOpções da análise (o subcomando padrão):\n")
    if argv and argv[0] in SUBCOMANDOS:
        funcao, _ = SUBCOMANDOS[argv[0]]
        return funcao(argv[1:])
    return _analisar(argv)
