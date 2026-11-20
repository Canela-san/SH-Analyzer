"""A materialização de um traço (docs/gui-plan.md, 7.2): a captura inteira passada pela cadeia de transformações,
gravada no cache com a sua pirâmide, para o gráfico desenhar o traço transformado em qualquer zoom.

**O que vai para o disco:** as amostras transformadas em ``float32`` (``<chave>.f32``) e a pirâmide delas
(``<chave>.shpir``, o formato de ``cache.py``). O ``float32`` arredonda cada valor a 2⁻²⁴ dele mesmo: no fundo de
escala, 256 vezes abaixo de um LSB do ADC de 16 bits, e o arredondamento é relativo (um valor pequeno, depois de um
passa-altas, guarda a mesma precisão relativa). O cache não perde nada do que a captura tem, com metade do espaço do
``float64``. As contas de um trecho (as medidas, o espectro de uma região) refazem a cadeia em ``float64`` a partir das
amostras do ADC (``Cadeia.previa``); a materialização serve para desenhar e para as contas da captura inteira.

**A chave é o conteúdo** (:func:`chave_da_materializacao`): a captura (a chave do cache das pirâmides: o CRC das
amostras), o canal, a taxa, as etapas **ligadas** (desligar e religar uma etapa reaproveita o arquivo), o conteúdo de
cada perfil de sonda aplicado e a média do canal (se a cadeia remove o DC). Duas vistas com a mesma receita dividem o
arquivo; mudar o perfil de sonda no disco muda a chave.

**A gravação:** as amostras vão direto para o arquivo final, bloco a bloco (um arquivo mapeado não se renomeia no
Windows, e o gráfico lê o começo enquanto o fim ainda está sendo feito); a pirâmide, gravada de forma atômica no
fim, é a marca de pronto. Amostras sem pirâmide são de uma materialização interrompida, e são refeitas.

**O limite de tamanho** apaga as materializações menos usadas (o par de arquivos junto); ``limpar`` apaga todas.

Sem Qt; o motor só pela ``supraharmonicos.api``.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import supraharmonicos.api as api

from . import cache as arquivos
from .cadeia import BLOCO_PADRAO, Cadeia, ContextoDaCadeia, CorrecaoSonda, RemoverDC
from .piramide import BLOCO_BASE, ConstrutorIncremental, Piramide

FORMATO = 1
"""Muda quando muda o que a materialização calcula: os arquivos de antes deixam de valer."""
DTYPE = np.dtype("<f4")
EXTENSAO_DADOS = ".f32"
LIMITE_PADRAO_BYTES = 8 * 1024**3
AMOSTRAS_POR_LEITURA_DA_MEDIA = 1 << 24


def pasta_padrao() -> Path:
    """Ao lado das pirâmides das capturas: ~/.cache/sh-analyzer/materializacoes no Linux."""
    return arquivos.pasta_padrao().parent / "materializacoes"


# ------------------------------------------------------------------ o contexto de um canal


def carregador_de_perfis() -> Callable[[str], object]:
    """Um ``carregar_perfil`` que guarda os perfis já lidos (pelo caminho e pela data do arquivo): a prévia pede o
    perfil a cada janela, e o mesmo objeto deixa o cálculo da margem (e o aviso de "fora da faixa") valer uma vez."""
    lidos: dict[tuple[str, int], object] = {}

    def carregar(caminho: str):
        try:
            data = Path(caminho).stat().st_mtime_ns
        except OSError:
            data = 0
        chave = (str(caminho), data)
        if chave not in lidos:
            lidos[chave] = api.carregar_perfil(Path(caminho))
        return lidos[chave]

    return carregar


def contexto_do_canal(canal: api.CanalDaCaptura, media: float | None = None,
                      carregar_perfil: Callable[[str], object] | None = None, *,
                      captura: api.Captura | None = None) -> ContextoDaCadeia:
    """O contexto da cadeia de um traço deste canal: a taxa, o perfil que a captura registra, a média do canal e,
    com a captura, como ler os outros canais dela (a expressão)."""
    ler = None if captura is None else (lambda numero, a, b: api.sinal_do_canal(captura, numero, a, b))
    return ContextoDaCadeia(canal.taxa_hz, perfil_do_canal=canal.perfil, media=media,
                            problema_sonda=canal.problema_sonda,
                            carregar_perfil=carregar_perfil or carregador_de_perfis(),
                            ler_canal=ler, n_canais=len(captura.canais) if captura is not None else 0)


def leitor_do_canal(captura: api.Captura, numero: int) -> Callable[[int, int], np.ndarray]:
    """``ler(a, b)``: as amostras ``[a, b)`` do canal na unidade física, sem a correção de sonda (ela é uma etapa)."""
    return lambda a, b: api.sinal_do_canal(captura, numero, a, b)


def media_do_canal(canal: api.CanalDaCaptura, *, progresso: Callable[[float], None] | None = None,
                   cancelado: Callable[[], bool] | None = None,
                   amostras_por_leitura: int = AMOSTRAS_POR_LEITURA_DA_MEDIA) -> float:
    """A média do canal inteiro na unidade física (o "remover o DC"): a soma exata dos códigos (inteiros, num
    acumulador ``float64``, exato até 2⁵³) pela conversão afim do canal. Uma passada pelo arquivo, em pedaços."""
    n = len(canal.amostras)
    if n == 0:
        return 0.0
    soma = 0.0
    for inicio in range(0, n, amostras_por_leitura):
        if cancelado is not None and cancelado():
            raise api.Cancelado()
        fim = min(n, inicio + amostras_por_leitura)
        soma += float(np.add.reduce(np.asarray(canal.amostras[inicio:fim]), dtype=np.float64))
        if progresso is not None:
            progresso(fim / n)
    return soma / n * canal.escala + canal.deslocamento


def precisa_da_media(cadeia: Cadeia) -> bool:
    return any(isinstance(e, RemoverDC) for e in cadeia.ligadas)


# ------------------------------------------------------------------ a chave


def _identidade_do_perfil(perfil) -> str:
    texto = getattr(perfil, "texto_json", None)
    if texto:
        return "sha256:" + hashlib.sha256(texto.encode("utf-8")).hexdigest()
    return f"{getattr(perfil, 'id', '?')}@{getattr(perfil, 'caminho', '?')}"


def chave_da_materializacao(chave_da_fonte: str, canal: int, cadeia: Cadeia, contexto: ContextoDaCadeia) -> str:
    """A chave do conteúdo (ver o começo do módulo). Levanta ``api.ErroSHAN`` se um perfil escolhido não abre."""
    ligadas = cadeia.ligadas
    perfis = [None if (p := e.perfil_usado(contexto)) is None else _identidade_do_perfil(p)
              for e in ligadas if isinstance(e, CorrecaoSonda)]
    conteudo = {"formato": FORMATO, "fonte": chave_da_fonte, "canal": canal, "taxa": float(contexto.taxa_hz),
                "etapas": Cadeia(ligadas).para_lista(), "perfis": perfis,
                "media": float(contexto.media) if precisa_da_media(cadeia) and contexto.media is not None else None}
    texto = json.dumps(conteudo, sort_keys=True, ensure_ascii=True)
    return hashlib.sha256(texto.encode("ascii")).hexdigest()[:32]


# ------------------------------------------------------------------ a materialização


@dataclass(frozen=True, eq=False)
class Materializacao:
    """Um traço materializado: as amostras transformadas (``float32``, em memmap) e a pirâmide delas."""

    chave: str
    amostras: np.ndarray
    piramide: Piramide

    @property
    def n_amostras(self) -> int:
        return self.piramide.n_amostras


def materializar(cadeia: Cadeia, ler: Callable[[int, int], np.ndarray], n_amostras: int,
                 contexto: ContextoDaCadeia, destino: Path, *, bloco: int = BLOCO_PADRAO,
                 progresso: Callable[[float], None] | None = None, cancelado: Callable[[], bool] | None = None,
                 parcial: Callable[[np.ndarray, Piramide], None] | None = None,
                 intervalo_parcial_s: float = 0.5) -> Piramide:
    """Passa o canal inteiro pela cadeia, bloco a bloco (``Cadeia.em_blocos``), gravando as amostras em
    ``destino`` (``float32``) e montando a pirâmide. ``parcial(amostras, piramide)`` recebe, a cada
    ``intervalo_parcial_s`` segundos, o que já está pronto (o começo do traço): o gráfico o mostra enquanto o resto
    é feito. Devolve a pirâmide do traço inteiro; não a grava."""
    if bloco % BLOCO_BASE:
        raise ValueError(f"o bloco precisa ser múltiplo de {BLOCO_BASE} amostras (recebido {bloco})")
    destino = Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)
    saida = np.memmap(destino, dtype=DTYPE, mode="w+", shape=(max(n_amostras, 1),))
    construtor = ConstrutorIncremental(n_amostras, DTYPE)
    ultimo_parcial = time.monotonic()
    try:
        for inicio, valores in cadeia.em_blocos(ler, n_amostras, contexto, bloco=bloco, progresso=progresso,
                                                cancelado=cancelado):
            convertidos = valores.astype(DTYPE)
            saida[inicio:inicio + len(convertidos)] = convertidos
            construtor.acrescentar(convertidos)
            if parcial is not None and not construtor.completa and \
                    time.monotonic() - ultimo_parcial >= intervalo_parcial_s:
                saida.flush()
                parcial(saida, construtor.piramide())
                ultimo_parcial = time.monotonic()
        saida.flush()
    finally:
        del saida
    return construtor.piramide()


class CacheDeMaterializacoes:
    """As materializações dos traços numa pasta, pela chave do conteúdo, com limite de tamanho. As em construção
    (``em_construcao``) nunca são apagadas; as abertas, quem chama diz (``manter``)."""

    def __init__(self, pasta: Path | None = None, limite_bytes: int = LIMITE_PADRAO_BYTES):
        self.pasta = Path(pasta) if pasta is not None else pasta_padrao()
        self.limite_bytes = limite_bytes
        self.em_construcao = arquivos.EmConstrucao()

    def caminhos(self, chave: str) -> tuple[Path, Path]:
        """Onde ficam as amostras e a pirâmide de ``chave``."""
        return self.pasta / f"{chave}{EXTENSAO_DADOS}", self.pasta / f"{chave}{arquivos.EXTENSAO}"

    def abrir(self, chave: str, n_amostras: int) -> Materializacao | None:
        """A materialização do cache, se estiver completa e bater com o canal; senão, ``None`` (e o que houver de
        uma materialização incompleta ou inválida é apagado)."""
        dados, piramide_caminho = self.caminhos(chave)
        if not piramide_caminho.exists():
            return None
        try:
            piramide = arquivos.abrir(piramide_caminho)
            tamanho = dados.stat().st_size
        except (arquivos.PiramideInvalida, OSError):
            self._apagar(chave)
            return None
        if piramide.n_amostras != n_amostras or piramide.dtype != DTYPE or tamanho != max(n_amostras, 1) * 4:
            del piramide
            self._apagar(chave)
            return None
        for caminho in (dados, piramide_caminho):
            try:
                os.utime(caminho)          # a data de uso: o limite apaga as menos usadas
            except OSError:
                pass
        return Materializacao(chave, np.memmap(dados, dtype=DTYPE, mode="r", shape=(max(n_amostras, 1),))[:n_amostras],
                              piramide)

    def obter(self, chave: str, cadeia: Cadeia, ler: Callable[[int, int], np.ndarray], n_amostras: int,
              contexto: ContextoDaCadeia, *, progresso=None, cancelado=None, parcial=None,
              bloco: int = BLOCO_PADRAO) -> Materializacao:
        """A materialização de ``chave``: do cache, ou feita agora (:func:`materializar`), gravada e aberta."""
        with self.em_construcao.marcar([chave]):
            pronta = self.abrir(chave, n_amostras)
            if pronta is not None:
                if progresso is not None:
                    progresso(1.0)
                return pronta
            dados, piramide_caminho = self.caminhos(chave)
            piramide_caminho.unlink(missing_ok=True)
            try:
                piramide = materializar(cadeia, ler, n_amostras, contexto, dados, bloco=bloco, progresso=progresso,
                                        cancelado=cancelado, parcial=parcial)
                arquivos.gravar(piramide, piramide_caminho)        # a marca de pronto
            except BaseException:
                self._apagar(chave)
                raise
            self.aparar(manter={chave})
            aberta = self.abrir(chave, n_amostras)
            assert aberta is not None
            return aberta

    def _apagar(self, chave: str) -> None:
        for caminho in self.caminhos(chave):
            try:
                caminho.unlink(missing_ok=True)
            except OSError:            # no Windows, um arquivo mapeado não se apaga: fica para a próxima vez
                pass

    def _por_chave(self) -> dict[str, tuple[float, int]]:
        """Cada materialização na pasta: a data do último uso e o tamanho (os dois arquivos juntos)."""
        grupos: dict[str, tuple[float, int]] = {}
        if not self.pasta.is_dir():
            return grupos
        for caminho in self.pasta.iterdir():
            if caminho.suffix not in (EXTENSAO_DADOS, arquivos.EXTENSAO):
                continue
            try:
                estado = caminho.stat()
            except OSError:
                continue
            data, tamanho = grupos.get(caminho.stem, (0.0, 0))
            grupos[caminho.stem] = (max(data, estado.st_mtime), tamanho + estado.st_size)
        return grupos

    @property
    def tamanho_bytes(self) -> int:
        return sum(tamanho for _, tamanho in self._por_chave().values())

    def aparar(self, manter: set[str] = frozenset()) -> None:
        """Apaga as materializações menos usadas até o total caber no limite (nunca as de ``manter`` nem as em
        construção)."""
        grupos = self._por_chave()
        intocaveis = set(manter) | self.em_construcao.atuais()
        total = sum(tamanho for _, tamanho in grupos.values())
        for chave, (_, tamanho) in sorted(grupos.items(), key=lambda item: item[1][0]):
            if total <= self.limite_bytes:
                break
            if chave in intocaveis:
                continue
            self._apagar(chave)
            if not any(c.exists() for c in self.caminhos(chave)):
                total -= tamanho

    def limpar(self, manter: set[str] = frozenset()) -> int:
        """Apaga todas as materializações (menos as de ``manter``, abertas, e as em construção); devolve os bytes
        liberados."""
        antes = self.tamanho_bytes
        intocaveis = set(manter) | self.em_construcao.atuais()
        for chave in list(self._por_chave()):
            if chave not in intocaveis:
                self._apagar(chave)
        return antes - self.tamanho_bytes
