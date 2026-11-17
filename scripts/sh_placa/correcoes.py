"""As duas correções simples do diagnóstico (docs/gui-plan.md, 11.9; a F3.6): os pinos da PRU, com o ``config-pin``
(como o ``firmware/setup.sh``), e o relógio da placa, acertado pelo do computador (como o ``hora`` do
``BeagleBone_Setup.sh``). Só a pedido do usuário: a interface confirma antes e mostra exatamente o que vai rodar
(:func:`comando_dos_pinos`, :func:`roteiro_do_relogio`); cada comando vai para o registro de atividade.

**O sudo** (só o relógio precisa: o ``config-pin`` escreve no pinmux, que é do grupo ``gpio``, e o ``debian`` está
nele): a senha vai pelo stdin para um askpass num diretório temporário em ``/dev/shm`` (a RAM), só do usuário. O
``sudo -A -v`` a lê uma vez, o arquivo some logo depois, e o comando de root roda com ``sudo -n``, com a credencial já
validada nesta sessão do shell; no fim, ``sudo -k``. (``SHAN_RAM`` troca a ``/dev/shm`` só nos testes, como o
``SH_ANALYZER_RAM`` do ``BeagleBone_Setup.sh``: o servidor do teste dá a cada um a sua.) **A senha nunca está numa linha de comando**, num argumento, no
registro de atividade ou no log. Uma senha errada é uma tentativa só (o askpass se apaga ao ser lido), e a resposta é
:class:`ErroDoSudo`, com ``senha_recusada``.

**O relógio, com a precisão do enlace:** o Python de root avisa que está pronto, e só então o computador manda a hora
dele (mais a meia ida e volta); a placa conta, pelo ``CLOCK_BOOTTIME``, o tempo do recebimento até acertar, e acerta
com o ``clock_settime``. O erro fica em ~1 ms no USB, em vez do tempo do sudo e da partida do Python (décimos de
segundo, o que o ``hora`` do ``BeagleBone_Setup.sh`` compensava pelo ``/proc/uptime``, com centésimos). Na placa
simulada (``SHAN_RAIZ``, que o sudo de verdade apaga do ambiente), o relógio dela é o deste computador mais um desvio,
num arquivo da árvore falsa (o que o agente lê): o acerto reescreve o desvio, e o relógio daqui não é tocado.
"""

from __future__ import annotations

import asyncio
import json
import shlex
import time
from collections.abc import Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .agente import ErroDaPlaca

if TYPE_CHECKING:                       # só a anotação: a interface mostra os comandos sem carregar o asyncssh
    from .conexao import ConexaoSSH

MODOS_DA_PRU = {"P9_31": "pruout", "P9_29": "pruout", "P9_30": "pruin", "P9_28": "pruout"}
"""Os pinos da PRU0 e os modos, na ordem do ``firmware/setup.sh`` (``tests/test_sh_placa_correcoes.py`` confere)."""
SAIDA_SENHA_RECUSADA = 98
SAIDA_SEM_DIRETORIO = 97
TEMPO_DO_SUDO_S = 30.0
ARQUIVO_DO_RELOGIO_SIMULADO = "run/simulador/relogio"
"""Na raiz falsa: o desvio do relógio da placa simulada, em segundos (o ``SIMULADOR`` do agente)."""

_VALIDAR_O_SUDO = """umask 077
d=$(mktemp -d "${{SHAN_RAM:-/dev/shm}}/sh-analyzer.XXXXXX") || exit {sem_diretorio}
trap 'rm -rf "$d"; sudo -k' EXIT
IFS= read -r senha || senha=
printf '%s\\n' "$senha" > "$d/senha"
senha=
printf '#!/bin/sh\\ncat "%s/senha" 2>/dev/null\\nrm -f "%s/senha"\\n' "$d" "$d" > "$d/askpass"
chmod 700 "$d/askpass"
SUDO_ASKPASS="$d/askpass" sudo -A -p '' -v 2>/dev/null || exit {recusada}
rm -f "$d/senha"
"""

CODIGO_DO_RELOGIO = f"""import json, os, sys, time
raiz = os.environ.get("SHAN_RAIZ") or "/"
simulado = os.path.join(raiz, "{ARQUIVO_DO_RELOGIO_SIMULADO}")
desvio = 0.0
if raiz != "/" and os.path.exists(simulado):
    with open(simulado) as f:
        desvio = float(f.read().strip() or 0)
print("pronto", flush=True)
linha = sys.stdin.readline()
chegou = time.clock_gettime(time.CLOCK_BOOTTIME)
antes = time.time() + desvio
hora = float(linha)
novo = hora + time.clock_gettime(time.CLOCK_BOOTTIME) - chegou
if raiz == "/":
    time.clock_settime(time.CLOCK_REALTIME, novo)
else:
    os.makedirs(os.path.dirname(simulado), exist_ok=True)
    with open(simulado, "w") as f:
        f.write(repr(novo - time.time()))
print(json.dumps({{"erro_antes_s": antes - hora, "acertado_para": novo}}), flush=True)
"""
"""O Python de root (o 3.7 da imagem) que acerta o relógio: ``erro_antes_s`` é a placa menos o computador, no
instante em que a hora chegou."""


class ErroDoSudo(ErroDaPlaca):
    """O sudo da placa não rodou o comando: a senha recusada (``senha_recusada``) ou outro motivo."""

    def __init__(self, motivo: str, senha_recusada: bool = False):
        super().__init__(motivo)
        self.senha_recusada = senha_recusada


@dataclass(frozen=True)
class RelogioAcertado:
    erro_antes_s: float                   # quanto a placa estava adiantada (+) ou atrasada (-)
    acertado_para: float                  # a hora posta (time.time() da placa)


def validar_o_sudo() -> str:
    """O começo de um roteiro com o sudo: a senha lida do stdin (a primeira linha) e validada pelo askpass em
    ``/dev/shm``, que some logo depois. Daí em diante, até o fim do roteiro, ``sudo -n`` roda como root sem a senha (a
    credencial é a deste shell); no fim, de qualquer jeito, ``sudo -k``. Sai com :data:`SAIDA_SENHA_RECUSADA` ou
    :data:`SAIDA_SEM_DIRETORIO`."""
    return _VALIDAR_O_SUDO.format(recusada=SAIDA_SENHA_RECUSADA, sem_diretorio=SAIDA_SEM_DIRETORIO)


def com_sudo(comando_de_root: str) -> str:
    """O roteiro que roda ``comando_de_root`` com o sudo, a senha pelo stdin (a primeira linha) e o askpass em
    ``/dev/shm``. O que vier no stdin depois da senha vai para o comando de root."""
    return validar_o_sudo() + f"sudo -n {comando_de_root}"


def roteiro_do_relogio() -> str:
    """O que roda na placa para acertar o relógio (o "Ver o comando" da interface mostra isto)."""
    return com_sudo("python3 -u -c " + shlex.quote(CODIGO_DO_RELOGIO))


def comando_dos_pinos(errados: Iterable[str]) -> str:
    """Os ``config-pin`` dos pinos fora do modo da PRU, na ordem do ``setup.sh``: ``config-pin P9_28 pruout && …``.
    ``ValueError`` num pino que não é da PRU, ou sem nenhum."""
    errados = set(errados)
    desconhecidos = errados - set(MODOS_DA_PRU)
    if desconhecidos or not errados:
        raise ValueError(f"pinos da PRU para corrigir: {sorted(errados)} (os da PRU são {', '.join(MODOS_DA_PRU)})")
    return " && ".join(f"config-pin {pino} {modo}" for pino, modo in MODOS_DA_PRU.items() if pino in errados)


async def corrigir_pinos(conexao: ConexaoSSH, errados: Iterable[str]) -> None:
    """Põe os pinos no modo da PRU (o ``config-pin``, sem sudo). ``ErroDaPlaca`` com a saída dele, se falhar."""
    errados = sorted(set(errados))
    r = await conexao.executar(comando_dos_pinos(errados),
                               descricao=f"pôr {', '.join(errados)} no modo da PRU (config-pin)")
    if r.codigo != 0:
        raise ErroDaPlaca(f"o config-pin falhou (código {r.codigo}): {(r.erro or r.saida).strip()[:300]}")


async def acertar_relogio(conexao: ConexaoSSH, senha_do_sudo: str, meia_ida_e_volta_s: float = 0.0,
                          tempo_limite_s: float = TEMPO_DO_SUDO_S) -> RelogioAcertado:
    """Acerta o relógio da placa pelo deste computador (o sudo, com ``senha_do_sudo``). ``meia_ida_e_volta_s``: a
    metade da latência do enlace, somada à hora enviada (o tempo de ela chegar)."""
    descricao = "acertar o relógio da placa pelo do computador (sudo)"
    async with conexao.canal(roteiro_do_relogio(), descricao) as (processo, desfecho):
        processo.stdin.write(senha_do_sudo + "\n")
        try:
            linha = await asyncio.wait_for(processo.stdout.readline(), tempo_limite_s)
            if linha.strip() == "pronto":
                processo.stdin.write(repr(time.time() + meia_ida_e_volta_s) + "\n")
                processo.stdin.write_eof()
                resto = await asyncio.wait_for(processo.stdout.read(), tempo_limite_s)
            else:
                resto = linha
            erro = await asyncio.wait_for(processo.stderr.read(), tempo_limite_s)
            await asyncio.wait_for(processo.wait(), tempo_limite_s)
        except asyncio.TimeoutError:
            desfecho.falha = f"sem resposta em {tempo_limite_s:g} s"
            raise ErroDaPlaca(f"a placa não acertou o relógio em {tempo_limite_s:g} s") from None
        conexao.concluir(processo, desfecho, descricao)
    if desfecho.codigo == SAIDA_SENHA_RECUSADA:
        raise ErroDoSudo("a placa recusou a senha do sudo", senha_recusada=True)
    if desfecho.codigo == SAIDA_SEM_DIRETORIO:
        raise ErroDoSudo("a placa não deixou criar o diretório temporário em /dev/shm (onde a senha fica, na RAM)")
    if desfecho.codigo != 0:
        detalhe = (erro or resto).strip().splitlines()[-1:] or ["sem saída"]
        raise ErroDoSudo(f"o relógio não foi acertado (código {desfecho.codigo}): {detalhe[0][:300]}")
    try:
        dados = json.loads(resto.strip().splitlines()[-1])
        return RelogioAcertado(float(dados["erro_antes_s"]), float(dados["acertado_para"]))
    except (IndexError, KeyError, TypeError, ValueError) as e:
        raise ErroDaPlaca(f"a resposta do acerto do relógio não se entende: {resto.strip()[:200]!r}") from e
