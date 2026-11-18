"""O ao vivo da captura para o computador (docs/gui-plan.md, 11.5; a F4.4): a cada bloco inteiro no ``.parcial``, os
últimos 50 ms de cada canal e o espectro dele, calculados numa thread pela ``api`` do motor.

**De bloco em bloco:** a saída contínua entrega um bloco de cada vez (2,6 s a 400 kS/s), e o ao vivo anda com ela.
:func:`calcular_quadro` abre o que chegou (``api.abrir_ao_vivo``: o cabeçalho provisório e os blocos inteiros, nas
unidades de cada canal, como o ``abrir_captura``) e, de cada canal, mede o bloco mais recente: o fim dele (o sinal) e
o Welch dele (o espectro), que entra na **média em potência dos últimos** :data:`BLOCOS_NA_MEDIA` **blocos** (o
espectro mostrado). As contas são as da Análise, sem a correção da sonda (o ao vivo é para ver a bancada).

**Uma conta por vez** (:class:`AoVivo`): um bloco que chega com a anterior ainda rodando espera, e só o mais recente
é calculado (um disco lento não acumula contas atrasadas).
"""

from __future__ import annotations

import logging
import math
import time
from collections import deque
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PySide6.QtCore import QObject, Signal
from shiboken6 import isValid
from supraharmonicos import api

log = logging.getLogger(__name__)

JANELA_DO_SINAL_S = 0.05
BLOCOS_NA_MEDIA = 8
PARAMETROS_DO_ESPECTRO = api.ParametrosEspectro(metodo="welch", modo="tom")


@dataclass(frozen=True)
class CanalAoVivo:
    """Um canal no último bloco: o sinal do fim dele (``tempo_s`` de -50 ms a 0, o fim do bloco) e o espectro, a
    média dos últimos ``na_media`` blocos (em dB na unidade do canal, o modo tom do Welch)."""

    numero: int
    posicao: int
    grandeza: str
    unidade: str
    taxa_hz: float
    tempo_s: np.ndarray
    sinal: np.ndarray
    freqs_hz: np.ndarray
    db: np.ndarray
    na_media: int


@dataclass(frozen=True)
class QuadroAoVivo:
    blocos: int
    canais: tuple[CanalAoVivo, ...]
    segundos_da_conta: float

    def canal(self, numero: int) -> CanalAoVivo | None:
        return next((c for c in self.canais if c.numero == numero), None)


def calcular_quadro(caminho: Path, blocos: int, historico: dict[int, deque], *, janela_s: float = JANELA_DO_SINAL_S,
                    na_media: int = BLOCOS_NA_MEDIA, sondas_dir: Path | None = None) -> QuadroAoVivo:
    """O quadro do bloco ``blocos`` (o último inteiro) de ``caminho``. ``historico`` guarda, por canal, as potências
    dos últimos blocos (quem chama o passa de novo a cada quadro; um espectro de outro tamanho recomeça a média)."""
    t0 = time.perf_counter()
    captura = api.abrir_ao_vivo(caminho, blocos, sondas_dir=sondas_dir)
    por_bloco = captura.cabecalho.samples_per_buffer
    k = len(captura.canais)
    canais = []
    for c in captura.canais:
        fim = len(c.amostras)
        # As amostras do último bloco neste canal: o bloco b tem as posições [b·S, (b+1)·S) do arquivo, e a amostra i
        # é do canal da posição i % k.
        inicio = math.ceil(((blocos - 1) * por_bloco - c.posicao) / k)
        sinal = api.sinal_do_canal(captura, c.numero, inicio, fim)
        n = min(len(sinal), max(2, round(janela_s * c.taxa_hz)))
        trecho = np.asarray(sinal[-n:], dtype=np.float64)
        tempo = (np.arange(n, dtype=np.float64) - (n - 1)) / c.taxa_hz
        espectro = api.espectro(sinal, c.taxa_hz, PARAMETROS_DO_ESPECTRO)
        potencia = np.power(10.0, espectro.db / 10.0)
        anteriores = historico.setdefault(c.numero, deque(maxlen=na_media))
        if anteriores and len(anteriores[-1]) != len(potencia):
            anteriores.clear()
        anteriores.append(potencia)
        media = 10.0 * np.log10(np.maximum(np.mean(anteriores, axis=0), np.finfo(np.float64).tiny))
        canais.append(CanalAoVivo(c.numero, c.posicao, c.nome_grandeza, c.unidade, c.taxa_hz, tempo, trecho,
                                  espectro.freqs_hz, media, len(anteriores)))
    return QuadroAoVivo(blocos, tuple(canais), time.perf_counter() - t0)


class AoVivo(QObject):
    """Os quadros de uma captura: :meth:`comecar` com o ``.parcial``; :meth:`bloco` a cada bloco inteiro a mais (o
    ``Progresso.blocos``); ``atualizou`` com cada :class:`QuadroAoVivo`. :meth:`parar` larga a captura (uma conta em
    curso termina e é descartada)."""

    atualizou = Signal(object)
    falhou = Signal(str)
    _pronto = Signal(int, object, object)                # (a geração, o quadro, o erro), da thread da conta

    def __init__(self, parent: QObject | None = None, *, sondas_dir: Path | None = None):
        super().__init__(parent)
        self.sondas_dir = sondas_dir
        self.caminho: Path | None = None
        self.quadro: QuadroAoVivo | None = None
        self._geracao = 0
        self._historico: dict[int, deque] = {}
        self._pendente: int | None = None
        self._calculando = False
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ao_vivo")
        self._pronto.connect(self._ao_ficar_pronto)
        self.destroyed.connect(lambda *_: self._executor.shutdown(wait=False, cancel_futures=True))

    def comecar(self, caminho: Path) -> None:
        self._geracao += 1
        self.caminho, self.quadro = Path(caminho), None
        self._historico = {}
        self._pendente, self._calculando = None, False

    def parar(self) -> None:
        self._geracao += 1
        self.caminho = None
        self._pendente, self._calculando = None, False

    def bloco(self, blocos: int) -> None:
        if self.caminho is None or blocos < 1:
            return
        self._pendente = blocos
        self._proximo()

    def _proximo(self) -> None:
        if self._calculando or self._pendente is None or self.caminho is None:
            return
        blocos, self._pendente = self._pendente, None
        self._calculando = True
        geracao, caminho, historico = self._geracao, self.caminho, self._historico
        futuro = self._executor.submit(calcular_quadro, caminho, blocos, historico, sondas_dir=self.sondas_dir)
        futuro.add_done_callback(lambda f: self._da_thread(geracao, f))

    def _da_thread(self, geracao: int, futuro: Future) -> None:
        if not isValid(self) or futuro.cancelled():
            return
        erro = futuro.exception()
        try:
            self._pronto.emit(geracao, None if erro else futuro.result(), erro)
        except RuntimeError:                    # apagado entre o isValid e o emit
            pass

    def _ao_ficar_pronto(self, geracao: int, quadro: QuadroAoVivo | None, erro: BaseException | None) -> None:
        if geracao != self._geracao:
            return
        self._calculando = False
        if erro is not None:
            log.warning("o ao vivo não deu para o bloco: %s", erro)
            self.falhou.emit(str(erro))
        else:
            self.quadro = quadro
            self.atualizou.emit(quadro)
        self._proximo()
