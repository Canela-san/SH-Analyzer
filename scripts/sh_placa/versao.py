"""O firmware deste aplicativo, para comparar com o da placa (docs/gui-plan.md, 11.9 e 11.10).

A versão gravada na placa (``~/firmware/VERSAO``) é o ``git describe --always`` do repositório no envio (o ``enviar``
do ``BeagleBone_Setup.sh``), com ``-dirty`` se o ``firmware/`` tinha mudanças. Ela muda a cada commit do repositório,
mesmo sem mudança no firmware: **comparar os textos** acusaria "outra versão" depois de qualquer commit da interface.
**O que importa é o código:** o firmware da placa é o deste aplicativo se o ``firmware/`` do commit da versão dela é
o mesmo de agora. O ``firmware/agente/`` fica de fora: o agente vai pelo stdin a cada chamada, e o da placa não roda.

Rodando do repositório (com o ``git``), :func:`firmware_do_aplicativo` dá a versão a comparar: a da placa, se o código
é o mesmo, ou o ``git describe`` de agora (com ``-dirty``, se o ``firmware/`` tem mudanças não commitadas). Fora de um
repositório (um pacote, mais tarde) ou sem o ``git``: ``None``, e a comparação não é feita. Só a biblioteca padrão.
"""

from __future__ import annotations

import logging
import re
import subprocess
from pathlib import Path

log = logging.getLogger(__name__)

RAIZ_DO_REPOSITORIO = Path(__file__).resolve().parents[2]
CAMINHOS_DO_FIRMWARE = ("firmware", ":!firmware/VERSAO", ":!firmware/agente")
TEMPO_DO_GIT_S = 10.0
_COMMIT = re.compile(r"(?:^|-g)([0-9a-f]{7,40})(?:-dirty)?$")


def _git(raiz: Path, *argumentos: str) -> subprocess.CompletedProcess | None:
    try:
        return subprocess.run(["git", "-C", str(raiz), *argumentos], capture_output=True, text=True,
                              timeout=TEMPO_DO_GIT_S, check=False)
    except (OSError, subprocess.TimeoutExpired) as e:
        log.info("o git não respondeu (%s): sem a versão do firmware do aplicativo", e)
        return None


def commit_da_versao(versao: str) -> str | None:
    """O commit de uma versão do ``git describe --always``: ``v0.8-137-g9b0ae82`` dá ``9b0ae82``; um hash puro, ele
    mesmo; uma versão sem commit (``v0.8.0``, um texto qualquer), ``None``."""
    m = _COMMIT.search(versao.strip())
    return m.group(1) if m else None


def firmware_do_aplicativo(versao_da_placa: str | None, raiz: Path = RAIZ_DO_REPOSITORIO) -> str | None:
    """A versão do firmware deste aplicativo, para comparar com ``versao_da_placa`` (ver o módulo)."""
    descricao = _git(raiz, "describe", "--always")
    if descricao is None or descricao.returncode != 0:
        return None
    atual = descricao.stdout.strip()
    mudancas = _git(raiz, "status", "--porcelain", "--", *CAMINHOS_DO_FIRMWARE)
    if mudancas is None or mudancas.returncode != 0:
        return None
    if mudancas.stdout.strip():
        return f"{atual}-dirty"
    commit = commit_da_versao(versao_da_placa) if versao_da_placa and not versao_da_placa.endswith("-dirty") else None
    if commit is not None:
        igual = _git(raiz, "diff", "--quiet", commit, "HEAD", "--", *CAMINHOS_DO_FIRMWARE)
        if igual is not None and igual.returncode == 0:
            return versao_da_placa                 # o mesmo código, enviado de um commit anterior
    return atual
