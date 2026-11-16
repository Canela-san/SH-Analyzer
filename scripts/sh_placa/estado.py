"""As respostas do agente da placa, lidas: o estado e a saúde (:class:`EstadoDaPlaca`, com o diagnóstico), o relógio
(:class:`RelogioDaPlaca`), as capturas (:class:`CapturasDaPlaca`) e os logs (:class:`LogsDaPlaca`). A visão geral, o
diagnóstico e os arquivos da interface mostram isto (docs/gui-plan.md, 11.4, 11.6 e 11.9); uma futura CLI também pode.

**O diagnóstico vem da placa:** as conferências são do agente (``firmware/agente/shan_agente.py``, o comando
``saude``), a fonte de verdade que a interface, a CLI e o ``setup.sh`` usam. Daqui só saem as duas que só o
computador faz: o relógio da placa comparado com o dele, e o firmware comparado com o deste aplicativo.

**O relógio comparado:** a hora da placa menos a do computador fica entre dois limites certos (:attr:`RelogioDaPlaca.
limites_s`): a placa leu a hora antes de a resposta chegar (``utc - recebido_em``), e o processo dela começou depois do
pedido (``utc - desde_o_inicio_s - enviado_em``). A estimativa é o meio, e a incerteza, a metade da faixa. Na placa de
verdade (15/11/2026), a faixa tinha ±0,02 s e cercava a diferença de um pingue-pongue num canal só (+0,539 s, com
±0,6 ms); a hora da chegada sozinha dava 35 a 70 ms a menos (a partida e o fim do Python na placa entram nela).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

TAXA_DE_REFERENCIA_BYTES_S = 800_000     # 400 kS/s x 2 bytes: quanto disco uma captura gasta por segundo
DIFERENCA_DE_RELOGIO_S = 2.0
NIVEIS = ("erro", "aviso", "info")


@dataclass(frozen=True)
class Problema:
    """Um item do diagnóstico. ``nivel``: ``"erro"`` (impede capturar), ``"aviso"`` ou ``"info"``."""

    nivel: str
    codigo: str
    texto: str
    correcao: str | None = None

    @classmethod
    def de_json(cls, d: dict) -> Problema:
        nivel = d.get("nivel") if d.get("nivel") in NIVEIS else "aviso"     # um nível novo de um agente mais novo
        return cls(nivel, str(d.get("codigo") or "desconhecido"), str(d.get("texto") or ""), d.get("correcao") or None)


def _ordenar(problemas: list[Problema]) -> list[Problema]:
    return sorted(problemas, key=lambda p: NIVEIS.index(p.nivel))


def _numero(valor: object) -> float | None:
    """Um número da resposta (um ``bool`` não é), ou ``None``."""
    return float(valor) if isinstance(valor, (int, float)) and not isinstance(valor, bool) else None


def _campo(dados: object, *chaves):
    for chave in chaves:
        if not isinstance(dados, dict):
            return None
        dados = dados.get(chave)
    return dados


@dataclass(frozen=True)
class EstadoDaPlaca:
    """O que o agente disse no ``estado`` ou na ``saude`` (``bruto`` guarda a resposta inteira), com acesso fácil aos
    campos. ``enviado_em`` e ``recebido_em``: o ``time.time()`` do computador quando pediu e quando a resposta chegou
    (o relógio da placa é comparado com eles)."""

    bruto: dict = field(repr=False)
    recebido_em: float | None = None
    enviado_em: float | None = None

    @classmethod
    def de_json(cls, resposta: dict, recebido_em: float | None = None, enviado_em: float | None = None) -> EstadoDaPlaca:
        return cls(resposta, recebido_em, enviado_em)

    def _campo(self, *chaves):
        return _campo(self.bruto, *chaves)

    @property
    def serie(self) -> str | None:
        return self._campo("placa", "serie")

    @property
    def nome_da_placa(self) -> str:
        nome = self._campo("placa", "modelo") or self._campo("placa", "nome") or "BeagleBone"
        return nome.replace("TI AM335x ", "")

    @property
    def sistema(self) -> str | None:
        return self._campo("sistema")

    @property
    def kernel(self) -> str | None:
        return self._campo("kernel")

    @property
    def versao_do_firmware(self) -> str | None:
        return self._campo("firmware", "firmware")

    @property
    def ligada_s(self) -> float | None:
        """Há quanto tempo a placa está ligada (o ``/proc/uptime``)."""
        return _numero(self._campo("ligada_s"))

    @property
    def carga(self) -> float | None:
        """A carga média do último minuto (um núcleo só: 1,0 é ele ocupado o tempo todo)."""
        carga = self._campo("carga")
        return _numero(carga[0]) if isinstance(carga, list) and carga else None

    @property
    def temperatura_c(self) -> float | None:
        return _numero(self._campo("temperatura_c"))

    @property
    def memoria_disponivel_bytes(self) -> int | None:
        kib = _numero(self._campo("memoria_disponivel_kib"))
        return None if kib is None else int(kib * 1024)

    @property
    def disco_bytes(self) -> tuple[int, int] | None:
        """``(livre, total)`` do cartão (a partição da pasta do firmware)."""
        livre, total = _numero(self._campo("disco", "livre_kib")), _numero(self._campo("disco", "total_kib"))
        return None if livre is None or not total else (int(livre * 1024), int(total * 1024))

    @property
    def pru(self) -> dict:
        """O ``remoteproc`` da PRU0: ``estado`` (``running``, ``offline``, ``crashed``…), ``firmware`` e ``nome``;
        vazio sem a PRU."""
        pru = self._campo("pru")
        return pru if isinstance(pru, dict) else {}

    @property
    def protocolo_da_pru(self) -> int | None:
        protocolo = self._campo("firmware", "protocolo_da_pru")
        return protocolo if isinstance(protocolo, int) else None

    @property
    def pinos(self) -> dict[str, tuple[str | None, str | None]]:
        """Cada pino da PRU: ``(modo de agora, modo que a PRU pede)``."""
        pinos = self._campo("pinos")
        return {p: (v.get("modo"), v.get("esperado")) for p, v in pinos.items() if isinstance(v, dict)} \
            if isinstance(pinos, dict) else {}

    @property
    def pinos_errados(self) -> list[str]:
        """Os pinos lidos fora do modo da PRU (um pino sem o pinmux, que não deu para ler, fica de fora)."""
        return [p for p, (modo, esperado) in self.pinos.items() if modo is not None and modo != esperado]

    @property
    def firmware_compilado(self) -> bool | None:
        """O ``ler_adc`` e o ``fw_pru.out`` compilados na pasta do firmware."""
        compilado = self._campo("firmware", "compilado")
        return compilado if isinstance(compilado, bool) else None

    @property
    def mem_496m(self) -> tuple[bool | None, bool | None]:
        """O ``mem=496M`` (a memória dos buffers da PRU fora do Linux): ``(no boot de agora, no próximo boot)``."""
        agora, proximo = self._campo("memoria_dos_buffers", "mem_496m"), self._campo("uenv", "mem_496m")
        return (agora if isinstance(agora, bool) else None, proximo if isinstance(proximo, bool) else None)

    @property
    def overlays(self) -> list[str]:
        overlays = self._campo("overlays")
        return [str(o) for o in overlays] if isinstance(overlays, list) else []

    @property
    def ferramentas(self) -> dict[str, str | None]:
        """Cada ferramenta e onde ela está na placa (``None``: não está)."""
        ferramentas = self._campo("ferramentas")
        return dict(ferramentas) if isinstance(ferramentas, dict) else {}

    @property
    def capturas_na_placa(self) -> tuple[int, int] | None:
        """``(quantidade, bytes)`` das capturas na pasta do firmware (a saúde as conta; a lista vem das capturas)."""
        quantidade, total = self._campo("capturas", "quantidade"), self._campo("capturas", "bytes")
        return (quantidade, total) if isinstance(quantidade, int) and isinstance(total, int) else None

    @property
    def minutos_de_captura_no_disco(self) -> float | None:
        """Quantos minutos de captura a 400 kS/s cabem no disco livre da pasta do firmware."""
        livre = self._campo("disco", "livre_kib")
        return None if livre is None else livre * 1024 / TAXA_DE_REFERENCIA_BYTES_S / 60

    @property
    def relogio(self) -> RelogioDaPlaca | None:
        dados = self._campo("relogio")
        return RelogioDaPlaca.de_json(dados, self.recebido_em, self.enviado_em) if isinstance(dados, dict) else None

    @property
    def tem_diagnostico(self) -> bool:
        """Se a resposta é a da ``saude`` (com as conferências da placa), e não só a do ``estado``."""
        return isinstance(self._campo("conferencias"), list)

    def conferencias(self) -> list[Problema]:
        """As conferências que a placa fez (a ``saude``), na ordem dela."""
        if not self.tem_diagnostico:
            raise ValueError("o diagnóstico vem da saúde da placa: esta é a resposta do estado "
                             "(use ClienteDoAgente.saude)")
        return [Problema.de_json(c) for c in self.bruto["conferencias"] if isinstance(c, dict)]

    def diagnostico(self, versao_do_aplicativo: str | None = None, agora: float | None = None) -> list[Problema]:
        """Os problemas da placa, do mais grave ao menos grave: as conferências dela e as do computador (o relógio
        comparado com ``agora``, por padrão a hora em que a resposta chegou, e o firmware com o do aplicativo)."""
        problemas = self.conferencias()
        versao = self.versao_do_firmware
        if versao is not None and versao_do_aplicativo and versao != versao_do_aplicativo:
            problemas.append(Problema("aviso", "firmware_diferente", f"O firmware da placa ({versao}) não é o deste "
                                      f"aplicativo ({versao_do_aplicativo}).", "Atualizar o firmware (Manutenção)."))
        relogio = self.relogio
        diferenca = None if relogio is None else relogio.diferenca_s(agora)
        if diferenca is not None and abs(diferenca) > DIFERENCA_DE_RELOGIO_S:
            problemas.append(Problema("aviso", "relogio", f"O relógio da placa está {diferenca:+.0f} s do computador "
                                      "(ela não tem bateria de RTC): a hora gravada nas capturas sai errada.",
                                      "Acertar o relógio pelo do computador."))
        return _ordenar(problemas)

    def pronta_para_capturar(self, versao_do_aplicativo: str | None = None, agora: float | None = None) -> bool:
        return not any(p.nivel == "erro" for p in self.diagnostico(versao_do_aplicativo, agora))


@dataclass(frozen=True)
class RelogioDaPlaca:
    """A hora da placa (``utc``), se o NTP a sincronizou, por onde o agente soube (``"adjtimex"``, ``"timesyncd"``) e
    há quanto tempo o processo dele rodava; ``enviado_em`` e ``recebido_em`` são do computador (ver o módulo)."""

    utc: float
    sincronizado: bool | None
    fonte: str | None
    recebido_em: float | None = None
    enviado_em: float | None = None
    desde_o_inicio_s: float | None = None

    @classmethod
    def de_json(cls, dados: dict, recebido_em: float | None = None,
                enviado_em: float | None = None) -> RelogioDaPlaca | None:
        if not isinstance(dados.get("utc"), (int, float)):
            return None
        desde = dados.get("desde_o_inicio_s")
        return cls(float(dados["utc"]), dados.get("sincronizado"), dados.get("fonte"), recebido_em, enviado_em,
                   float(desde) if isinstance(desde, (int, float)) else None)

    @property
    def limites_s(self) -> tuple[float, float] | None:
        """Entre quanto e quanto a diferença (a placa menos o computador) está com certeza; ``None`` sem o pedido, a
        chegada ou o tempo de processo (fora do Linux), ou se os limites se cruzam (o relógio do computador pulou no
        meio da chamada)."""
        if self.recebido_em is None or self.enviado_em is None or self.desde_o_inicio_s is None:
            return None
        baixo, alto = self.utc - self.recebido_em, self.utc - self.desde_o_inicio_s - self.enviado_em
        return (baixo, alto) if baixo <= alto else None

    @property
    def incerteza_s(self) -> float | None:
        """A metade da faixa dos :attr:`limites_s`: a estimativa está no máximo isto longe da diferença de verdade."""
        limites = self.limites_s
        return None if limites is None else (limites[1] - limites[0]) / 2

    def diferenca_s(self, agora: float | None = None) -> float:
        """A hora da placa menos a do computador: o meio dos :attr:`limites_s`; sem eles, contra a chegada da
        resposta (um pouco a menos que a de verdade); com ``agora``, contra ele."""
        if agora is not None:
            return self.utc - agora
        limites = self.limites_s
        if limites is not None:
            return (limites[0] + limites[1]) / 2
        return self.utc - (self.recebido_em if self.recebido_em is not None else time.time())


@dataclass(frozen=True)
class CapturaNaPlaca:
    """Um ``.bin`` na placa: o caminho relativo à pasta do firmware, o tamanho, a data e o resumo do cabeçalho (o do
    agente; ``None`` num arquivo sem o cabeçalho)."""

    arquivo: str
    bytes: int
    modificado: float
    cabecalho: dict | None = field(default=None, repr=False)

    @classmethod
    def de_json(cls, dados: dict) -> CapturaNaPlaca:
        cabecalho = dados.get("cabecalho")
        return cls(str(dados.get("arquivo")), int(dados.get("bytes") or 0), float(dados.get("modificado") or 0.0),
                   cabecalho if isinstance(cabecalho, dict) else None)

    @property
    def titulo(self) -> str | None:
        return _campo(self.cabecalho, "titulo")

    @property
    def taxa_hz(self) -> int | None:
        return _campo(self.cabecalho, "taxa_hz")

    @property
    def canais(self) -> tuple[int, ...]:
        return tuple(_campo(self.cabecalho, "canais") or ())

    @property
    def duracao_s(self) -> float | None:
        return _campo(self.cabecalho, "duracao_s")

    @property
    def problemas(self) -> list[str]:
        """A integridade, em frases curtas para a lista (vazia = nada de errado)."""
        c = self.cabecalho
        if c is None:
            return ["sem o cabeçalho (de um firmware antigo, ou outro arquivo)"]
        problemas = []
        if not c.get("crc_valido"):
            problemas.append("o cabeçalho está corrompido (o CRC não confere)")
        if c.get("final") is False:
            problemas.append("sem o cabeçalho final: a captura foi interrompida, ou ainda está gravando")
        elif c.get("completa") is False:
            esperado = c.get("bytes_esperados")
            problemas.append(f"o arquivo tem {self.bytes} bytes, e o cabeçalho diz {esperado}: cortado, ou com outro "
                             "grudado")
        if c.get("buffers_sobrescritos"):
            problemas.append(f"{c['buffers_sobrescritos']} buffer(s) sobrescrito(s): amostras perdidas")
        if c.get("amostras_atrasadas"):
            problemas.append(f"{c['amostras_atrasadas']} amostra(s) atrasada(s): a taxa real é menor")
        if c.get("quadros_sdo_ruido"):
            problemas.append(f"{c['quadros_sdo_ruido']} quadro(s) com ruído na linha SDO")
        return problemas


@dataclass(frozen=True)
class ColetaNaPlaca:
    """O manifesto de uma coleta (o ``resumo.csv`` da campanha, o ``pontos_coletados.csv`` da sonda)."""

    arquivo: str
    colunas: tuple[str, ...]
    linhas: tuple[tuple[str, ...], ...]
    cortado: bool
    modificado: float | None

    @classmethod
    def de_json(cls, dados: dict) -> ColetaNaPlaca:
        return cls(str(dados.get("arquivo")), tuple(dados.get("colunas") or ()),
                   tuple(tuple(linha) for linha in dados.get("linhas") or ()), bool(dados.get("cortado")),
                   dados.get("modificado"))

    @property
    def pasta(self) -> str:
        return self.arquivo.rpartition("/")[0]

    def linhas_como_dicts(self) -> list[dict[str, str]]:
        return [dict(zip(self.colunas, linha, strict=False)) for linha in self.linhas]


@dataclass(frozen=True)
class CapturasDaPlaca:
    """O comando ``capturas``: as mais recentes primeiro (o agente manda até 2000; ``total`` é quantas há)."""

    pasta: str
    total: int | None
    capturas: tuple[CapturaNaPlaca, ...]
    coletas: tuple[ColetaNaPlaca, ...]

    @classmethod
    def de_json(cls, resposta: dict) -> CapturasDaPlaca:
        return cls(str(resposta.get("pasta")), resposta.get("total"),
                   tuple(CapturaNaPlaca.de_json(c) for c in resposta.get("capturas") or () if isinstance(c, dict)),
                   tuple(ColetaNaPlaca.de_json(c) for c in resposta.get("coletas") or () if isinstance(c, dict)))

    @property
    def existe(self) -> bool:
        """Se a pasta do firmware existe na placa."""
        return self.total is not None

    @property
    def bytes(self) -> int:
        return sum(c.bytes for c in self.capturas)


@dataclass(frozen=True)
class LinhaDeLog:
    utc: float | None
    nivel: int | None                     # o do syslog: 0 (emerg) a 7 (debug); 3 e menos são erros
    origem: str | None                    # "kernel", ou o programa
    texto: str

    @classmethod
    def de_json(cls, d: dict) -> LinhaDeLog:
        return cls(d.get("utc"), d.get("nivel"), d.get("origem"), str(d.get("texto") or ""))

    @property
    def erro(self) -> bool:
        return self.nivel is not None and self.nivel <= 3


@dataclass(frozen=True)
class LogsDaPlaca:
    """O comando ``logs``: o kernel e o diário do systemd, já filtrados pelo agente. ``None`` onde a placa não deixou
    ler (o ``dmesg_restrict``, um sistema sem o ``journalctl``)."""

    kernel: tuple[LinhaDeLog, ...] | None
    diario: tuple[LinhaDeLog, ...] | None

    @classmethod
    def de_json(cls, resposta: dict) -> LogsDaPlaca:
        def linhas(chave):
            dados = resposta.get(chave)
            return None if dados is None else tuple(LinhaDeLog.de_json(d) for d in dados if isinstance(d, dict))

        return cls(linhas("kernel"), linhas("diario"))

    def todas(self) -> list[LinhaDeLog]:
        """O kernel e o diário juntos, na ordem da hora (as sem hora no fim)."""
        juntas = [*(self.kernel or ()), *(self.diario or ())]
        return sorted(juntas, key=lambda linha: (linha.utc is None, linha.utc or 0.0))
