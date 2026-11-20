"""O Python do aplicativo empacotado (o PyInstaller; F7.12 em docs/gui-progress.md, 4h).

Fora do pacote, a placa simulada e o agente local rodam com o Python deste processo (``sys.executable``): o
``python3`` da placa simulada, a primeira linha (``#!``) dos programas dela, o ``ler_adc`` simulado e o agente pelo
:class:`~sh_placa.agente.TransporteLocal`. **No pacote**, ``sys.executable`` é o executável do aplicativo, que abriria
a janela. Com a variável :data:`VARIAVEL` no ambiente, o ponto de entrada do pacote (``empacotamento/entrada.py``) faz
dele um Python (:func:`rodar`): ``-c CÓDIGO``, ``-`` (o código pelo stdin, o do agente), ``-m MÓDULO`` e um script,
com os argumentos; ``-u``, ``-I``, ``-B``, ``-E``, ``-s`` e ``-S`` são aceitos. :func:`ambiente` dá a variável para
quem lança esses programas (vazia fora do pacote): o ambiente da placa simulada e o do agente local. Os módulos que
eles importam são os do pacote (a receita junta os do agente e os dos programas da placa simulada).

Só a biblioteca padrão.
"""

from __future__ import annotations

import builtins
import os
import runpy
import sys
import types

VARIAVEL = "SHAN_COMO_PYTHON"
OPCOES_SEM_EFEITO = ("-I", "-B", "-E", "-s", "-S")
"""As opções do Python que o pacote aceita e não mudam nada nele (não há site-packages nem .pyc a escrever)."""
USO = "uso: python [-u] [-c CÓDIGO | -m MÓDULO | - | SCRIPT] [ARGUMENTOS...]"


def empacotado() -> bool:
    return bool(getattr(sys, "frozen", False))


def ambiente() -> dict[str, str]:
    """O que pôr no ambiente de quem roda ``sys.executable`` como Python: no pacote, :data:`VARIAVEL`; fora, nada."""
    return {VARIAVEL: "1"} if empacotado() else {}


def pedido(ambiente_do_processo: dict[str, str] | None = None) -> bool:
    """Se este processo foi lançado para ser um Python (no pacote, com :data:`VARIAVEL` no ambiente)."""
    return empacotado() and bool((os.environ if ambiente_do_processo is None else ambiente_do_processo).get(VARIAVEL))


def _sem_buffer() -> None:
    for fluxo in (sys.stdout, sys.stderr):
        reconfigurar = getattr(fluxo, "reconfigure", None)
        if reconfigurar is not None:
            reconfigurar(write_through=True)


def _executar(codigo: str, nome_do_arquivo: str) -> None:
    """O código como o ``__main__`` (um módulo novo: as classes do código acham o módulo delas em ``sys.modules``)."""
    principal = types.ModuleType("__main__")
    principal.__dict__["__builtins__"] = builtins
    anterior = sys.modules.get("__main__")
    sys.modules["__main__"] = principal
    try:
        exec(compile(codigo, nome_do_arquivo, "exec"), principal.__dict__)
    finally:
        if anterior is not None:
            sys.modules["__main__"] = anterior


def rodar(argv: list[str]) -> int:
    """Faz o que ``python ARGV`` faria; devolve o código de saída (um ``SystemExit`` do código passa adiante)."""
    i = 0
    while i < len(argv) and argv[i].startswith("-") and argv[i] != "-":
        opcao = argv[i]
        if opcao == "-u":
            _sem_buffer()
        elif opcao == "-c":
            if i + 1 >= len(argv):
                sys.stderr.write("Argument expected for the -c option\n" + USO + "\n")
                return 2
            sys.argv = ["-c", *argv[i + 2:]]
            _executar(argv[i + 1], "<string>")
            return 0
        elif opcao == "-m":
            if i + 1 >= len(argv):
                sys.stderr.write("Argument expected for the -m option\n" + USO + "\n")
                return 2
            sys.argv = [argv[i + 1], *argv[i + 2:]]
            runpy.run_module(argv[i + 1], run_name="__main__", alter_sys=True)
            return 0
        elif opcao not in OPCOES_SEM_EFEITO:
            sys.stderr.write(f"opção do Python que o aplicativo empacotado não tem: {opcao}\n{USO}\n")
            return 2
        i += 1
    if i >= len(argv):
        sys.stderr.write("o Python do aplicativo empacotado não é interativo\n" + USO + "\n")
        return 2
    alvo, sys.argv = argv[i], argv[i:]
    if alvo == "-":
        _executar(sys.stdin.read(), "<stdin>")
        return 0
    sys.path.insert(0, os.path.dirname(os.path.abspath(alvo)))
    runpy.run_path(alvo, run_name="__main__")
    return 0
