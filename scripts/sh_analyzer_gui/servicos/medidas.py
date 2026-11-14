"""As medidas da região (docs/gui-plan.md, 3.4 e 9.4): de cada traço visível de uma vista, entre os cursores ou na
janela de tempo, calculadas **das amostras** pela ``api`` (``medir_regiao``), nunca do desenho.

Em segundo plano (uma região grande leva o filtro da fundamental): cada pedido cancela o anterior, e só o resultado
do mais recente chega (``prontas``). Uma região com mais de :data:`LIMITE_DE_AMOSTRAS` amostras não é medida (a
conta leria tudo para a memória): a tabela diz para aproximar o zoom ou usar os cursores.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace

from PySide6.QtCore import QObject, Signal
from supraharmonicos.api import ErroSHAN, MedidasDaRegiao, medir_regiao

from ..modelo.objetos import Projeto, Traco, Vista
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
    vista: Vista
    inicio_s: float
    fim_s: float
    dos_cursores: bool


def _indice(t: float, t0: float, taxa: float, n: int) -> int:
    return int(min(max(round((t - t0) * taxa), 0), n))


class ServicoDeMedidas(QObject):
    """``prontas(pedido, medidas)``: as medidas do pedido mais recente, uma por traço visível."""

    prontas = Signal(object, object)

    def __init__(self, tarefas: GerenciadorDeTarefas, parent: QObject | None = None):
        super().__init__(parent)
        self.tarefas = tarefas
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
            i0 = _indice(pedido.inicio_s, r.deslocamento_s, canal.taxa_hz, n)
            i1 = _indice(pedido.fim_s, r.deslocamento_s, canal.taxa_hz, n)
            planos.append((traco, fonte.fonte.captura, r, i0, i1, n, canal.unidade))
        if not planos:
            self._atual = None
            self.prontas.emit(pedido, [])
            return None

        def medir_todos(progresso, cancelado):
            resultados = []
            for k, (traco, captura, r, i0, i1, n, unidade) in enumerate(planos):
                if cancelado():
                    return None
                erro, medidas, delta = "", None, None
                if i1 - i0 > LIMITE_DE_AMOSTRAS:
                    erro = f"região grande demais ({i1 - i0} amostras): aproxime o zoom ou use os cursores"
                else:
                    com_f1 = pedido.dos_cursores or i1 - i0 <= LIMITE_DA_F1_NA_JANELA
                    try:
                        medidas = medir_regiao(captura, r.canal, i0, i1, ganho=r.ganho, offset=r.offset,
                                               fundamental=com_f1)
                    except ErroSHAN as e:
                        erro = str(e)
                    else:
                        if not com_f1:
                            medidas = replace(medidas, problema_f1=AVISO_DA_F1)
                if pedido.dos_cursores:
                    a, b = min(i0, n - 1), min(i1, n - 1)
                    if 0 <= a and 0 <= b:
                        pontos = medir_pontos(captura, r, (a, b))
                        delta = pontos[1] - pontos[0]
                resultados.append(MedidaDoTraco(traco, pedido.inicio_s, pedido.fim_s, medidas, erro, delta, unidade))
                progresso((k + 1) / len(planos))
            return resultados

        tarefa = self.tarefas.iniciar("Medidas", medir_todos, "medidas", mostrar=False)
        tarefa.terminou.connect(self._terminou)
        self._atual = tarefa
        return tarefa

    def _terminou(self, tarefa: Tarefa) -> None:
        if tarefa is not self._atual:
            return                                # um pedido antigo: o mais recente vale
        self._atual = None
        if tarefa.estado == "concluida" and tarefa.resultado is not None:
            self.prontas.emit(self._pedido, tarefa.resultado)


def medir_pontos(captura, receita, indices) -> list[float]:
    """O valor do traço (com o ganho e o offset) em cada amostra de ``indices``."""
    from supraharmonicos.api import sinal_do_canal

    return [float(sinal_do_canal(captura, receita.canal, i, i + 1)[0]) * receita.ganho + receita.offset
            if i >= 0 else math.nan for i in indices]
