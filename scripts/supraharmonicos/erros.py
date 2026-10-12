"""Exceções do SH-Analyzer.

Convenção para quem for contribuir
----------------------------------
Código de biblioteca (tudo em ``supraharmonicos`` exceto os módulos ``cli_*``)
NUNCA chama ``sys.exit``/``raise SystemExit`` nem ``print`` direto para erros:
levanta uma exceção desta hierarquia. Quem decide o que fazer com ela é a
borda do programa (``cli_adc_tool.main``/``cli_gerar_perfil.main``), que
imprime ``Erro: <mensagem>`` no stderr e devolve o código de saída 1 (ou
dispara ``parser.error`` -> código 2 para :class:`ErroUso`).

A mensagem NÃO leva o prefixo ``"Erro: "`` -- ele é colocado pela CLI. Assim a
mesma exceção pode ser reaproveitada como texto de um aviso (``"Aviso: pulando
... -- <mensagem>"``) sem gambiarra de remover prefixo.
"""


class ErroSHAN(Exception):
    """Erro esperado e explicável ao usuário (arquivo ruim, flag inválida,
    perfil de sonda inconsistente...). A mensagem é o texto final, em
    português, já com o contexto necessário (caminho do arquivo, nome da
    flag, valor recebido)."""


class ErroUso(ErroSHAN):
    """Combinação inválida de argumentos de linha de comando (modos
    incompatíveis, flag obrigatória ausente...). A CLI trata como
    ``parser.error`` (mensagem de uso + código de saída 2) em vez de um erro
    comum (código 1)."""
