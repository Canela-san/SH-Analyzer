"""A descoberta das placas (docs/gui-plan.md, 11.3; AQ-01): quais BeagleBones estão ao alcance, por onde, e quão
perto.

**As fontes** (cada uma pode falhar sozinha, e a varredura segue com as outras, dizendo qual falhou):

* **o USB** (:class:`FonteUSB`): a porta serial do gadget da placa (o ``pyserial``: o VID:PID e o nº de série, que é o
  da EEPROM, o mesmo do cabeçalho v8) e a sondagem da porta 22 nos IPs fixos do gadget, 192.168.6.2 (ECM, a rede do
  Linux e do macOS) e 192.168.7.2 (RNDIS, a do Windows). Na placa de verdade (15/11/2026): ``1d6b:0104``,
  "BeagleBoard.org", "BeagleBoneBlack";
* **a LAN** (:class:`FonteMDNS`): o mDNS (``zeroconf``), o ``beaglebone.local`` e os nomes que as placas anunciam. A
  imagem da BeagleBoard não anuncia o SSH, e sim o Cloud9 e o Node-RED (``_http._tcp``, "Cloud9 IDE for <nome>"): é
  por eles que uma placa de outro nome aparece. Ela responde pelos dois IPs do USB também;
* **as conhecidas** (:class:`FonteConhecidas`): os endereços em que o usuário já conectou (a WAN, com o host e a
  porta que ele informou);
* **o simulador** (:class:`FonteSimulador`), sempre.

**A sonda** (:class:`SondaSSH`) abre a porta, mede a latência, confere a saudação do SSH e lê a chave de host (uma
troca de chaves, sem autenticar: nada sai daqui). A chave fica guardada por um tempo, para não cansar a placa (a troca
de chaves custa a ela uns décimos de segundo do único núcleo).

**A mesma placa por vários caminhos aparece uma vez** (:func:`agrupar`): o mesmo nº de série, a mesma chave de host
(o USB, o mDNS e a LAN de uma placa apresentam a mesma) ou o mesmo endereço. Com um gadget só no USB, os IPs do USB
são dele. As placas conhecidas (``conhecidas.py``) ligam a chave de host ao nº de série; uma conhecida que não
respondeu agora aparece como ausente, com a hora da última vez.
"""

from __future__ import annotations

import asyncio
import contextlib
import ipaddress
import logging
import sys
import time
from collections.abc import Awaitable, Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass

import asyncssh

from .conexao import CHAVES_DE_HOST
from .conhecidas import PlacaConhecida
from .destino import Destino
from .simulador import SERIE_SIMULADA

log = logging.getLogger(__name__)

IDS_DO_GADGET = {(0x1D6B, 0x0104), (0x0451, 0x6141)}
"""O VID:PID do gadget USB das imagens da BeagleBoard (o da Linux Foundation; o da TI nas imagens antigas)."""
IPS_DO_USB = {"192.168.6.2": "ECM", "192.168.7.2": "RNDIS"}
IP_PREFERIDO_DO_USB = "192.168.7.2" if sys.platform == "win32" else "192.168.6.2"
"""Os dois respondem no Linux; o ECM é o da rede do Linux (e o único fora do Windows), e o RNDIS, o do Windows."""
NOMES_MDNS = ("beaglebone.local.",)
TIPOS_MDNS = ("_ssh._tcp.local.", "_sftp-ssh._tcp.local.", "_workstation._tcp.local.", "_http._tcp.local.")
PISTAS_MDNS = ("beagle", "cloud9 ide for ", "node-red for ")
"""Um serviço anunciado é de uma placa se o nome dele ou do host tem uma destas (a imagem anuncia o Cloud9 e o
Node-RED "for <nome do host>"); os outros hosts da rede ficam de fora."""
TEMPO_DA_SONDA_S = 1.5
TEMPO_DO_MDNS_S = 1.5
VALIDADE_DA_CHAVE_S = 120.0
ORDEM_DOS_TIPOS = {"usb": 0, "lan": 1, "wan": 2, "simulador": 3}
ESTADOS = ("disponivel", "so_serial", "pelo_salto", "ausente", "simulador")
"""``disponivel``: o SSH responde; ``so_serial``: a placa está no USB, mas a rede dela não respondeu (ainda ligando?);
``pelo_salto``: conhecida atrás de um salto, que só se sonda conectando; ``ausente``: conhecida, e não achada agora;
``simulador``."""


@dataclass(frozen=True)
class Caminho:
    """Um jeito de chegar a uma placa. ``destino`` é ``None`` na porta serial sem rede e no simulador."""

    tipo: str                             # "usb", "lan", "wan" ou "simulador"
    destino: Destino | None
    detalhe: str                          # "USB (ECM)", "beaglebone.local (mDNS)", "porta serial /dev/ttyACM0"
    latencia_ms: float | None = None


@dataclass(frozen=True)
class Achado:
    """O que uma fonte achou. ``respondeu``: ``True`` (o SSH respondeu, ou o gadget está no USB), ``None`` (não
    sondado: atrás de um salto)."""

    caminho: Caminho
    serie: str | None = None
    impressao: str | None = None
    nome: str | None = None
    porta_serial: str | None = None
    respondeu: bool | None = True


@dataclass(frozen=True)
class PlacaVista:
    """Uma placa na lista: os caminhos (o melhor primeiro), o estado e, se for uma conhecida, o nome que o usuário
    viu nela."""

    chave: str                            # a identidade na lista: o nº de série, a chave de host ou o endereço
    nome: str
    serie: str | None
    impressao: str | None
    caminhos: tuple[Caminho, ...]
    estado: str
    porta_serial: str | None
    vista_em: float | None                # agora, se está ao alcance; a última conexão, se ausente
    conhecida: PlacaConhecida | None

    @property
    def melhor(self) -> Caminho | None:
        """O caminho para conectar: o primeiro com um endereço."""
        return next((c for c in self.caminhos if c.destino is not None), None)

    @property
    def latencia_ms(self) -> float | None:
        melhor = self.melhor
        return melhor.latencia_ms if melhor is not None else None


Fonte = Callable[[Sequence[PlacaConhecida]], Awaitable[list[Achado]]]


class SondaSSH:
    """A sondagem de um endereço: ``(latência em ms, impressão da chave de host)`` se há um SSH nele, ``None`` se
    não. Numa varredura, o mesmo endereço é sondado uma vez (o USB e o mDNS acham os mesmos IPs); a chave de host
    fica guardada por ``validade_s``, enquanto a saudação do servidor não mudar."""

    def __init__(self, tempo_s: float = TEMPO_DA_SONDA_S, validade_s: float = VALIDADE_DA_CHAVE_S):
        self.tempo_s, self.validade_s = tempo_s, validade_s
        self.trocas_de_chaves = 0             # quantas vezes a chave de host foi lida da placa (o custo para ela)
        self._chaves: dict[tuple[str, int], tuple[float, str, str]] = {}
        self._desta_varredura: dict[tuple[str, int], asyncio.Task] = {}

    def nova_varredura(self) -> None:
        self._desta_varredura = {}

    async def sondar(self, host: str, porta: int = 22) -> tuple[float, str | None] | None:
        tarefa = self._desta_varredura.get((host, porta))
        if tarefa is None:
            tarefa = self._desta_varredura[(host, porta)] = asyncio.ensure_future(self._sondar(host, porta))
        return await asyncio.shield(tarefa)

    async def _sondar(self, host: str, porta: int) -> tuple[float, str | None] | None:
        inicio = time.monotonic()
        try:
            leitor, escritor = await asyncio.wait_for(asyncio.open_connection(host, porta), self.tempo_s)
        except (OSError, asyncio.TimeoutError):
            return None
        latencia_ms = (time.monotonic() - inicio) * 1000
        try:
            saudacao = (await asyncio.wait_for(leitor.readline(), self.tempo_s)).decode("ascii", "replace").strip()
        except (OSError, asyncio.TimeoutError):
            saudacao = ""
        finally:
            escritor.close()
            with contextlib.suppress(OSError):
                await escritor.wait_closed()
        if not saudacao.startswith("SSH-"):
            return None
        return latencia_ms, await self._impressao(host, porta, saudacao)

    async def _impressao(self, host: str, porta: int, saudacao: str) -> str | None:
        guardada = self._chaves.get((host, porta))
        if guardada is not None and guardada[1] == saudacao and time.monotonic() - guardada[0] < self.validade_s:
            return guardada[2]
        self.trocas_de_chaves += 1
        try:
            chave = await asyncio.wait_for(asyncssh.get_server_host_key(
                host, porta, config=None, server_host_key_algs=CHAVES_DE_HOST), 2 * self.tempo_s)
        except (asyncssh.Error, OSError, asyncio.TimeoutError) as e:
            log.info("a chave de host de %s:%d não deu para ler: %s", host, porta, e)
            return None
        if chave is None:
            return None
        impressao = chave.get_fingerprint()
        self._chaves[(host, porta)] = (time.monotonic(), saudacao, impressao)
        return impressao


def _nome_do_produto(produto: str | None) -> str | None:
    """``BeagleBoneBlack`` (o produto do gadget) vira ``BeagleBone Black``."""
    if not produto:
        return None
    if produto.startswith("BeagleBone") and len(produto) > len("BeagleBone"):
        resto = produto[len("BeagleBone"):]
        return "BeagleBone " + "".join(f" {c}" if c.isupper() and i else c for i, c in enumerate(resto))
    return produto


def _listar_portas_seriais() -> list:
    from serial.tools import list_ports
    return list_ports.comports()


class FonteUSB:
    """A porta serial do gadget e a porta 22 nos IPs do USB."""

    nome = "USB"

    def __init__(self, sonda: SondaSSH, listar_portas: Callable[[], Iterable] = _listar_portas_seriais,
                 ips: Mapping[str, str] = IPS_DO_USB, porta: int = 22):
        self.sonda, self.listar_portas, self.ips, self.porta = sonda, listar_portas, dict(ips), porta

    async def __call__(self, _conhecidas: Sequence[PlacaConhecida] = ()) -> list[Achado]:
        portas = await asyncio.to_thread(lambda: list(self.listar_portas()))   # o sysfs, ou o registro do Windows
        achados = [Achado(Caminho("usb", None, f"porta serial {p.device}"), serie=p.serial_number or None,
                          nome=_nome_do_produto(p.product), porta_serial=p.device)
                   for p in portas if (p.vid, p.pid) in IDS_DO_GADGET]
        sondas = await asyncio.gather(*(self.sonda.sondar(ip, self.porta) for ip in self.ips))
        for (ip, rede), sonda in zip(self.ips.items(), sondas, strict=True):
            if sonda is not None:
                achados.append(Achado(Caminho("usb", Destino(ip, self.porta), f"USB ({rede})", sonda[0]),
                                      impressao=sonda[1]))
        return achados


async def consultar_mdns(nomes: Sequence[str], tempo_s: float = TEMPO_DO_MDNS_S) -> dict[str, list[str]]:
    """Pelo mDNS: os IPv4 de cada nome em ``nomes`` (``beaglebone.local.``) e dos hosts dos serviços de placa
    anunciados (:data:`TIPOS_MDNS`, filtrados por :data:`PISTAS_MDNS`), ``{host: [ip, …]}``."""
    from zeroconf import AddressResolver, IPVersion, ServiceStateChange
    from zeroconf.asyncio import AsyncServiceBrowser, AsyncServiceInfo, AsyncZeroconf

    achados: dict[str, list[str]] = {}
    servicos: list[tuple[str, str]] = []

    def mudou(zeroconf, service_type: str, name: str, state_change: ServiceStateChange) -> None:
        if state_change is ServiceStateChange.Added:
            servicos.append((service_type, name))

    async def resolver(nome: str) -> None:
        resolvedor = AddressResolver(nome)
        if await resolvedor.async_request(zc.zeroconf, int(tempo_s * 1000)):
            achados[nome] = resolvedor.parsed_addresses(IPVersion.V4Only)

    zc = AsyncZeroconf(ip_version=IPVersion.V4Only)
    try:
        navegador = AsyncServiceBrowser(zc.zeroconf, list(TIPOS_MDNS), handlers=[mudou])
        await asyncio.gather(asyncio.sleep(tempo_s), *(resolver(n) for n in nomes))
        await navegador.async_cancel()
        for tipo, nome in servicos:
            info = AsyncServiceInfo(tipo, nome)
            if not await info.async_request(zc.zeroconf, int(tempo_s * 1000)) or not info.server:
                continue
            texto = f"{nome} {info.server}".lower()
            if info.server in nomes or any(p in texto for p in PISTAS_MDNS):
                achados.setdefault(info.server, info.parsed_addresses(IPVersion.V4Only))
    finally:
        await zc.async_close()
    return achados


class FonteMDNS:
    """Os nomes do mDNS e os serviços das placas, cada IP sondado na porta 22."""

    nome = "mDNS"

    def __init__(self, sonda: SondaSSH, consultar: Callable[[Sequence[str]], Awaitable[dict[str, list[str]]]] =
                 consultar_mdns, nomes: Sequence[str] = NOMES_MDNS, ips_do_usb: Mapping[str, str] = IPS_DO_USB,
                 porta: int = 22):
        self.sonda, self.consultar, self.nomes = sonda, consultar, tuple(nomes)
        self.ips_do_usb, self.porta = dict(ips_do_usb), porta

    async def __call__(self, conhecidas: Sequence[PlacaConhecida] = ()) -> list[Achado]:
        nomes_conhecidos = {_com_ponto(d.host) for p in conhecidas for d in p.destinos if d.host.endswith(".local")}
        respostas = await self.consultar(tuple(dict.fromkeys((*self.nomes, *sorted(nomes_conhecidos)))))
        pares = [(host, ip) for host, ips in respostas.items() for ip in ips]
        sondas = await asyncio.gather(*(self.sonda.sondar(ip, self.porta) for _host, ip in pares))
        achados = []
        for (host, ip), sonda in zip(pares, sondas, strict=True):
            if sonda is not None:
                nome = host.rstrip(".")
                achados.append(Achado(Caminho("usb" if ip in self.ips_do_usb else "lan", Destino(ip, self.porta),
                                              f"{nome} (mDNS)", sonda[0]),
                                      impressao=sonda[1], nome=nome.removesuffix(".local")))
        return achados


def _com_ponto(nome: str) -> str:
    return nome if nome.endswith(".") else nome + "."


def _tipo_do_endereco(host: str) -> str:
    try:
        return "lan" if ipaddress.ip_address(host).is_private else "wan"
    except ValueError:
        return "lan" if host.endswith(".local") else "wan"


class FonteConhecidas:
    """Os endereços das placas conhecidas que não são os do USB (a LAN, a WAN). **Um endereço é da placa só se ela
    apresenta a chave de host dela** (o IP de uma rede com DHCP pode ser de outra placa hoje). Atrás de um salto,
    não sonda: a conexão com o salto é do usuário, na hora de conectar."""

    nome = "conhecidas"

    def __init__(self, sonda: SondaSSH, ips_do_usb: Mapping[str, str] = IPS_DO_USB):
        self.sonda, self.ips_do_usb = sonda, dict(ips_do_usb)

    async def __call__(self, conhecidas: Sequence[PlacaConhecida] = ()) -> list[Achado]:
        pares = [(p, d) for p in conhecidas for d in p.destinos if d.host not in self.ips_do_usb]
        diretos = [(p, d) for p, d in pares if d.salto is None]
        sondas = await asyncio.gather(*(self.sonda.sondar(d.host, d.porta) for _p, d in diretos))
        achados = []
        for (p, d), sonda in zip(diretos, sondas, strict=True):
            if sonda is not None:
                dela = p.impressao is None or sonda[1] == p.impressao
                achados.append(Achado(Caminho(_tipo_do_endereco(d.host), d, "conhecida", sonda[0]),
                                      serie=p.serie if dela else None, impressao=sonda[1]))
        achados += [Achado(Caminho("wan", d, f"pelo salto {d.salto}"), serie=p.serie, respondeu=None)
                    for p, d in pares if d.salto is not None]
        return achados


class FonteSimulador:
    nome = "simulador"

    async def __call__(self, _conhecidas: Sequence[PlacaConhecida] = ()) -> list[Achado]:
        return [Achado(Caminho("simulador", None, "neste computador", 0.0), serie=SERIE_SIMULADA,
                       nome="Simulador")]


def agrupar(achados: Sequence[Achado], conhecidas: Sequence[PlacaConhecida] = (),
            agora: float | None = None) -> list[PlacaVista]:
    """Os achados de todas as fontes, uma placa por grupo (ver o módulo), e as conhecidas não achadas como
    ausentes. Na ordem da lista: as disponíveis, as só no USB, as ausentes e o simulador."""
    agora = time.time() if agora is None else agora
    pai = list(range(len(achados)))

    def raiz(i: int) -> int:
        while pai[i] != i:
            pai[i] = pai[pai[i]]
            i = pai[i]
        return i

    serie_da_impressao = {p.impressao: p.serie for p in conhecidas if p.impressao}
    por_chave: dict[str, int] = {}
    for i, a in enumerate(achados):
        for chave in _chaves(a, serie_da_impressao):
            if chave in por_chave:
                pai[raiz(i)] = raiz(por_chave[chave])
            else:
                por_chave[chave] = i

    def series(i: int) -> set[str]:
        return {s for j, a in enumerate(achados) if raiz(j) == raiz(i) for s in _series(a, serie_da_impressao)}

    # Com um gadget só no USB, os IPs do USB são dele (a não ser que uma conhecida diga que é outra placa).
    gadgets = [i for i, a in enumerate(achados) if a.porta_serial is not None]
    if len(gadgets) == 1:
        (g,) = gadgets
        for i, a in enumerate(achados):
            if a.caminho.tipo == "usb" and a.caminho.destino is not None and raiz(i) != raiz(g):
                if not (series(i) and series(g) and series(i) != series(g)):
                    pai[raiz(i)] = raiz(g)

    grupos: dict[int, list[Achado]] = {}
    for i, a in enumerate(achados):
        grupos.setdefault(raiz(i), []).append(a)
    por_serie = {p.serie: p for p in conhecidas}
    placas = [_placa(grupo, serie_da_impressao, por_serie, agora) for grupo in grupos.values()]
    achadas = {p.serie for p in placas if p.serie and p.estado != "simulador"}
    placas += [_ausente(p) for p in conhecidas if p.serie not in achadas]
    ordem = {estado: i for i, estado in enumerate(ESTADOS)}
    return sorted(placas, key=lambda p: (ordem[p.estado], p.nome.lower(), p.chave))


def _series(a: Achado, serie_da_impressao: Mapping[str, str]) -> set[str]:
    return {s for s in (a.serie, serie_da_impressao.get(a.impressao) if a.impressao else None) if s}


def _chaves(a: Achado, serie_da_impressao: Mapping[str, str]) -> set[str]:
    if a.caminho.tipo == "simulador":
        return {"simulador"}           # nunca junto de uma placa de verdade: o nº de série dele é inventado
    chaves = {f"serie:{s}" for s in _series(a, serie_da_impressao)}
    if a.impressao:
        chaves.add(f"impressao:{a.impressao}")
    d = a.caminho.destino
    if d is not None and d.salto is None:
        chaves.add(f"endereco:{d.host}:{d.porta}")
    return chaves


def _ordem_do_caminho(c: Caminho, respondeu: bool | None) -> tuple:
    preferido = c.destino is not None and c.destino.host == IP_PREFERIDO_DO_USB
    return (respondeu is not True, c.destino is None, ORDEM_DOS_TIPOS.get(c.tipo, 9), not preferido,
            c.latencia_ms if c.latencia_ms is not None else float("inf"))


def _placa(grupo: list[Achado], serie_da_impressao: Mapping[str, str], por_serie: Mapping[str, PlacaConhecida],
           agora: float) -> PlacaVista:
    serie = next((s for a in grupo for s in sorted(_series(a, serie_da_impressao))), None)
    simulador = any(a.caminho.tipo == "simulador" for a in grupo)
    conhecida = por_serie.get(serie) if serie and not simulador else None
    impressao = next((a.impressao for a in grupo if a.impressao), conhecida.impressao if conhecida else None)
    # Os caminhos, um por endereço (o USB e o mDNS acham o mesmo IP): os detalhes juntos, a menor latência.
    caminhos: dict[object, tuple[Caminho, bool | None]] = {}
    for a in grupo:
        c = a.caminho
        chave = c.destino if c.destino is not None else (c.tipo, c.detalhe)
        anterior = caminhos.get(chave)
        if anterior is None:
            caminhos[chave] = (c, a.respondeu)
            continue
        velho, respondeu = anterior
        latencias = [x for x in (velho.latencia_ms, c.latencia_ms) if x is not None]
        detalhe = velho.detalhe if c.detalhe in velho.detalhe.split(" · ") else f"{velho.detalhe} · {c.detalhe}"
        tipo = min((velho.tipo, c.tipo), key=lambda t: ORDEM_DOS_TIPOS.get(t, 9))
        caminhos[chave] = (Caminho(tipo, velho.destino, detalhe, min(latencias) if latencias else None),
                           True if True in (respondeu, a.respondeu) else respondeu)
    ordenados = sorted(caminhos.values(), key=lambda par: _ordem_do_caminho(*par))
    porta_serial = next((a.porta_serial for a in grupo if a.porta_serial), None)
    if simulador:
        estado = "simulador"
    elif any(r is True and c.destino is not None for c, r in ordenados):
        estado = "disponivel"
    elif porta_serial is not None:
        estado = "so_serial"
    else:
        estado = "pelo_salto"                # só os não sondados ficam sem resposta num grupo
    nome = conhecida.nome if conhecida else next((a.nome for a in grupo if a.nome), "BeagleBone")
    primeiro = ordenados[0][0]
    if serie:
        chave = f"serie:{serie}"
    elif impressao:
        chave = f"impressao:{impressao}"
    elif primeiro.destino is not None:
        chave = f"endereco:{primeiro.destino.host}:{primeiro.destino.porta}"
    else:
        chave = f"caminho:{primeiro.detalhe}"
    vista_em = agora if estado in ("disponivel", "so_serial", "simulador") else \
        (conhecida.vista_em if conhecida else None)
    return PlacaVista(chave, nome, serie, impressao, tuple(c for c, _r in ordenados), estado, porta_serial, vista_em,
                      conhecida)


def _ausente(p: PlacaConhecida) -> PlacaVista:
    caminhos = tuple(Caminho("usb" if d.host in IPS_DO_USB else _tipo_do_endereco(d.host), d, "conhecida")
                     for d in p.destinos)
    return PlacaVista(f"serie:{p.serie}", p.nome, p.serie, p.impressao, caminhos, "ausente", None, p.vista_em, p)


class Descoberta:
    """Uma varredura de todas as fontes ao mesmo tempo (:meth:`varrer`). As que falharam na última ficam em
    :attr:`falhas` (para a interface dizer "o mDNS não respondeu"), com o motivo no log."""

    def __init__(self, fontes: Sequence[Fonte] | None = None, sonda: SondaSSH | None = None):
        self.sonda = sonda if sonda is not None else SondaSSH()
        self.fontes: list[Fonte] = list(fontes) if fontes is not None else [
            FonteUSB(self.sonda), FonteMDNS(self.sonda), FonteConhecidas(self.sonda), FonteSimulador()]
        self.falhas: list[str] = []

    async def varrer(self, conhecidas: Sequence[PlacaConhecida] = (), agora: float | None = None) -> list[PlacaVista]:
        self.sonda.nova_varredura()
        resultados = await asyncio.gather(*(fonte(conhecidas) for fonte in self.fontes), return_exceptions=True)
        achados: list[Achado] = []
        falhas = []
        for fonte, resultado in zip(self.fontes, resultados, strict=True):
            nome = getattr(fonte, "nome", type(fonte).__name__)
            if isinstance(resultado, asyncio.CancelledError):
                raise resultado
            if isinstance(resultado, BaseException):
                log.warning("a fonte %s da descoberta falhou: %s", nome, resultado, exc_info=resultado)
                falhas.append(f"{nome}: {resultado}")
            else:
                achados.extend(resultado)
        self.falhas = falhas
        return agrupar(achados, conhecidas, agora)
