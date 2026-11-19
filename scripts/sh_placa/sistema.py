"""O sistema da placa (docs/gui-plan.md, 11.10; a Fase 6): reiniciar e desligar com segurança (a F6.5). Desligar da
tomada corrompe o cartão; o desligar seguro para o sistema antes.

**Reiniciar e desligar** (:func:`reiniciar`, :func:`desligar`): pelo sudo, o ``systemctl reboot`` (ou ``poweroff``)
destacado e um segundo depois, para o comando voltar com o código antes de a conexão cair (a queda, aqui, é
esperada: quem chama avisa a conexão antes, ``ConexaoDaPlaca.esperar``). Com uma captura rodando (o ``ler_adc``), recusa
(:data:`SAIDA_CAPTURA_RODANDO`), a não ser com ``mesmo_capturando``: a captura seria cortada.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .agente import ErroDaPlaca
from .correcoes import SAIDA_SEM_DIRETORIO, SAIDA_SENHA_RECUSADA, ErroDoSudo, com_sudo

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
                    f"sudo -n setsid sh -c 'sleep 1; systemctl {acao}' < /dev/null > /dev/null 2>&1 &\n"
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
