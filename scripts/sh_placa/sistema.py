"""O sistema da placa (docs/gui-plan.md, 11.10; a Fase 6): reiniciar e desligar com segurança (a F6.5). Desligar da
tomada corrompe o cartão; o desligar seguro para o sistema antes.

**Reiniciar e desligar** (:func:`reiniciar`, :func:`desligar`): pelo sudo, o ``systemctl reboot`` (ou ``poweroff``)
destacado e um segundo depois, para o comando voltar com o código antes de a conexão cair (a queda, aqui, é
esperada: quem chama avisa a conexão antes, ``ConexaoDaPlaca.esperar``). **Quem destaca é o root**
(``sudo -n sh -c 'setsid … &'``), e não um ``sudo -n … &`` deste shell: sem terminal, a credencial do sudo é do
processo pai, e este shell sai logo depois do ``&``; o sudo do fundo, adotado pelo init antes de conferir a
credencial, pediria a senha e falharia calado (foi o que a placa de verdade fez em 19/11/2026). Com uma captura rodando (o ``ler_adc``), recusa
(:data:`SAIDA_CAPTURA_RODANDO`), a não ser com ``mesmo_capturando``: a captura seria cortada.

**O ``ler_adc`` esquecido** (:func:`capturas_rodando`, :func:`parar_ler_adc`, a F6.6): o que o ``pgrep`` acha na placa
(uma captura do terminal, de um ``coletar.sh``, de outra janela) e o parar como o Ctrl+C: o ``INT``, que fecha o
arquivo e para a PRU; o ``TERM`` só se ele não sair em :data:`ESPERA_DO_INT_S`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .agente import ErroDaPlaca
from .correcoes import SAIDA_SEM_DIRETORIO, SAIDA_SENHA_RECUSADA, ErroDoSudo, com_sudo, validar_o_sudo

if TYPE_CHECKING:
    from .conexao import ConexaoSSH

SAIDA_CAPTURA_RODANDO = 85
ACOES = {"reboot": "reiniciar a placa", "poweroff": "desligar a placa"}


class CapturaRodando(ErroDaPlaca):
    """Uma captura roda na placa (o ``ler_adc``): reiniciar ou desligar a cortaria."""


def roteiro_de_energia(acao: str, mesmo_capturando: bool = False) -> str:
    """O que roda na placa para ``acao`` (``"reboot"`` ou ``"poweroff"``): o "Ver o comando"."""
    if acao not in ACOES:
        raise ValueError(f"ação desconhecida: {acao!r}")
    conferir = "" if mesmo_capturando else \
        f"if pgrep -x ler_adc > /dev/null 2>&1; then echo 'uma captura está rodando (ler_adc)' >&2; exit {SAIDA_CAPTURA_RODANDO}; fi\n"
    return com_sudo("true\n" + conferir +
                    f"sudo -n sh -c 'setsid sh -c \"sleep 1; systemctl {acao}\" < /dev/null > /dev/null 2>&1 &'\n"
                    f"echo 'a placa vai {'reiniciar' if acao == 'reboot' else 'desligar'} em 1 s'")


async def _energia(conexao: ConexaoSSH, acao: str, senha_do_sudo: str, mesmo_capturando: bool) -> None:
    r = await conexao.executar(roteiro_de_energia(acao, mesmo_capturando), entrada=senha_do_sudo + "\n",
                               tempo_limite=30, descricao=f"{ACOES[acao]} (sudo)")
    if r.codigo == SAIDA_SENHA_RECUSADA:
        raise ErroDoSudo("a placa recusou a senha do sudo", senha_recusada=True)
    if r.codigo == SAIDA_SEM_DIRETORIO:
        raise ErroDoSudo("a placa não deixou criar o diretório temporário em /dev/shm (onde a senha fica, na RAM)")
    if r.codigo == SAIDA_CAPTURA_RODANDO:
        raise CapturaRodando("uma captura está rodando na placa (ler_adc): pare-a antes, ou confirme que pode "
                             "cortá-la")
    if r.codigo != 0:
        raise ErroDaPlaca(f"a placa não aceitou {ACOES[acao]} (código {r.codigo}): "
                          f"{(r.erro or r.saida).strip()[-200:] or 'sem saída'}")


async def reiniciar(conexao: ConexaoSSH, senha_do_sudo: str, *, mesmo_capturando: bool = False) -> None:
    await _energia(conexao, "reboot", senha_do_sudo, mesmo_capturando)


async def desligar(conexao: ConexaoSSH, senha_do_sudo: str, *, mesmo_capturando: bool = False) -> None:
    await _energia(conexao, "poweroff", senha_do_sudo, mesmo_capturando)


# ------------------------------------------------------------------ o ler_adc esquecido

SAIDA_AINDA_RODA = 86
ESPERA_DO_INT_S = 10


@dataclass(frozen=True)
class CapturaNaPlaca:
    """Um ``ler_adc`` rodando na placa: o PID e a linha de comando."""

    pid: int
    linha: str


async def capturas_rodando(conexao: ConexaoSSH) -> list[CapturaNaPlaca]:
    """Os ``ler_adc`` que rodam na placa (o ``pgrep -a``)."""
    r = await conexao.executar("pgrep -a -x ler_adc", descricao="as capturas que rodam na placa (pgrep -a -x ler_adc)")
    if r.codigo not in (0, 1):
        raise ErroDaPlaca(f"o pgrep falhou (código {r.codigo}): {(r.erro or r.saida).strip()[-200:]}")
    capturas = []
    for linha in r.saida.splitlines():
        pid, _, resto = linha.strip().partition(" ")
        if pid.isdigit():
            capturas.append(CapturaNaPlaca(int(pid), resto.strip()))
    return capturas


def roteiro_de_parar_ler_adc() -> str:
    """O que roda na placa para parar os ``ler_adc`` (o "Ver o comando")."""
    return validar_o_sudo() + f"""p=$(pgrep -x ler_adc | tr '\\n' ' ')
[ -n "$p" ] || {{ echo 'nenhum ler_adc rodando'; exit 0; }}
sudo -n kill -INT $p
i=0
while [ $i -lt {ESPERA_DO_INT_S * 10} ] && pgrep -x ler_adc > /dev/null 2>&1; do sleep 0.1; i=$((i+1)); done
if pgrep -x ler_adc > /dev/null 2>&1; then
    sudo -n kill -TERM $(pgrep -x ler_adc | tr '\\n' ' ')
    sleep 2
fi
if pgrep -x ler_adc > /dev/null 2>&1; then echo "o ler_adc não parou (PID $(pgrep -x ler_adc | tr '\\n' ' '))" >&2; exit {SAIDA_AINDA_RODA}; fi
echo "parado: $p"
"""


async def parar_ler_adc(conexao: ConexaoSSH, senha_do_sudo: str) -> str:
    """Para os ``ler_adc`` da placa (ver o módulo); devolve o que a placa disse ("parado: 1234")."""
    r = await conexao.executar(roteiro_de_parar_ler_adc(), entrada=senha_do_sudo + "\n", tempo_limite=40,
                               descricao="parar o ler_adc da placa (sudo)")
    if r.codigo == SAIDA_SENHA_RECUSADA:
        raise ErroDoSudo("a placa recusou a senha do sudo", senha_recusada=True)
    if r.codigo == SAIDA_SEM_DIRETORIO:
        raise ErroDoSudo("a placa não deixou criar o diretório temporário em /dev/shm (onde a senha fica, na RAM)")
    if r.codigo != 0:
        raise ErroDaPlaca(f"o ler_adc não parou (código {r.codigo}): {(r.erro or r.saida).strip()[-200:]}")
    return r.saida.strip().splitlines()[-1] if r.saida.strip() else ""

