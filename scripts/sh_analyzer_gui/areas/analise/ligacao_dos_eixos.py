"""Os eixos ligados entre as vistas da grade (AN-09): as vistas de tempo que aparecem andam juntas no tempo, e as de
espectro juntas na frequência (em Hz: uma na escala linear e outra na log mostram a mesma faixa). O zoom ou o pan de
uma leva as outras do mesmo tipo, a cada passo do gesto.

Ao ligar (ou a grade mudar), as outras vão para a janela da vista ativa (sem ela no grupo, a da primeira com dados):
ligadas, elas mostram o mesmo trecho desde o começo. Uma vista sem traço não manda nem recebe: o eixo dela não diz
nada. Os tempos são os da vista (o eixo comum, a partir do começo de cada captura com o deslocamento de cada traço):
duas capturas alinhadas (TR-07) ficam alinhadas também entre as vistas.
"""

from __future__ import annotations

from functools import partial

from PySide6.QtCore import QObject
from shiboken6 import isValid

from ...componentes.grade_de_vistas import AbasEmGrade
from .vista_espectro import VistaDeEspectro
from .vista_tempo import VistaDeTempo


def grupo_de(widget) -> str | None:
    """O eixo que ``widget`` divide com as outras células: ``"tempo"``, ``"frequencia"`` ou nenhum."""
    if isinstance(widget, VistaDeTempo):
        return "tempo"
    if isinstance(widget, VistaDeEspectro):
        return "frequencia"
    return None


def _janela(widget) -> tuple[float, float] | None:
    if isinstance(widget, VistaDeTempo):
        return widget.janela_de_tempo()
    return widget.faixa_de_frequencia()


def _mostrar(widget, inicio: float, fim: float) -> None:
    if isinstance(widget, VistaDeTempo):
        widget.mostrar_tempo(inicio, fim)
    else:
        widget.mostrar_frequencias(inicio, fim)


class LigacaoDosEixos(QObject):
    def __init__(self, grade: AbasEmGrade, parent: QObject | None = None):
        super().__init__(parent)
        self.grade = grade
        self.ligada = True
        self._conexoes: list[tuple[object, object]] = []
        self._propagando = False
        grade.celulasMudaram.connect(self.refazer)

    def ligar(self, ligar: bool) -> None:
        if ligar != self.ligada:
            self.ligada = ligar
            self.refazer()

    def ligados(self) -> list:
        """As vistas que andam juntas agora (as das células, com eixo a dividir), na ordem das células."""
        if not self.ligada or not isValid(self.grade):
            return []
        vistas = [w for w in self.grade.visiveis() if isValid(w) and grupo_de(w) is not None]
        grupos = [grupo_de(w) for w in vistas]
        return [w for w, g in zip(vistas, grupos) if grupos.count(g) > 1]

    def refazer(self) -> None:
        for sinal, alvo in self._conexoes:
            try:
                sinal.disconnect(alvo)
            except (RuntimeError, TypeError):
                pass                          # a vista já saiu
        self._conexoes = []
        ligados = self.ligados()
        for w in ligados:
            sinal = w.tempoMudou if grupo_de(w) == "tempo" else w.frequenciaMudou
            alvo = partial(self._mudou, w)
            sinal.connect(alvo)
            self._conexoes.append((sinal, alvo))
        ativa = self.grade.currentWidget()
        for grupo in ("tempo", "frequencia"):
            do_grupo = [w for w in ligados if grupo_de(w) == grupo and w.tem_dados]
            if do_grupo:
                referencia = ativa if ativa in do_grupo else do_grupo[0]
                janela = _janela(referencia)
                if janela is not None:
                    self._mudou(referencia, *janela)

    def _mudou(self, origem, inicio: float, fim: float) -> None:
        if self._propagando or not isValid(origem) or not origem.tem_dados:
            return
        self._propagando = True                # as outras mudam e avisam: o aviso delas não volta para cá
        try:
            grupo = grupo_de(origem)
            for w in self.ligados():
                if w is not origem and grupo_de(w) == grupo and w.tem_dados and _janela(w) != (inicio, fim):
                    _mostrar(w, inicio, fim)
        finally:
            self._propagando = False
