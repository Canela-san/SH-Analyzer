"""A captura que chega pela saída contínua do ``ler_adc`` (``ler_adc -o - --progresso-json``; docs/gui-plan.md, 11.6),
gravada num arquivo deste computador à medida que chega.

**O fluxo** é o cabeçalho provisório (4096 bytes), os blocos e o cabeçalho final DEPOIS do último bloco (um pipe não
volta ao começo). :func:`fechar` deixa o arquivo como o ``ler_adc`` o gravaria no cartão: o cabeçalho final no lugar
do provisório, sem os 4096 bytes do fim.

**A queda** (a conexão que cai, o ``ler_adc`` que para com o código 6) deixa o arquivo sem o cabeçalho final, e talvez
com um pedaço do bloco que não chegou. :func:`fechar` o fecha com o que chegou: os blocos inteiros, os campos do fim
calculados aqui (os blocos, o CRC das amostras e o sinal de cada canal, das amostras; o tempo, a taxa medida e os
contadores da PRU, das linhas de progresso, :class:`Acompanhamento`) e a marca ``fim_pelo_computador`` no cabeçalho.
O resultado é uma captura válida e conferível, que a análise abre como qualquer outra.

**As linhas de progresso** (``--progresso-json``, no stderr do ``ler_adc``): uma por evento, ``{"evento": "inicio" |
"bloco" | "fim", "formato": 1, ...}``; as outras linhas do stderr são o texto para humanos. :class:`Acompanhamento`
as lê e guarda o que o fechamento precisa.

Depende de: ``cabecalho``, ``erros``. Sem rede e sem Qt: quem recebe o fluxo (o ``sh_placa``) grava o arquivo e
chama :func:`fechar` no fim.
"""

from __future__ import annotations

import json
import logging
import os
import zlib
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from . import cabecalho as cab
from .erros import ErroSHAN

log = logging.getLogger(__name__)

FORMATO_DO_PROGRESSO = 1
"""A versão das linhas do ``--progresso-json`` que este módulo entende (``PROGRESSO_FORMATO`` do ``ler_adc.c``)."""


class CapturaVazia(ErroSHAN):
    """Nada que dê uma captura chegou: nem o cabeçalho provisório inteiro."""


@dataclass
class Acompanhamento:
    """O que as linhas do ``--progresso-json`` disseram até agora. :meth:`receber` lê uma linha do stderr do
    ``ler_adc`` e devolve o evento (ou ``None``, numa linha de texto)."""

    inicio: dict | None = None
    blocos: dict[int, dict] = field(default_factory=dict)    # o evento de cada bloco, pelo número dele (1, 2, ...)
    fim: dict | None = None

    def receber(self, linha: str) -> dict | None:
        linha = linha.strip()
        if not linha.startswith("{"):
            return None
        try:
            evento = json.loads(linha)
        except ValueError:
            log.warning(f"linha de progresso do ler_adc que não se entende: {linha[:200]!r}")
            return None
        if not isinstance(evento, dict) or evento.get("formato") != FORMATO_DO_PROGRESSO:
            log.warning(f"linha de progresso do ler_adc de outro formato: {linha[:200]!r}")
            return None
        tipo = evento.get("evento")
        if tipo == "inicio":
            self.inicio = evento
        elif tipo == "bloco" and isinstance(evento.get("bloco"), int):
            self.blocos[evento["bloco"]] = evento
        elif tipo == "fim":
            self.fim = evento
        return evento

    def ate(self, blocos: int) -> dict | None:
        """O último evento de bloco até o bloco ``blocos`` (o dele, ou o do anterior mais próximo que chegou)."""
        numeros = [n for n in self.blocos if n <= blocos]
        return self.blocos[max(numeros)] if numeros else None


@dataclass(frozen=True)
class Fechamento:
    """Como :func:`fechar` deixou a captura."""

    cabecalho: cab.CabecalhoArquivo
    pelo_computador: bool                 # a saída caiu: o fim (os campos [final]) é deste computador
    bytes_descartados: int                # o pedaço do bloco que não chegou inteiro (0 no fluxo inteiro)
    crc_confere: bool | None              # o CRC das amostras do arquivo é o do ler_adc? None: o fim é daqui

    @property
    def blocos(self) -> int:
        return self.cabecalho.blocos_gravados


def fechar(caminho: Path, acompanhamento: Acompanhamento | None = None, *,
           crc_das_amostras: int | None = None) -> Fechamento:
    """Deixa em ``caminho`` a captura como o ``ler_adc`` a gravaria (ver o módulo) e a devolve conferida.

    ``acompanhamento``: as linhas de progresso que chegaram (só a queda as usa). ``crc_das_amostras``: o CRC-32 dos
    blocos, calculado por quem recebeu à medida que chegavam (sem ele, o arquivo inteiro é lido de novo para conferir
    o do ``ler_adc``). Uma captura já fechada (o cabeçalho do começo já é o final) volta como está.

    ``CapturaVazia`` se nem o cabeçalho provisório chegou; ``ErroSHAN`` num arquivo que não é o de uma saída contínua
    (outro cabeçalho; no fim, o cabeçalho de outra captura ou de outros blocos)."""
    caminho = Path(caminho)
    tamanho_do_arquivo = caminho.stat().st_size
    with open(caminho, "rb") as f:
        provisorio = f.read(cab.CABECALHO_TAMANHO_V9)
    if len(provisorio) < cab.CABECALHO_TAMANHO_V9:
        raise CapturaVazia(f"'{caminho.name}': chegaram {len(provisorio)} bytes, e o cabeçalho tem "
                           f"{cab.CABECALHO_TAMANHO_V9}: nada da captura chegou")
    inicial = cab.interpretar_cabecalho(provisorio, caminho)
    if inicial is None or inicial.versao_cabecalho < 9 or not inicial.crc32_valido:
        raise ErroSHAN(f"'{caminho.name}' não começa com o cabeçalho de uma saída contínua (v9, com o CRC certo)")
    t = inicial.tamanho_cabecalho
    bloco = inicial.samples_per_buffer * inicial.bytes_por_amostra
    corpo = tamanho_do_arquivo - t
    if inicial.blocos_gravados or inicial.fim_pelo_computador:
        return _ja_fechada(caminho, inicial, corpo, bloco)
    final = _cabecalho_final(caminho, inicial, corpo, bloco)
    if final is None:
        return _fechar_parcial(caminho, provisorio, inicial, corpo, bloco, acompanhamento or Acompanhamento())
    bruto_final, cabecalho = final
    with open(caminho, "r+b") as f:
        f.write(bruto_final)
        f.truncate(tamanho_do_arquivo - t)
    if crc_das_amostras is not None:
        confere = crc_das_amostras == cabecalho.crc32_amostras
    else:
        confere = cab.conferir_crc_das_amostras(caminho, cabecalho)
    return Fechamento(cabecalho, False, 0, confere)


def _ja_fechada(caminho: Path, cabecalho: cab.CabecalhoArquivo, corpo: int, bloco: int) -> Fechamento:
    """O cabeçalho do começo já é o final (``fechar`` chamado de novo): nada muda, se os blocos são os dele."""
    if corpo != cabecalho.blocos_gravados * bloco:
        raise ErroSHAN(f"'{caminho.name}': o cabeçalho diz {cabecalho.blocos_gravados} bloco(s), e o arquivo tem "
                       f"{corpo} bytes de amostras")
    confere = None if cabecalho.fim_pelo_computador else cab.conferir_crc_das_amostras(caminho, cabecalho)
    return Fechamento(cabecalho, cabecalho.fim_pelo_computador, 0, confere)


def _cabecalho_final(caminho: Path, inicial: cab.CabecalhoArquivo, corpo: int,
                     bloco: int) -> tuple[bytes, cab.CabecalhoArquivo] | None:
    """O cabeçalho final no fim do arquivo, se ele está lá: os últimos ``t`` bytes depois de blocos inteiros, com o CRC
    certo, da mesma captura e com os blocos que o arquivo tem."""
    t = inicial.tamanho_cabecalho
    if corpo < t or (corpo - t) % bloco:
        return None
    blocos = (corpo - t) // bloco
    with open(caminho, "rb") as f:
        f.seek(t + blocos * bloco)
        bruto = f.read(t)
    final = cab.interpretar_cabecalho(bruto, caminho)
    if final is None or not final.crc32_valido:
        return None                         # amostras de um bloco que não chegou inteiro, e não um cabeçalho
    if final.id_captura != inicial.id_captura:
        raise ErroSHAN(f"'{caminho.name}': o cabeçalho do fim é de outra captura ({final.id_captura}; a do começo é "
                       f"{inicial.id_captura})")
    if final.blocos_gravados != blocos or final.total_amostras_gravadas != blocos * inicial.samples_per_buffer:
        raise ErroSHAN(f"'{caminho.name}': o cabeçalho do fim diz {final.blocos_gravados} bloco(s), e chegaram "
                       f"{blocos}")
    return bruto, final


def _fechar_parcial(caminho: Path, provisorio: bytes, inicial: cab.CabecalhoArquivo, corpo: int, bloco: int,
                    acompanhamento: Acompanhamento) -> Fechamento:
    """A saída caiu: os blocos inteiros ficam, e o fim é calculado aqui."""
    blocos = corpo // bloco
    descartados = corpo - blocos * bloco
    os.truncate(caminho, inicial.tamanho_cabecalho + blocos * bloco)
    fixa: dict[str, object] = {"blocos_gravados": blocos, "total_amostras_gravadas": blocos * inicial.samples_per_buffer}
    extensao: dict[str, object] = {}
    if blocos:
        crc, estatisticas = _medir_os_blocos(caminho, inicial, blocos)
        extensao.update(crc32_amostras=crc, **estatisticas)
        fixa.update(_do_progresso(acompanhamento, blocos))
        extensao.update(_tempo_do_fim(inicial, acompanhamento, blocos, fixa.get("taxa_medida_hz")))
    novo = cab.reescrever_campos(provisorio, fixa=fixa, extensao=extensao, reserva={"fim_pelo_computador": 1})
    with open(caminho, "r+b") as f:
        f.write(novo)
    log.info(f"'{caminho.name}': a saída contínua caiu, e a captura foi fechada aqui com {blocos} bloco(s) inteiro(s)"
             + (f" ({descartados} bytes do bloco seguinte descartados)" if descartados else ""))
    return Fechamento(cab.interpretar_cabecalho(novo, caminho), True, descartados, None)


_CONTADORES_DO_PROGRESSO = ("amostras_atrasadas", "buffers_sobrescritos", "quadros_preambulo_ruim",
                            "folga_minima_ciclos", "atraso_maximo_ciclos", "divergencias_fase_a",
                            "divergencias_fase_c", "ciclos_rebase")


def _do_progresso(acompanhamento: Acompanhamento, blocos: int) -> dict[str, object]:
    """Os campos da PRU e a taxa medida, das linhas de progresso: os contadores acumulados até o último bloco que tem
    linha (a do último bloco que chegou pode não ter chegado) e a taxa entre o 1º e esse bloco, como a do ``ler_adc``
    (os instantes em que cada bloco foi visto pronto). Sem as linhas, os campos ficam os do cabeçalho provisório."""
    campos: dict[str, object] = {}
    if acompanhamento.inicio is not None and "versao_protocolo_pru" in acompanhamento.inicio:
        campos["versao_protocolo_pru"] = int(acompanhamento.inicio["versao_protocolo_pru"])
    ultimo = acompanhamento.ate(blocos)
    if ultimo is None:
        return campos
    campos.update({nome: int(ultimo[nome]) for nome in _CONTADORES_DO_PROGRESSO if nome in ultimo})
    primeiro = acompanhamento.blocos.get(1)
    if primeiro is not None and ultimo["bloco"] >= 2:
        intervalo = float(ultimo["t_s"]) - float(primeiro["t_s"])
        amostras_por_bloco = int(ultimo["amostras"]) // int(ultimo["bloco"])
        if intervalo > 0:
            campos["taxa_medida_hz"] = (ultimo["bloco"] - 1) * amostras_por_bloco / intervalo
    return campos


def _tempo_do_fim(inicial: cab.CabecalhoArquivo, acompanhamento: Acompanhamento, blocos: int,
                  taxa_medida: float | None) -> dict[str, object]:
    """O fim da captura (o instante em que o último bloco foi visto pronto, do começo dela) e o pior bloco no ARM.
    Sem a linha do último bloco, o tempo dos que faltam é estimado pela taxa (a medida, ou a pedida)."""
    ultimo = acompanhamento.ate(blocos)
    taxa = taxa_medida or inicial.pru_clock_hz / inicial.sample_period_ticks
    vistos, duracao = (0, 0.0) if ultimo is None else (int(ultimo["bloco"]), float(ultimo["t_s"]))
    duracao += (blocos - vistos) * inicial.samples_per_buffer / taxa
    fim = inicial.timestamp_unix + (inicial.timestamp_ns or 0) * 1e-9 + duracao
    gravacoes = [float(e.get("gravacao_ms", 0.0)) for n, e in acompanhamento.blocos.items() if n <= blocos]
    return {"timestamp_fim_unix": int(fim), "timestamp_fim_ns": min(int(round((fim % 1) * 1e9)), 999_999_999),
            "duracao_monotonica_s": duracao, "pior_bloco_ms": int(round(max(gravacoes, default=0.0)))}


def _medir_os_blocos(caminho: Path, inicial: cab.CabecalhoArquivo, blocos: int) -> tuple[int, dict[str, list]]:
    """O CRC-32 das amostras e o sinal de cada canal (mínimo, máximo, saturadas, média e desvio, em códigos), como o
    ``ler_adc`` os mede: o canal de cada amostra é o da posição dela no ARQUIVO (um bloco não tem um número inteiro de
    varreduras com 3, 5, 6 ou 7 canais). Bloco a bloco: memória constante."""
    k = inicial.num_canais
    por_bloco = inicial.samples_per_buffer
    minimos = np.full(k, 65535, dtype=np.int64)
    maximos = np.zeros(k, dtype=np.int64)
    saturadas = np.zeros(k, dtype=np.int64)
    contadas = np.zeros(k, dtype=np.int64)
    somas = np.zeros(k, dtype=np.int64)
    quadrados = np.zeros(k, dtype=np.float64)
    crc = 0
    with open(caminho, "rb") as f:
        f.seek(inicial.tamanho_cabecalho)
        for j in range(blocos):
            bruto = f.read(por_bloco * 2)
            crc = zlib.crc32(bruto, crc)
            codigos = np.frombuffer(bruto, dtype="<u2")
            fase = (j * por_bloco) % k
            for p in range(k):
                canal = codigos[(p - fase) % k::k]
                if not len(canal):
                    continue
                minimos[p] = min(minimos[p], int(canal.min()))
                maximos[p] = max(maximos[p], int(canal.max()))
                saturadas[p] += int(np.count_nonzero((canal == 0) | (canal == 65535)))
                x = canal.astype(np.int64) - 32768
                contadas[p] += len(canal)
                somas[p] += int(x.sum())
                quadrados[p] += float(np.dot(x.astype(np.float64), x.astype(np.float64)))
    medias, desvios = [], []
    for p in range(k):
        n = int(contadas[p])
        media = somas[p] / n if n else 0.0
        medias.append(32768.0 + media if n else 0.0)
        desvios.append(float(np.sqrt(max(quadrados[p] / n - media * media, 0.0))) if n else 0.0)
    return crc, {"codigo_minimo": [int(v) for v in minimos], "codigo_maximo": [int(v) for v in maximos],
                 "amostras_saturadas": [int(v) for v in saturadas], "media_codigos": medias,
                 "desvio_codigos": desvios}
