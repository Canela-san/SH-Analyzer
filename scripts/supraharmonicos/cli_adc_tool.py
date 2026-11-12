"""Linha de comando do ``adc_tool``: definição das flags e ``main()``.

Esta é a BORDA do programa -- o único lugar (junto com ``cli_gerar_perfil``)
que liga o logging ao console, lê ``sys.argv`` e traduz exceções em código de
saída:

* ``ErroUso``  -> ``parser.error`` (mensagem de uso + código 2);
* ``ErroSHAN`` -> ``Erro: <mensagem>`` no stderr + código 1;
* sucesso      -> código 0.

A lógica de cada modo está em ``modos`` (e nas camadas abaixo dele) e as flags
em ``opcoes_analise`` (``montar_parser``, compartilhado com a interface gráfica);
aqui só se roda o parser e se escolhe o modo.
"""


import logging

from .contexto import anunciar_cabecalho, resolver_contexto
from .erros import ErroSHAN, ErroUso
from .modos import executar_conversao, executar_exportacao_hdf5, executar_plotagem
from .opcoes_analise import montar_parser, validar_flags_numericas
from .registro import configurar_logging_cli

__all__ = ["main", "montar_parser"]       # montar_parser continua importável daqui (testes, notebooks)

log = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> int:
    """Ponto de entrada do ``adc_tool``. Devolve o código de saída do processo."""
    parser = montar_parser()
    args = parser.parse_args(argv)
    configurar_logging_cli()

    try:
        if args.export_hdf5 is not None and args.converter is not None:
            raise ErroUso("--export-hdf5 e -c/--converter não podem ser usados juntos -- escolha um modo.")
        validar_flags_numericas(args)

        ctx = resolver_contexto(args)
        anunciar_cabecalho(ctx, args.formato)

        if args.export_hdf5 is not None:
            executar_exportacao_hdf5(args, ctx)
        elif args.converter is not None:
            executar_conversao(args, ctx)
        else:
            executar_plotagem(args, ctx)
    except ErroUso as e:
        parser.error(str(e))  # imprime o uso + a mensagem e sai com código 2
    except ErroSHAN as e:
        log.error(str(e))
        return 1
    return 0
