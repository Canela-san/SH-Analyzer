"""A captura contínua (docs/gui-plan.md, 11.6; a F4.2): o ``ler_adc -o - --progresso-json`` na placa, pelo SSH e com o
sudo dela, e a captura gravada num arquivo deste computador enquanto chega: no fim, byte a byte o arquivo que o
``ler_adc`` gravaria no cartão (``supraharmonicos.saida_continua``).

**O roteiro na placa** (:func:`roteiro_da_captura`): na pasta do firmware, confere o ``ler_adc`` (sem ele, sai com
:data:`SAIDA_SEM_LER_ADC`; um de antes da saída contínua, sem o ``--progresso-json`` na ajuda, com
:data:`SAIDA_SEM_SAIDA_CONTINUA`: a placa precisa do firmware novo), valida o sudo com a senha (a primeira linha do
stdin, como em ``correcoes.py``) e roda o ``sudo -n ./ler_adc`` em segundo plano. O stdout do canal é o fluxo da
captura; o stderr, o texto do ``ler_adc`` e as linhas de progresso.

**Parar** (:meth:`CapturaContinua.parar`): uma linha no stdin do roteiro. Na placa, o ``sudo`` roda um shell de root
(:data:`_PARAR_COMO_ROOT`) com o ``ler_adc`` em segundo plano e um leitor dessa linha, que manda o ``SIGINT`` direto
ao ``ler_adc``. Tem de ser do lado root (achado na placa de verdade em 17/11/2026): o usuário não pode mandar sinais
ao ``sudo``, que roda inteiro como root, e um ``sudo -n kill`` de outro processo não teria a credencial (ela é do
shell que a validou, e vence em 15 min, menos que uma captura longa); o sinal do canal SSH chegaria só ao shell do
usuário. O ``ler_adc`` para como no Ctrl+C: o bloco em curso é descartado, e o cabeçalho final sai depois do último
inteiro. O stdin que fecha (o canal que acabou) também
para a captura. Um Parar antes de a captura começar (sem a linha ``inicio``) espera por ela: o sinal não chega ao
``ler_adc`` antes de ele saber parar.

**O arquivo:** gravado em ``<nome>.parcial`` enquanto chega e renomeado no fim, fechado. Uma captura que já existe não
é sobrescrita. **A queda** (a conexão que cai, a placa que para de mandar) e **o disco daqui que recusa a gravação**
(cheio, removido): a captura para, e o que chegou é fechado aqui, com os blocos inteiros e a marca do fim escrito pelo
computador (:class:`CapturaRecebida` com ``caiu`` e a ``falha``). Um cancelamento (o aplicativo que fecha no meio)
deixa o ``.parcial``, que :func:`recuperar` fecha depois. Do lado da placa, o canal que fecha dá ao ``ler_adc`` o
código 6 (a saída fechada), e a PRU para.

**O ao vivo:** ``ao_progresso`` recebe um :class:`Progresso` a cada linha de progresso, a cada bloco que chega inteiro
e, entre eles, a cada :data:`INTERVALO_DO_PROGRESSO_S` (os bytes e a vazão). As amostras de um bloco contado em
``blocos`` já estão no arquivo (no ``.parcial``, a partir do byte ``bytes_do_cabecalho + (k - 1) · bytes_por_bloco``):
quem mostra o sinal ao vivo as lê de lá.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shlex
import time
import zlib
from collections import deque
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from supraharmonicos import saida_continua

from .agente import PASTA_DO_FIRMWARE, ErroDaPlaca
from .correcoes import SAIDA_SEM_DIRETORIO, SAIDA_SENHA_RECUSADA, ErroDoSudo, validar_o_sudo
from .erros import ErroDeConexao

if TYPE_CHECKING:                       # só a anotação: este módulo não carrega o asyncssh
    from .conexao import ConexaoSSH

log = logging.getLogger(__name__)

SAIDA_SEM_LER_ADC = 95
SAIDA_SEM_SAIDA_CONTINUA = 96
SAIDA_NOME_EXISTE = 94                  # no cartão: o arquivo pedido já existe na pasta do firmware
SAIDA_OUTRA_CAPTURA = 93                # no cartão: já há um ler_adc rodando
OPCOES_DO_RECEPTOR = ("-o", "--saida", "--progresso-json")
"""As opções do ``ler_adc`` que a captura contínua põe ela mesma (o pedido não as traz)."""
MOTIVOS = {0: "ok", 1: "erro", 2: "uso", 3: "sobrescrito", 4: "adc_mudo", 5: "interrompida", 6: "saida_fechada"}
"""Os códigos de saída do ``ler_adc`` (``imprimir_ajuda`` dele), pelos nomes do ``motivo`` da linha ``fim``."""
LEITURA_BYTES = 256 * 1024
INTERVALO_DO_PROGRESSO_S = 0.5
LINHAS_DE_TEXTO = 400
"""O texto do ``ler_adc`` guardado no resultado (as últimas linhas): o resumo do fim e os avisos cabem."""
SUFIXO_PARCIAL = ".parcial"

_PARAR_COMO_ROOT = """exec 3<&0
"$@" </dev/null 3<&- &
p=$!
(IFS= read -r _ <&3; kill -INT "$p") >/dev/null 2>&1 &
q=$!
exec 3<&-
wait "$p"
c=$?
kill "$q" 2>/dev/null
exit "$c"
"""
"""O shell de root que roda o ``ler_adc`` (os argumentos dele) e espera o Parar: uma linha no stdin, ou o stdin que
fecha. O ``ler_adc`` em segundo plano nasce com o ``SIGINT`` ignorado (um shell sem controle de jobs faz isso), mas
instala o tratador dele mesmo assim."""

_ROTEIRO = """cd {pasta} 2>/dev/null && [ -x ./ler_adc ] || exit {sem_ler_adc}
./ler_adc --help 2>/dev/null | grep -q -e --progresso-json || exit {sem_saida_continua}
{validar}trap 'exit 143' HUP TERM
sudo -n sh -c {parar} ler_adc ./ler_adc {argumentos} -o - --progresso-json
"""


class ErroDaCaptura(ErroDaPlaca):
    """A captura não começou (nada dela chegou): o ``ler_adc`` recusou o pedido ou não achou a PRU. ``codigo`` é o
    dele, e ``texto``, o que ele escreveu (a causa)."""

    def __init__(self, motivo: str, codigo: int | None = None, texto: Sequence[str] = ()):
        super().__init__(motivo)
        self.codigo, self.texto = codigo, tuple(texto)


class FirmwareSemSaidaContinua(ErroDaCaptura):
    """O ``ler_adc`` da placa é de antes da saída contínua (sem o ``-o -``): ela precisa do firmware novo."""


class FirmwareSemLerAdc(ErroDaCaptura):
    """A pasta do firmware da placa não tem o ``ler_adc`` compilado."""


class _GravacaoFalhou(ErroDaPlaca):
    """O disco deste computador recusou a gravação: o ``canal`` a deixa passar como está (um ``OSError`` viraria "a
    conexão caiu"), e a captura é fechada com o que foi gravado."""


@dataclass(frozen=True)
class Progresso:
    """Como a captura vai. ``blocos``: os inteiros já no arquivo (as amostras e a linha de progresso deles chegaram)."""

    blocos: int
    blocos_pedidos: int                   # 0: até o Parar
    bytes_recebidos: int
    segundos: float                       # o tempo da captura no último bloco (o t_s dele), 0 antes do 1º
    vazao_bytes_s: float                  # a média desde o começo do fluxo
    inicio: dict | None                   # a linha "inicio" (a configuração, o tamanho do bloco)
    ultimo_bloco: dict | None             # a linha do último bloco (os contadores de integridade)
    parada_pedida: bool


@dataclass(frozen=True)
class CapturaRecebida:
    """O fim da captura: o arquivo fechado, como o ``ler_adc`` terminou e o texto dele."""

    arquivo: Path
    fechamento: saida_continua.Fechamento
    codigo: int | None                    # o do ler_adc; None: a conexão caiu antes de ele terminar
    motivo: str                           # o do ler_adc (MOTIVOS), "conexao_caiu" ou "gravacao_no_computador"
    falha: str                            # o que interrompeu a captura deste lado (a queda, o disco); "" sem nada
    parada_pedida: bool
    texto: tuple[str, ...]                # as últimas linhas do texto do ler_adc (o stderr, sem as de progresso)
    bytes_recebidos: int
    duracao_s: float

    @property
    def caiu(self) -> bool:
        """O fim é deste computador: a conexão caiu, ou o ``ler_adc`` parou sem mandar o cabeçalho final."""
        return self.fechamento.pelo_computador

    @property
    def blocos(self) -> int:
        return self.fechamento.blocos


def roteiro_da_captura(argumentos: Sequence[str], pasta_firmware: str = PASTA_DO_FIRMWARE) -> str:
    """O que roda na placa (o "Ver o comando" da interface mostra isto). ``argumentos``: os do ``ler_adc`` (a taxa,
    os canais, ``--blocos``, ``-t``...), sem os do receptor (:data:`OPCOES_DO_RECEPTOR`); ``ValueError`` com eles.
    Uma pasta relativa é a partir do ``$HOME``, como a do agente."""
    argumentos = [str(a) for a in argumentos]
    proprias = [a for a in argumentos if a in OPCOES_DO_RECEPTOR or a.startswith("--saida=")]
    if proprias:
        raise ValueError(f"a captura contínua põe {', '.join(OPCOES_DO_RECEPTOR)} ela mesma: tire {proprias[0]} do "
                         "pedido")
    if not argumentos:
        raise ValueError("a captura contínua precisa dos argumentos do ler_adc (a taxa e os canais)")
    pasta = shlex.quote(pasta_firmware) if pasta_firmware.startswith("/") else (
        '"$HOME"/' + shlex.quote(pasta_firmware.lstrip("~/") or "."))
    return _ROTEIRO.format(pasta=pasta, sem_ler_adc=SAIDA_SEM_LER_ADC, sem_saida_continua=SAIDA_SEM_SAIDA_CONTINUA,
                           validar=validar_o_sudo(), parar=shlex.quote(_PARAR_COMO_ROOT),
                           argumentos=" ".join(map(shlex.quote, argumentos)))


def caminho_parcial(arquivo: Path) -> Path:
    return arquivo.with_name(arquivo.name + SUFIXO_PARCIAL)


def recuperar(parcial: Path) -> saida_continua.Fechamento:
    """Fecha um ``.parcial`` que ficou (o aplicativo fechou no meio de uma captura) e o renomeia para o nome dele. Sem
    as linhas de progresso, o tempo é o nominal dos blocos (``saida_continua.fechar``). ``FileExistsError`` se o nome
    final já existe (nada é sobrescrito)."""
    parcial = Path(parcial)
    if not parcial.name.endswith(SUFIXO_PARCIAL):
        raise ValueError(f"'{parcial.name}' não é uma captura parcial ({SUFIXO_PARCIAL})")
    final = parcial.with_name(parcial.name[:-len(SUFIXO_PARCIAL)])
    if final.exists():
        raise FileExistsError(f"'{final.name}' já existe: '{parcial.name}' fica como está")
    fechamento = saida_continua.fechar(parcial)
    os.rename(parcial, final)
    return fechamento


def erro_antes_de_comecar(codigo: int | None, texto: Sequence[str]) -> ErroDaPlaca:
    """O erro de uma captura que não começou, pelo código do roteiro (o firmware, o sudo, o nome que já existe, a
    outra captura rodando) ou pelo que o ``ler_adc`` escreveu (``texto``)."""
    texto = tuple(texto)
    if codigo == SAIDA_SEM_LER_ADC:
        return FirmwareSemLerAdc("a pasta do firmware da placa não tem o ler_adc compilado (o setup da placa, ou a "
                                 "atualização do firmware)", codigo, texto)
    if codigo == SAIDA_SEM_SAIDA_CONTINUA:
        return FirmwareSemSaidaContinua("o ler_adc da placa é de antes da captura direto no computador (sem o -o -): "
                                        "atualize o firmware da placa", codigo, texto)
    if codigo == SAIDA_SENHA_RECUSADA:
        return ErroDoSudo("a placa recusou a senha do sudo", senha_recusada=True)
    if codigo == SAIDA_SEM_DIRETORIO:
        return ErroDoSudo("a placa não deixou criar o diretório temporário em /dev/shm (onde a senha fica, na RAM)")
    if codigo == SAIDA_NOME_EXISTE:
        return ErroDaCaptura("já existe uma captura com esse nome na placa: escolha outro (nada é sobrescrito)", codigo,
                             texto)
    if codigo == SAIDA_OUTRA_CAPTURA:
        return ErroDaCaptura("já há uma captura rodando na placa (um ler_adc): espere ela terminar", codigo, texto)
    erros = [linha for linha in texto if "erro" in linha.lower()] or list(texto)
    causa = erros[-1].strip() if erros else "sem mensagem"
    return ErroDaCaptura(f"o ler_adc não começou a captura (código {codigo}): {causa[:300]}", codigo, texto)


class CapturaContinua:
    """Uma captura contínua: :meth:`rodar` a faz do começo ao fim e devolve a :class:`CapturaRecebida`; :meth:`parar`
    (no laço dela) pede o fim. ``arquivo``: o nome final da captura neste computador (a pasta tem de existir).

    Erros antes de chegar alguma coisa: :class:`FirmwareSemLerAdc`, :class:`FirmwareSemSaidaContinua`,
    ``ErroDoSudo`` (a senha), :class:`ErroDaCaptura` (o ``ler_adc`` recusou) e ``ErroDeConexao`` (sem conexão);
    ``FileExistsError`` se ``arquivo`` (ou o ``.parcial`` dele) já existe. Depois de chegar o começo da captura, ela
    sempre volta fechada, mesmo com a queda."""

    def __init__(self, conexao: ConexaoSSH, argumentos: Sequence[str], arquivo: Path, *, senha_do_sudo: str,
                 pasta_firmware: str = PASTA_DO_FIRMWARE, ao_progresso: Callable[[Progresso], object] | None = None,
                 ao_texto: Callable[[str], object] | None = None):
        self.conexao = conexao
        self.argumentos = tuple(str(a) for a in argumentos)
        self.arquivo = Path(arquivo)
        self.roteiro = roteiro_da_captura(self.argumentos, pasta_firmware)
        self._senha = senha_do_sudo
        self.ao_progresso, self.ao_texto = ao_progresso, ao_texto
        self.acompanhamento = saida_continua.Acompanhamento()
        self.parada_pedida = False
        self.bytes_recebidos = 0
        self._texto: deque[str] = deque(maxlen=LINHAS_DE_TEXTO)
        self._stdin = None
        self._parar_enviado = False
        self._crc = 0                          # o CRC-32 das amostras, menos os últimos bytes (o cabeçalho final?)
        self._cauda = bytearray()
        self._cabecalho = saida_continua.cab.CABECALHO_TAMANHO_V9
        self._blocos_por_bytes = 0
        self._t0 = 0.0
        self._ultimo_aviso = 0.0

    @property
    def descricao(self) -> str:
        return f"captura contínua: ler_adc {' '.join(self.argumentos)} -o -"

    def parar(self) -> None:
        """Pede o fim da captura (o Ctrl+C do ``ler_adc``). Chamado no laço da captura (de um ``ao_progresso``,
        inclusive); as outras vezes não mudam nada. O ``ao_progresso`` seguinte já diz ``parada_pedida``."""
        if self.parada_pedida:
            return
        self.parada_pedida = True
        self._enviar_o_parar()
        try:
            asyncio.get_running_loop().call_soon(self._avisar)     # depois do aviso em curso, e não dentro dele
        except RuntimeError:                                       # antes de rodar: o primeiro aviso dirá
            pass

    # ------------------------------------------------------------------ a captura

    async def rodar(self) -> CapturaRecebida:
        parcial = caminho_parcial(self.arquivo)
        if self.arquivo.exists():
            raise FileExistsError(f"'{self.arquivo.name}' já existe: escolha outro nome (nada é sobrescrito)")
        self._t0 = time.monotonic()
        codigo: int | None = None
        falha, motivo = "", None
        with open(parcial, "xb", buffering=0) as f:
            try:
                async with self.conexao.canal(self.roteiro, self.descricao, binario=True) as (processo, desfecho):
                    self._stdin = processo.stdin
                    processo.stdin.write((self._senha + "\n").encode())
                    if self.parada_pedida:
                        self._enviar_o_parar()
                    await asyncio.gather(self._receber_o_fluxo(processo.stdout, f),
                                         self._ler_o_texto(processo.stderr))
                    await processo.wait()
                    self.conexao.concluir(processo, desfecho, self.descricao)
                    codigo = desfecho.codigo
            except (ErroDeConexao, _GravacaoFalhou) as e:
                if not self.bytes_recebidos and isinstance(e, ErroDeConexao):
                    f.close()
                    parcial.unlink(missing_ok=True)
                    raise
                falha = str(e)
                motivo = "conexao_caiu" if isinstance(e, ErroDeConexao) else "gravacao_no_computador"
                log.warning("captura interrompida deste lado (%s, %d bytes recebidos): fechando o que chegou", falha,
                            self.bytes_recebidos)
            except BaseException:
                if not self.bytes_recebidos:
                    f.close()
                    parcial.unlink(missing_ok=True)
                raise
            finally:
                self._stdin = None
        if not self.bytes_recebidos:
            parcial.unlink(missing_ok=True)
            raise self._erro_antes_de_comecar(codigo)
        return await self._fechar(parcial, codigo, motivo, falha)

    async def _fechar(self, parcial: Path, codigo: int | None, motivo: str | None, falha: str) -> CapturaRecebida:
        # O CRC dos blocos, se o fim do fluxo for o cabeçalho final (o fechar confere isso e só então o usa).
        crc = self._crc if len(self._cauda) == self._cabecalho else None
        try:
            fechamento = await asyncio.to_thread(saida_continua.fechar, parcial, self.acompanhamento,
                                                 crc_das_amostras=crc)
        except saida_continua.CapturaVazia as e:
            parcial.unlink(missing_ok=True)
            raise ErroDaCaptura(f"a captura não chegou a começar: {e}", codigo, self._texto) from e
        if self.arquivo.exists():
            raise FileExistsError(f"'{self.arquivo.name}' apareceu durante a captura: ela ficou em '{parcial.name}'")
        os.rename(parcial, self.arquivo)
        if motivo is None:
            motivo = (self.acompanhamento.fim or {}).get("motivo") or MOTIVOS.get(codigo, f"codigo_{codigo}")
        recebida = CapturaRecebida(self.arquivo, fechamento, codigo, motivo, falha, self.parada_pedida,
                                   tuple(self._texto), self.bytes_recebidos, time.monotonic() - self._t0)
        log.info("captura contínua em '%s': %d bloco(s), %s%s", self.arquivo.name, recebida.blocos, motivo,
                 ", fechada pelo computador" if recebida.caiu else "")
        return recebida

    def _erro_antes_de_comecar(self, codigo: int | None) -> ErroDaPlaca:
        return erro_antes_de_comecar(codigo, self._texto)

    # ------------------------------------------------------------------ o que chega

    async def _receber_o_fluxo(self, stdout, f) -> None:
        while True:
            dados = await stdout.read(LEITURA_BYTES)
            if not dados:
                return
            try:
                _gravar(f, dados)
            except OSError as e:
                raise _GravacaoFalhou(f"o disco deste computador recusou a captura ({e.strerror or e}): ela parou "
                                      "no que já estava gravado") from e
            self._contar(dados)

    def _contar(self, dados: bytes) -> None:
        """Os bytes, o CRC das amostras (sem os últimos ``bytes_do_cabecalho``, que podem ser o cabeçalho final) e os
        blocos que chegaram inteiros."""
        antes = self.bytes_recebidos
        self.bytes_recebidos += len(dados)
        corpo = memoryview(dados)[max(self._cabecalho - antes, 0):]
        self._cauda += corpo
        if len(self._cauda) > self._cabecalho:
            n = len(self._cauda) - self._cabecalho
            self._crc = zlib.crc32(memoryview(self._cauda)[:n], self._crc)
            del self._cauda[:n]
        inicio = self.acompanhamento.inicio
        bloco = int(inicio["bytes_por_bloco"]) if inicio and inicio.get("bytes_por_bloco") else 0
        blocos = (self.bytes_recebidos - self._cabecalho) // bloco if bloco else 0
        agora = time.monotonic()
        if blocos != self._blocos_por_bytes or agora - self._ultimo_aviso >= INTERVALO_DO_PROGRESSO_S:
            self._blocos_por_bytes = blocos
            self._avisar()

    async def _ler_o_texto(self, stderr) -> None:
        while True:
            bruta = await stderr.readline()
            if not bruta:
                return
            linha = bruta.decode("utf-8", errors="replace").rstrip("\r\n")
            evento = self.acompanhamento.receber(linha)
            if evento is None:
                if linha.strip():
                    self._texto.append(linha)
                    if self.ao_texto is not None:
                        self.ao_texto(linha)
                continue
            if evento.get("evento") == "inicio":
                self._cabecalho = int(evento.get("bytes_do_cabecalho") or self._cabecalho)
                if self.parada_pedida:
                    self._enviar_o_parar()
            self._avisar()

    def _enviar_o_parar(self) -> None:
        """A linha do Parar, uma vez, só com o ``ler_adc`` já capturando (a linha ``inicio``)."""
        if self._parar_enviado or self._stdin is None or self.acompanhamento.inicio is None:
            return
        try:
            self._stdin.write(b"parar\n")
            self._parar_enviado = True
        except OSError as e:                   # o canal já fechou (BrokenPipeError): a captura acabou
            log.info("o Parar não foi enviado (%s): o canal já fechou", e)

    def _avisar(self) -> None:
        self._ultimo_aviso = time.monotonic()
        if self.ao_progresso is None:
            return
        inicio = self.acompanhamento.inicio
        ultimo = self.acompanhamento.ate(self._blocos_por_bytes) if self._blocos_por_bytes else None
        decorrido = max(time.monotonic() - self._t0, 1e-9)
        self.ao_progresso(Progresso(
            blocos=int(ultimo["bloco"]) if ultimo else 0,
            blocos_pedidos=int((inicio or {}).get("blocos") or 0),
            bytes_recebidos=self.bytes_recebidos, segundos=float(ultimo["t_s"]) if ultimo else 0.0,
            vazao_bytes_s=self.bytes_recebidos / decorrido, inicio=inicio, ultimo_bloco=ultimo,
            parada_pedida=self.parada_pedida))


def _gravar(f, dados: bytes) -> None:
    """Tudo de ``dados`` no arquivo (o ``write`` sem buffer pode gravar só uma parte); o disco cheio é ``OSError``."""
    vista = memoryview(dados)
    while vista:
        n = f.write(vista)
        if not n:
            raise OSError(28, "sem espaço no disco para a captura")
        vista = vista[n:]
