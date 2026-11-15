"""Os traços com transformações, em segundo plano (docs/gui-plan.md, 7.2 e 8.3): a materialização de cada um e a
prévia da janela visível enquanto ela não fica pronta.

**Uma materialização por conteúdo:** os traços com a mesma fonte, o mesmo canal e as mesmas etapas ligadas dividem
um :class:`EstadoDaMaterializacao` (duas vistas do mesmo traço fazem a conta uma vez). Quem desenha
:meth:`ServicoDeMaterializacao.acompanhar` o traço e recebe o estado; ``mudou(estado)`` sai a cada passo (o começo já
feito, o progresso, o fim, um erro). Um estado sem ninguém acompanhando é cancelado: mudar o corte de um filtro três
vezes seguidas deixa só a última conta rodando.

**As materializações rodam uma de cada vez** (a fila das pesadas do :class:`GerenciadorDeTarefas`): duas ao mesmo
tempo engasgavam o desenho, disputando o GIL com a interface. As que esperam a vez ficam :attr:`na_fila
<EstadoDaMaterializacao.na_fila>`, e ``mudou`` sai quando cada uma começa.

**A média do canal** (o "remover o DC") é calculada na primeira materialização que precisa dela e fica guardada.

**A prévia** (:meth:`ServicoDeMaterializacao.previa`) roda num conjunto de threads só dela, de uma thread: uma
materialização longa não a deixa na fila, e cada pedido novo de um traço cancela o anterior (vale o mais recente).

Os resultados chegam à interface pela fila de eventos (as tarefas terminam noutra thread).
"""

from __future__ import annotations

from collections.abc import Callable, Hashable
from pathlib import Path

import numpy as np
from PySide6.QtCore import QObject, Signal

from ..dados import materializacao as mat
from ..dados.avisos import avisos_do_traco
from ..dados.cadeia import Cadeia, ContextoDaCadeia
from ..dados.captura import Aviso
from ..dados.piramide import Piramide, construir
from ..modelo.objetos import FonteDoProjeto
from .tarefas import GerenciadorDeTarefas, Tarefa

LIMITE_DA_PREVIA = 1 << 20
"""A maior janela (em amostras, sem a margem) que a prévia calcula: ~115 ms com a correção de sonda e dois filtros.
Numa janela maior, o gráfico mostra o que a materialização já fez."""


class EstadoDaMaterializacao:
    """A materialização de uma fonte, um canal e uma cadeia, como a interface a vê (só na thread da interface)."""

    def __init__(self, fonte: FonteDoProjeto, numero: int, cadeia: Cadeia):
        self.fonte, self.numero, self.cadeia = fonte, numero, cadeia
        self.pronta: mat.Materializacao | None = None
        self.parcial: tuple[np.ndarray, Piramide] | None = None    # o começo já feito
        self.progresso: float | None = 0.0                          # None: parada (pronta, com erro ou cancelada)
        self.erro = ""
        self.tarefa: Tarefa | None = None
        self.usuarios: set[Hashable] = set()
        self._parcial_novo: tuple[np.ndarray, Piramide] | None = None   # escrito pela thread de trabalho

    @property
    def n_amostras(self) -> int:
        return len(self.fonte.canal(self.numero).amostras)

    @property
    def na_fila(self) -> bool:
        """A materialização espera a vez (outra roda antes dela)."""
        return self.tarefa is not None and self.tarefa.estado == "esperando"

    def __repr__(self) -> str:
        estado = "pronta" if self.pronta else f"erro: {self.erro}" if self.erro else f"{self.progresso}"
        return f"<Materialização {self.fonte.nome} canal {self.numero} [{self.cadeia.resumo()}]: {estado}>"


class Previa:
    """O resultado de uma prévia: os valores da janela ``[inicio, inicio + len(amostras))`` do canal e a pirâmide
    deles."""

    def __init__(self, inicio: int, amostras: np.ndarray, piramide: Piramide):
        self.inicio, self.amostras, self.piramide = inicio, amostras, piramide

    @property
    def fim(self) -> int:
        return self.inicio + len(self.amostras)


class ServicoDeMaterializacao(QObject):
    mudou = Signal(object)            # EstadoDaMaterializacao

    def __init__(self, tarefas: GerenciadorDeTarefas, cache: mat.CacheDeMaterializacoes | None = None,
                 parent: QObject | None = None):
        super().__init__(parent)
        self.tarefas = tarefas
        self.cache = cache or mat.CacheDeMaterializacoes()
        self.previas = GerenciadorDeTarefas(threads=1, parent=self)
        self._estados: dict[tuple, EstadoDaMaterializacao] = {}
        self._de_usuario: dict[Hashable, tuple] = {}
        self._estado_da_tarefa: dict[Tarefa, EstadoDaMaterializacao] = {}
        self._medias: dict[tuple[str, int], float] = {}
        self._carregar = mat.carregador_de_perfis()
        self._previa_de: dict[Hashable, Tarefa] = {}

    # ------------------------------------------------------------------ o contexto

    def contexto(self, fonte: FonteDoProjeto, numero: int) -> ContextoDaCadeia:
        """O contexto da cadeia de um traço deste canal (com a média, se já foi calculada)."""
        return mat.contexto_do_canal(fonte.canal(numero), self._medias.get((fonte.id, numero)), self._carregar)

    def media_conhecida(self, fonte: FonteDoProjeto, numero: int) -> float | None:
        return self._medias.get((fonte.id, numero))

    # ------------------------------------------------------------------ a materialização

    def acompanhar(self, usuario: Hashable, fonte: FonteDoProjeto, numero: int,
                   cadeia: Cadeia) -> EstadoDaMaterializacao | None:
        """O estado da materialização de ``cadeia`` neste canal, para ``usuario`` (um traço): começa a conta se for
        a primeira vez. ``None`` se a cadeia não tem etapa ligada (o traço é o canal como ele é). O que ``usuario``
        acompanhava antes é largado."""
        ligadas = Cadeia(cadeia.ligadas)
        chave = (fonte.id, numero, ligadas)
        if self._de_usuario.get(usuario) == chave:
            return self._estados[chave]
        self.largar(usuario)
        if ligadas.vazia:
            return None
        estado = self._estados.get(chave)
        if estado is None:
            estado = EstadoDaMaterializacao(fonte, numero, ligadas)
            self._estados[chave] = estado
            self._iniciar(estado)
        estado.usuarios.add(usuario)
        self._de_usuario[usuario] = chave
        return estado

    def largar(self, usuario: Hashable) -> None:
        """``usuario`` não precisa mais da materialização que acompanhava; sem ninguém, ela é cancelada."""
        self.cancelar_previa(usuario)
        chave = self._de_usuario.pop(usuario, None)
        estado = self._estados.get(chave) if chave is not None else None
        if estado is None:
            return
        estado.usuarios.discard(usuario)
        if not estado.usuarios:
            del self._estados[chave]
            if estado.tarefa is not None and estado.tarefa.ativa:
                estado.tarefa.cancelar()

    # ------------------------------------------------------------------ o cache

    def abertas(self) -> set[str]:
        """As chaves das materializações prontas que os traços usam."""
        return {e.pronta.chave for e in self._estados.values() if e.pronta is not None}

    def definir_cache(self, pasta: Path, limite_bytes: int) -> None:
        """A pasta e o limite do cache das materializações. Outra pasta é um cache novo (uma materialização que
        já está rodando termina no antigo, que a tarefa guardou); passar do limite apaga as menos usadas na hora
        (nunca as abertas nem as em construção)."""
        if Path(pasta) != self.cache.pasta:
            self.cache = mat.CacheDeMaterializacoes(pasta, limite_bytes)
        else:
            self.cache.limite_bytes = limite_bytes
        self.cache.aparar(manter=self.abertas())

    def limpar_cache(self) -> int:
        """Apaga as materializações do cache, menos as abertas e as em construção; devolve os bytes liberados."""
        return self.cache.limpar(manter=self.abertas())

    def estado_de(self, usuario: Hashable) -> EstadoDaMaterializacao | None:
        chave = self._de_usuario.get(usuario)
        return self._estados.get(chave) if chave is not None else None

    def avisos(self, traco, fonte: FonteDoProjeto | None, erro: str = "") -> tuple[Aviso, ...]:
        """Os avisos do chip de ``traco`` (``dados/avisos.py``): os do canal, os da cadeia neste canal, a
        integridade da captura e o erro da materialização dele (ou ``erro``, o da conta de quem desenha). Nada para
        uma fonte ausente (o chip já diz "ausente")."""
        if fonte is None or fonte.esta_ausente:
            return ()
        r = traco.receita
        try:
            canal = fonte.canal(r.canal)
        except KeyError as e:
            return (Aviso("erro", e.args[0]),)
        estado = self.estado_de(traco)
        erro = erro or (estado.erro if estado is not None else "")
        return avisos_do_traco(canal, r.cadeia, self.contexto(fonte, r.canal), integridade=fonte.integridade,
                               erro=erro)

    def _iniciar(self, estado: EstadoDaMaterializacao) -> None:
        fonte, numero, cadeia = estado.fonte, estado.numero, estado.cadeia
        origem = fonte.fonte
        captura, canal = origem.captura, fonte.canal(numero)
        n = len(canal.amostras)
        media = self._medias.get((fonte.id, numero))
        precisa = mat.precisa_da_media(cadeia) and media is None
        carregar, cache = self._carregar, self.cache

        def trabalho(progresso, cancelado):
            nonlocal media
            parte = 0.0
            if precisa:
                parte = 0.1                       # a média: uma passada só de leitura, mais rápida que a cadeia
                media = mat.media_do_canal(canal, progresso=lambda f: progresso(parte * f), cancelado=cancelado)
            ctx = mat.contexto_do_canal(canal, media, carregar)
            chave = mat.chave_da_materializacao(origem.chave, numero, cadeia, ctx)

            def parcial(amostras, piramide):
                estado._parcial_novo = (amostras, piramide)

            pronta = cache.obter(chave, cadeia, mat.leitor_do_canal(captura, numero), n, ctx,
                                 progresso=lambda f: progresso(parte + (1 - parte) * f), cancelado=cancelado,
                                 parcial=parcial)
            return pronta, media

        estado.tarefa = self.tarefas.iniciar(self.tr("Transformar {} (canal {}: {})").format(
            fonte.nome, numero, cadeia.resumo()), trabalho, fonte.id, pesada=True, ao_comecar=self._comecou,
            ao_terminar=self._terminou, ao_progredir=self._progrediu)
        self._estado_da_tarefa[estado.tarefa] = estado

    def _comecou(self, tarefa: Tarefa) -> None:
        estado = self._estado_da_tarefa.get(tarefa)
        if estado is not None and tarefa.ativa:
            self.mudou.emit(estado)

    def _progrediu(self, tarefa: Tarefa, fracao: float) -> None:
        estado = self._estado_da_tarefa.get(tarefa)
        if estado is None or not tarefa.ativa:
            return
        estado.progresso = fracao
        novo, estado._parcial_novo = estado._parcial_novo, None
        if novo is not None:
            estado.parcial = novo
        self.mudou.emit(estado)

    def _terminou(self, tarefa: Tarefa) -> None:
        estado = self._estado_da_tarefa.pop(tarefa, None)
        if estado is None:
            return
        estado.progresso, estado.parcial, estado._parcial_novo = None, None, None
        if tarefa.estado == "concluida":
            estado.pronta, media = tarefa.resultado
            if media is not None:
                self._medias[(estado.fonte.id, estado.numero)] = media
        elif tarefa.estado == "falhou":
            estado.erro = tarefa.erro or self.tr("a transformação falhou")
        self.mudou.emit(estado)

    # ------------------------------------------------------------------ a prévia

    def previa(self, usuario: Hashable, fonte: FonteDoProjeto, numero: int, cadeia: Cadeia, inicio: int, fim: int,
               ao_terminar: Callable[[Previa | None, str], None]) -> bool:
        """Calcula a cadeia na janela ``[inicio, fim)`` do canal (com a margem) e chama ``ao_terminar(previa, erro)``
        na thread da interface; um pedido novo de ``usuario`` cancela o anterior. Não pede nada (e devolve False)
        numa janela maior que :data:`LIMITE_DA_PREVIA`."""
        self.cancelar_previa(usuario)
        n = len(fonte.canal(numero).amostras)
        inicio, fim = max(0, int(inicio)), min(n, int(fim))
        if fim - inicio > LIMITE_DA_PREVIA or fim <= inicio:
            return False
        ler = mat.leitor_do_canal(fonte.fonte.captura, numero)
        ctx = self.contexto(fonte, numero)
        cadeia = Cadeia(cadeia.ligadas)

        def calcular(_progresso, cancelado):
            valores = cadeia.previa(ler, n, inicio, fim, ctx).valores
            if cancelado():
                return None
            return Previa(inicio, valores, construir(valores)[0])

        def terminou(tarefa: Tarefa) -> None:
            if self._previa_de.get(usuario) is tarefa:
                del self._previa_de[usuario]
            if tarefa.estado == "concluida" and tarefa.resultado is not None:
                ao_terminar(tarefa.resultado, "")
            elif tarefa.estado == "falhou":
                ao_terminar(None, tarefa.erro)

        self._previa_de[usuario] = self.previas.iniciar("Prévia", calcular, mostrar=False, ao_terminar=terminou)
        return True

    def cancelar_previa(self, usuario: Hashable) -> None:
        tarefa = self._previa_de.pop(usuario, None)
        if tarefa is not None:
            tarefa.cancelar()

    def encerrar(self, espera_ms: int = 10_000) -> bool:
        return self.previas.encerrar(espera_ms)

