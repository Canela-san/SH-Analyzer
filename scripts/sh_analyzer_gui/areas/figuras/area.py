"""A área Figuras (a F5.3; o F1 de docs/gui-plan.md, 10.1): à esquerda, as figuras do projeto e os modelos de página;
no centro, a página da figura escolhida no tamanho real; à direita, as propriedades dela e do painel escolhido.

**Uma vista vira figura com um clique** (FG-01, :meth:`AreaDeFiguras.figura_da_vista`): uma figura IEEE de uma
coluna com um painel ligado à vista. **O painel ligado acompanha a vista:** os traços, as opções e a janela que ela
mostra (a Análise avisa, ``exibicaoMudou``) refazem a página. **Congelar** guarda a cópia da vista e a janela do
momento; religar volta a acompanhar as duas. Toda edição é um passo de desfazer (``MudarFigura`` e companhia).

**A prévia é o próprio desenho da exportação** (``dados/desenho_da_figura.py``), no dpi da tela: os dados saem das
capturas na thread da interface (:func:`colher`, que só junta referências) e o Matplotlib desenha numa de trabalho;
um pedido que chega com outro desenhando espera o fim dele, e só a página mais nova aparece. Com a área escondida,
nada se desenha: o pedido fica para quando ela aparecer.
"""

from __future__ import annotations

import math
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QImage
from PySide6.QtWidgets import QHBoxLayout, QListWidget, QListWidgetItem, QVBoxLayout, QWidget
from shiboken6 import isValid

from ...componentes import area_de_transferencia
from ...componentes.numeros import formatar_bytes
from ...componentes.painel import TituloDoPainel
from ...componentes.toast import Toast
from ...dados import figura as fig
from ...dados.desenho_da_figura import colher, desenhar, pontos, registrar_as_fontes, vista_do_painel
from ...dados.exportar_figura import OpcoesDeExportacao, em_bytes, nome_do_arquivo
from ...dados.exportar_figura import exportar as exportar_figura
from ...dados.figura import Figura, Painel
from ...dados.pacote import empacotar as empacotar_figura
from ...dados.proveniencia import da_figura
from ...modelo.comandos import AdicionarFigura, MudarAnotacoes, MudarFigura, RemoverFigura
from ...modelo.objetos import Projeto, Vista, novo_id
from ...modelo.persistencia import descrever_vista
from ...servicos.tarefas import Tarefa
from ...tema.aplicar import aparencia
from ...tema.icones import IconeDoTema, icone
from ...tema.tokens import CLARO, cor_do_traco
from .dados_do_projeto import DadosDoProjeto
from .elementos import TracoDoPainel
from .pagina import PaginaDaFigura
from .propriedades import PropriedadesDaFigura

ESPERA_MS = 120                 # junta os pedidos de desenho de uma rajada (girar a altura, o zoom da vista)
LARGURA_DAS_LATERAIS = 260
LADO_DA_COPIA_PX = 6000
LARGURA_DAS_PROPRIEDADES = 340


def _versao() -> str:
    """A versão do aplicativo (a que ``app.criar_aplicacao`` registra), para a proveniência."""
    return QCoreApplication.applicationVersion() or "dev"


def dpi_da_copia(f: Figura) -> float:
    """O dpi do PNG copiado: 300, ou menos numa página grande (até ~6 000 px no lado maior; 150 no mínimo)."""
    lado = max(f.largura_mm, f.altura_mm) / 25.4
    return float(max(150, min(300, math.floor(LADO_DA_COPIA_PX / lado))))


def descricao_da_pagina(f: Figura) -> str:
    """"IEEE, 1 coluna · 2 painéis"."""
    n = len(f.paineis)
    return f"{f.pagina.nome} · {n} {'painel' if n == 1 else 'painéis'}"


TIPOS_COM_FIGURA = ("tempo", "espectro", "bandas", "espectrograma", "harmonicos")

class AreaDeFiguras(QWidget):
    resumoMudou = Signal(str)            # a linha da barra de status
    desenhada = Signal()                 # uma página nova apareceu (os testes esperam por ela)
    exportada = Signal(object)           # o caminho da figura exportada
    empacotada = Signal(object)          # o caminho do pacote reproduzível
    copiada = Signal()

    def __init__(self, analise, tarefas, materializacoes, vista_ativa=lambda: None, dialogos_de=lambda: None,
                 parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("area_figuras")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.analise, self.tarefas, self.materializacoes = analise, tarefas, materializacoes
        self.vista_ativa, self.dialogos_de = vista_ativa, dialogos_de
        self._pasta_da_exportacao: Path | None = None
        self.projeto: Projeto | None = None
        self.dados: DadosDoProjeto | None = None
        self.figura_id: str | None = None
        self.painel_id: str | None = None
        self._geracao = 0
        self._desenhando = None             # a tarefa em curso
        self._de_novo = False
        self._pendente = False
        self._fontes_ouvidas: set = set()
        registrar_as_fontes()

        self.espera = QTimer(self)
        self.espera.setSingleShot(True)
        self.espera.setInterval(ESPERA_MS)
        self.espera.timeout.connect(self._desenhar)

        # A esquerda: as figuras e os modelos
        lateral = QWidget()
        lateral.setObjectName("lateral_figuras")
        lateral.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        lateral.setFixedWidth(LARGURA_DAS_LATERAIS)
        titulo = TituloDoPainel(self.tr("Figuras do projeto"))
        acao_nova = QAction(self.tr("Nova figura (com a vista aberta na Análise, se houver)"), self)
        IconeDoTema(acao_nova, "mais")
        acao_nova.triggered.connect(lambda: self.nova_figura())
        self.nova = titulo.adicionar_botao(acao_nova)
        self.nova.setObjectName("nova_figura")
        titulo.adicionar_ajuda("figuras")
        self.lista = QListWidget()
        self.lista.setObjectName("lista_de_figuras")
        self.lista.setIconSize(QSize(16, 16))
        self.lista.currentRowChanged.connect(self._lista_mudou)
        self.modelos = QListWidget()
        self.modelos.setObjectName("modelos_de_pagina")
        for m in fig.MODELOS:
            item = QListWidgetItem(m.nome)
            item.setData(Qt.ItemDataRole.UserRole, m.id)
            item.setToolTip(self.tr("{} mm de largura. Pôr a figura escolhida nesta página (ou começar uma nova "
                                    "nela)").format(f"{m.largura_mm:g}".replace(".", ",")))
            self.modelos.addItem(item)
        self.modelos.itemClicked.connect(self._modelo_clicado)
        for lista in (self.lista, self.modelos):
            lista.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            lista.setTextElideMode(Qt.TextElideMode.ElideRight)
        coluna = QVBoxLayout(lateral)
        coluna.setContentsMargins(0, 0, 0, 0)
        coluna.setSpacing(0)
        coluna.addWidget(titulo)
        coluna.addWidget(self.lista, 3)
        coluna.addWidget(TituloDoPainel(self.tr("Modelos")))
        coluna.addWidget(self.modelos, 2)

        # O centro e a direita
        self.pagina = PaginaDaFigura()
        self.pagina.painelClicado.connect(self.escolher_painel)
        self.pagina.zoomMudou.connect(self.pedir_desenho)
        self.propriedades = PropriedadesDaFigura()
        self.propriedades.setFixedWidth(LARGURA_DAS_PROPRIEDADES)
        self.propriedades.mudar.connect(self._mudar)
        self.propriedades.congelarPedido.connect(self.congelar)
        self.propriedades.acrescentarPedido.connect(self.acrescentar_painel)
        self.propriedades.apagarPedido.connect(self.apagar_figura)
        self.propriedades.tracos_de = self.tracos_do_painel
        self.propriedades.secao_das_anotacoes.anotacoes_de = self.anotacoes_do_painel
        self.propriedades.secao_das_anotacoes.mudar_anotacoes = self.mudar_anotacoes
        self.exportacao = self.propriedades.exportacao
        self.exportacao.exportarPedido.connect(self.exportar)
        self.exportacao.copiarPedido.connect(self.copiar)
        self.exportacao.empacotarPedido.connect(self.empacotar)
        self.exportacao.contar_pontos = self._contar_pontos

        linha = QHBoxLayout(self)
        linha.setContentsMargins(0, 0, 0, 0)
        linha.setSpacing(0)
        linha.addWidget(lateral)
        linha.addWidget(self.pagina, 1)
        linha.addWidget(self.propriedades)

        aparencia().mudou.connect(self._tema_mudou)
        self._tema_mudou(aparencia().tema)
        analise.exibicaoMudou.connect(self._vista_mudou)
        materializacoes.mudou.connect(self._materializacao_mudou)

    def _tema_mudou(self, tema) -> None:
        if isValid(self):
            for i in range(self.modelos.count()):
                self.modelos.item(i).setIcon(icone("pagina", tema.texto2))

    # ------------------------------------------------------------------ o projeto

    def acompanhar(self, projeto: Projeto) -> None:
        anterior = self.projeto
        if anterior is not None and isValid(anterior):
            for sinal, alvo in self._ligacoes(anterior):
                sinal.disconnect(alvo)
        self.projeto = projeto
        self.dados = DadosDoProjeto(projeto, self.analise, self.materializacoes)
        self._fontes_ouvidas = set()
        for sinal, alvo in self._ligacoes(projeto):
            sinal.connect(alvo)
        for fonte in projeto.fontes:
            self._ouvir_a_fonte(fonte)
        self.figura_id = projeto.figuras[0].id if projeto.figuras else None
        self.painel_id = None
        self._figuras_mudaram()

    def _ligacoes(self, projeto: Projeto):
        return [(projeto.figurasMudaram, self._figuras_mudaram), (projeto.vistaEntrou, self._vistas_mudaram),
                (projeto.vistaSaiu, self._vistas_mudaram), (projeto.vistaMudou, self._vistas_mudaram),
                (projeto.tracoEntrou, self._tracos_mudaram), (projeto.tracoSaiu, self._tracos_mudaram),
                (projeto.tracoMudou, self._traco_mudou), (projeto.fonteEntrou, self._fonte_entrou)]

    def _fonte_entrou(self, fonte, _indice: int) -> None:
        self._ouvir_a_fonte(fonte)
        self.pedir_desenho()

    def _ouvir_a_fonte(self, fonte) -> None:
        """A pirâmide de uma captura chega depois de abrir o projeto: a página se refaz com ela."""
        if fonte not in self._fontes_ouvidas:
            self._fontes_ouvidas.add(fonte)
            fonte.piramidesProntas.connect(lambda *_a: self.pedir_desenho())

    @property
    def figura(self) -> Figura | None:
        if self.projeto is None or self.figura_id is None:
            return None
        return next((f for f in self.projeto.figuras if f.id == self.figura_id), None)

    def _figuras_mudaram(self) -> None:
        figuras = self.projeto.figuras if self.projeto is not None else ()
        if self.figura_id not in {f.id for f in figuras}:
            self.figura_id = figuras[0].id if figuras else None
        figura = self.figura
        if figura is not None and self.painel_id not in {p.id for p in figura.paineis}:
            self.painel_id = figura.em_ordem()[0].id if figura.paineis else None
        self.lista.blockSignals(True)
        self.lista.clear()
        for f in figuras:
            item = QListWidgetItem(f"{f.nome}\n{descricao_da_pagina(f)}")
            item.setData(Qt.ItemDataRole.UserRole, f.id)
            self.lista.addItem(item)
        ids = [f.id for f in figuras]
        self.lista.setCurrentRow(ids.index(self.figura_id) if self.figura_id in ids else -1)
        self.lista.blockSignals(False)
        self._mostrar()

    def _vistas_mudaram(self, *_a) -> None:
        self._mostrar()

    def _tracos_mudaram(self, vista: Vista, _traco, _posicao: int) -> None:
        if self._usa(vista.id):
            self.pedir_desenho()

    def _traco_mudou(self, traco, _campos) -> None:
        if any(self._usa(v.id) for v in self.projeto.vistas if traco in v.tracos):
            self.pedir_desenho()

    def _vista_mudou(self, vista: Vista) -> None:
        if self._usa(vista.id):
            self.pedir_desenho()

    def _materializacao_mudou(self, estado) -> None:
        if self.dados is not None and self.dados.esperando and estado.pronta is not None:
            self.pedir_desenho()

    def _usa(self, id_da_vista: str | None) -> bool:
        """Se a figura escolhida tem um painel ligado à vista (o congelado não muda com ela)."""
        figura = self.figura
        return figura is not None and id_da_vista in figura.vistas_ligadas()

    # ------------------------------------------------------------------ mostrar

    def _mostrar(self) -> None:
        figura = self.figura
        vistas = [(v.id, v.nome, v.tipo) for v in self._vistas_de_dados()] if self.projeto is not None else []
        self.propriedades.mostrar(figura, self.painel_id, vistas)
        self.pagina.escolher(self.painel_id)
        self.pagina.mostrar_vazio(figura is None)
        self.resumoMudou.emit(self.resumo())
        self.pedir_desenho()

    def resumo(self) -> str:
        """A linha da barra de status: "Afundamento · 88 × 66 mm · 2 painéis · ligada a «V e I»"."""
        figura = self.figura
        if figura is None:
            return self.tr("Nenhuma figura")
        tamanho = f"{figura.largura_mm:g} × {figura.altura_mm:g} mm"
        n = len(figura.paineis)
        partes = [figura.nome, tamanho, self.tr("{} painel").format(n) if n == 1 else self.tr("{} painéis").format(n)]
        nomes = [v.nome for v in self.projeto.vistas if v.id in figura.vistas_ligadas()]
        if nomes:
            partes.append(self.tr("ligada a {}").format(", ".join(f"“{n}”" for n in nomes)))
        if any(p.congelado is not None for p in figura.paineis):
            partes.append(self.tr("com painel congelado"))
        return " · ".join(partes)

    def escolher_figura(self, id_: str) -> None:
        if id_ != self.figura_id:
            self.figura_id, self.painel_id = id_, None
            self._figuras_mudaram()

    def escolher_painel(self, id_: str) -> None:
        if id_ != self.painel_id:
            self.painel_id = id_
            self.propriedades.mostrar(self.figura, id_, [(v.id, v.nome, v.tipo) for v in self._vistas_de_dados()])
            self.pagina.escolher(id_)

    def _lista_mudou(self, linha: int) -> None:
        item = self.lista.item(linha)
        if item is not None:
            self.escolher_figura(item.data(Qt.ItemDataRole.UserRole))

    # ------------------------------------------------------------------ editar

    def _empilhar(self, comando) -> None:
        self.projeto.pilha.push(comando)

    def _mudar(self, nova: Figura, texto: str, juntar: bool) -> None:
        self._empilhar(MudarFigura(self.projeto, nova, texto, juntar=juntar))

    def figura_da_vista(self, vista: Vista, id_do_modelo: str = "ieee_1") -> Figura:
        """FG-01: a vista vira uma figura (de uma coluna da IEEE, um painel ligado a ela), que fica escolhida."""
        figura = fig.nova(novo_id(), vista.nome, id_do_modelo, vista=vista.id, id_do_painel=novo_id())
        self._empilhar(AdicionarFigura(self.projeto, figura))
        self.escolher_figura(figura.id)
        return figura

    def _vistas_de_dados(self) -> list:
        """As vistas que viram painel (a dos perfis de sonda ainda não: o desenho da figura não faz o Bode)."""
        return [v for v in self.projeto.vistas if v.tipo in TIPOS_COM_FIGURA]

    def nova_figura(self, id_do_modelo: str = "ieee_1") -> Figura:
        """O + da lista: com a vista aberta na Análise, a figura dela; sem nenhuma, uma figura com o painel vazio."""
        vista = self.vista_ativa()
        if vista is not None and vista.tipo in TIPOS_COM_FIGURA:
            return self.figura_da_vista(vista, id_do_modelo)
        n = len(self.projeto.figuras) + 1
        figura = fig.nova(novo_id(), self.tr("Figura {}").format(n), id_do_modelo, id_do_painel=novo_id())
        self._empilhar(AdicionarFigura(self.projeto, figura))
        self.escolher_figura(figura.id)
        return figura

    def _modelo_clicado(self, item: QListWidgetItem) -> None:
        id_ = item.data(Qt.ItemDataRole.UserRole)
        figura = self.figura
        if figura is None:
            self.nova_figura(id_)
        elif figura.modelo != id_:
            self._mudar(fig.trocar_modelo(figura, id_), self.tr("Trocar a página para {}").format(
                fig.modelo(id_).nome), False)

    def acrescentar_painel(self) -> None:
        figura = self.figura
        if figura is None:
            return
        id_ = novo_id()
        try:
            nova = fig.acrescentar_painel(figura, id_)
        except fig.FiguraInvalida as erro:
            self.propriedades.acrescentar.setToolTip(str(erro))
            return
        self.painel_id = id_
        self._mudar(nova, self.tr("Pôr um painel"), False)

    def congelar(self, id_do_painel: str, congelar: bool) -> None:
        """Congela o painel (a cópia da vista e a janela que ela mostra agora) ou o religa à vista."""
        figura = self.figura
        painel = next((p for p in figura.paineis if p.id == id_do_painel), None) if figura is not None else None
        if painel is None or (painel.congelado is not None) == congelar:
            return
        if congelar:
            viva = next((v for v in self.projeto.vistas if v.id == painel.vista), None)
            if viva is None:
                return
            novo = replace(painel, congelado=descrever_vista(viva),
                           limites_x=painel.limites_x or self.analise.janela_da_vista(viva))
            texto = self.tr("Congelar o painel")
        else:
            if painel.vista not in {v.id for v in self.projeto.vistas}:
                return
            novo = replace(painel, congelado=None, limites_x=None)
            texto = self.tr("Religar o painel à vista")
        self._mudar(fig.trocar_painel(figura, novo), texto, False)

    def apagar_figura(self) -> None:
        figura = self.figura
        if figura is not None:
            self._empilhar(RemoverFigura(self.projeto, figura.id))

    # ------------------------------------------------------------------ desenhar

    def pedir_desenho(self) -> None:
        self.espera.start()

    def showEvent(self, evento) -> None:
        super().showEvent(evento)
        if self._pendente:
            self.pedir_desenho()

    def _colher(self, figura: Figura):
        """As vistas como estão e os dados da figura, colhidos aqui (na thread da interface)."""
        vistas = {v.id: descrever_vista(v) for v in self.projeto.vistas}
        self.dados.comecar()
        colhidos = colher(figura, vistas, self.dados)
        self.dados.terminar()
        return vistas, colhidos

    def tracos_do_painel(self, painel: Painel) -> list[TracoDoPainel]:
        """Os traços que o painel desenha, como a vista os mostra (o espectro: os da vista de tempo ligada a ele)."""
        if self.projeto is None:
            return []
        vista = vista_do_painel(painel, {v.id: descrever_vista(v) for v in self.projeto.vistas})
        if vista is None:
            return []
        if vista.tipo == "espectro":
            return [TracoDoPainel(s.traco, s.nome, s.cor, s.tracejado) for s in self.dados.espectros(vista)] \
                if self.dados is not None and painel.congelado is None else []
        tracos = []
        for t in vista.tracos:
            if t.receita.visivel:
                cor, tracejado = cor_do_traco(t.receita.cor, CLARO)
                tracos.append(TracoDoPainel(t.id, t.receita.nome, cor, tracejado))
        return tracos

    def anotacoes_do_painel(self, painel: Painel) -> tuple:
        """As anotações que o painel desenha: as da vista ligada, ou as da cópia congelada."""
        if painel.congelado is not None:
            return painel.congelado.anotacoes
        vista = next((v for v in self.projeto.vistas if v.id == painel.vista), None) if self.projeto else None
        return vista.anotacoes if vista is not None else ()

    def mudar_anotacoes(self, painel: Painel, anotacoes: tuple, texto: str) -> None:
        """As anotações do painel trocadas: na vista ligada (um passo dela, que a Análise também mostra) ou na cópia
        congelada (um passo da figura)."""
        figura = self.figura
        if self.projeto is None or figura is None:
            return
        if painel.congelado is not None:
            novo = replace(painel, congelado=replace(painel.congelado, anotacoes=tuple(anotacoes)))
            self._mudar(fig.trocar_painel(figura, novo), texto, False)
            return
        vista = next((v for v in self.projeto.vistas if v.id == painel.vista), None)
        if vista is not None:
            self._empilhar(MudarAnotacoes(vista, anotacoes, texto=texto))

    def _contar_pontos(self) -> int:
        figura = self.figura
        if figura is None:
            return 0
        vistas, colhidos = self._colher(figura)
        return pontos(figura, vistas, colhidos)

    # ------------------------------------------------------------------ exportar e copiar

    def exportar(self, opcoes: OpcoesDeExportacao, caminho: Path | None = None) -> Tarefa | None:
        """Exporta a figura escolhida (pergunta onde, sem ``caminho``) numa tarefa, com o progresso na seção e no
        painel das tarefas; no fim, o aviso na janela."""
        return self._exportar(opcoes, caminho, pacote=False)

    def empacotar(self, opcoes: OpcoesDeExportacao, caminho: Path | None = None) -> Tarefa | None:
        """FG-08: o pacote reproduzível (um ``.zip`` com a figura no formato de ``opcoes``, os dados dela, o script
        que a refaz e a proveniência), como a exportação: numa tarefa, perguntando onde sem ``caminho``."""
        return self._exportar(opcoes, caminho, pacote=True)

    def _exportar(self, opcoes: OpcoesDeExportacao, caminho: Path | None, *, pacote: bool) -> Tarefa | None:
        figura = self.figura
        if figura is None:
            return None
        formato = opcoes.dados_do_formato
        extensao = ".zip" if pacote else formato.extensao
        if caminho is None:
            pasta = self._pasta_da_exportacao or (self.projeto.caminho.parent if self.projeto.caminho else Path.home())
            dialogos = self.dialogos_de()
            sugestao = nome_do_arquivo(figura, opcoes).removesuffix(formato.extensao) + extensao
            titulo, filtro = ((self.tr("Exportar o pacote reproduzível"), self.tr("Pacote reproduzível (*.zip)"))
                              if pacote else (self.tr("Exportar a figura"), f"{formato.nome} (*{formato.extensao})"))
            caminho = dialogos.salvar_arquivo(titulo, filtro, str(pasta / sugestao)) if dialogos else None
            if caminho is None:
                return None
        caminho = Path(caminho)
        if caminho.suffix.lower() not in {extensao, ".tiff" if formato.id == "tiff" and not pacote else extensao}:
            caminho = caminho.with_name(caminho.name + extensao)
        self._pasta_da_exportacao = caminho.parent
        vistas, colhidos = self._colher(figura)
        proveniencia = da_figura(figura, vistas, self.dados.fontes_da_proveniencia(), aplicativo=_versao())
        andamento = self.tr("Empacotando…") if pacote else self.tr("Exportando…")
        self.exportacao.definir_ocupada(True, andamento)

        def trabalho(progresso, cancelado):
            gravar = empacotar_figura if pacote else exportar_figura
            gravar(figura, vistas, colhidos, caminho, opcoes, proveniencia=proveniencia, aplicativo=_versao(),
                   progresso=progresso, cancelado=cancelado)
            return caminho

        nome = (self.tr("Empacotar a figura {} ({})") if pacote else self.tr("Exportar a figura {} ({})")).format(
            figura.nome, formato.nome)
        return self.tarefas.iniciar(
            nome, trabalho, "figuras", pesada=True,
            ao_progredir=lambda _t, f: self.exportacao.definir_ocupada(True, f"{andamento} {round(100 * f)} %"),
            ao_terminar=lambda tarefa: self._exportou(tarefa, pacote))

    def _exportou(self, tarefa: Tarefa, pacote: bool) -> None:
        if not isValid(self):
            return
        self.exportacao.definir_ocupada(False)
        if tarefa.estado == "concluida":
            caminho = tarefa.resultado
            texto = self.tr("Pacote reproduzível: {} ({})") if pacote else self.tr("Figura exportada: {} ({})")
            Toast.mostrar(self.window(), texto.format(caminho.name, formatar_bytes(caminho.stat().st_size)),
                          "sucesso")
            (self.empacotada if pacote else self.exportada).emit(caminho)
        elif tarefa.estado == "falhou":
            texto = (self.tr("O pacote não foi feito: {}") if pacote
                     else self.tr("A figura não foi exportada: {}"))
            Toast.mostrar(self.window(), texto.format(tarefa.erro), "erro")

    def copiar(self) -> Tarefa | None:
        """FG-09: a figura na área de transferência, em PNG (:func:`dpi_da_copia`) e em SVG (o texto editável)."""
        figura = self.figura
        if figura is None:
            return None
        vistas, colhidos = self._colher(figura)
        proveniencia = da_figura(figura, vistas, self.dados.fontes_da_proveniencia(), aplicativo=_versao())

        def trabalho(progresso, cancelado):
            kw = {"proveniencia": proveniencia, "aplicativo": _versao(), "cancelado": cancelado}
            png = em_bytes(figura, vistas, colhidos, OpcoesDeExportacao("png", dpi_da_copia(figura)),
                           progresso=lambda f: progresso(f / 2), **kw)
            svg = em_bytes(figura, vistas, colhidos, OpcoesDeExportacao("svg"),
                           progresso=lambda f: progresso(0.5 + f / 2), **kw)
            return png, svg

        self.exportacao.definir_ocupada(True, self.tr("Copiando…"))
        return self.tarefas.iniciar(self.tr("Copiar a figura {}").format(figura.nome), trabalho, "figuras",
                                    pesada=True, ao_terminar=self._copiou)

    def _copiou(self, tarefa: Tarefa) -> None:
        if not isValid(self):
            return
        self.exportacao.definir_ocupada(False)
        if tarefa.estado != "concluida":
            if tarefa.estado == "falhou":
                Toast.mostrar(self.window(), self.tr("A figura não foi copiada: {}").format(tarefa.erro), "erro")
            return
        png, svg = tarefa.resultado
        area_de_transferencia.copiar({"image/png": png, "image/svg+xml": svg}, QImage.fromData(png, "PNG"))
        Toast.mostrar(self.window(), self.tr("Figura copiada (PNG e SVG)"), "sucesso")
        self.copiada.emit()

    def _desenhar(self) -> None:
        """Colhe os dados aqui e desenha a página numa thread de trabalho."""
        figura = self.figura
        if figura is None or self.projeto is None:
            return
        if not self.isVisible():
            self._pendente = True
            return
        if self._desenhando is not None:
            self._de_novo = True
            return
        self._pendente = False
        vistas, colhidos = self._colher(figura)
        self.pagina.definir_tamanho(figura.largura_mm, figura.altura_mm)
        dpi = self.pagina.dpi_do_desenho()
        self._geracao += 1
        geracao = self._geracao

        def trabalho(_progresso, _cancelado):
            pagina = desenhar(figura, vistas, colhidos, dpi=dpi, exato=False)
            return pagina.pixels(), pagina.paineis, pagina.eixos

        self._desenhando = self.tarefas.iniciar(self.tr("Desenhar a figura {}").format(figura.nome), trabalho,
                                                "figuras", mostrar=False,
                                                ao_terminar=lambda t: self._desenhou(t, geracao, dpi))

    def _desenhou(self, tarefa, geracao: int, dpi: float) -> None:
        if not isValid(self):
            return
        self._desenhando = None
        if self._de_novo:
            self._de_novo = False
            self.pedir_desenho()
        if geracao != self._geracao or tarefa.estado != "concluida":
            return
        pixels, caixas, eixos = tarefa.resultado
        self.pagina.mostrar(pixels, caixas, dpi)
        self.propriedades.definir_eixos(eixos)
        self.pagina.escolher(self.painel_id)
        self.desenhada.emit()
