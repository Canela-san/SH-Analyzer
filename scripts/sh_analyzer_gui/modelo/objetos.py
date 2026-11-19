"""O estado observável do projeto (docs/gui-plan.md, 7.1 e 8.4): o projeto, as fontes, as vistas e os traços.

**Quem muda o estado são os comandos** (``comandos.py``), pela pilha de desfazer do projeto: os métodos que
começam com ``_`` são deles. Quem desenha só escuta os sinais.

**Os sinais sobem:** o traço avisa a vista (``Traco.mudou``), a vista avisa o projeto (``tracoEntrou``,
``tracoSaiu``, ``tracoMudou``). Um painel que mostra o projeto inteiro (a árvore, a legenda) escuta só o projeto. Os
repasses são de sinal para sinal, ligados no Qt, sem código Python no meio: nada roda num objeto meio destruído
quando a janela fecha.

**Quem é dono de quem:** os objetos não têm pai no Qt; o Python os mantém vivos enquanto alguém os usa (o projeto,
uma vista, um comando na pilha de desfazer). Um traço removido continua vivo dentro do comando que o removeu, pronto
para voltar.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from pathlib import Path

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QUndoStack
from shiboken6 import isValid

from ..dados.captura import CanalDaCaptura, Fonte
from ..dados.espectros import OPCOES_DO_TIPO
from ..dados.figura import Figura
from ..dados.projeto import TIPOS_DE_VISTA, FonteSalva, ModeloDeCaptura
from ..dados.receita import ReceitaDoTraco, proxima_cor


def novo_id() -> str:
    """Um identificador curto, único na prática, que vai para o arquivo de projeto."""
    return uuid.uuid4().hex[:12]


class Traco(QObject):
    """Um traço numa vista: a receita (``ReceitaDoTraco``) e nada de dados. ``mudou(traco, campos)`` diz quais
    campos da receita mudaram, para quem desenha refazer só o necessário (a cor não refaz a consulta)."""

    mudou = Signal(object, object)

    def __init__(self, receita: ReceitaDoTraco, id: str | None = None):
        super().__init__()
        self.id = id or novo_id()
        self._receita = receita

    @property
    def receita(self) -> ReceitaDoTraco:
        return self._receita

    @property
    def nome(self) -> str:
        return self._receita.nome

    def _definir(self, receita: ReceitaDoTraco) -> None:
        campos = self._receita.diferencas(receita)
        if campos:
            self._receita = receita
            self.mudou.emit(self, campos)

    def __repr__(self) -> str:
        return f"Traco({self.nome!r}, fonte={self._receita.fonte}, canal={self._receita.canal})"


class Vista(QObject):
    """Um gráfico (por enquanto, o de tempo) com os seus traços, em ordem (a da legenda)."""

    tracoEntrou = Signal(object, object, int)     # vista, traço, posição
    tracoSaiu = Signal(object, object, int)
    tracoMudou = Signal(object, object)           # traço, campos (o repasse do Traco.mudou)
    mudou = Signal(object, object)                # vista, campos

    def __init__(self, nome: str, tipo: str = "tempo", id: str | None = None, opcoes=None):
        super().__init__()
        if tipo not in TIPOS_DE_VISTA:
            raise ValueError(f"tipo de vista desconhecido: {tipo!r} (use {', '.join(TIPOS_DE_VISTA)})")
        if not nome.strip():
            raise ValueError("o nome da vista não pode ficar vazio")
        self.id = id or novo_id()
        self.tipo = tipo
        # As opções do espectro (``OpcoesDoEspectro``): o método, a escala, o trecho, a vista de tempo ligada...
        self._opcoes = (opcoes or OPCOES_DO_TIPO[tipo]()) if tipo in OPCOES_DO_TIPO else None
        self._nome = nome.strip()
        self._tracos: list[Traco] = []
        self._anotacoes: tuple = ()             # ``dados.anotacoes.Anotacao``: o texto, a seta, a região, a cota

    @property
    def nome(self) -> str:
        return self._nome

    @property
    def anotacoes(self) -> tuple:
        return self._anotacoes

    def _definir_anotacoes(self, anotacoes) -> None:
        anotacoes = tuple(anotacoes)
        if anotacoes != self._anotacoes:
            self._anotacoes = anotacoes
            self.mudou.emit(self, frozenset({"anotacoes"}))

    @property
    def tracos(self) -> tuple[Traco, ...]:
        return tuple(self._tracos)

    def indice(self, traco: Traco) -> int:
        return self._tracos.index(traco)

    def proxima_cor(self) -> int:
        """A cor de um traço novo nesta vista: a primeira posição livre da paleta."""
        return proxima_cor(t.receita.cor for t in self._tracos)

    def _inserir(self, traco: Traco, indice: int | None = None) -> int:
        if traco in self._tracos:
            raise ValueError(f"{traco!r} já está na vista {self.nome!r}")
        indice = len(self._tracos) if indice is None else max(0, min(indice, len(self._tracos)))
        self._tracos.insert(indice, traco)
        traco.mudou.connect(self.tracoMudou)
        self.tracoEntrou.emit(self, traco, indice)
        return indice

    def _retirar(self, traco: Traco) -> int:
        indice = self._tracos.index(traco)
        del self._tracos[indice]
        traco.mudou.disconnect(self.tracoMudou)
        self.tracoSaiu.emit(self, traco, indice)
        return indice

    @property
    def opcoes(self):
        return self._opcoes

    def _definir_opcoes(self, opcoes) -> None:
        if opcoes != self._opcoes:
            self._opcoes = opcoes
            self.mudou.emit(self, frozenset({"opcoes"}))

    def _definir_nome(self, nome: str) -> None:
        nome = nome.strip()
        if not nome:
            raise ValueError("o nome da vista não pode ficar vazio")
        if nome != self._nome:
            self._nome = nome
            self.mudou.emit(self, frozenset({"nome"}))

    def __repr__(self) -> str:
        return f"Vista({self.nome!r}, {len(self._tracos)} traços)"


class FonteDoProjeto(QObject):
    """Uma captura no projeto: a ``Fonte`` (a ``api`` do motor e a chave do cache) e, quando prontas, as pirâmides
    de cada canal (F1.4). ``id`` é o nome da fonte nas receitas dos traços.

    **Ausente** (``fonte is None``): o projeto lembra dela (``origem``, do arquivo de projeto), mas o arquivo não foi
    achado. Os traços dela ficam no projeto, sem desenho, e voltam quando a captura for localizada; ao salvar, ela
    é gravada como estava."""

    piramidesProntas = Signal(object)            # a fonte
    estadoMudou = Signal(object)                 # a fonte: a pirâmide andou, a integridade foi conferida

    INTEGRIDADES = ("pendente", "conferindo", "confere", "nao_confere", "sem_crc", "erro")

    def __init__(self, fonte: Fonte | None, id: str | None = None, *, origem: FonteSalva | None = None):
        super().__init__()
        if fonte is None and origem is None:
            raise ValueError("uma fonte ausente precisa da origem (a do arquivo de projeto)")
        self.id = id or (origem.id if origem is not None else novo_id())
        self.fonte = fonte
        self.origem = origem
        self.piramides: list | None = None
        self.progresso_da_piramide: float | None = None     # None: sem construção em andamento
        self.integridade = "pendente"

    @classmethod
    def ausente(cls, origem: FonteSalva) -> FonteDoProjeto:
        return cls(None, origem.id, origem=origem)

    @property
    def esta_ausente(self) -> bool:
        return self.fonte is None

    @property
    def nome(self) -> str:
        return self.fonte.nome if self.fonte is not None else self.origem.nome

    @property
    def caminho(self) -> Path:
        return self.fonte.caminho if self.fonte is not None else Path(self.origem.caminho_absoluto)

    @property
    def canais(self) -> tuple[CanalDaCaptura, ...]:
        return self.fonte.canais if self.fonte is not None else ()

    def canal(self, numero: int) -> CanalDaCaptura:
        """O canal pelo número do cabeçalho. Levanta ``KeyError`` se a captura não tiver esse canal."""
        for canal in self.fonte.canais:
            if canal.numero == numero:
                return canal
        raise KeyError(f"{self.nome} não tem o canal {numero}")

    def posicao_do_canal(self, numero: int) -> int:
        """A posição do canal na captura (a ordem das pirâmides)."""
        return self.fonte.canais.index(self.canal(numero))

    def definir_piramides(self, piramides: list) -> None:
        self.piramides = piramides
        self.progresso_da_piramide = None
        self.piramidesProntas.emit(self)
        self.estadoMudou.emit(self)

    def definir_progresso_da_piramide(self, fracao: float | None) -> None:
        self.progresso_da_piramide = fracao
        self.estadoMudou.emit(self)

    def definir_integridade(self, integridade: str) -> None:
        if integridade not in self.INTEGRIDADES:
            raise ValueError(f"integridade desconhecida: {integridade!r}")
        if integridade != self.integridade:
            self.integridade = integridade
            self.estadoMudou.emit(self)

    def __repr__(self) -> str:
        return f"FonteDoProjeto({self.nome!r})"


class Projeto(QObject):
    """O projeto: as fontes, as vistas e a pilha de desfazer. ``modificadoMudou(bool)`` acompanha a pilha: depois
    de salvar, ``pilha.setClean()``."""

    fonteEntrou = Signal(object, int)
    fonteSaiu = Signal(object, int)
    vistaEntrou = Signal(object, int)
    vistaSaiu = Signal(object, int)
    tracoEntrou = Signal(object, object, int)     # vista, traço, posição
    tracoSaiu = Signal(object, object, int)
    tracoMudou = Signal(object, object)           # traço, campos
    vistaMudou = Signal(object, object)           # vista, campos
    modificadoMudou = Signal(bool)
    nomeMudou = Signal(str)
    modelosMudaram = Signal()                     # os modelos de captura da Aquisição
    figurasMudaram = Signal()                     # as figuras (a área Figuras)

    def __init__(self, caminho: Path | None = None):
        super().__init__()
        self.caminho = Path(caminho) if caminho is not None else None
        self._fontes: list[FonteDoProjeto] = []
        self._vistas: list[Vista] = []
        self._modelos: list[ModeloDeCaptura] = []
        self._figuras: list[Figura] = []
        self.pilha = QUndoStack(self)
        self.pilha.cleanChanged.connect(self._limpo_mudou)

    # ------------------------------------------------------------------ leitura

    @property
    def nome(self) -> str:
        return self.caminho.stem if self.caminho is not None else "sem título"

    @property
    def modificado(self) -> bool:
        return not self.pilha.isClean()

    @property
    def fontes(self) -> tuple[FonteDoProjeto, ...]:
        return tuple(self._fontes)

    @property
    def vistas(self) -> tuple[Vista, ...]:
        return tuple(self._vistas)

    def fonte(self, id: str) -> FonteDoProjeto:
        for fonte in self._fontes:
            if fonte.id == id:
                return fonte
        raise KeyError(f"o projeto não tem a fonte {id!r}")

    def vista(self, id: str) -> Vista:
        for vista in self._vistas:
            if vista.id == id:
                return vista
        raise KeyError(f"o projeto não tem a vista {id!r}")

    @property
    def modelos_de_captura(self) -> tuple[ModeloDeCaptura, ...]:
        """Os modelos de captura (o formulário da Aquisição com um nome), na ordem em que foram guardados."""
        return tuple(self._modelos)

    @property
    def figuras(self) -> tuple[Figura, ...]:
        """As figuras do projeto (``dados/figura.py``: valores imutáveis; quem muda é o comando, trocando a inteira)."""
        return tuple(self._figuras)

    def figura(self, id: str) -> Figura:
        for figura in self._figuras:
            if figura.id == id:
                return figura
        raise KeyError(f"o projeto não tem a figura {id!r}")

    def modelo_de_captura(self, nome: str) -> ModeloDeCaptura | None:
        for modelo in self._modelos:
            if modelo.nome == nome:
                return modelo
        return None

    def tracos(self) -> Iterator[tuple[Vista, Traco]]:
        """Todos os traços de todas as vistas, com a vista de cada um."""
        for vista in self._vistas:
            for traco in vista.tracos:
                yield vista, traco

    def tracos_da_fonte(self, fonte_id: str) -> list[tuple[Vista, Traco]]:
        return [(v, t) for v, t in self.tracos() if t.receita.fonte == fonte_id]

    def cores_do_canal(self, fonte_id: str, canal: int) -> list[int]:
        """As cores (posições na paleta) dos traços deste canal, em todas as vistas: o ponto colorido da árvore."""
        return [t.receita.cor for _, t in self.tracos() if t.receita.fonte == fonte_id and t.receita.canal == canal]

    def definir_caminho(self, caminho: Path) -> None:
        """O arquivo do projeto (ao salvar como); o nome do projeto é o do arquivo."""
        self.caminho = Path(caminho)
        self.nomeMudou.emit(self.nome)

    # ------------------------------------------------------------------ para os comandos

    def _inserir_fonte(self, fonte: FonteDoProjeto, indice: int | None = None) -> int:
        if any(f.id == fonte.id for f in self._fontes):
            raise ValueError(f"a fonte {fonte.id!r} já está no projeto")
        indice = len(self._fontes) if indice is None else max(0, min(indice, len(self._fontes)))
        self._fontes.insert(indice, fonte)
        self.fonteEntrou.emit(fonte, indice)
        return indice

    def _retirar_fonte(self, fonte: FonteDoProjeto) -> int:
        indice = self._fontes.index(fonte)
        del self._fontes[indice]
        self.fonteSaiu.emit(fonte, indice)
        return indice

    def _inserir_vista(self, vista: Vista, indice: int | None = None) -> int:
        if vista in self._vistas:
            raise ValueError(f"{vista!r} já está no projeto")
        indice = len(self._vistas) if indice is None else max(0, min(indice, len(self._vistas)))
        self._vistas.insert(indice, vista)
        for sinal, repasse in self._repasses(vista):
            sinal.connect(repasse)
        self.vistaEntrou.emit(vista, indice)
        return indice

    def _retirar_vista(self, vista: Vista) -> int:
        indice = self._vistas.index(vista)
        del self._vistas[indice]
        for sinal, repasse in self._repasses(vista):
            sinal.disconnect(repasse)
        self.vistaSaiu.emit(vista, indice)
        return indice

    def _por_modelo(self, modelo: ModeloDeCaptura, indice: int | None = None) -> None:
        """Guarda ``modelo`` no lugar do de mesmo nome (ou em ``indice``, ou no fim)."""
        atual = [m.nome for m in self._modelos]
        if modelo.nome in atual:
            self._modelos[atual.index(modelo.nome)] = modelo
        else:
            indice = len(self._modelos) if indice is None else max(0, min(indice, len(self._modelos)))
            self._modelos.insert(indice, modelo)
        self.modelosMudaram.emit()

    def _tirar_modelo(self, nome: str) -> int:
        indice = [m.nome for m in self._modelos].index(nome)
        del self._modelos[indice]
        self.modelosMudaram.emit()
        return indice

    def _por_figura(self, figura: Figura, indice: int | None = None) -> None:
        """Guarda ``figura`` no lugar da de mesmo id (ou em ``indice``, ou no fim)."""
        atual = [f.id for f in self._figuras]
        if figura.id in atual:
            self._figuras[atual.index(figura.id)] = figura
        else:
            indice = len(self._figuras) if indice is None else max(0, min(indice, len(self._figuras)))
            self._figuras.insert(indice, figura)
        self.figurasMudaram.emit()

    def _tirar_figura(self, id: str) -> int:
        indice = [f.id for f in self._figuras].index(id)
        del self._figuras[indice]
        self.figurasMudaram.emit()
        return indice

    def _repasses(self, vista: Vista):
        return ((vista.tracoEntrou, self.tracoEntrou), (vista.tracoSaiu, self.tracoSaiu),
                (vista.tracoMudou, self.tracoMudou), (vista.mudou, self.vistaMudou))

    def _limpo_mudou(self, limpo: bool) -> None:
        # A pilha se limpa ao ser destruída, com o projeto já no meio da destruição.
        if isValid(self):
            self.modificadoMudou.emit(not limpo)

    def __repr__(self) -> str:
        return f"Projeto({self.nome!r}, {len(self._fontes)} fontes, {len(self._vistas)} vistas)"
