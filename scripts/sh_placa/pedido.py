"""O pedido de uma captura (docs/gui-plan.md, 11.5; a F4.3): o que o formulário da Aquisição monta, sem Qt.

:class:`PedidoDeCaptura` guarda o formulário inteiro (os canais com a grandeza, a sonda, a faixa e o ganho; a taxa; a
duração, os blocos ou "até parar"; o título e a descrição; o destino; o avançado), monta os argumentos do ``ler_adc``
(:meth:`~PedidoDeCaptura.argumentos`) e o comando que a tela mostra (:func:`comando`), e vai e volta de um ``dict``
(os modelos de captura do projeto).

**A validação** (:func:`validar`) devolve os :class:`Problema` por campo, com o nível: o ``"erro"`` impede a captura
(o ``ler_adc`` a recusaria, ou ela sairia errada); o ``"aviso"`` deixa capturar, mas diz o que vai faltar; o
``"info"`` só explica. **As regras do C** (``firmware/ler_adc.c``, ``analisar_argumentos``) estão aqui como lá: os
canais de 0 a 7 sem repetir, as três faixas bipolares, o título e a descrição em bytes, o ganho positivo, as esperas
de CS de 1 a 10 000 e o teto da PRU (:func:`teto_ticks_da_pru`, a conta de ``teto_ticks_da_pru``). **As de fora do
C:** o id de sonda que a análise aceita (``supraharmonicos.sonda.PADRAO_SONDA_ID``), o perfil na pasta das sondas e a
calibração dele contra a faixa e o ganho do canal (o que ``conferir_calibracao_perfil`` avisaria depois, na análise),
a Nyquist por canal contra a faixa dos supraharmônicos, e o :class:`Contexto` (o espaço no destino, a vazão do
enlace, uma captura do mesmo nome no cartão).

**O caminho de volta** (:func:`ler_argumentos`): a linha de comando lida como o ``ler_adc.c`` a lê, com os mesmos
erros de uso (:class:`ErroDeUso`). A placa simulada captura por ela, e ``tests/test_sh_placa_pedido.py`` confere as
duas direções contra o C de verdade, compilado num harness.
"""

from __future__ import annotations

import math
import re
import shlex
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path

GRANDEZAS = ("tensao", "corrente", "temperatura")
"""As grandezas do ``--grandeza`` (``GRANDEZA_TENSAO``, ``_CORRENTE`` e ``_TEMPERATURA`` do C, nessa ordem)."""
GRANDEZA_PADRAO = "tensao"
FAIXAS_V = (20.48, 10.24, 5.12)
"""As faixas totais do ADS8688 (±10,24, ±5,12 e ±2,56 V), na ordem dos códigos ``FAIXA_ADC_*`` do C."""
FAIXA_PADRAO_V = 20.48
TOLERANCIA_DA_FAIXA_V = 0.005                  # a do analisar_lista_faixas
MODOS_SPI = ("rapido", "rapido:a", "rapido:c", "lenta")
"""Os modos do ``--spi``: o rápido lendo na fase B (o padrão), na A ou na C, e o lento de antes de 22/10/2026."""
_SINONIMOS_DO_SPI = {"rápido": "rapido", "rapido:b": "rapido", "lento": "lenta"}
SPI_PADRAO = "rapido"
ATRASOS_CS_PADRAO = (3, 1, 3)                  # ATRASO_CS_SETUP/HOLD/ALTO_PADRAO (memoria_pru.h)
ATRASO_CS_MAXIMO = 10_000
CANAL_PADRAO = 1
NUM_CANAIS = 8
FREQUENCIA_PADRAO_HZ = 400_000
FREQUENCIA_MAXIMA_HZ = 500_000                 # o ADS8688 converte até 500 kS/s no total
RELOGIO_DA_PRU_HZ = 200_000_000
TETO_TICKS_SPI_RAPIDO = 477                    # 419 287 S/s com as esperas padrão (T7g)
TETO_TICKS_SPI_LENTO = 610                     # 327 868 S/s (T7f)
AMOSTRAS_POR_BLOCO = 1_048_576                 # SAMPLES_PER_BUFFER (memoria_pru.h)
BYTES_POR_AMOSTRA = 2
BYTES_DO_CABECALHO = 4096
BLOCOS_PADRAO = 1
LIMITE_DO_TITULO = 127                         # bytes em UTF-8, sem o nulo (CABECALHO_TITULO_TAMANHO - 1)
LIMITE_DA_DESCRICAO = 271
LIMITE_DA_SONDA = 31
GANHO_MAXIMO = 1e12
BANDA_DOS_SUPRAHARMONICOS_HZ = (2_000.0, 150_000.0)
DESTINOS = ("computador", "cartao")
"""``"computador"``: a saída contínua (``-o -``, a F4.2); ``"cartao"``: o ``-o`` no cartão da placa."""
NIVEIS = ("erro", "aviso", "info")
FOLGA_DO_ENLACE = 2.0
"""A vazão do enlace que deixa a captura contínua tranquila: o dobro da dela (o plano, 11.3)."""
FOLGA_DO_DISCO = 0.9
"""Acima desta fração do espaço livre, o destino fica apertado (o aviso)."""
TOLERANCIA_DA_CALIBRACAO = 1e-3               # a do conferir_calibracao_perfil
_PADRAO_DO_ID_DE_SONDA = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")   # supraharmonicos.sonda.PADRAO_SONDA_ID
_PADRAO_DO_ARQUIVO = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.+-]*\.bin$")
_NUMERO_DO_C = re.compile(r"\s*[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?")   # o que o strtod lê de um decimal
_INTEIRO_DO_C = re.compile(r"\s*[+-]?\d+")                            # o que o strtol lê


class ErroDeUso(ValueError):
    """A linha de comando que o ``ler_adc`` recusaria (o código 2), com a mensagem dele."""


@dataclass(frozen=True)
class Canal:
    """Um canal da captura: o número (0 a 7), a grandeza (:data:`GRANDEZAS`), o id da sonda (``""``: nenhuma), a
    faixa total do ADC em volts (:data:`FAIXAS_V`) e o ganho (unidades físicas por volt no pino; ``None``: não
    declarado, e a análise usa 1)."""

    numero: int
    grandeza: str = GRANDEZA_PADRAO
    sonda: str = ""
    faixa_v: float = FAIXA_PADRAO_V
    ganho: float | None = None

    @property
    def lsb_v(self) -> float:
        """O tamanho de um código, em volts no pino."""
        return self.faixa_v / 65536


@dataclass(frozen=True)
class PedidoDeCaptura:
    """Uma captura pedida: o formulário inteiro. Os canais ficam na ordem em que o ADC os varre (a crescente),
    qualquer que seja a dada. A duração é ``duracao_s`` (o ``--duracao``, em blocos inteiros) ou, sem ela, ``blocos``
    (o ``--blocos``; 0 = até parar)."""

    canais: tuple[Canal, ...] = (Canal(CANAL_PADRAO),)
    taxa_hz: int = FREQUENCIA_PADRAO_HZ
    duracao_s: float | None = None
    blocos: int = BLOCOS_PADRAO
    titulo: str = ""
    descricao: str = ""
    destino: str = "computador"
    arquivo_no_cartao: str = ""            # o -o no cartão; "" = o nome do ler_adc (captura_AAAAMMDD_HHMMSS.bin)
    spi: str = SPI_PADRAO
    atrasos_cs: tuple[int, int, int] = ATRASOS_CS_PADRAO
    forcar_taxa: bool = False

    def __post_init__(self):
        object.__setattr__(self, "canais", tuple(sorted(self.canais, key=lambda c: c.numero)))
        object.__setattr__(self, "atrasos_cs", tuple(self.atrasos_cs))
        object.__setattr__(self, "spi", _SINONIMOS_DO_SPI.get(self.spi, self.spi))

    # ------------------------------------------------------------------ o que sai do pedido

    @property
    def numeros(self) -> tuple[int, ...]:
        return tuple(c.numero for c in self.canais)

    def canal(self, numero: int) -> Canal:
        for c in self.canais:
            if c.numero == numero:
                return c
        raise KeyError(f"o canal {numero} não está no pedido")

    @property
    def ticks(self) -> int:
        """O período da amostragem em ticks de 5 ns (o que a PRU usa: a divisão inteira)."""
        return RELOGIO_DA_PRU_HZ // self.taxa_hz

    @property
    def taxa_real_hz(self) -> float:
        """A taxa que a PRU faz de fato: 200 MHz ÷ :attr:`ticks` (igual à pedida só com um divisor de 200 MHz)."""
        return RELOGIO_DA_PRU_HZ / self.ticks

    @property
    def taxa_por_canal_hz(self) -> float:
        return self.taxa_real_hz / max(1, len(self.canais))

    @property
    def nyquist_por_canal_hz(self) -> float:
        return self.taxa_por_canal_hz / 2

    @property
    def blocos_pedidos(self) -> int:
        """Os blocos que o ``ler_adc`` vai gravar (0 = até parar)."""
        if self.duracao_s is not None:
            return blocos_para_duracao(self.duracao_s, self.taxa_hz)
        return self.blocos

    @property
    def ate_parar(self) -> bool:
        return self.blocos_pedidos == 0

    @property
    def duracao_real_s(self) -> float | None:
        """A duração dos blocos inteiros (``None`` até parar)."""
        if self.ate_parar:
            return None
        return self.blocos_pedidos * AMOSTRAS_POR_BLOCO / self.taxa_real_hz

    @property
    def bytes_por_segundo(self) -> float:
        return self.taxa_real_hz * BYTES_POR_AMOSTRA

    @property
    def bytes_do_arquivo(self) -> int | None:
        """O tamanho do ``.bin`` no fim (``None`` até parar)."""
        if self.ate_parar:
            return None
        return BYTES_DO_CABECALHO + self.blocos_pedidos * AMOSTRAS_POR_BLOCO * BYTES_POR_AMOSTRA

    def argumentos(self) -> list[str]:
        """Os argumentos do ``ler_adc``, na ordem da ajuda dele, sem o destino da saída contínua (o ``-o -`` e o
        ``--progresso-json`` são de quem recebe, ``sh_placa/captura.py``). Uma opção por canal só entra quando algum
        canal foge do padrão, e então com todos os canais dela: o comando fica curto e diz tudo."""
        args = [str(self.taxa_hz), ",".join(str(n) for n in self.numeros)]
        if self.duracao_s is not None:
            args += ["--duracao", texto_da_duracao(self.duracao_s)]
        else:
            args += ["--blocos", str(self.blocos)]
        if self.titulo:
            args += ["-t", self.titulo]
        if self.descricao:
            args += ["-d", self.descricao]
        if any(c.grandeza != GRANDEZA_PADRAO for c in self.canais):
            args += ["--grandeza", ",".join(f"{c.numero}:{c.grandeza}" for c in self.canais)]
        if any(c.sonda for c in self.canais):
            args += ["--sonda", ",".join(f"{c.numero}:{c.sonda}" for c in self.canais if c.sonda)]
        if any(c.ganho is not None for c in self.canais):
            args += ["--ganho", ",".join(f"{c.numero}:{_texto_do_numero(c.ganho)}" for c in self.canais
                                         if c.ganho is not None)]
        if any(not _mesma_faixa(c.faixa_v, FAIXA_PADRAO_V) for c in self.canais):
            args += ["--faixa-adc", ",".join(f"{c.numero}:{_texto_da_faixa(c.faixa_v)}" for c in self.canais)]
        if self.spi != SPI_PADRAO:
            args += ["--spi", self.spi]
        if tuple(self.atrasos_cs) != ATRASOS_CS_PADRAO:
            args += ["--atraso-cs", ",".join(str(a) for a in self.atrasos_cs)]
        if self.forcar_taxa:
            args.append("--forcar-taxa")
        if self.destino == "cartao" and self.arquivo_no_cartao:
            args += ["-o", self.arquivo_no_cartao]
        return args

    def com(self, **mudancas) -> PedidoDeCaptura:
        """Uma cópia com ``mudancas`` (o ``dataclasses.replace``)."""
        return replace(self, **mudancas)

    def com_canal(self, canal: Canal) -> PedidoDeCaptura:
        """Uma cópia com ``canal`` no lugar do de mesmo número (ou a mais, se ele não estava)."""
        outros = tuple(c for c in self.canais if c.numero != canal.numero)
        return replace(self, canais=(*outros, canal))

    def sem_canal(self, numero: int) -> PedidoDeCaptura:
        return replace(self, canais=tuple(c for c in self.canais if c.numero != numero))


def comando(pedido: PedidoDeCaptura) -> str:
    """O comando que a tela mostra, como se digitaria na pasta do firmware da placa: o do cartão, ou o da saída
    contínua (com o ``-o -``: a captura vem pelo SSH)."""
    args = pedido.argumentos()
    if pedido.destino == "computador":
        args += ["-o", "-"]
    return "sudo ./ler_adc " + shlex.join(args)


# ------------------------------------------------------------------ as contas do C


def teto_ticks_da_pru(spi: str = SPI_PADRAO, atrasos_cs: Sequence[int] = ATRASOS_CS_PADRAO) -> int:
    """O menor período, em ticks, com toda amostra na grade, para o SPI e as esperas de CS (``teto_ticks_da_pru`` do
    ``ler_adc.c``): cada iteração de setup ou de hold além do padrão soma 2 ciclos, e a espera de CS alto, a partir de
    10 iterações, soma 2·A + 1."""
    s, h, a = (int(x) for x in atrasos_cs)
    teto = TETO_TICKS_SPI_LENTO if _SINONIMOS_DO_SPI.get(spi, spi) == "lenta" else TETO_TICKS_SPI_RAPIDO
    teto += 2 * (s - ATRASOS_CS_PADRAO[0]) + 2 * (h - ATRASOS_CS_PADRAO[1])
    if a >= 10:
        teto += 2 * a + 1
    return teto


def taxa_maxima_hz(spi: str = SPI_PADRAO, atrasos_cs: Sequence[int] = ATRASOS_CS_PADRAO) -> int:
    """A maior taxa total sem passar do teto da PRU (o "Use até N Hz" do ``ler_adc``), limitada à do ADC."""
    return min(FREQUENCIA_MAXIMA_HZ, RELOGIO_DA_PRU_HZ // teto_ticks_da_pru(spi, atrasos_cs))


def blocos_para_duracao(segundos: float, taxa_hz: int) -> int:
    """Os blocos inteiros que cobrem ``segundos`` à taxa pedida, pelo menos 1 (``calcular_blocos_para_duracao``: a
    taxa pedida, não a real, e o arredondamento para cima)."""
    return max(1, math.ceil(segundos * taxa_hz / AMOSTRAS_POR_BLOCO))


def texto_da_duracao(segundos: float) -> str:
    """O ``--duracao`` de ``segundos``: em horas ou minutos quando é um número inteiro deles (``2h``, ``10m``),
    senão em segundos (``30s``, ``2.5s``)."""
    if segundos >= 3600 and segundos % 3600 == 0:
        return f"{int(segundos // 3600)}h"
    if segundos >= 60 and segundos % 60 == 0:
        return f"{int(segundos // 60)}m"
    return f"{_texto_do_numero(segundos)}s"


def _texto_do_numero(valor: float) -> str:
    """O número mais curto que volta igual (o ``repr``), sem o ``.0`` dos inteiros."""
    texto = repr(float(valor))
    return texto[:-2] if texto.endswith(".0") else texto


def _mesma_faixa(a: float, b: float) -> bool:
    return abs(a - b) < TOLERANCIA_DA_FAIXA_V


def _texto_da_faixa(faixa_v: float) -> str:
    for faixa in FAIXAS_V:
        if _mesma_faixa(faixa_v, faixa):
            return _texto_do_numero(faixa)
    return _texto_do_numero(faixa_v)


def faixa_conhecida(faixa_v: float) -> float | None:
    """A faixa de :data:`FAIXAS_V` que ``faixa_v`` é (com a tolerância do C), ou ``None``."""
    for faixa in FAIXAS_V:
        if _mesma_faixa(faixa_v, faixa):
            return faixa
    return None


# ------------------------------------------------------------------ o caminho de volta: a linha de comando do C


@dataclass(frozen=True)
class LinhaDeComando:
    """Uma linha de comando do ``ler_adc`` lida: o pedido, a saída (``-o``; ``None`` = o nome automático, ``"-"`` = a
    saída contínua), o ``--progresso-json`` e o ``-v``."""

    pedido: PedidoDeCaptura
    arquivo: str | None = None
    progresso_json: bool = False
    verboso: bool = False

    @property
    def continua(self) -> bool:
        return self.arquivo == "-"


_COM_VALOR = {"--blocos": "blocos", "--duracao": "duracao", "-o": "arquivo", "--saida": "arquivo",
              "-t": "titulo", "--titulo": "titulo", "-d": "descricao", "--descricao": "descricao",
              "--grandeza": "grandeza", "--sonda": "sonda", "--ganho": "ganho", "--faixa-adc": "faixa",
              "--atraso-cs": "atrasos", "--spi": "spi"}


def ler_argumentos(argv: Sequence[str]) -> LinhaDeComando:
    """A linha de comando (sem o nome do programa) lida como o ``analisar_argumentos`` do ``ler_adc.c``: a
    frequência é o 1º argumento quando ele não começa com ``-``; os canais, o primeiro outro que não é opção; numa
    opção repetida, vale a última. ``ErroDeUso`` com a mensagem do C, no que ele recusaria."""
    argv = list(argv)
    frequencia = FREQUENCIA_PADRAO_HZ
    i = 0
    if argv and not argv[0].startswith("-"):
        frequencia = _frequencia(argv[0])
        i = 1
    textos: dict[str, str] = {}
    texto_canais: str | None = None
    forcar = progresso = verboso = False
    while i < len(argv):
        a = argv[i]
        if a in _COM_VALOR:
            if i + 1 >= len(argv):
                raise ErroDeUso(f"{a} precisa de um valor (veja --help).")
            textos[_COM_VALOR[a]] = argv[i + 1]
            i += 2
            continue
        if a == "--forcar-taxa":
            forcar = True
        elif a in ("-v", "--verbose", "--verboso"):
            verboso = True
        elif a == "--progresso-json":
            progresso = True
        elif a.startswith("-"):
            raise ErroDeUso(f"opção desconhecida '{a}' (veja ler_adc --help).")
        elif texto_canais is None:
            texto_canais = a
        else:
            raise ErroDeUso(f"argumento a mais: '{a}' (os canais já são '{texto_canais}'; a frequência vem antes "
                            "deles).")
        i += 1

    numeros = _lista_de_canais(texto_canais) if texto_canais is not None else [CANAL_PADRAO]
    grandezas = dict.fromkeys(numeros, GRANDEZA_PADRAO)
    sondas = dict.fromkeys(numeros, "")
    faixas = dict.fromkeys(numeros, FAIXA_PADRAO_V)
    ganhos: dict[int, float | None] = dict.fromkeys(numeros)
    for canal, valor in _pares(textos.get("grandeza"), "--grandeza", "0:tensao", numeros):
        if valor not in GRANDEZAS:
            raise ErroDeUso(f"grandeza '{valor}' desconhecida em --grandeza: use tensao, corrente ou temperatura.")
        grandezas[canal] = valor
    for canal, valor in _pares(textos.get("sonda"), "--sonda", "1:sct013_100a_sn001", numeros):
        if not 1 <= len(valor.encode()) <= LIMITE_DA_SONDA:
            raise ErroDeUso(f"id de sonda '{valor}' em --sonda: precisa ter de 1 a {LIMITE_DA_SONDA} bytes.")
        sondas[canal] = valor
    citadas: set[int] = set()
    for canal, valor in _pares(textos.get("faixa"), "--faixa-adc", "1:5.12", numeros):
        if canal in citadas:
            raise ErroDeUso(f"o canal {canal} aparece duas vezes em --faixa-adc.")
        citadas.add(canal)
        faixa = faixa_conhecida(_numero_do_c(valor)) if _numero_do_c(valor) is not None else None
        if faixa is None:
            raise ErroDeUso(f"faixa '{valor}' em --faixa-adc: use 20.48 (±10,24 V), 10.24 (±5,12 V) ou 5.12 "
                            "(±2,56 V).")
        faixas[canal] = faixa
    for canal, valor in _pares(textos.get("ganho"), "--ganho", "1:19.357", numeros):
        ganho = _numero_do_c(valor)
        if ganho is None or not ganho > 0.0 or ganho > GANHO_MAXIMO:
            raise ErroDeUso(f"ganho '{valor}' em --ganho: use um número positivo (ex.: 19.357).")
        ganhos[canal] = ganho

    atrasos = ATRASOS_CS_PADRAO
    if "atrasos" in textos:
        atrasos = _atrasos(textos["atrasos"])
    spi = SPI_PADRAO
    if "spi" in textos:
        spi = _SINONIMOS_DO_SPI.get(textos["spi"], textos["spi"])
        if spi not in MODOS_SPI:
            raise ErroDeUso(f"--spi '{textos['spi']}': use rapido, rapido:a, rapido:c ou lenta.")
    teto = teto_ticks_da_pru(spi, atrasos)
    if RELOGIO_DA_PRU_HZ // frequencia < teto and not forcar:
        raise ErroDeUso(f"{frequencia} Hz pedem {RELOGIO_DA_PRU_HZ // frequencia} ticks por amostra, abaixo do teto "
                        f"da PRU com o SPI {'lento' if spi == 'lenta' else 'rápido'} e estas esperas de CS ({teto} "
                        f"ticks): as amostras atrasariam e a taxa real sairia menor que a do cabeçalho. Use até "
                        f"{RELOGIO_DA_PRU_HZ // teto} Hz, ou --forcar-taxa para varrer o teto.")

    if "blocos" in textos and "duracao" in textos:
        raise ErroDeUso("--blocos e --duracao não podem ser usados juntos.")
    blocos, duracao = BLOCOS_PADRAO, None
    if "blocos" in textos:
        texto = textos["blocos"]
        if not _INTEIRO_DO_C.fullmatch(texto) or int(texto) < 0:
            raise ErroDeUso(f"--blocos '{texto}': use um inteiro >= 0 (0 = até Ctrl+C).")
        blocos = int(texto)
    elif "duracao" in textos:
        duracao = _duracao(textos["duracao"])

    titulo, descricao = textos.get("titulo", ""), textos.get("descricao", "")
    if len(titulo.encode()) > LIMITE_DO_TITULO:
        raise ErroDeUso(f"--titulo tem {len(titulo.encode())} bytes; o limite é {LIMITE_DO_TITULO}.")
    if len(descricao.encode()) > LIMITE_DA_DESCRICAO:
        raise ErroDeUso(f"--descricao tem {len(descricao.encode())} bytes; o limite é {LIMITE_DA_DESCRICAO}.")
    arquivo = textos.get("arquivo")
    if arquivo == "":
        raise ErroDeUso("nome de arquivo vazio em -o.")

    canais = tuple(Canal(n, grandezas[n], sondas[n], faixas[n], ganhos[n]) for n in numeros)
    pedido = PedidoDeCaptura(canais, frequencia, duracao, blocos, titulo, descricao,
                             "computador" if arquivo == "-" else "cartao",
                             arquivo if arquivo not in (None, "-") else "", spi, atrasos, forcar)
    return LinhaDeComando(pedido, arquivo, progresso, verboso)


def _frequencia(texto: str) -> int:
    if not texto.isdigit() or not 1 <= int(texto) <= FREQUENCIA_MAXIMA_HZ:
        raise ErroDeUso(f"frequência inválida '{texto}': use um inteiro em Hz, de 1 a {FREQUENCIA_MAXIMA_HZ} (ex.: "
                        "400000; sufixos como '400k' não são aceitos).")
    return int(texto)


def _lista_de_canais(texto: str) -> list[int]:
    """Os canais de ``"0,1,3"`` em ordem crescente (o ``strtok`` pula os vazios, como em ``"0,,1"``)."""
    numeros: list[int] = []
    for token in filter(None, texto.split(",")):
        if not _INTEIRO_DO_C.fullmatch(token) or not 0 <= int(token) < NUM_CANAIS:
            raise ErroDeUso(f"canal '{token}' inválido em '{texto}': o ADS8688 tem os canais 0 a {NUM_CANAIS - 1}.")
        if int(token) in numeros:
            raise ErroDeUso(f"o canal {int(token)} aparece duas vezes em '{texto}'.")
        numeros.append(int(token))
    if not numeros:
        raise ErroDeUso(f"lista de canais vazia: '{texto}'.")
    return sorted(numeros)


def _pares(texto: str | None, opcao: str, exemplo: str, numeros: Sequence[int]) -> Iterable[tuple[int, str]]:
    """Os pares ``canal:valor`` de uma opção por canal (o ``canal_do_par``): o canal tem de estar na captura."""
    for token in filter(None, (texto or "").split(",")):
        canal, dois_pontos, valor = token.partition(":")
        if not dois_pontos:
            raise ErroDeUso(f"'{token}' em {opcao}: use o formato 'canal:valor' (ex.: '{exemplo}').")
        if not _INTEIRO_DO_C.fullmatch(canal):
            raise ErroDeUso(f"'{canal}' não é um número de canal em {opcao}.")
        if int(canal) not in numeros:
            raise ErroDeUso(f"{opcao} cita o canal {int(canal)}, que não está na captura.")
        yield int(canal), valor


def _numero_do_c(texto: str) -> float | None:
    """O número que o ``strtod`` leria do texto inteiro (sem o ``_`` e os espaços no fim que o ``float`` aceita)."""
    if not _NUMERO_DO_C.fullmatch(texto):
        return None
    return float(texto)


def _atrasos(texto: str) -> tuple[int, int, int]:
    partes = texto.split(",")
    if len(partes) != 3 or not all(_INTEIRO_DO_C.fullmatch(p) and 1 <= int(p) <= ATRASO_CS_MAXIMO for p in partes):
        raise ErroDeUso(f"--atraso-cs '{texto}': use três inteiros de 1 a {ATRASO_CS_MAXIMO} separados por vírgula "
                        "(ex.: 3,1,3).")
    return int(partes[0]), int(partes[1]), int(partes[2])


def _duracao(texto: str) -> float:
    """``analisar_duracao_em_segundos``: um número com o sufixo opcional s, m ou h (maiúsculo também)."""
    multiplicadores = {"": 1.0, "s": 1.0, "m": 60.0, "h": 3600.0}
    numero, sufixo = (texto[:-1], texto[-1].lower()) if texto and texto[-1] in "sSmMhH" else (texto, "")
    valor = _numero_do_c(numero) if numero else None
    if valor is None or not valor * multiplicadores[sufixo] > 0.0:
        raise ErroDeUso(f"--duracao '{texto}': use um número positivo, com s, m ou h (ex.: 600, 10m, 1.5h).")
    return valor * multiplicadores[sufixo]


# ------------------------------------------------------------------ a validação


@dataclass(frozen=True)
class Problema:
    """Um problema do pedido, no campo onde ele aparece: ``"titulo"``, ``"descricao"``, ``"canais"``,
    ``"grandeza"``, ``"sonda"``, ``"faixa"``, ``"ganho"``, ``"taxa"``, ``"duracao"``, ``"destino"``, ``"arquivo"``,
    ``"spi"`` ou ``"atrasos"``; ``canal`` nos de um canal. O nível é um de :data:`NIVEIS`."""

    campo: str
    nivel: str
    mensagem: str
    canal: int | None = None

    @property
    def impede(self) -> bool:
        return self.nivel == "erro"


@dataclass(frozen=True)
class PerfilDisponivel:
    """Um perfil de sonda da pasta das sondas, como a validação o usa: a calibração com que ele foi gerado
    (``calibracao_adc``: o ganho e a faixa do canal da sonda, e se a faixa era a real do ADC) e a faixa de
    frequência em que a correção vale. ``problema``: por que ele não abre (a análise o recusaria)."""

    id: str
    caminho: Path
    ganho: float | None = None
    faixa_v: float | None = None
    faixa_confiavel: bool = False
    faixa_de_frequencia_hz: tuple[float, float] | None = None
    id_declarado: str = ""
    problema: str = ""


def perfis_de_sonda(pasta: Path) -> dict[str, PerfilDisponivel]:
    """Os perfis de ``pasta`` (os ``<id>.json`` que a análise procura), pelo id do nome do arquivo."""
    from supraharmonicos.erros import ErroSHAN  # o numpy só para quem lê os perfis
    from supraharmonicos.sonda import carregar_perfil_sonda

    perfis: dict[str, PerfilDisponivel] = {}
    pasta = Path(pasta)
    if not pasta.is_dir():
        return perfis
    for caminho in sorted(pasta.glob("*.json")):
        id_ = caminho.stem
        try:
            perfil = carregar_perfil_sonda(caminho)
        except ErroSHAN as e:
            perfis[id_] = PerfilDisponivel(id_, caminho, problema=str(e))
            continue
        cal = perfil.calibracao_adc or {}
        try:
            ganho = cal.get("ganho", {}).get("sonda")
            faixa = cal.get("faixa_v", {}).get("sonda")
            confiavel = bool(cal.get("faixa_v_confiavel", {}).get("sonda"))
            ganho = float(ganho) if ganho is not None else None
            faixa = float(faixa) if faixa is not None else None
        except (AttributeError, TypeError, ValueError):
            ganho = faixa = None                     # um bloco malformado: a análise também não confere
            confiavel = False
        perfis[id_] = PerfilDisponivel(id_, caminho, ganho, faixa, confiavel, perfil.faixa_freq_valida_hz,
                                       perfil.id)
    return perfis


@dataclass(frozen=True)
class Contexto:
    """O que a validação sabe além do pedido (``None``: não sabe, e não confere): os perfis da pasta das sondas, o
    espaço livre no computador (na pasta da captura) e no cartão da placa, a vazão medida do enlace (bytes/s) e as
    capturas que já estão no cartão (os nomes)."""

    perfis: Mapping[str, PerfilDisponivel] | None = None
    pasta_das_sondas: Path | None = None
    livre_no_computador: int | None = None
    livre_no_cartao: int | None = None
    vazao_do_enlace: float | None = None
    capturas_no_cartao: frozenset[str] = field(default_factory=frozenset)


def validar(pedido: PedidoDeCaptura, contexto: Contexto | None = None) -> list[Problema]:
    """Os problemas do pedido, na ordem do formulário; uma lista sem erro (:attr:`Problema.impede`) é uma captura que
    o ``ler_adc`` aceita."""
    ctx = contexto or Contexto()
    problemas: list[Problema] = []
    problemas += _validar_textos(pedido)
    problemas += _validar_canais(pedido, ctx)
    taxa_ok = isinstance(pedido.taxa_hz, int) and 1 <= pedido.taxa_hz <= FREQUENCIA_MAXIMA_HZ
    avancado = _validar_avancado(pedido)
    if taxa_ok:
        problemas += _validar_taxa(pedido, sem_teto=bool(avancado))
    else:
        problemas.append(Problema("taxa", "erro", f"a taxa total vai de 1 a {FREQUENCIA_MAXIMA_HZ} S/s, em inteiros"))
    problemas += _validar_duracao(pedido)
    if taxa_ok and not any(p.impede for p in problemas if p.campo == "duracao"):
        problemas += _validar_destino(pedido, ctx)
    return problemas + avancado


def impede(problemas: Iterable[Problema]) -> bool:
    return any(p.impede for p in problemas)


def _validar_textos(p: PedidoDeCaptura) -> list[Problema]:
    problemas = []
    for campo, texto, limite, nome in (("titulo", p.titulo, LIMITE_DO_TITULO, "O título"),
                                       ("descricao", p.descricao, LIMITE_DA_DESCRICAO, "A descrição")):
        if "\x00" in texto:
            problemas.append(Problema(campo, "erro", f"{nome} tem um caractere nulo, que o cabeçalho não guarda"))
        tamanho = len(texto.encode())
        if tamanho > limite:
            problemas.append(Problema(campo, "erro", f"{nome} tem {tamanho} bytes em UTF-8; o limite é {limite} "
                                                     "(um acento ocupa 2)"))
    return problemas


def _validar_canais(p: PedidoDeCaptura, ctx: Contexto) -> list[Problema]:
    problemas: list[Problema] = []
    if not p.canais:
        return [Problema("canais", "erro", "ligue pelo menos um canal")]
    numeros = [c.numero for c in p.canais]
    for n in sorted(set(numeros)):
        if not (isinstance(n, int) and 0 <= n < NUM_CANAIS):
            problemas.append(Problema("canais", "erro", f"o canal {n} não existe: o ADS8688 tem os canais 0 a 7", n))
        elif numeros.count(n) > 1:
            problemas.append(Problema("canais", "erro", f"o canal {n} aparece duas vezes", n))
    for c in p.canais:
        if c.grandeza not in GRANDEZAS:
            problemas.append(Problema("grandeza", "erro", f"a grandeza '{c.grandeza}' não existe: use tensão, "
                                                          "corrente ou temperatura", c.numero))
        faixa = faixa_conhecida(c.faixa_v) if isinstance(c.faixa_v, (int, float)) else None
        if faixa is None:
            problemas.append(Problema("faixa", "erro", "a faixa do ADC é ±10,24, ±5,12 ou ±2,56 V", c.numero))
        if c.ganho is not None and not (isinstance(c.ganho, (int, float)) and math.isfinite(c.ganho)
                                        and 0 < c.ganho <= GANHO_MAXIMO):
            problemas.append(Problema("ganho", "erro", "o ganho é um número positivo (unidades por volt no pino)",
                                      c.numero))
        problemas += _validar_sonda(p, c, faixa, ctx)
    return problemas


def _validar_sonda(p: PedidoDeCaptura, c: Canal, faixa: float | None, ctx: Contexto) -> list[Problema]:
    n = c.numero
    if not c.sonda:
        if c.grandeza == "corrente":
            return [Problema("sonda", "aviso", "sem a sonda, a análise não corrige a resposta em frequência da "
                                               "corrente: só o ganho escalar", n)]
        return []
    if len(c.sonda.encode()) > LIMITE_DA_SONDA:
        return [Problema("sonda", "erro", f"o id da sonda tem {len(c.sonda.encode())} bytes; o limite é "
                                          f"{LIMITE_DA_SONDA}", n)]
    if not _PADRAO_DO_ID_DE_SONDA.match(c.sonda) or ".." in c.sonda:
        return [Problema("sonda", "erro", "o id da sonda é o nome do perfil: letras, dígitos, '_', '-' e '.', "
                                          "sem '..' (a análise recusa outro)", n)]
    if c.grandeza == "temperatura":
        return [Problema("sonda", "aviso", "a análise não aplica uma sonda a um canal de temperatura", n)]
    if ctx.perfis is None:
        return []
    perfil = ctx.perfis.get(c.sonda)
    onde = f" em {ctx.pasta_das_sondas}" if ctx.pasta_das_sondas is not None else ""
    if perfil is None:
        return [Problema("sonda", "aviso", f"não há o perfil {c.sonda}.json{onde}: a análise não vai corrigir este "
                                           "canal enquanto ele não existir", n)]
    if perfil.problema:
        return [Problema("sonda", "aviso", f"o perfil {c.sonda}.json não abre: {perfil.problema}", n)]
    problemas = []
    if perfil.id_declarado and perfil.id_declarado != c.sonda:
        problemas.append(Problema("sonda", "aviso", f"o arquivo {c.sonda}.json declara o id "
                                                    f"'{perfil.id_declarado}': é o perfil de outra sonda?", n))
    ganho = c.ganho if c.ganho is not None else 1.0
    if perfil.ganho is not None and isinstance(ganho, (int, float)) and \
            not math.isclose(perfil.ganho, ganho, rel_tol=TOLERANCIA_DA_CALIBRACAO):
        problemas.append(Problema("ganho", "aviso", f"o perfil {c.sonda} foi gerado com o ganho "
                                                    f"{_texto_do_numero(perfil.ganho)}, e este canal tem "
                                                    f"{_texto_do_numero(ganho)}: a corrente corrigida sairia "
                                                    f"×{ganho / perfil.ganho:.4g}", n))
    # A faixa só pesa quando o perfil não foi gerado em volts reais do pino (a captura nova sempre é: o cabeçalho
    # traz a faixa do ADC, e o conferir_calibracao_perfil dispensa a comparação).
    if perfil.faixa_v is not None and faixa is not None and not perfil.faixa_confiavel and \
            not math.isclose(perfil.faixa_v, faixa, rel_tol=TOLERANCIA_DA_CALIBRACAO):
        problemas.append(Problema("faixa", "aviso", f"o perfil {c.sonda} foi gerado com a faixa "
                                                    f"{_texto_da_faixa(perfil.faixa_v)} V: as amplitudes sairiam "
                                                    f"×{faixa / perfil.faixa_v:.4g}", n))
    if perfil.faixa_de_frequencia_hz is not None and isinstance(p.taxa_hz, int) and \
            1 <= p.taxa_hz <= FREQUENCIA_MAXIMA_HZ:
        _, maxima = perfil.faixa_de_frequencia_hz
        if p.nyquist_por_canal_hz > maxima * 1.001:
            problemas.append(Problema("sonda", "info", f"o perfil {c.sonda} vale até {maxima / 1e3:.1f} kHz: acima, "
                                                       "a correção fica a do último ponto", n))
    return problemas


def _validar_taxa(p: PedidoDeCaptura, *, sem_teto: bool) -> list[Problema]:
    problemas = []
    if not sem_teto:
        teto = teto_ticks_da_pru(p.spi, p.atrasos_cs)
        if p.ticks < teto:
            maxima = RELOGIO_DA_PRU_HZ // teto
            spi = "lento" if p.spi == "lenta" else "rápido"
            if p.forcar_taxa:
                problemas.append(Problema("taxa", "aviso", f"acima do teto da PRU ({maxima} S/s com o SPI {spi}), "
                                                           "forçada: a taxa real sai menor que a do cabeçalho"))
            else:
                problemas.append(Problema("taxa", "erro", f"até {maxima} S/s com o SPI {spi} e estas esperas de CS "
                                                          "(o teto da PRU): acima, as amostras atrasam"))
    if RELOGIO_DA_PRU_HZ % p.taxa_hz:
        problemas.append(Problema("taxa", "info", f"a PRU amostra a cada {p.ticks} ticks de 5 ns: a taxa real é "
                                                  f"{p.taxa_real_hz:.2f} S/s (um divisor de 200 MHz sai exato)"))
    nyquist = p.nyquist_por_canal_hz
    minima, maxima = BANDA_DOS_SUPRAHARMONICOS_HZ
    if p.canais and nyquist < maxima:
        if nyquist <= minima:
            texto = "nada da faixa dos supraharmônicos (2 a 150 kHz) fica coberto"
        else:
            texto = "a faixa de 2 a 150 kHz não fica coberta"
        problemas.append(Problema("taxa", "aviso", f"cada canal vai até {nyquist / 1e3:.1f} kHz (a Nyquist): "
                                                   f"{texto}"))
    return problemas


def _validar_duracao(p: PedidoDeCaptura) -> list[Problema]:
    if p.duracao_s is not None:
        if not (isinstance(p.duracao_s, (int, float)) and math.isfinite(p.duracao_s) and p.duracao_s > 0):
            return [Problema("duracao", "erro", "a duração é um tempo positivo")]
        return []
    if not isinstance(p.blocos, int) or p.blocos < 0:
        return [Problema("duracao", "erro", "os blocos são um inteiro, 0 ou mais (0 = até parar)")]
    return []


def _validar_destino(p: PedidoDeCaptura, ctx: Contexto) -> list[Problema]:
    if p.destino not in DESTINOS:
        return [Problema("destino", "erro", f"destino desconhecido: '{p.destino}'")]
    problemas = []
    no_computador = p.destino == "computador"
    livre = ctx.livre_no_computador if no_computador else ctx.livre_no_cartao
    onde = "no computador" if no_computador else "no cartão da placa"
    tamanho = p.bytes_do_arquivo
    if livre is not None:
        if tamanho is None:
            minutos = max(0.0, livre - BYTES_DO_CABECALHO) / p.bytes_por_segundo / 60
            problemas.append(Problema("destino", "info", f"até parar: cabem ~{_minutos(minutos)} {onde}"))
        elif tamanho > livre:
            problemas.append(Problema("destino", "erro", f"não cabe {onde}: a captura tem {_mb(tamanho)}, e há "
                                                         f"{_mb(livre)} livres"))
        elif tamanho > FOLGA_DO_DISCO * livre:
            problemas.append(Problema("destino", "aviso", f"quase todo o espaço livre {onde}: {_mb(tamanho)} de "
                                                          f"{_mb(livre)}"))
    if no_computador and ctx.vazao_do_enlace is not None and ctx.vazao_do_enlace > 0:
        precisa = p.bytes_por_segundo
        if ctx.vazao_do_enlace < precisa:
            problemas.append(Problema("destino", "aviso", f"o enlace mediu {_mbs(ctx.vazao_do_enlace)}, menos que os "
                                                          f"{_mbs(precisa)} da captura: o ler_adc vai ficar para trás "
                                                          "e perder amostras. Prefira o cartão"))
        elif ctx.vazao_do_enlace < FOLGA_DO_ENLACE * precisa:
            problemas.append(Problema("destino", "aviso", f"o enlace mediu {_mbs(ctx.vazao_do_enlace)}, menos que o "
                                                          f"dobro dos {_mbs(precisa)} da captura: pouca folga para "
                                                          "um soluço do cabo"))
    if not no_computador and p.arquivo_no_cartao:
        nome = p.arquivo_no_cartao
        if not _PADRAO_DO_ARQUIVO.match(nome) or len(nome.encode()) > 255:
            problemas.append(Problema("arquivo", "erro", "o nome no cartão: letras, dígitos, '_', '-', '+' e '.', "
                                                         "terminado em .bin, sem pastas"))
        elif nome in ctx.capturas_no_cartao:
            problemas.append(Problema("arquivo", "erro", f"já existe {nome} no cartão: o ler_adc gravaria por cima"))
    return problemas


def _validar_avancado(p: PedidoDeCaptura) -> list[Problema]:
    problemas = []
    if p.spi not in MODOS_SPI:
        problemas.append(Problema("spi", "erro", f"o SPI '{p.spi}' não existe: use o rápido (fase A, B ou C) ou o "
                                                 "lento"))
    if len(p.atrasos_cs) != 3 or not all(isinstance(a, int) and 1 <= a <= ATRASO_CS_MAXIMO for a in p.atrasos_cs):
        problemas.append(Problema("atrasos", "erro", f"as esperas do CS são três inteiros de 1 a {ATRASO_CS_MAXIMO} "
                                                     "(passos de 10 ns)"))
    return problemas


def _mb(n: float) -> str:
    return f"{n / 1e9:.2f} GB" if n >= 1e9 else f"{n / 1e6:.0f} MB"


def _mbs(n: float) -> str:
    return f"{n / 1e6:.2f} MB/s"


def _minutos(m: float) -> str:
    return f"{m / 60:.1f} h" if m >= 120 else f"{m:.0f} min"


# ------------------------------------------------------------------ os modelos de captura (o projeto)


def para_dict(p: PedidoDeCaptura) -> dict:
    """O pedido num ``dict`` de JSON (um modelo de captura no ``.shproj``)."""
    return {
        "canais": [{"numero": c.numero, "grandeza": c.grandeza, "sonda": c.sonda, "faixa_v": c.faixa_v,
                    "ganho": c.ganho} for c in p.canais],
        "taxa_hz": p.taxa_hz,
        "duracao_s": p.duracao_s,
        "blocos": p.blocos,
        "titulo": p.titulo,
        "descricao": p.descricao,
        "destino": p.destino,
        "arquivo_no_cartao": p.arquivo_no_cartao,
        "spi": p.spi,
        "atrasos_cs": list(p.atrasos_cs),
        "forcar_taxa": p.forcar_taxa,
    }


def de_dict(dados) -> PedidoDeCaptura:
    """O pedido de :func:`para_dict`; ``ValueError`` com o campo, num que não tem a forma certa. Um campo que falta
    fica com o padrão; os valores fora das regras passam (a :func:`validar` os mostra no formulário)."""
    if not isinstance(dados, dict):
        raise ValueError("o modelo de captura não é um objeto")
    padrao = PedidoDeCaptura()

    def campo(nome, tipos, valor_padrao):
        valor = dados.get(nome, valor_padrao)
        if isinstance(valor, bool) and bool not in tipos:
            raise ValueError(f"o campo '{nome}' do modelo de captura tem um tipo errado")
        if not isinstance(valor, tipos):
            raise ValueError(f"o campo '{nome}' do modelo de captura tem um tipo errado")
        return valor

    canais_brutos = campo("canais", (list,), [])
    canais = []
    for bruto in canais_brutos:
        if not isinstance(bruto, dict) or isinstance(bruto.get("numero"), bool) or \
                not isinstance(bruto.get("numero"), int):
            raise ValueError("um canal do modelo de captura não tem o número")
        ganho = bruto.get("ganho")
        faixa = bruto.get("faixa_v", FAIXA_PADRAO_V)
        if (ganho is not None and (isinstance(ganho, bool) or not isinstance(ganho, (int, float)))) or \
                isinstance(faixa, bool) or not isinstance(faixa, (int, float)) or \
                not isinstance(bruto.get("grandeza", GRANDEZA_PADRAO), str) or \
                not isinstance(bruto.get("sonda", ""), str):
            raise ValueError(f"o canal {bruto['numero']} do modelo de captura tem um campo com o tipo errado")
        canais.append(Canal(bruto["numero"], bruto.get("grandeza", GRANDEZA_PADRAO), bruto.get("sonda", ""),
                            float(faixa), float(ganho) if ganho is not None else None))
    duracao = campo("duracao_s", (int, float, type(None)), None)
    atrasos = campo("atrasos_cs", (list,), list(padrao.atrasos_cs))
    if len(atrasos) != 3 or any(isinstance(a, bool) or not isinstance(a, int) for a in atrasos):
        raise ValueError("o campo 'atrasos_cs' do modelo de captura são três inteiros")
    return PedidoDeCaptura(
        canais=tuple(canais) if "canais" in dados else padrao.canais,
        taxa_hz=campo("taxa_hz", (int,), padrao.taxa_hz),
        duracao_s=float(duracao) if duracao is not None else None,
        blocos=campo("blocos", (int,), padrao.blocos),
        titulo=campo("titulo", (str,), ""),
        descricao=campo("descricao", (str,), ""),
        destino=campo("destino", (str,), padrao.destino),
        arquivo_no_cartao=campo("arquivo_no_cartao", (str,), ""),
        spi=campo("spi", (str,), padrao.spi),
        atrasos_cs=tuple(atrasos),
        forcar_taxa=campo("forcar_taxa", (bool,), False),
    )
