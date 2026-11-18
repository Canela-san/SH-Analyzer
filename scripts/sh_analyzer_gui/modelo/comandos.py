"""Os comandos de desfazer (docs/gui-plan.md, 8.4): **toda edição do projeto é um destes**, empilhado na pilha do
projeto (``projeto.pilha.push(comando)``). O ``push`` já executa o comando; o desfazer o reverte.

**Validação antes de empilhar:** cada comando calcula o estado novo no construtor. Uma mudança inválida levanta
``ReceitaInvalida`` (ou ``ValueError``) ali, antes do ``push``, e a pilha não recebe nada pela metade.

**Os textos** ("Mudar a cor de V_A", "Remover 3 traços") aparecem na dica do desfazer e, depois, no histórico.

**Sem comandos filhos do Qt** (``QUndoCommand(parent=...)``): o Python não segura o filho, e o Qt chamaria um objeto
já recolhido (o processo caiu assim num teste). Um comando de vários passos guarda os passos ele mesmo
(``RemoverFonte``).
"""

from __future__ import annotations

from collections.abc import Mapping

from PySide6.QtGui import QUndoCommand

from ..dados.projeto import ModeloDeCaptura
from .objetos import FonteDoProjeto, Projeto, Traco, Vista

ID_MUDAR_TRACOS = 1001
"""O ``id()`` das mudanças que se juntam (arrastar um valor gera uma mudança por passo; o desfazer volta tudo)."""

_CAMPOS = {"nome": "o nome", "cor": "a cor", "ganho": "o ganho", "offset": "o offset",
           "deslocamento_s": "o deslocamento no tempo", "faixa": "a faixa", "unidade": "a unidade"}


def _quais(tracos) -> str:
    return tracos[0].nome if len(tracos) == 1 else f"{len(tracos)} traços"


class AdicionarTraco(QUndoCommand):
    """Põe ``traco`` na ``vista`` (no fim, ou em ``indice``)."""

    def __init__(self, vista: Vista, traco: Traco, indice: int | None = None):
        super().__init__(f"Adicionar {traco.nome}")
        if traco in vista.tracos:
            raise ValueError(f"{traco!r} já está na vista {vista.nome!r}")
        self.vista, self.traco, self.indice = vista, traco, indice

    def redo(self) -> None:
        self.indice = self.vista._inserir(self.traco, self.indice)

    def undo(self) -> None:
        self.vista._retirar(self.traco)


class _Remocao:
    """Tirar traços de uma vista e devolvê-los, cada um na posição de antes. Um passo dentro de um comando (não é
    um ``QUndoCommand``: o comando que o usa o guarda e o chama)."""

    def __init__(self, vista: Vista, tracos):
        fora = [t for t in tracos if t not in vista.tracos]
        if fora:
            raise ValueError(f"{fora[0]!r} não está na vista {vista.nome!r}")
        self.vista = vista
        # Na ordem da vista: o desfazer reinsere do primeiro ao último, e cada um volta à sua posição.
        self.posicoes = sorted(((vista.indice(t), t) for t in tracos), key=lambda par: par[0])

    def fazer(self) -> None:
        for _, traco in reversed(self.posicoes):
            self.vista._retirar(traco)

    def desfazer(self) -> None:
        for indice, traco in self.posicoes:
            self.vista._inserir(traco, indice)


class RemoverTracos(QUndoCommand):
    """Tira ``tracos`` da ``vista``; o desfazer os põe de volta, cada um na posição de antes."""

    def __init__(self, vista: Vista, tracos):
        tracos = list(dict.fromkeys(tracos))
        if not tracos:
            raise ValueError("nenhum traço para remover")
        remocao = _Remocao(vista, tracos)
        super().__init__(f"Remover {_quais(tracos)}")
        self.vista, self.remocao = vista, remocao

    def redo(self) -> None:
        self.remocao.fazer()

    def undo(self) -> None:
        self.remocao.desfazer()


class MudarTracos(QUndoCommand):
    """Muda campos da receita de um ou mais traços, como um passo só de desfazer:
    ``MudarTracos([a, b], cor=2)``. Com ``juntar``, mudanças seguidas dos mesmos campos nos mesmos traços viram uma
    (arrastar o ganho não enche a pilha). ``juntar`` pode ser ``True`` ou uma marca (qualquer objeto): com a marca,
    só se juntam as do mesmo gesto, e dois arrastos seguidos do mesmo traço ficam em dois passos de desfazer.
    ``texto`` troca o texto automático ("Mover V_A").

    Com uma mudança diferente para cada traço, ``tracos`` é o dicionário ``{traço: {campo: valor}}`` e não vêm
    ``mudancas``: trocar a unidade converte o ganho e o offset de cada um, que podem diferir."""

    def __init__(self, tracos, *, juntar: object = False, texto: str | None = None, **mudancas):
        if isinstance(tracos, Mapping):
            if mudancas:
                raise ValueError("com uma mudança para cada traço, as mudanças vão no dicionário")
            de_cada = {t: dict(m) for t, m in tracos.items()}
        else:
            de_cada = {t: mudancas for t in dict.fromkeys(tracos)}
        if not de_cada or not all(de_cada.values()):
            raise ValueError("diga quais traços e o que muda")
        tracos = list(de_cada)
        antes = [t.receita for t in tracos]
        depois = [r.com(**de_cada[t]) for t, r in zip(tracos, antes)]      # valida aqui, antes do push
        juntas: dict = {}
        for m in de_cada.values():
            juntas.update(m)
        super().__init__(texto or self._texto(tracos, antes, depois, juntas))
        self.tracos, self.antes, self.depois = tracos, antes, depois
        self.campos = frozenset(juntas)
        self.juntar = juntar

    @staticmethod
    def _texto(tracos, antes, depois, mudancas: dict) -> str:
        if set(mudancas) == {"visivel"}:
            return f"{'Mostrar' if mudancas['visivel'] else 'Esconder'} {_quais(tracos)}"
        if len(mudancas) == 1 and next(iter(mudancas)) in _CAMPOS:
            campo = next(iter(mudancas))
            if campo == "nome" and len(tracos) == 1:
                return f"Renomear {antes[0].nome} para {depois[0].nome}"
            return f"Mudar {_CAMPOS[campo]} de {_quais(tracos)}"
        return f"Mudar {_quais(tracos)}"

    def id(self) -> int:
        return ID_MUDAR_TRACOS if self.juntar else -1

    @property
    def muda_algo(self) -> bool:
        """Se o comando muda alguma receita (um gesto parado não precisa entrar na pilha)."""
        return any(a != d for a, d in zip(self.antes, self.depois))

    def mergeWith(self, outro: QUndoCommand) -> bool:
        if not (isinstance(outro, MudarTracos) and outro.juntar and outro.juntar == self.juntar
                and outro.campos == self.campos and outro.tracos == self.tracos):
            return False
        self.depois = outro.depois
        return True

    def redo(self) -> None:
        for traco, receita in zip(self.tracos, self.depois):
            traco._definir(receita)

    def undo(self) -> None:
        for traco, receita in zip(self.tracos, self.antes):
            traco._definir(receita)


class AdicionarVista(QUndoCommand):
    def __init__(self, projeto: Projeto, vista: Vista, indice: int | None = None):
        super().__init__(f"Nova vista {vista.nome}")
        if vista in projeto.vistas:
            raise ValueError(f"{vista!r} já está no projeto")
        self.projeto, self.vista, self.indice = projeto, vista, indice

    def redo(self) -> None:
        self.indice = self.projeto._inserir_vista(self.vista, self.indice)

    def undo(self) -> None:
        self.projeto._retirar_vista(self.vista)


class RemoverVista(QUndoCommand):
    """Tira a vista do projeto, com os traços dentro dela (o desfazer a devolve inteira, no mesmo lugar)."""

    def __init__(self, projeto: Projeto, vista: Vista):
        super().__init__(f"Fechar a vista {vista.nome}")
        self.projeto, self.vista = projeto, vista
        self.indice = projeto.vistas.index(vista)

    def redo(self) -> None:
        self.indice = self.projeto._retirar_vista(self.vista)

    def undo(self) -> None:
        self.projeto._inserir_vista(self.vista, self.indice)


class RenomearVista(QUndoCommand):
    def __init__(self, vista: Vista, nome: str):
        nome = nome.strip()
        if not nome:
            raise ValueError("o nome da vista não pode ficar vazio")
        super().__init__(f"Renomear a vista {vista.nome} para {nome}")
        self.vista, self.antes, self.depois = vista, vista.nome, nome

    def redo(self) -> None:
        self.vista._definir_nome(self.depois)

    def undo(self) -> None:
        self.vista._definir_nome(self.antes)


class MudarOpcoesDaVista(QUndoCommand):
    """Troca as opções de uma vista de espectro (a escala, o método, o trecho...). Com ``juntar``, mudanças seguidas
    da mesma vista viram um passo só (arrastar a resolução não enche a pilha)."""

    ID = 4101

    def __init__(self, vista: Vista, opcoes, *, texto: str | None = None, juntar: bool = False):
        super().__init__(texto or f"Opções do espectro {vista.nome}")
        self.vista, self.antes, self.depois, self.juntar = vista, vista.opcoes, opcoes, juntar

    def id(self) -> int:
        return self.ID if self.juntar else -1

    def mergeWith(self, outro) -> bool:
        if not isinstance(outro, MudarOpcoesDaVista) or outro.vista is not self.vista:
            return False
        self.depois = outro.depois
        return True

    def redo(self) -> None:
        self.vista._definir_opcoes(self.depois)

    def undo(self) -> None:
        self.vista._definir_opcoes(self.antes)


class AdicionarFonte(QUndoCommand):
    """Põe uma captura aberta no projeto. Plotar os canais é outro passo (``AdicionarTraco``)."""

    def __init__(self, projeto: Projeto, fonte: FonteDoProjeto):
        super().__init__(f"Abrir {fonte.nome}")
        if any(f.id == fonte.id for f in projeto.fontes):
            raise ValueError(f"a fonte {fonte.id!r} já está no projeto")
        self.projeto, self.fonte, self.indice = projeto, fonte, None

    def redo(self) -> None:
        self.indice = self.projeto._inserir_fonte(self.fonte, self.indice)

    def undo(self) -> None:
        self.projeto._retirar_fonte(self.fonte)


class RemoverFonte(QUndoCommand):
    """Fecha uma captura: tira os traços dela de todas as vistas e depois a fonte. Um passo só de desfazer, que
    devolve tudo no lugar.

    Os passos ficam no próprio comando, não como comandos filhos do Qt: um filho criado só com ``parent=`` não tem
    quem segure o lado Python dele, e o Qt chamaria um objeto já recolhido."""

    def __init__(self, projeto: Projeto, fonte: FonteDoProjeto):
        por_vista: dict[str, tuple[Vista, list[Traco]]] = {}
        for vista, traco in projeto.tracos_da_fonte(fonte.id):
            por_vista.setdefault(vista.id, (vista, []))[1].append(traco)
        remocoes = [_Remocao(vista, tracos) for vista, tracos in por_vista.values()]
        super().__init__(f"Fechar {fonte.nome}")
        self.projeto, self.fonte, self.remocoes = projeto, fonte, remocoes
        self.indice = projeto.fontes.index(fonte)

    def redo(self) -> None:
        for remocao in self.remocoes:
            remocao.fazer()
        self.indice = self.projeto._retirar_fonte(self.fonte)

    def undo(self) -> None:
        self.projeto._inserir_fonte(self.fonte, self.indice)
        for remocao in reversed(self.remocoes):
            remocao.desfazer()


class GuardarModeloDeCaptura(QUndoCommand):
    """Guarda o formulário da captura com um nome (no lugar do de mesmo nome, se houver: o desfazer o devolve)."""

    def __init__(self, projeto: Projeto, modelo: ModeloDeCaptura):
        if not modelo.nome.strip():
            raise ValueError("o modelo de captura precisa de um nome")
        self.anterior = projeto.modelo_de_captura(modelo.nome)
        super().__init__(f"{'Atualizar' if self.anterior else 'Guardar'} o modelo {modelo.nome}")
        self.projeto, self.modelo = projeto, modelo
        self.indice: int | None = None

    def redo(self) -> None:
        self.projeto._por_modelo(self.modelo)

    def undo(self) -> None:
        if self.anterior is not None:
            self.projeto._por_modelo(self.anterior)
        else:
            self.projeto._tirar_modelo(self.modelo.nome)


class ApagarModeloDeCaptura(QUndoCommand):
    def __init__(self, projeto: Projeto, nome: str):
        self.modelo = projeto.modelo_de_captura(nome)
        if self.modelo is None:
            raise ValueError(f"o projeto não tem o modelo de captura {nome!r}")
        super().__init__(f"Apagar o modelo {nome}")
        self.projeto = projeto
        self.indice = 0

    def redo(self) -> None:
        self.indice = self.projeto._tirar_modelo(self.modelo.nome)

    def undo(self) -> None:
        self.projeto._por_modelo(self.modelo, self.indice)
