"""A captura no cartão (docs/gui-plan.md, 11.5; a F4.4): o ``ler_adc -o NOME --progresso-json`` na placa,
**desacoplado da conexão**. O cabo USB tem mau contato, e o motivo de gravar no cartão é a captura sobreviver a ele:
a queda interrompe só o acompanhamento, e a conexão seguinte (ou o aplicativo aberto de novo) volta a acompanhar.

**Na placa** (:meth:`CapturaNoCartao.iniciar`), na pasta do firmware: o roteiro confere o ``ler_adc`` (os códigos
da captura contínua, :data:`~sh_placa.captura.SAIDA_SEM_LER_ADC` e
:data:`~sh_placa.captura.SAIDA_SEM_SAIDA_CONTINUA`), o nome (:data:`~sh_placa.captura.SAIDA_NOME_EXISTE`: nada é
sobrescrito) e outra captura rodando (:data:`~sh_placa.captura.SAIDA_OUTRA_CAPTURA`), valida o sudo com a senha (a
primeira linha do stdin, como em ``correcoes.py``) e lança, num ``setsid`` de root (:data:`_LANCAR`), o ``ler_adc``
com o ``HUP`` ignorado (ele respeita o herdado), o texto dele, as linhas de progresso, o PID e, no fim, o código de
saída em :data:`PASTA_EM_CURSO` ``/NOME/`` (uma pasta oculta da pasta do firmware, que o agente não lista).

**O acompanhamento** (:meth:`CapturaNoCartao.acompanhar`): um ``tail -F`` das linhas de progresso e do texto (no
modo arquivo, o ``ler_adc`` escreve o resumo no stdout e os erros e avisos no stderr, junto das linhas de progresso),
desde o começo, até o ``ler_adc`` terminar (o ``--pid`` do ``tail``) e o código aparecer. A queda é ``ErroDeConexao`` (a
captura segue na placa); acompanhar de novo relê tudo desde o começo. :func:`em_curso` lista as capturas da pasta
(rodando ou terminadas e ainda não recolhidas), para quem conecta saber o que acompanhar.

**Parar** (:meth:`CapturaNoCartao.parar`): um ``sudo kill -INT`` no PID, com a senha validada no mesmo roteiro (a
credencial do sudo é do shell que a validou). O ``ler_adc`` para como no Ctrl+C: o bloco em curso é descartado, e o
cabeçalho final fica certo no arquivo. **No fim**, :meth:`CapturaNoCartao.limpar` apaga a pasta dela em
:data:`PASTA_EM_CURSO`; a captura fica no cartão, para a transferência.
"""

from __future__ import annotations

import asyncio
import logging
import shlex
from collections import deque
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from supraharmonicos import saida_continua

from .agente import PASTA_DO_FIRMWARE
from .captura import (
    LINHAS_DE_TEXTO,
    MOTIVOS,
    OPCOES_DO_RECEPTOR,
    SAIDA_NOME_EXISTE,
    SAIDA_OUTRA_CAPTURA,
    SAIDA_SEM_LER_ADC,
    SAIDA_SEM_SAIDA_CONTINUA,
    ErroDaCaptura,
    Progresso,
    erro_antes_de_comecar,
)
from .correcoes import validar_o_sudo

if TYPE_CHECKING:                       # só a anotação: este módulo não carrega o asyncssh
    from .conexao import ConexaoSSH

log = logging.getLogger(__name__)

PASTA_EM_CURSO = ".em_curso"
SAIDA_SEM_PASTA = 92                    # a pasta da captura em .em_curso não foi criada
SAIDA_NAO_LANCOU = 91                   # o ler_adc não deu o PID a tempo
SAIDA_SEM_CAPTURA = 90                  # acompanhar ou parar uma captura que não está em .em_curso
TEMPO_PARA_INICIAR_S = 60.0
TEMPO_PARA_PARAR_S = 30.0
MARCA_DO_FIM = "shan-fim"

_LANCAR = """d=$1
shift
trap '' HUP
"$@" >"$d/texto" 2>"$d/progresso" </dev/null &
p=$!
echo "$p" >"$d/pid"
wait "$p"
echo "$?" >"$d/codigo"
"""
"""O shell de root, num ``setsid``, que roda o ``ler_adc`` (os argumentos dele) e guarda o PID e o código de saída na
pasta da captura (o primeiro argumento). O ``HUP`` ignorado passa ao ``ler_adc``, que o respeita; o ``SIGINT`` de um
processo em segundo plano nasce ignorado, mas o ``ler_adc`` instala o tratador dele mesmo assim."""

_INICIAR = """cd {pasta} 2>/dev/null && [ -x ./ler_adc ] || exit {sem_ler_adc}
./ler_adc --help 2>/dev/null | grep -q -e --progresso-json || exit {sem_progresso}
[ -e {nome} ] && exit {nome_existe}
pgrep -x ler_adc >/dev/null 2>&1 && exit {outra}
{validar}umask 022
c="$PWD"/{em_curso}/{nome}
rm -rf "$c" && mkdir -p "$c" || exit {sem_pasta}
sudo -n setsid sh -c {lancar} ler_adc "$c" ./ler_adc {argumentos} </dev/null >/dev/null 2>&1 &
i=0
while [ ! -s "$c/pid" ] && [ ! -s "$c/codigo" ] && [ $i -lt 100 ]; do sleep 0.1; i=$((i+1)); done
[ -s "$c/pid" ] || exit {nao_lancou}
"""
"""O começo: as conferências, o sudo validado (o trecho de ``correcoes.py``, que usa o ``$d`` para a pasta do askpass
e o apaga na saída, e deixa o ``umask 077``: daí o ``$c`` e o ``umask 022``, para o texto e o progresso que o root
grava serem legíveis pelo usuário) e o lançamento."""

_ACOMPANHAR = """d={pasta}/{em_curso}/{nome}
[ -d "$d" ] || exit {sem_captura}
i=0
while [ ! -s "$d/pid" ] && [ $i -lt 50 ]; do sleep 0.1; i=$((i+1)); done
p=$(cat "$d/pid" 2>/dev/null)
[ -n "$p" ] || exit {sem_captura}
if [ -s "$d/codigo" ]; then
    cat "$d/progresso" 2>/dev/null
    cat "$d/texto" >&2 2>/dev/null
else
    trap 'kill $a $b 2>/dev/null; exit 143' HUP TERM
    tail -n +1 -F -s 0.5 --pid="$p" "$d/progresso" 2>/dev/null &
    a=$!
    tail -n +1 -F -s 0.5 --pid="$p" "$d/texto" 3>&2 2>/dev/null 1>&3 &
    b=$!
    wait $a $b
    i=0
    while [ ! -s "$d/codigo" ] && [ $i -lt 50 ]; do sleep 0.1; i=$((i+1)); done
fi
echo "{marca} $(cat "$d/codigo" 2>/dev/null)"
"""

_PARAR = """d={pasta}/{em_curso}/{nome}
p=$(cat "$d/pid" 2>/dev/null)
[ -n "$p" ] || exit {sem_captura}
[ -s "$d/codigo" ] && exit 0
{validar}sudo -n kill -INT "$p"
"""

_LIMPAR = """rm -rf {pasta}/{em_curso}/{nome}
rmdir {pasta}/{em_curso} 2>/dev/null
true
"""

_EM_CURSO = """e={pasta}/{em_curso}
[ -d "$e" ] || exit 0
for d in "$e"/*/; do
    [ -d "$d" ] || continue
    p=$(cat "$d/pid" 2>/dev/null)
    v=0
    [ -n "$p" ] && [ -d "/proc/$p" ] && v=1
    printf '%s\\t%s\\t%s\\n' "$(basename "$d")" "$v" "$(cat "$d/codigo" 2>/dev/null)"
done
"""


def _pasta(pasta_firmware: str) -> str:
    """A pasta do firmware no shell da placa (uma relativa é a partir do ``$HOME``, como a do agente)."""
    return shlex.quote(pasta_firmware) if pasta_firmware.startswith("/") else (
        '"$HOME"/' + shlex.quote(pasta_firmware.lstrip("~/") or "."))


def roteiro_de_inicio(nome: str, argumentos: Sequence[str], pasta_firmware: str = PASTA_DO_FIRMWARE) -> str:
    """O que roda na placa para começar a captura ``nome`` (o "Ver o comando" mostra isto). ``argumentos``: os do
    ``ler_adc`` sem os do receptor nem o ``-o`` (o ``-o NOME --progresso-json`` vem daqui); ``ValueError`` com eles."""
    argumentos = [str(a) for a in argumentos]
    proprias = [a for a in argumentos if a in OPCOES_DO_RECEPTOR or a.startswith("--saida=")]
    if proprias:
        raise ValueError(f"a captura no cartão põe -o e --progresso-json ela mesma: tire {proprias[0]} do pedido")
    if not argumentos:
        raise ValueError("a captura no cartão precisa dos argumentos do ler_adc (a taxa e os canais)")
    _conferir_o_nome(nome)
    completos = [*argumentos, "-o", nome, "--progresso-json"]
    return _INICIAR.format(pasta=_pasta(pasta_firmware), sem_ler_adc=SAIDA_SEM_LER_ADC,
                           sem_progresso=SAIDA_SEM_SAIDA_CONTINUA, nome_existe=SAIDA_NOME_EXISTE,
                           outra=SAIDA_OUTRA_CAPTURA, em_curso=PASTA_EM_CURSO, nome=shlex.quote(nome),
                           sem_pasta=SAIDA_SEM_PASTA, validar=validar_o_sudo(), lancar=shlex.quote(_LANCAR),
                           argumentos=" ".join(map(shlex.quote, completos)), nao_lancou=SAIDA_NAO_LANCOU)


def _conferir_o_nome(nome: str) -> None:
    if not nome or "/" in nome or nome in (".", "..") or nome.startswith("."):
        raise ValueError(f"'{nome}' não é um nome de captura no cartão (sem pastas, sem começar com '.')")


@dataclass(frozen=True)
class CapturaEmCurso:
    """Uma captura em :data:`PASTA_EM_CURSO`: rodando, ou terminada (com o código) e ainda não recolhida."""

    nome: str
    rodando: bool
    codigo: int | None


@dataclass(frozen=True)
class CapturaGravadaNoCartao:
    """O fim de uma captura no cartão: como o ``ler_adc`` terminou, a linha ``fim`` dele e o texto."""

    nome: str                             # na pasta do firmware (a transferência acha pela lista do agente)
    codigo: int | None
    motivo: str
    fim: dict | None                      # a linha "fim" do --progresso-json (o CRC, a integridade)
    blocos: int
    parada_pedida: bool
    texto: tuple[str, ...]
    duracao_s: float                      # o tempo da captura (o t_s do último bloco)

    @property
    def gravou(self) -> bool:
        """Há uma captura no cartão (pelo menos um bloco inteiro)."""
        return self.blocos > 0

    @property
    def integridade(self) -> tuple[int, int, int] | None:
        """As amostras atrasadas, os buffers sobrescritos e os quadros com ruído no SDO do fim (None sem ele)."""
        if self.fim is None:
            return None
        return tuple(int(self.fim.get(c) or 0) for c in ("amostras_atrasadas", "buffers_sobrescritos",
                                                          "quadros_preambulo_ruim"))


async def em_curso(conexao: ConexaoSSH, pasta_firmware: str = PASTA_DO_FIRMWARE) -> list[CapturaEmCurso]:
    """As capturas no cartão que a placa tem em :data:`PASTA_EM_CURSO` (as que rodam e as que ninguém recolheu)."""
    r = await conexao.executar(_EM_CURSO.format(pasta=_pasta(pasta_firmware), em_curso=PASTA_EM_CURSO),
                               descricao="as capturas no cartão em curso")
    capturas = []
    for linha in r.saida.splitlines():
        partes = linha.split("\t")
        if len(partes) != 3 or not partes[0]:
            continue
        nome, rodando, codigo = partes
        capturas.append(CapturaEmCurso(nome, rodando == "1", int(codigo) if codigo.strip().lstrip("-").isdigit()
                                       else None))
    return capturas


class CapturaNoCartao:
    """Uma captura no cartão chamada ``nome`` (o ``-o`` do ``ler_adc``, na pasta do firmware): :meth:`iniciar` a
    lança; :meth:`acompanhar` a segue até o fim (de novo depois de uma queda, ou para uma que outro aplicativo
    lançou); :meth:`parar` pede o fim; :meth:`limpar` recolhe a pasta dela em :data:`PASTA_EM_CURSO`.
    ``ao_progresso`` recebe um :class:`~sh_placa.captura.Progresso` a cada linha de progresso (os ``bytes_recebidos``
    são os do arquivo no cartão), e ``ao_texto``, cada linha do texto do ``ler_adc``."""

    def __init__(self, conexao: ConexaoSSH, nome: str, *, pasta_firmware: str = PASTA_DO_FIRMWARE,
                 ao_progresso: Callable[[Progresso], object] | None = None,
                 ao_texto: Callable[[str], object] | None = None):
        _conferir_o_nome(nome)
        self.conexao, self.nome, self.pasta_firmware = conexao, nome, pasta_firmware
        self.ao_progresso, self.ao_texto = ao_progresso, ao_texto
        self.parada_pedida = False
        self.acompanhamento = saida_continua.Acompanhamento()
        self._texto: deque[str] = deque(maxlen=LINHAS_DE_TEXTO)

    def _formatar(self, modelo: str, **extras) -> str:
        return modelo.format(pasta=_pasta(self.pasta_firmware), em_curso=PASTA_EM_CURSO,
                             nome=shlex.quote(self.nome), sem_captura=SAIDA_SEM_CAPTURA, **extras)

    async def iniciar(self, argumentos: Sequence[str], senha_do_sudo: str) -> None:
        """Lança a captura na placa e volta com o ``ler_adc`` rodando (o PID dele dado). Os erros do roteiro:
        ``FirmwareSemLerAdc``, ``FirmwareSemSaidaContinua`` (o ``ler_adc`` de antes do ``--progresso-json``),
        ``ErroDoSudo``, :class:`~sh_placa.captura.ErroDaCaptura` (o nome que existe, outra captura rodando) e
        ``ErroDeConexao``. O ``ler_adc`` que recusa o pedido aparece no :meth:`acompanhar`."""
        roteiro = roteiro_de_inicio(self.nome, argumentos, self.pasta_firmware)
        r = await self.conexao.executar(roteiro, entrada=senha_do_sudo + "\n", tempo_limite=TEMPO_PARA_INICIAR_S,
                                        descricao=f"começar a captura no cartão: ler_adc {' '.join(argumentos)} -o "
                                                  f"{self.nome}")
        if r.codigo == 0:
            log.info("captura no cartão '%s' lançada", self.nome)
            return
        if r.codigo == SAIDA_NAO_LANCOU:
            raise ErroDaCaptura("o ler_adc não começou na placa (nenhum PID em 10 s)", r.codigo)
        if r.codigo == SAIDA_SEM_PASTA:
            raise ErroDaCaptura(f"a placa não deixou criar a pasta {PASTA_EM_CURSO} na pasta do firmware (o disco "
                                "cheio?)", r.codigo)
        raise erro_antes_de_comecar(r.codigo, (r.erro or r.saida).splitlines())

    async def acompanhar(self) -> CapturaGravadaNoCartao:
        """Segue a captura desde o começo das linhas de progresso até o ``ler_adc`` terminar. ``ErroDeConexao`` na
        queda (a captura segue na placa: acompanhe de novo depois); :class:`~sh_placa.captura.ErroDaCaptura` se o
        ``ler_adc`` terminou sem começar (o pedido recusado, a PRU), com o texto dele."""
        self.acompanhamento = saida_continua.Acompanhamento()
        self._texto.clear()
        codigo: int | None = None
        sem_captura = False
        descricao = f"acompanhar a captura no cartão {self.nome}"
        async with self.conexao.canal(self._formatar(_ACOMPANHAR, marca=MARCA_DO_FIM), descricao) as (
                processo, desfecho):
            processo.stdin.write_eof()
            resultados = await asyncio.gather(self._ler_o_progresso(processo.stdout),
                                              self._ler_o_texto(processo.stderr))
            codigo = resultados[0]
            await processo.wait()
            self.conexao.concluir(processo, desfecho, descricao)      # sem o código: ErroDeConexao (a queda)
            sem_captura = desfecho.codigo == SAIDA_SEM_CAPTURA
        if sem_captura:
            raise ErroDaCaptura(f"a placa não tem a captura {self.nome} em curso ({PASTA_EM_CURSO})", SAIDA_SEM_CAPTURA)
        a = self.acompanhamento
        if a.inicio is None:
            raise erro_antes_de_comecar(codigo, self._texto)
        ultimo = a.ate(max(a.blocos)) if a.blocos else None
        fim = a.fim
        blocos = int(fim["blocos"]) if fim and fim.get("blocos") is not None else (int(ultimo["bloco"]) if ultimo
                                                                                    else 0)
        motivo = (fim or {}).get("motivo") or MOTIVOS.get(codigo, f"codigo_{codigo}")
        parada = self.parada_pedida or motivo == "interrompida"
        gravada = CapturaGravadaNoCartao(self.nome, codigo, motivo, fim, blocos, parada,
                                         tuple(self._texto), float(ultimo["t_s"]) if ultimo else 0.0)
        log.info("captura no cartão '%s': %d bloco(s), %s", self.nome, blocos, motivo)
        return gravada

    async def _ler_o_progresso(self, stdout) -> int | None:
        codigo = None
        while True:
            bruta = await stdout.readline()
            if not bruta:
                return codigo
            linha = bruta.rstrip("\r\n") if isinstance(bruta, str) else bruta.decode("utf-8", "replace").rstrip()
            if linha.startswith(MARCA_DO_FIM):
                resto = linha[len(MARCA_DO_FIM):].strip()
                codigo = int(resto) if resto.lstrip("-").isdigit() else None
                continue
            if self.acompanhamento.receber(linha) is not None:
                self._avisar()
            else:                             # no modo arquivo, os erros e avisos do ler_adc vão para o stderr
                self._guardar_texto(linha)

    async def _ler_o_texto(self, stderr) -> None:
        while True:
            bruta = await stderr.readline()
            if not bruta:
                return
            self._guardar_texto(bruta.rstrip("\r\n") if isinstance(bruta, str)
                                else bruta.decode("utf-8", "replace").rstrip())

    def _guardar_texto(self, linha: str) -> None:
        if linha.strip():
            self._texto.append(linha)
            if self.ao_texto is not None:
                self.ao_texto(linha)

    def _avisar(self) -> None:
        if self.ao_progresso is None:
            return
        a = self.acompanhamento
        inicio = a.inicio or {}
        ultimo = a.ate(max(a.blocos)) if a.blocos else None
        blocos = int(ultimo["bloco"]) if ultimo else 0
        cabecalho = int(inicio.get("bytes_do_cabecalho") or 0)
        no_arquivo = cabecalho + blocos * int(inicio.get("bytes_por_bloco") or 0) if inicio else 0
        segundos = float(ultimo["t_s"]) if ultimo else 0.0
        self.ao_progresso(Progresso(
            blocos=blocos, blocos_pedidos=int(inicio.get("blocos") or 0), bytes_recebidos=no_arquivo,
            segundos=segundos, vazao_bytes_s=(no_arquivo - cabecalho) / segundos if segundos > 0 else 0.0,
            inicio=a.inicio, ultimo_bloco=ultimo, parada_pedida=self.parada_pedida))

    async def parar(self, senha_do_sudo: str) -> None:
        """O Ctrl+C do ``ler_adc`` na placa. O acompanhamento vê o fim."""
        self.parada_pedida = True
        r = await self.conexao.executar(self._formatar(_PARAR, validar=validar_o_sudo()),
                                        entrada=senha_do_sudo + "\n", tempo_limite=TEMPO_PARA_PARAR_S,
                                        descricao=f"parar a captura no cartão {self.nome} (kill -INT)")
        if r.codigo not in (0, 1):            # 1: o ler_adc já tinha terminado entre o cat e o kill
            raise erro_antes_de_comecar(r.codigo, (r.erro or r.saida).splitlines())

    async def limpar(self) -> None:
        """Apaga a pasta da captura em :data:`PASTA_EM_CURSO` (o texto e o progresso dela); a captura fica."""
        await self.conexao.executar(self._formatar(_LIMPAR), descricao=f"recolher a captura no cartão {self.nome}")
