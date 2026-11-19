"""As tarefas longas na placa (docs/gui-plan.md, 11.2; a F6.1): a atualização do firmware, a limpeza do cartão, o
que leva mais que um comando e não pode morrer com a conexão. O cabo USB tem mau contato: uma atualização cortada no
meio da troca dos arquivos deixaria a placa sem firmware. Por isso a tarefa roda **desacoplada da conexão** (o
``setsid``), e a conexão só a lança e a acompanha.

**Na placa**, cada tarefa tem uma pasta, ``~/.sh-analyzer/tarefas/<id>/`` (só do usuário):

* ``roteiro.sh`` -- o que ela faz (o aplicativo o manda pelo stdin, depois da senha e do título: nada disso vai numa
  linha de comando);
* ``tipo``, ``titulo``, ``inicio`` e ``pid`` (o do ``rodar.sh``, que a lança);
* ``passos`` -- uma linha por passo, ``nome<TAB>estado<TAB>hora<TAB>texto`` (o estado: ``comecou``, ``ok``,
  ``aviso`` ou ``falhou``), escrita pela função ``passo`` do roteiro;
* ``resultado`` -- ``chave=valor``, escrito pela função ``resultado`` (a versão instalada, a cópia guardada…);
* ``log`` -- a saída do roteiro (o stdout e o stderr juntos);
* ``codigo`` -- o código de saída, escrito no fim (com o ``mv``: quem lê nunca vê um código pela metade).

**O sudo** (como em ``correcoes.py``, mas dentro da tarefa): a senha vai pelo stdin para um askpass num diretório
temporário da ``/dev/shm`` (a RAM), só do usuário; o ``rodar.sh``, já destacado, a valida com ``sudo -A -v`` (o
askpass a apaga ao ser lido) e apaga o diretório logo depois. Daí em diante o roteiro usa ``sudo -n`` (ou a função
``como_root``), no mesmo shell (o roteiro é lido com o ``.``, e não num ``bash`` filho: a credencial do sudo vale
para o shell que a validou). No fim, de qualquer jeito, ``sudo -k``. Conferido na placa de verdade em 19/11/2026: a
credencial validada no ``setsid`` vale para os comandos seguintes dele (simples, num pipe, numa substituição, numa
função; mas não numa função chamada num pipe, que roda num subshell: lá, o ``sudo -n`` direto). **A senha nunca está
numa linha de comando**, num argumento, no registro de atividade ou no log; a senha
errada é :class:`~sh_placa.correcoes.ErroDoSudo`, e a tarefa nem começa.

**Acompanhar** (:meth:`TarefaNaPlaca.acompanhar`): um ``tail -F`` dos passos e do log, desde o começo, até o
``rodar.sh`` terminar (o ``--pid`` do ``tail``). A queda é ``ErroDeConexao`` e não para a tarefa: a conexão seguinte
acompanha de novo, desde o começo, e :func:`tarefas_na_placa` diz quais existem (para quem conecta, ou abre o
aplicativo de novo, saber o que acompanhar). **Uma tarefa interrompida** (a placa desligou, ou alguém a matou) é a
que não roda mais e não tem código: :attr:`EstadoDaTarefa.interrompida`.
"""

from __future__ import annotations

import asyncio
import re
import secrets
import shlex
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from .agente import ErroDaPlaca
from .correcoes import SAIDA_SEM_DIRETORIO, SAIDA_SENHA_RECUSADA, ErroDoSudo

if TYPE_CHECKING:                       # só a anotação: este módulo não carrega o asyncssh
    from .conexao import ConexaoSSH

PASTA_DAS_TAREFAS = ".sh-analyzer/tarefas"
"""A pasta das tarefas na placa, relativa ao home."""
ESTADOS_DO_PASSO = ("comecou", "ok", "aviso", "falhou")
SAIDA_SEM_TAREFA = 90                   # estado, acompanhar ou limpar uma tarefa que não existe
SAIDA_NAO_LANCOU = 91                   # o rodar.sh não deu o PID a tempo
SAIDA_JA_EXISTE = 92                    # a pasta da tarefa já existe (um id repetido)
SAIDA_RODANDO = 93                      # limpar uma tarefa que ainda roda
TEMPO_DO_LANCAMENTO_S = 45.0
LIMITE_DO_LOG = 256 * 1024
"""Do log, :meth:`TarefaNaPlaca.estado` traz só o fim (uma compilação com avisos passa de dezenas de kB)."""
_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,80}$")

_RODAR = r"""# o rodar.sh de uma tarefa do SH-Analyzer (sh_placa/tarefas.py): $1 = a pasta dela, $2 = a do askpass (ou vazio)
SHAN_TAREFA=$1; _askpass=$2
cd "$HOME" || exit 1
exec > "$SHAN_TAREFA/log" 2>&1 < /dev/null
printf '%s\n' "$$" > "$SHAN_TAREFA/pid"
_fim() {
    _c=$?
    trap - EXIT
    [ -n "$_askpass" ] && { rm -rf "$_askpass"; sudo -k 2>/dev/null; }
    printf '%s\n' "$_c" > "$SHAN_TAREFA/codigo.tmp" && mv -f "$SHAN_TAREFA/codigo.tmp" "$SHAN_TAREFA/codigo"
    exit "$_c"
}
trap _fim EXIT
passo() {   # passo NOME ESTADO [TEXTO]: uma linha em passos (o estado: comecou, ok, aviso, falhou)
    printf '%s\t%s\t%s\t%s\n' "$1" "$2" "$(date +%s)" "$(printf '%s' "${3:-}" | tr '\t\n' '  ')" \
        >> "$SHAN_TAREFA/passos"
}
resultado() {   # resultado CHAVE VALOR: uma linha em resultado
    printf '%s=%s\n' "$1" "$(printf '%s' "$2" | tr '\n' ' ')" >> "$SHAN_TAREFA/resultado"
}
como_root() { sudo -n "$@"; }   # nunca num pipe: lá a função roda num subshell, e a credencial é do shell
if [ -n "$_askpass" ]; then
    SUDO_ASKPASS="$_askpass/askpass" sudo -A -p '' -v 2>/dev/null
    _v=$?
    rm -rf "$_askpass"
    [ "$_v" -eq 0 ] || exit 98
    : > "$SHAN_TAREFA/sudo"
fi
umask 022
. "$SHAN_TAREFA/roteiro.sh"
"""
"""O que roda destacado (``setsid``): a saída para o ``log``, o PID, o sudo validado, as funções do roteiro e, no
fim (o ``trap`` do ``EXIT``, também no ``exit`` do roteiro), o código. O roteiro é lido com o ``.``: no mesmo shell
que validou o sudo, com o ``umask`` de sempre (o 077 do lançamento é para a pasta da tarefa e o askpass: um arquivo
de sistema criado com ele ficaria só do root, e o kernel lê o firmware da PRU com as credenciais de quem pede o
``start``)."""

_LANCAR = r"""set -u
umask 077
base="$HOME/{pasta}"; id=$1; tipo=$2; com_sudo=$3
d="$base/$id"
mkdir -p "$base" && mkdir "$d" || exit {ja_existe}
IFS= read -r senha || senha=
IFS= read -r titulo || titulo=
cat > "$d/roteiro.sh"
printf '%s\n' "$tipo" > "$d/tipo"
printf '%s\n' "$titulo" > "$d/titulo"
date +%s > "$d/inicio"
cat > "$d/rodar.sh" <<'SHAN_FIM_DO_RODAR'
{rodar}SHAN_FIM_DO_RODAR
a=
if [ "$com_sudo" = 1 ]; then
    a=$(mktemp -d "${{SHAN_RAM:-/dev/shm}}/sh-analyzer.XXXXXX") || {{ rm -rf "$d"; exit {sem_diretorio}; }}
    printf '%s\n' "$senha" > "$a/senha"
    printf '#!/bin/sh\ncat "%s/senha" 2>/dev/null\nrm -f "%s/senha"\n' "$a" "$a" > "$a/askpass"
    chmod 700 "$a/askpass"
fi
senha=
setsid bash "$d/rodar.sh" "$d" "$a" < /dev/null > /dev/null 2>&1 &
i=0
while [ "$i" -lt 300 ]; do
    if [ -f "$d/codigo" ]; then
        if [ "$(cat "$d/codigo")" = {recusada} ]; then rm -rf "$d"; exit {recusada}; fi
        break
    fi
    if [ -f "$d/pid" ] && {{ [ "$com_sudo" != 1 ] || [ -f "$d/sudo" ]; }}; then break; fi
    sleep 0.1
    i=$((i + 1))
done
[ -f "$d/pid" ] || {{ [ -n "$a" ] && rm -rf "$a"; exit {nao_lancou}; }}
cat "$d/pid"
"""

_DESCREVER = r"""d="$HOME/{pasta}/$1"
[ -d "$d" ] || exit {sem_tarefa}
for f in tipo titulo inicio pid codigo; do printf '%s\t%s\n' "$f" "$(cat "$d/$f" 2>/dev/null)"; done
p=$(cat "$d/pid" 2>/dev/null)
if [ -n "$p" ] && [ ! -f "$d/codigo" ] && kill -0 "$p" 2>/dev/null && grep -q rodar.sh "/proc/$p/cmdline" 2>/dev/null
then printf 'rodando\t1\n'; else printf 'rodando\t0\n'; fi
echo "--passos"
cat "$d/passos" 2>/dev/null
echo "--resultado"
cat "$d/resultado" 2>/dev/null
if [ "${{2:-0}}" = 1 ]; then echo "--log"; tail -c {limite} "$d/log" 2>/dev/null; fi
"""
"""Os fatos de uma tarefa (``$1``, o id; ``$2`` = 1, com o fim do log): ``chave<TAB>valor`` e as seções ``--passos``,
``--resultado`` e ``--log``. Um PID que roda e não é o ``rodar.sh`` (a placa reiniciou, e o número voltou para
outro processo) não conta."""

_LIMPAR = r"""d="$HOME/{pasta}/$1"
[ -d "$d" ] || exit {sem_tarefa}
p=$(cat "$d/pid" 2>/dev/null)
if [ -n "$p" ] && [ ! -f "$d/codigo" ] && kill -0 "$p" 2>/dev/null && grep -q rodar.sh "/proc/$p/cmdline" 2>/dev/null
then exit {rodando}; fi
rm -rf -- "$d"
"""

_ACOMPANHAR = r"""d="$HOME/{pasta}/$1"
[ -d "$d" ] || exit {sem_tarefa}
: >> "$d/passos"
: >> "$d/log"
p=$(cat "$d/pid" 2>/dev/null)
if [ -n "$p" ] && [ ! -f "$d/codigo" ] && kill -0 "$p" 2>/dev/null; then
    tail -n +1 -F --pid="$p" -s 0.3 "$d/passos" "$d/log" 2>/dev/null
else
    tail -n +1 "$d/passos" "$d/log" 2>/dev/null
fi
printf '\n==> SHAN-FIM <==\n'
cat "$d/codigo" 2>/dev/null
"""
"""Os passos e o log, desde o começo, até o ``rodar.sh`` terminar: o ``tail`` separa os dois arquivos com as linhas
``==> caminho <==``; no fim, a marca e o código."""


def _formatar(modelo: str, **extras) -> str:
    return modelo.format(pasta=PASTA_DAS_TAREFAS, sem_tarefa=SAIDA_SEM_TAREFA, nao_lancou=SAIDA_NAO_LANCOU,
                         ja_existe=SAIDA_JA_EXISTE, rodando=SAIDA_RODANDO, recusada=SAIDA_SENHA_RECUSADA,
                         sem_diretorio=SAIDA_SEM_DIRETORIO, limite=LIMITE_DO_LOG, **extras)


def roteiro_de_lancamento() -> str:
    """O que roda na placa para lançar uma tarefa (o "Ver o comando" mostra isto e o roteiro da tarefa)."""
    return _formatar(_LANCAR, rodar=_RODAR)


def novo_id(tipo: str) -> str:
    """Um id para uma tarefa nova: o tipo, a data e a hora deste computador e um sufixo ao acaso."""
    base = re.sub(r"[^a-z0-9]+", "-", tipo.lower()).strip("-") or "tarefa"
    return f"{base}-{time.strftime('%Y%m%d-%H%M%S')}-{secrets.token_hex(2)}"


def _conferir_id(id_: str) -> str:
    if not _ID.match(id_):
        raise ValueError(f"id de tarefa inválido: {id_!r}")
    return id_


@dataclass(frozen=True)
class Passo:
    nome: str
    estado: str                         # ESTADOS_DO_PASSO
    texto: str = ""
    em: float | None = None             # a hora da placa (o relógio dela pode estar errado)


@dataclass(frozen=True)
class EstadoDaTarefa:
    """O que se sabe de uma tarefa: os passos na ordem em que chegaram (um passo pode aparecer mais de uma vez, do
    ``comecou`` ao ``ok``), o resultado, o fim do log e o código (``None`` enquanto roda)."""

    id: str
    tipo: str = ""
    titulo: str = ""
    rodando: bool = False
    codigo: int | None = None
    passos: tuple[Passo, ...] = ()
    resultado: dict[str, str] = field(default_factory=dict)
    log: str = ""
    inicio: float | None = None

    @property
    def terminou(self) -> bool:
        return self.codigo is not None

    @property
    def interrompida(self) -> bool:
        """Não roda mais e não tem código: a placa desligou ou reiniciou no meio, ou alguém a matou."""
        return not self.rodando and self.codigo is None

    def passo(self, nome: str) -> Passo | None:
        """O último estado do passo ``nome``."""
        for p in reversed(self.passos):
            if p.nome == nome:
                return p
        return None

    def estados(self) -> dict[str, Passo]:
        """O último estado de cada passo, na ordem em que cada um apareceu pela primeira vez."""
        ultimos: dict[str, Passo] = {}
        for p in self.passos:
            ultimos[p.nome] = p
        return ultimos


def ler_passo(linha: str) -> Passo | None:
    partes = linha.rstrip("\n").split("\t", 3)
    if len(partes) < 2 or not partes[0] or partes[1] not in ESTADOS_DO_PASSO:
        return None
    try:
        em = float(partes[2]) if len(partes) > 2 and partes[2] else None
    except ValueError:
        em = None
    return Passo(partes[0], partes[1], partes[3] if len(partes) > 3 else "", em)


def ler_resultado(texto: str) -> dict[str, str]:
    resultado = {}
    for linha in texto.splitlines():
        chave, igual, valor = linha.partition("=")
        if igual and chave:
            resultado[chave] = valor
    return resultado


def _inteiro(texto: str) -> int | None:
    try:
        return int(texto.strip())
    except ValueError:
        return None


def _ler_estado(id_: str, texto: str) -> EstadoDaTarefa:
    campos: dict[str, str] = {}
    secoes: dict[str, list[str]] = {"passos": [], "resultado": [], "log": []}
    atual = None
    for linha in texto.splitlines(keepends=True):
        marca = linha.rstrip("\n")
        if marca in ("--passos", "--resultado", "--log") and (atual != "log"):
            atual = marca[2:]
            continue
        if atual is None:
            chave, _, valor = marca.partition("\t")
            campos[chave] = valor
        else:
            secoes[atual].append(linha)
    passos = tuple(p for p in (ler_passo(x) for x in secoes["passos"]) if p is not None)
    inicio = _inteiro(campos.get("inicio", ""))
    return EstadoDaTarefa(id_, campos.get("tipo", ""), campos.get("titulo", ""), campos.get("rodando") == "1",
                          _inteiro(campos.get("codigo", "")), passos, ler_resultado("".join(secoes["resultado"])),
                          "".join(secoes["log"]), None if inicio is None else float(inicio))


class TarefaNaPlaca:
    """Uma tarefa na placa, pelo id (:meth:`lancar` cria uma; :func:`tarefas_na_placa` acha as que existem)."""

    def __init__(self, conexao: ConexaoSSH, id_: str):
        self.conexao, self.id = conexao, _conferir_id(id_)

    @classmethod
    async def lancar(cls, conexao: ConexaoSSH, tipo: str, titulo: str, roteiro: str, *,
                     senha_do_sudo: str | None = None, id_: str | None = None,
                     tempo_limite_s: float = TEMPO_DO_LANCAMENTO_S) -> TarefaNaPlaca:
        """Lança ``roteiro`` (bash, com as funções ``passo``, ``resultado`` e ``como_root``) destacado da conexão.
        Com ``senha_do_sudo``, o sudo é validado antes do roteiro começar (a senha recusada é :class:`ErroDoSudo`,
        e a tarefa não existe). ``ErroDaPlaca`` se não lançou."""
        id_ = _conferir_id(id_ or novo_id(tipo))
        if "\n" in titulo or "\n" in (senha_do_sudo or ""):
            raise ValueError("o título e a senha são de uma linha só")
        comando = (f"bash -c {shlex.quote(roteiro_de_lancamento())} lancar {shlex.quote(id_)} {shlex.quote(tipo)} "
                   f"{1 if senha_do_sudo is not None else 0}")
        entrada = f"{senha_do_sudo or ''}\n{titulo}\n{roteiro}"
        r = await conexao.executar(comando, entrada=entrada, tempo_limite=tempo_limite_s,
                                   descricao=f"lançar a tarefa {titulo} ({id_}, destacada da conexão"
                                             f"{', com o sudo' if senha_do_sudo is not None else ''})")
        if r.codigo == SAIDA_SENHA_RECUSADA:
            raise ErroDoSudo("a placa recusou a senha do sudo", senha_recusada=True)
        if r.codigo == SAIDA_SEM_DIRETORIO:
            raise ErroDoSudo("a placa não deixou criar o diretório temporário em /dev/shm (onde a senha fica, na RAM)")
        if r.codigo == SAIDA_JA_EXISTE:
            raise ErroDaPlaca(f"já existe uma tarefa {id_} na placa (ou a pasta ~/{PASTA_DAS_TAREFAS} não pôde ser "
                              "criada: o cartão está cheio?)")
        if r.codigo != 0:
            detalhe = (r.erro or r.saida).strip()[-300:] or "sem saída"
            raise ErroDaPlaca(f"a tarefa {titulo} não começou na placa (código {r.codigo}): {detalhe}")
        return cls(conexao, id_)

    async def estado(self, com_log: bool = False) -> EstadoDaTarefa:
        r = await self.conexao.executar(
            f"sh -c {shlex.quote(_formatar(_DESCREVER))} sh {shlex.quote(self.id)} {1 if com_log else 0}",
            descricao=f"ler o estado da tarefa {self.id}")
        if r.codigo == SAIDA_SEM_TAREFA:
            raise ErroDaPlaca(f"a tarefa {self.id} não existe mais na placa")
        if r.codigo != 0:
            raise ErroDaPlaca(f"não deu para ler a tarefa {self.id} (código {r.codigo})")
        return _ler_estado(self.id, r.saida)

    async def acompanhar(self, ao_mudar: Callable[[EstadoDaTarefa], None] | None = None,
                         ao_log: Callable[[str], None] | None = None) -> EstadoDaTarefa:
        """Os passos e o log ao vivo (``ao_mudar(estado)`` a cada passo novo, ``ao_log(texto)`` a cada pedaço do
        log), desde o começo, até a tarefa terminar; devolve o estado final, com o fim do log. A queda é
        ``ErroDeConexao`` (a tarefa segue na placa: acompanhe de novo)."""
        pasta = f"{PASTA_DAS_TAREFAS}/{self.id}"
        passos: list[Passo] = []
        atual = None
        comando = f"sh -c {shlex.quote(_formatar(_ACOMPANHAR))} sh {shlex.quote(self.id)}"
        fim = False
        resto_do_codigo: list[str] = []
        base = await self.estado()
        async with self.conexao.canal(comando, f"acompanhar a tarefa {self.id}") as (processo, desfecho):
            async for linha in processo.stdout:
                marca = linha.rstrip("\n")
                if fim:
                    resto_do_codigo.append(marca)
                    continue
                if marca.startswith("==> ") and marca.endswith(" <=="):
                    nome = marca[4:-4]
                    if nome == "SHAN-FIM":
                        fim = True
                    elif nome.endswith(f"{pasta}/passos"):
                        atual = "passos"
                    elif nome.endswith(f"{pasta}/log"):
                        atual = "log"
                    continue
                if atual == "passos":
                    p = ler_passo(linha)
                    if p is not None:
                        passos.append(p)
                        if ao_mudar is not None:
                            ao_mudar(EstadoDaTarefa(self.id, base.tipo, base.titulo, True, None, tuple(passos),
                                                    {}, "", base.inicio))
                elif atual == "log" and ao_log is not None and linha != "\n":
                    ao_log(linha)
            await processo.wait()
            self.conexao.concluir(processo, desfecho, f"acompanhar a tarefa {self.id}")
        if desfecho.codigo == SAIDA_SEM_TAREFA:
            raise ErroDaPlaca(f"a tarefa {self.id} não existe mais na placa")
        return await self.estado(com_log=True)

    async def esperar(self, intervalo_s: float = 0.5, tempo_limite_s: float = 600.0) -> EstadoDaTarefa:
        """Espera o fim lendo o estado de tempos em tempos (para os testes e quem não quer o log ao vivo)."""
        limite = time.monotonic() + tempo_limite_s
        while True:
            e = await self.estado(com_log=True)
            if e.terminou or e.interrompida:
                return e
            if time.monotonic() > limite:
                raise ErroDaPlaca(f"a tarefa {self.id} não terminou em {tempo_limite_s:g} s")
            await asyncio.sleep(intervalo_s)

    async def limpar(self) -> None:
        """Apaga a pasta da tarefa na placa (a que ainda roda fica: ``ErroDaPlaca``)."""
        r = await self.conexao.executar(f"sh -c {shlex.quote(_formatar(_LIMPAR))} sh {shlex.quote(self.id)}",
                                        descricao=f"apagar a tarefa {self.id} (terminada)")
        if r.codigo == SAIDA_RODANDO:
            raise ErroDaPlaca(f"a tarefa {self.id} ainda roda na placa")
        if r.codigo not in (0, SAIDA_SEM_TAREFA):
            raise ErroDaPlaca(f"não deu para apagar a tarefa {self.id} (código {r.codigo})")


async def tarefas_na_placa(conexao: ConexaoSSH, tipo: str | None = None) -> list[EstadoDaTarefa]:
    """As tarefas que estão na placa (rodando, terminadas e ainda não limpas, ou interrompidas), as mais antigas
    primeiro; só as do ``tipo``, se dado."""
    r = await conexao.executar(f"sh -c {shlex.quote(_listar(_formatar(_DESCREVER)))}",
                               descricao="listar as tarefas na placa")
    if r.codigo != 0:
        raise ErroDaPlaca(f"não deu para listar as tarefas da placa (código {r.codigo})")
    tarefas = []
    for bloco in r.saida.split("--tarefa ")[1:]:
        id_, _, resto = bloco.partition("\n")
        if _ID.match(id_):
            tarefas.append(_ler_estado(id_, resto))
    tarefas.sort(key=lambda t: (t.inicio or 0, t.id))
    return [t for t in tarefas if tipo is None or t.tipo == tipo]


def _listar(descrever: str) -> str:
    """O roteiro que lista as tarefas: o :data:`_DESCREVER` de cada uma, numa função (sem o ``sh -c`` aninhado)."""
    corpo = descrever.replace("$1", "$_id").replace("${2:-0}", "0")
    corpo = corpo.replace(f"exit {SAIDA_SEM_TAREFA}", "return")
    return (f'base="$HOME/{PASTA_DAS_TAREFAS}"\n[ -d "$base" ] || exit 0\n'
            f"descrever() {{\n{corpo}}}\n"
            'for _d in "$base"/*/; do\n    [ -d "$_d" ] || continue\n    _id=$(basename "$_d")\n'
            '    echo "--tarefa $_id"\n    descrever\ndone\n')
