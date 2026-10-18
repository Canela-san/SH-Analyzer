"""Logging do SH-Analyzer: como as mensagens de progresso e aviso chegam ao console.

Convenção para quem for contribuir
----------------------------------
* Módulos de biblioteca fazem ``log = logging.getLogger(__name__)`` e usam

    - ``log.info(...)``    -> informação de progresso/resultado (vai para o **stdout**);
    - ``log.warning(...)`` -> aviso ao usuário, texto SEM o prefixo ``"Aviso: "``
      (vai para o **stderr**; o prefixo é colocado pelo handler).

  Nunca ``print(...)`` em biblioteca. Erros fatais NÃO são logados: levante
  :class:`supraharmonicos.erros.ErroSHAN`.
* Só a borda do programa (``cli_*.main``) chama :func:`configurar_logging_cli`.
  Quem usa o pacote como biblioteca (notebooks, testes, outros scripts) não
  vê nada a menos que configure o logging do jeito que quiser -- o logger
  ``"supraharmonicos"`` leva um ``NullHandler``, como manda a boa prática.
* O destino (stdout/stderr) é resolvido em cada ``emit`` -- não no momento da
  configuração --, para funcionar com ``contextlib.redirect_stdout``,
  ``capsys`` do pytest etc.

O formato reproduz exatamente o que os scripts monolíticos antigos imprimiam
com ``print``: stdout só com a mensagem; stderr com ``"Aviso: "`` na frente.
"""

from __future__ import annotations

import logging
import sys

NOME_RAIZ = "supraharmonicos"


class _HandlerSys(logging.Handler):
    """Escreve em ``sys.stdout``/``sys.stderr`` *vigentes no momento da emissão*."""

    def __init__(self, nome_fluxo: str, nivel_min: int, nivel_max_exclusivo: int | None, prefixos: dict[int, str]):
        super().__init__(level=nivel_min)
        self._nome_fluxo = nome_fluxo
        self._nivel_max_exclusivo = nivel_max_exclusivo
        self._prefixos = prefixos

    def emit(self, record: logging.LogRecord) -> None:
        if self._nivel_max_exclusivo is not None and record.levelno >= self._nivel_max_exclusivo:
            return
        try:
            prefixo = ""
            for nivel in sorted(self._prefixos, reverse=True):
                if record.levelno >= nivel:
                    prefixo = self._prefixos[nivel]
                    break
            fluxo = getattr(sys, self._nome_fluxo)
            fluxo.write(f"{prefixo}{record.getMessage()}\n")
            fluxo.flush()
        except Exception:  # noqa: BLE001 -- padrão do logging: nunca derrubar o programa por falha de log
            self.handleError(record)


def configurar_logging_cli(nivel: int = logging.INFO) -> None:
    """Liga o logging do pacote ao console, no formato histórico dos scripts.

    Idempotente: chamar duas vezes (ex.: ``main()`` invocado várias vezes em
    testes) substitui os handlers em vez de duplicar as mensagens."""
    raiz = logging.getLogger(NOME_RAIZ)
    for h in list(raiz.handlers):
        if isinstance(h, _HandlerSys):
            raiz.removeHandler(h)
    raiz.addHandler(_HandlerSys("stdout", logging.DEBUG, logging.WARNING, {}))
    raiz.addHandler(_HandlerSys("stderr", logging.WARNING, None, {logging.WARNING: "Aviso: ", logging.ERROR: "Erro: "}))
    raiz.setLevel(nivel)
    raiz.propagate = False
