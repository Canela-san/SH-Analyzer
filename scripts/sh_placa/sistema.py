"""O sistema da placa (docs/gui-plan.md, 11.10; a Fase 6): reiniciar e desligar com segurança (a F6.5). Desligar da
tomada corrompe o cartão; o desligar seguro para o sistema antes.

**Reiniciar e desligar** (:func:`reiniciar`, :func:`desligar`): pelo sudo, o ``systemctl reboot`` (ou ``poweroff``)
destacado e um segundo depois, para o comando voltar com o código antes de a conexão cair (a queda, aqui, é
esperada: quem chama avisa a conexão antes, ``ConexaoDaPlaca.esperar``). **Quem destaca é o root**
(``sudo -n sh -c 'setsid … &'``), e não um ``sudo -n … &`` deste shell: sem terminal, a credencial do sudo é do
processo pai, e este shell sai logo depois do ``&``; o sudo do fundo, adotado pelo init antes de conferir a
credencial, pediria a senha e falharia calado (foi o que a placa de verdade fez em 19/11/2026). Com uma captura rodando (o ``ler_adc``), recusa
(:data:`SAIDA_CAPTURA_RODANDO`), a não ser com ``mesmo_capturando``: a captura seria cortada.

**A senha, os serviços, a limpeza e a partição** (a F6.7): trocar a senha do usuário pelo ``chpasswd`` (a nova pelo
stdin, nunca na linha de comando); ligar e desligar os serviços da imagem (``systemctl enable/disable --now``); limpar
as tarefas terminadas, o diário guardado e o cache do ``apt``; expandir a partição da raiz pelo script da imagem.

**O ``ler_adc`` esquecido** (:func:`capturas_rodando`, :func:`parar_ler_adc`, a F6.6): o que o ``pgrep`` acha na placa
(uma captura do terminal, de um ``coletar.sh``, de outra janela) e o parar como o Ctrl+C: o ``INT``, que fecha o
arquivo e para a PRU; o ``TERM`` só se ele não sair em :data:`ESPERA_DO_INT_S`.
"""

from __future__ import annotations

import re
import shlex
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


# ------------------------------------------------------------------ a senha

SAIDA_SEM_A_SENHA_NOVA = 87
SAIDA_CHPASSWD_FALHOU = 88


def conferir_a_senha_nova(nova: str) -> str | None:
    """O porquê de a senha nova não servir (``None``: serve): vazia, curta, com uma quebra de linha (o ``chpasswd``
    leria duas) ou igual ao nome do usuário."""
    if not nova:
        return "a senha nova está vazia"
    if "\n" in nova or "\r" in nova:
        return "a senha nova não pode ter uma quebra de linha"
    if len(nova) < 6:
        return "a senha nova precisa de pelo menos 6 caracteres"
    return None


def roteiro_da_senha(usuario: str = "debian") -> str:
    """O que roda na placa para trocar a senha de ``usuario`` (o "Ver o comando"): a senha nova vai pelo stdin, depois
    da do sudo, e chega ao ``chpasswd`` pelo ``printf`` do shell (um comando de dentro dele: não aparece no ``ps``)."""
    return validar_o_sudo() + (
        f"IFS= read -r nova || exit {SAIDA_SEM_A_SENHA_NOVA}\n"
        f"[ -n \"$nova\" ] || exit {SAIDA_SEM_A_SENHA_NOVA}\n"
        f"printf '%s:%s\\n' {shlex.quote(usuario)} \"$nova\" | sudo -n chpasswd || exit {SAIDA_CHPASSWD_FALHOU}\n"
        "nova=\n"
        "echo 'senha trocada'\n")


async def trocar_senha(conexao: ConexaoSSH, senha_do_sudo: str, nova: str, usuario: str = "debian") -> None:
    """Troca a senha de ``usuario`` (a do SSH e a do sudo, daí em diante) pelo ``chpasswd``."""
    problema = conferir_a_senha_nova(nova)
    if problema is not None:
        raise ValueError(problema)
    r = await conexao.executar(roteiro_da_senha(usuario), entrada=f"{senha_do_sudo}\n{nova}\n", tempo_limite=30,
                               descricao=f"trocar a senha de {usuario} (sudo, chpasswd)")
    if r.codigo == SAIDA_SENHA_RECUSADA:
        raise ErroDoSudo("a placa recusou a senha do sudo (a de agora)", senha_recusada=True)
    if r.codigo == SAIDA_SEM_DIRETORIO:
        raise ErroDoSudo("a placa não deixou criar o diretório temporário em /dev/shm (onde a senha fica, na RAM)")
    if r.codigo != 0:
        raise ErroDaPlaca(f"a senha não foi trocada (código {r.codigo}): "
                          f"{(r.erro or r.saida).strip()[-200:] or 'sem saída'}")


# ------------------------------------------------------------------ os serviços da imagem

UNIDADE = re.compile(r"^[A-Za-z0-9@._-]+\.(service|socket)$")


def roteiro_do_servico(unidade: str, ligar: bool) -> str:
    if not UNIDADE.match(unidade):
        raise ValueError(f"unidade do systemd inválida: {unidade!r}")
    return com_sudo(f"systemctl {'enable' if ligar else 'disable'} --now {shlex.quote(unidade)}")


async def ligar_servico(conexao: ConexaoSSH, unidade: str, ligar: bool, senha_do_sudo: str) -> None:
    """Liga (``enable --now``) ou desliga (``disable --now``) um serviço da imagem: vale agora e nos próximos boots."""
    r = await conexao.executar(roteiro_do_servico(unidade, ligar), entrada=senha_do_sudo + "\n", tempo_limite=60,
                               descricao=f"{'ligar' if ligar else 'desligar'} o {unidade} (sudo, systemctl)")
    _conferir(r, f"o systemctl não {'ligou' if ligar else 'desligou'} o {unidade}")


# ------------------------------------------------------------------ a limpeza do cartão

LIMPEZAS = {"tarefas": "as tarefas terminadas da manutenção", "diario": "o diário do systemd guardado no cartão",
            "apt": "os pacotes que o apt baixou"}
TAMANHO_DO_DIARIO = "16M"


def roteiro_de_limpar(qual: str) -> str:
    """O que roda na placa para limpar ``qual`` (``"diario"``: o diário guardado fica com
    :data:`TAMANHO_DO_DIARIO`, o deste boot inteiro; ``"apt"``: o ``apt-get clean``). As tarefas vão sem o sudo
    (:func:`limpar_as_tarefas`)."""
    if qual == "diario":
        return com_sudo(f"journalctl --vacuum-size={TAMANHO_DO_DIARIO}")
    if qual == "apt":
        return com_sudo("apt-get clean")
    raise ValueError(f"limpeza desconhecida: {qual!r}")


async def limpar(conexao: ConexaoSSH, qual: str, senha_do_sudo: str) -> None:
    r = await conexao.executar(roteiro_de_limpar(qual), entrada=senha_do_sudo + "\n", tempo_limite=120,
                               descricao=f"limpar {LIMPEZAS[qual]} (sudo)")
    _conferir(r, f"não deu para limpar {LIMPEZAS[qual]}")


async def limpar_as_tarefas(conexao: ConexaoSSH) -> int:
    """Apaga as tarefas que terminaram (ou foram interrompidas) da manutenção; a que roda fica. Quantas apagou."""
    from .tarefas import TarefaNaPlaca, tarefas_na_placa

    apagadas = 0
    for tarefa in await tarefas_na_placa(conexao):
        if tarefa.terminou or tarefa.interrompida:
            await TarefaNaPlaca(conexao, tarefa.id).limpar()
            apagadas += 1
    return apagadas


# ------------------------------------------------------------------ a partição

def roteiro_de_expandir(script: str) -> str:
    """O script da imagem que faz a partição da raiz ocupar o cartão inteiro (o ``grow_partition.sh`` da
    BeagleBoard); o sistema de arquivos cresce no próximo boot."""
    if not re.match(r"^/[A-Za-z0-9_./-]+$", script) or ".." in script:
        raise ValueError(f"caminho de script inválido: {script!r}")
    return com_sudo('"${SHAN_RAIZ:-}"' + shlex.quote(script))     # na placa de verdade, o SHAN_RAIZ é vazio


async def expandir_a_particao(conexao: ConexaoSSH, script: str, senha_do_sudo: str) -> str:
    r = await conexao.executar(roteiro_de_expandir(script), entrada=senha_do_sudo + "\n", tempo_limite=300,
                               descricao="expandir a partição da raiz (sudo, grow_partition.sh)")
    _conferir(r, "a partição não foi expandida")
    return (r.saida or "").strip()[-400:]


def _conferir(r, falhou: str) -> None:
    if r.codigo == SAIDA_SENHA_RECUSADA:
        raise ErroDoSudo("a placa recusou a senha do sudo", senha_recusada=True)
    if r.codigo == SAIDA_SEM_DIRETORIO:
        raise ErroDoSudo("a placa não deixou criar o diretório temporário em /dev/shm (onde a senha fica, na RAM)")
    if r.codigo != 0:
        raise ErroDaPlaca(f"{falhou} (código {r.codigo}): {(r.erro or r.saida).strip()[-200:] or 'sem saída'}")
