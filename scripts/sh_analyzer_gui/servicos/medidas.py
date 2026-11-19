"""As medidas da região (docs/gui-plan.md, 3.4 e 9.4): de cada traço visível de uma vista, entre os cursores ou na
janela de tempo, calculadas **das amostras** pela ``api`` (``medir_regiao``), nunca do desenho.

Num traço com transformações, as medidas são as do sinal transformado, o mesmo que a tela mostra: a cadeia roda na
região com a margem dela (``Cadeia.previa``), em ``float64`` a partir das amostras do ADC, e a ``api`` mede o
resultado (``medir_sinal``). Longe das bordas da captura, é o traço inteiro transformado (``dados/cadeia.py``).

Um traço com o tempo próprio (a escala destravada, ``graficos/escalas.py``) mede o trecho **dele** que aparece na
região da tela (``PedidoDeMedida.por_traco``), e a medida guarda esse trecho (``MedidaDoTraco.inicio_s``/``fim_s``).

Em segundo plano (uma região grande leva o filtro da fundamental): cada pedido cancela o anterior, e só o resultado
do mais recente chega (``prontas``). **Um traço transformado numa região maior que a prévia** (:data:`LIMITE_DA_PREVIA
<sh_analyzer_gui.servicos.materializar.LIMITE_DA_PREVIA>`) faz a conta do tamanho da materialização dele: o pedido
vai para a fila das pesadas (``GerenciadorDeTarefas``) e espera a vez, em vez de disputar o GIL com ela e com a
interface (o desenho engasgava). Até lá, a tabela fica com as medidas anteriores, e o resumo diz de que região são. Uma região com mais de :data:`LIMITE_DE_AMOSTRAS` amostras não é medida (a
conta leria tudo para a memória): a tabela diz para aproximar o zoom ou usar os cursores.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field, replace

from PySide6.QtCore import QObject, Signal
from supraharmonicos.api import ErroSHAN, MedidasDaRegiao, medir_regiao, medir_sinal

from ..dados import materializacao as mat
from ..modelo.objetos import Projeto, Traco, Vista
from .materializar import LIMITE_DA_PREVIA
from .tarefas import GerenciadorDeTarefas, Tarefa

LIMITE_DE_AMOSTRAS = 20_000_000
LIMITE_DA_F1_NA_JANELA = 1_000_000
"""Sem os cursores (a janela visível, medida a cada parada do zoom), a f1 só até este tamanho: ela é a conta cara
(~1 s a cada 4 M amostras, segurando o GIL aos pedaços) e rodaria a cada zoom. Entre os cursores, vale o limite
geral."""
AVISO_DA_F1 = "f₁ calculada até 1 M amostras na janela visível: aproxime o zoom ou use os cursores"


@dataclass(frozen=True)
class MedidaDoTraco:
    traco: Traco
    inicio_s: float
    fim_s: float
    medidas: MedidasDaRegiao | None
    erro: str = ""
    delta_y: float | None = None         # o valor no cursor 2 menos o do cursor 1 (só com os cursores)
    unidade: str = ""


@dataclass(frozen=True)
class PedidoDeMedida:
    """A região da vista (s) e, dos traços com o tempo próprio, a região de cada um no tempo dele."""

    vista: Vista
    inicio_s: float
    fim_s: float
    dos_cursores: bool
    por_traco: Mapping[Traco, tuple[float, float]] = field(default_factory=dict)

    def regiao_de(self, traco: Traco) -> tuple[float, float]:
        return self.por_traco.get(traco, (self.inicio_s, self.fim_s))


def _indice(t: float, t0: float, taxa: float, n: int) -> int:
    return int(min(max(round((t - t0) * taxa), 0), n))


class ServicoDeMedidas(QObject):
    """``prontas(pedido, medidas)``: as medidas do pedido mais recente, uma por traço visível."""

    prontas = Signal(object, object)

    def __init__(self, tarefas: GerenciadorDeTarefas, parent: QObject | None = None, materializacoes=None):
        super().__init__(parent)
        self.tarefas = tarefas
        self.materializacoes = materializacoes         # o contexto das cadeias (a média do canal), se houver
        self._atual: Tarefa | None = None
        self._pedido: PedidoDeMedida | None = None

    def medir(self, projeto: Projeto, pedido: PedidoDeMedida) -> Tarefa | None:
        if self._atual is not None:
            self._atual.cancelar()
        self._pedido = pedido
        planos = []
        for traco in pedido.vista.tracos:
            r = traco.receita
            if not r.visivel:
                continue
            try:
                fonte = projeto.fonte(r.fonte)
            except KeyError:
                continue
            if fonte.esta_ausente:
                continue
            canal = fonte.canal(r.canal)
            n = len(canal.amostras)
            inicio, fim = pedido.regiao_de(traco)
            i0 = _indice(inicio, r.deslocamento_s, canal.taxa_hz, n)
            i1 = _indice(fim, r.deslocamento_s, canal.taxa_hz, n)
            planos.append((traco, fonte.fonte.captura, r, i0, i1, n, r.unidade_de(canal.unidade),
                           self._contexto(fonte, r)))
        if not planos:
            self._atual = None
            self.prontas.emit(pedido, [])
            return None

        def medir_todos(progresso, cancelado):
            resultados = []
            for k, (traco, captura, r, i0, i1, n, unidade, ctx) in enumerate(planos):
                if cancelado():
                    return None
                erro, medidas, delta = "", None, None
                if i1 - i0 > LIMITE_DE_AMOSTRAS:
                    erro = f"região grande demais ({i1 - i0} amostras): aproxime o zoom ou use os cursores"
                else:
                    com_f1 = pedido.dos_cursores or i1 - i0 <= LIMITE_DA_F1_NA_JANELA
                    try:
                        if ctx is None:
                            medidas = medir_regiao(captura, r.canal, i0, i1, ganho=r.ganho, offset=r.offset,
                                                   fundamental=com_f1)
                        else:
                            sinal = r.cadeia.previa(mat.leitor_do_canal(captura, r.canal), n, i0, i1, ctx).valores
                            medidas = medir_sinal(sinal * r.ganho + r.offset, ctx.taxa_hz, fundamental=com_f1)
                    except ErroSHAN as e:
                        erro = str(e)
                    else:
                        if not com_f1:
                            medidas = replace(medidas, problema_f1=AVISO_DA_F1)
                if pedido.dos_cursores:
                    a, b = min(i0, n - 1), min(i1, n - 1)
                    if 0 <= a and 0 <= b:
                        pontos = medir_pontos(captura, r, (a, b), ctx, n)
                        delta = pontos[1] - pontos[0]
                resultados.append(MedidaDoTraco(traco, *pedido.regiao_de(traco), medidas, erro, delta, unidade))
                progresso((k + 1) / len(planos))
            return resultados

        pesada = any(ctx is not None and i1 - i0 > LIMITE_DA_PREVIA for _t, _c, _r, i0, i1, _n, _u, ctx in planos)
        tarefa = self.tarefas.iniciar("Medidas", medir_todos, "medidas", mostrar=False, pesada=pesada,
                                      ao_terminar=self._terminou)
        self._atual = tarefa
        return tarefa

    def _contexto(self, fonte, receita):
        """O contexto da cadeia do traço, ou None sem cadeia (as medidas do canal como ele é)."""
        if receita.cadeia.vazia:
            return None
        if self.materializacoes is not None:
            return self.materializacoes.contexto(fonte, receita.canal)
        return mat.contexto_do_canal(fonte.canal(receita.canal))

    def _terminou(self, tarefa: Tarefa) -> None:
        if tarefa is not self._atual:
            return                                # um pedido antigo: o mais recente vale
        self._atual = None
        if tarefa.estado == "concluida" and tarefa.resultado is not None:
            self.prontas.emit(self._pedido, tarefa.resultado)


def medir_pontos(captura, receita, indices, contexto=None, n_amostras: int | None = None) -> list[float]:
    """O valor do traço (com a cadeia, o ganho e o offset) em cada amostra de ``indices``."""
    from supraharmonicos.api import sinal_do_canal

    def valor(i: int) -> float:
        if contexto is None:
            return float(sinal_do_canal(captura, receita.canal, i, i + 1)[0])
        return float(receita.cadeia.previa(mat.leitor_do_canal(captura, receita.canal), n_amostras, i, i + 1,
                                           contexto).valores[0])

    return [valor(i) * receita.ganho + receita.offset if i >= 0 else math.nan for i in indices]


def valores_no_trecho(fonte, receita, inicio: float, fim: float, contexto=None):
    """Os valores do traço (com a cadeia, o ganho e o offset) entre ``inicio`` e ``fim`` (s, no tempo da vista, com
    o deslocamento do traço), o tempo na vista da primeira amostra e a taxa: ``(valores, t0, taxa)``. ``contexto``:
    o da cadeia (``None`` sem cadeia). A primeira amostra é a que está em ``inicio`` ou logo depois, e a última a que
    está em ``fim`` ou logo antes; fora da captura, o trecho encolhe (pode ficar vazio)."""
    from supraharmonicos.api import sinal_do_canal

    canal = fonte.canal(receita.canal)
    n, taxa, deslocamento = len(canal.amostras), canal.taxa_hz, receita.deslocamento_s
    i0 = min(max(math.ceil((inicio - deslocamento) * taxa - 1e-9), 0), n)
    i1 = min(max(math.floor((fim - deslocamento) * taxa + 1e-9) + 1, i0), n)
    captura = fonte.fonte.captura
    if contexto is None or receita.cadeia.vazia:
        valores = sinal_do_canal(captura, receita.canal, i0, i1)
    else:
        valores = receita.cadeia.previa(mat.leitor_do_canal(captura, receita.canal), n, i0, i1, contexto).valores
    return valores * receita.ganho + receita.offset, deslocamento + i0 / taxa, taxa
