"""Os arquivos do projeto na janela (docs/gui-plan.md, 7.3; F1.3): novo, abrir, salvar, salvar como, os recentes, o
salvamento automático e a recuperação depois de uma queda.

**As perguntas e os diálogos de arquivo** passam por :class:`Dialogos`. Os testes trocam ``controle.dialogos`` por
respostas prontas; sem tela (``offscreen``), um diálogo que ninguém previu levanta erro em vez de travar o teste.

**As capturas** são o ``.bin`` (com o cabeçalho, ou o legado), o ``.csv`` e o ``.h5`` do ``adc_tool`` (PD-02). Uma sem
o cabeçalho pergunta a taxa e os canais (``areas/analise/sem_cabecalho.py``), com a última resposta já escrita; o
projeto os guarda, e reabri-lo não pergunta de novo.

**Nunca se perde trabalho sem perguntar:** fechar a janela, abrir outro projeto ou começar um novo com mudanças não
salvas pergunta antes (salvar, descartar ou cancelar). O salvamento automático grava a cada minuto num arquivo ao
lado (``.shproj~``; o de um projeto sem título vai para a pasta de recuperação), e some ao salvar ou descartar.
"""

from __future__ import annotations

import base64
import json
import logging
from pathlib import Path

from PySide6.QtCore import QByteArray, QObject, QTimer
from PySide6.QtWidgets import QApplication, QDialog, QFileDialog, QMessageBox, QWidget

from . import preferencias
from .areas.analise.sem_cabecalho import DialogoSemCabecalho
from .configuracao import esquecer, gravar, lembrar, ler_lista, ler_texto, pasta_de_recuperacao
from .dados import projeto as arquivo
from .dados.captura import Aviso, CapturaSemCabecalho, ErroSHAN, Fonte, ParametrosSemCabecalho, abrir_fonte
from .modelo.comandos import AdicionarFonte
from .modelo.objetos import FonteDoProjeto, Projeto
from .modelo.persistencia import descrever, montar

log = logging.getLogger(__name__)

INTERVALO_AUTOMATICO_MS = 60_000
CHAVE_DOS_RECENTES = "recentes/projetos"
CHAVE_DAS_CAPTURAS_RECENTES = "recentes/capturas"
CHAVE_DA_TAXA_E_DOS_CANAIS = "capturas/sem_cabecalho"
"""A última taxa e os últimos canais de uma captura sem o cabeçalho: a sugestão da próxima."""
NOME_SEM_TITULO = "sem-titulo" + arquivo.EXTENSAO
FILTRO = "Projetos do SH-Analyzer (*.shproj)"
FILTRO_DE_ABRIR = ("Capturas e projetos (*.bin *.csv *.h5 *.hdf5 *.shproj);;Capturas do SH-Analyzer (*.bin);;"
                   "Exportadas pelo adc_tool (*.csv *.h5 *.hdf5);;Projetos do SH-Analyzer (*.shproj);;"
                   "Todos os arquivos (*)")
ORIGEM_DO_PROJETO = "projeto"
"""A origem dos avisos da abertura do projeto no painel de avisos (saem juntos ao abrir outro)."""


class DialogoSemTela(RuntimeError):
    """Um diálogo modal pedido sem tela: nos testes, um diálogo que o teste não previu."""


class Dialogos:
    """As perguntas ao usuário. Cada método devolve a resposta (ou ``None`` se ele cancelar)."""

    def __init__(self, pai: QWidget):
        self.pai = pai

    def _conferir_tela(self, o_que: str) -> None:
        if QApplication.platformName() == "offscreen":
            raise DialogoSemTela(f"{o_que} sem tela: troque controle.dialogos por respostas prontas no teste")

    def abrir_arquivos(self, titulo: str, filtro: str, pasta: str = "") -> list[Path]:
        self._conferir_tela(f"o diálogo {titulo!r}")
        caminhos, _ = QFileDialog.getOpenFileNames(self.pai, titulo, pasta, filtro)
        return [Path(c) for c in caminhos]

    def abrir_arquivo(self, titulo: str, filtro: str, pasta: str = "") -> Path | None:
        self._conferir_tela(f"o diálogo {titulo!r}")
        caminho, _ = QFileDialog.getOpenFileName(self.pai, titulo, pasta, filtro)
        return Path(caminho) if caminho else None

    def salvar_arquivo(self, titulo: str, filtro: str, sugestao: str = "") -> Path | None:
        self._conferir_tela(f"o diálogo {titulo!r}")
        caminho, _ = QFileDialog.getSaveFileName(self.pai, titulo, sugestao, filtro)
        return Path(caminho) if caminho else None

    def escolher_pasta(self, titulo: str, pasta: str = "") -> Path | None:
        self._conferir_tela(f"o diálogo {titulo!r}")
        caminho = QFileDialog.getExistingDirectory(self.pai, titulo, pasta)
        return Path(caminho) if caminho else None

    def parametros_da_captura(self, caminho: Path, pedido: CapturaSemCabecalho,
                              sugestao: ParametrosSemCabecalho | None) -> ParametrosSemCabecalho | None:
        """A taxa e os canais de uma captura sem o cabeçalho (``pedido``: o que o arquivo diz)."""
        self._conferir_tela(f"a taxa e os canais de {caminho.name}")
        dialogo = DialogoSemCabecalho(caminho.name, pedido.tipo, pedido.canais, pedido.n_amostras, sugestao, self.pai)
        if dialogo.exec() != QDialog.DialogCode.Accepted:
            return None
        return dialogo.parametros()

    def perguntar(self, titulo: str, texto: str, opcoes: dict[str, str], padrao: str) -> str | None:
        """``opcoes``: a chave da resposta -> o texto do botão. A tecla Esc devolve ``None``."""
        self._conferir_tela(f"a pergunta {titulo!r}")
        caixa = QMessageBox(QMessageBox.Icon.Question, titulo, texto, parent=self.pai)
        botoes = {caixa.addButton(rotulo, QMessageBox.ButtonRole.ActionRole): chave
                  for chave, rotulo in opcoes.items()}
        cancelar = caixa.addButton(self.pai.tr("Cancelar"), QMessageBox.ButtonRole.RejectRole)
        for botao, chave in botoes.items():
            if chave == padrao:
                caixa.setDefaultButton(botao)
        caixa.setEscapeButton(cancelar)
        caixa.exec()
        return botoes.get(caixa.clickedButton())


class ControleDoProjeto(QObject):
    """Ligado à janela (``janela.controle``). As ações da janela chamam estes métodos; cada um devolve se fez o que
    pediu (``False`` quando o usuário cancelou ou deu erro, com o erro mostrado)."""

    def __init__(self, janela):
        super().__init__(janela)
        self.janela = janela
        self.dialogos = Dialogos(janela)
        self.temporizador = QTimer(self)
        self.temporizador.setInterval(INTERVALO_AUTOMATICO_MS)
        self.temporizador.timeout.connect(self.salvar_automatico)
        self.temporizador.start()

    @property
    def projeto(self) -> Projeto:
        return self.janela.projeto

    # ------------------------------------------------------------------ recentes

    def recentes(self) -> list[Path]:
        return [Path(c) for c in ler_lista(CHAVE_DOS_RECENTES)]

    def _lembrar(self, caminho: Path) -> None:
        lembrar(CHAVE_DOS_RECENTES, str(Path(caminho).resolve()))

    # ------------------------------------------------------------------ descartar

    def pode_descartar(self) -> bool:
        """Com mudanças não salvas, pergunta: salvar (e só segue se salvou), descartar ou cancelar."""
        if not self.projeto.modificado:
            return True
        resposta = self.dialogos.perguntar(
            self.tr("Mudanças não salvas"),
            self.tr("O projeto “{}” tem mudanças que não foram salvas. Salvar antes de continuar?")
            .format(self.projeto.nome),
            {"salvar": self.tr("Salvar"), "descartar": self.tr("Descartar")}, "salvar")
        if resposta == "salvar":
            return self.salvar()
        if resposta == "descartar":
            self._apagar_automatico()
            return True
        return False

    # ------------------------------------------------------------------ novo, abrir

    def novo(self) -> bool:
        if not self.pode_descartar():
            return False
        self._apagar_automatico()
        self.janela.trocar_projeto(Projeto())
        self.janela.avisos.remover_origem(ORIGEM_DO_PROJETO)
        return True

    def abrir(self, caminho: Path | None = None) -> bool:
        """Abre um ``.shproj`` (pede o arquivo se ``caminho`` for ``None``). Se houver um salvamento automático
        mais novo (uma queda), pergunta se quer recuperá-lo."""
        if not self.pode_descartar():
            return False
        if caminho is None:
            caminho = self.dialogos.abrir_arquivo(self.tr("Abrir projeto"), FILTRO, self._pasta_inicial())
            if caminho is None:
                return False
        caminho = Path(caminho)
        ler_de, recuperado = caminho, False
        pendente = arquivo.recuperacao_pendente(caminho)
        if pendente is not None:
            resposta = self.dialogos.perguntar(
                self.tr("Recuperar o projeto"),
                self.tr("O SH-Analyzer fechou sem salvar as últimas mudanças de “{}”. Recuperar a versão salva "
                        "automaticamente?").format(caminho.stem),
                {"recuperar": self.tr("Recuperar"), "descartar": self.tr("Abrir a última salva")}, "recuperar")
            if resposta is None:
                return False
            if resposta == "recuperar" or not caminho.is_file():
                ler_de, recuperado = pendente, True
            else:
                pendente.unlink(missing_ok=True)
        try:
            salvo = arquivo.abrir(ler_de)
        except (arquivo.ProjetoInvalido, OSError) as e:
            self._erro(self.tr("Não foi possível abrir {}: {}").format(caminho.name, e))
            if isinstance(e, FileNotFoundError):
                esquecer(CHAVE_DOS_RECENTES, str(caminho.resolve()))
            return False
        projeto, avisos = montar(salvo, caminho, caminho.parent, abrir=self._abrir_fonte)
        log.info("projeto aberto: %s%s (%d fonte(s), %d vista(s))", ler_de, " (recuperado)" if recuperado else "",
                 len(projeto.fontes), len(projeto.vistas))
        self._mostrar(projeto, salvo, avisos)
        if recuperado:
            projeto.pilha.resetClean()                # o recuperado ainda não está no arquivo principal
        self._lembrar(caminho)
        return True

    # ------------------------------------------------------------------ capturas

    def recentes_capturas(self) -> list[Path]:
        return [Path(c) for c in ler_lista(CHAVE_DAS_CAPTURAS_RECENTES)]

    def abrir_arquivos(self, caminhos=None) -> bool:
        """Ctrl+O e o arrastar e soltar: capturas (``.bin``, ``.csv``, ``.h5``) entram no projeto aberto; um projeto
        (``.shproj``) substitui o aberto (o primeiro, se vierem vários)."""
        if caminhos is None:
            caminhos = self.dialogos.abrir_arquivos(self.tr("Abrir"), FILTRO_DE_ABRIR, self._pasta_inicial())
        caminhos = [Path(c) for c in caminhos]
        projetos = [c for c in caminhos if c.suffix.lower() == arquivo.EXTENSAO]
        capturas = [c for c in caminhos if c.suffix.lower() != arquivo.EXTENSAO]
        if projetos and not self.abrir(projetos[0]):
            return False
        return bool(self.abrir_capturas(capturas)) or bool(projetos)

    def abrir_capturas(self, caminhos) -> list[FonteDoProjeto]:
        """Abre cada captura pela ``api`` e a põe no projeto (um passo de desfazer cada). Uma que não abre vira uma
        mensagem, e as outras seguem; uma que já está no projeto não entra de novo; uma sem o cabeçalho pergunta a
        taxa e os canais (cancelar a deixa de fora)."""
        abertas = []
        for caminho in map(Path, caminhos):
            ja = next((f for f in self.projeto.fontes if not f.esta_ausente and
                       f.caminho.resolve() == caminho.resolve()), None)
            if ja is not None:
                self._aviso(self.tr("{} já está aberta").format(caminho.name))
                continue
            try:
                aberta = self._abrir_perguntando(caminho)
            except (ErroSHAN, OSError) as e:
                self._erro(self.tr("Não foi possível abrir {}: {}").format(caminho.name, e))
                continue
            if aberta is None:
                continue
            fonte = FonteDoProjeto(aberta)
            self.projeto.pilha.push(AdicionarFonte(self.projeto, fonte))
            cab = aberta.captura.cabecalho
            log.info("captura aberta: %s (%s, %s, %d canal(is) a %g Hz)", caminho, aberta.captura.tipo,
                     f"cabeçalho v{cab.versao_cabecalho}" if cab is not None else "sem cabeçalho",
                     len(fonte.canais), fonte.canais[0].taxa_hz if fonte.canais else 0.0)
            lembrar(CHAVE_DAS_CAPTURAS_RECENTES, str(caminho.resolve()))
            abertas.append(fonte)
        return abertas

    def _abrir_perguntando(self, caminho: Path) -> Fonte | None:
        """Abre a captura; uma sem o cabeçalho pergunta a taxa e os canais (com a última resposta escrita) e abre com
        eles. ``None`` se o usuário cancelar; levanta ``ErroSHAN`` se não abre."""
        try:
            return self._abrir_fonte(caminho)
        except CapturaSemCabecalho as pedido:
            parametros = self.dialogos.parametros_da_captura(caminho, pedido, self._ultima_taxa_e_canais())
            if parametros is None:
                return None
            aberta = self._abrir_fonte(caminho, parametros=parametros)
            gravar(CHAVE_DA_TAXA_E_DOS_CANAIS, json.dumps({"taxa_total_hz": parametros.taxa_total_hz,
                                                           "canais": list(parametros.canais)}))
            return aberta

    @staticmethod
    def _ultima_taxa_e_canais() -> ParametrosSemCabecalho | None:
        try:
            dados = json.loads(ler_texto(CHAVE_DA_TAXA_E_DOS_CANAIS, "") or "null")
            return ParametrosSemCabecalho(dados["taxa_total_hz"], tuple(dados["canais"]))
        except (json.JSONDecodeError, TypeError, KeyError, ErroSHAN):
            return None

    def oferecer_recuperacao(self) -> bool:
        """Na partida: se o último projeto sem título ficou num salvamento automático (uma queda), pergunta se quer
        recuperá-lo. Devolve se recuperou."""
        base = pasta_de_recuperacao() / NOME_SEM_TITULO
        pendente = arquivo.recuperacao_pendente(base)
        if pendente is None:
            return False
        resposta = self.dialogos.perguntar(
            self.tr("Recuperar o projeto"),
            self.tr("O SH-Analyzer fechou sem salvar um projeto sem título. Recuperá-lo?"),
            {"recuperar": self.tr("Recuperar"), "descartar": self.tr("Descartar")}, "recuperar")
        if resposta != "recuperar":
            if resposta == "descartar":
                pendente.unlink(missing_ok=True)
            return False
        try:
            salvo = arquivo.abrir(pendente)
        except (arquivo.ProjetoInvalido, OSError) as e:
            self._erro(self.tr("Não foi possível recuperar o projeto: {}").format(e))
            return False
        projeto, avisos = montar(salvo, None, base.parent, abrir=self._abrir_fonte)
        self._mostrar(projeto, salvo, avisos)
        projeto.pilha.resetClean()
        return True

    def _mostrar(self, projeto: Projeto, salvo: arquivo.ProjetoSalvo, avisos: list[Aviso]) -> None:
        self.janela.trocar_projeto(projeto)
        self.janela.avisos.remover_origem(ORIGEM_DO_PROJETO)
        self.janela.avisos.adicionar(avisos, ORIGEM_DO_PROJETO)
        estado = salvo.layout.get("janela")
        if estado:
            try:
                self.janela.restaurar_estado(QByteArray(base64.b64decode(estado, validate=True)))
            except ValueError:
                pass                                   # o layout é só conforto: estragado, fica o atual

    # ------------------------------------------------------------------ salvar

    def salvar(self) -> bool:
        if self.projeto.caminho is None:
            return self.salvar_como()
        return self._salvar_em(self.projeto.caminho)

    def salvar_como(self, caminho: Path | None = None) -> bool:
        if caminho is None:
            sugestao = str(self.projeto.caminho or Path(self._pasta_inicial()) / f"{self.tr('projeto')}.shproj")
            caminho = self.dialogos.salvar_arquivo(self.tr("Salvar o projeto como"), FILTRO, sugestao)
            if caminho is None:
                return False
        caminho = Path(caminho)
        if caminho.suffix.lower() != arquivo.EXTENSAO:
            caminho = caminho.with_name(caminho.name + arquivo.EXTENSAO)
        sem_titulo = self.projeto.caminho is None
        if not self._salvar_em(caminho):
            return False
        if sem_titulo:
            self._apagar_automatico(pasta_de_recuperacao() / NOME_SEM_TITULO)
        self.projeto.definir_caminho(caminho)
        return True

    def _salvar_em(self, caminho: Path) -> bool:
        try:
            arquivo.salvar(self._descrever(caminho.parent), caminho)
        except (OSError, ValueError) as e:
            self._erro(self.tr("Não foi possível salvar {}: {}").format(caminho.name, e))
            return False
        self.projeto.pilha.setClean()
        log.info("projeto salvo: %s", caminho)
        self._lembrar(caminho)
        return True

    def _descrever(self, pasta: Path) -> arquivo.ProjetoSalvo:
        estado = base64.b64encode(bytes(self.janela.estado())).decode("ascii")
        return descrever(self.projeto, pasta, layout={"janela": estado},
                         versao_do_aplicativo=QApplication.instance().applicationVersion())

    # ------------------------------------------------------------------ automático

    def _base_do_automatico(self) -> Path:
        return self.projeto.caminho or pasta_de_recuperacao() / NOME_SEM_TITULO

    def salvar_automatico(self) -> Path | None:
        """Grava o salvamento automático, se houver mudanças. Um erro aqui não interrompe nada (vai para a barra
        de status): o trabalho continua, e o salvamento manual ainda funciona."""
        if not self.projeto.modificado:
            return None
        base = self._base_do_automatico()
        try:
            return arquivo.salvar_automatico(self._descrever(base.parent), base)
        except (OSError, ValueError) as e:
            log.warning("o salvamento automático em %s falhou: %s", base, e)
            self.janela.statusBar().showMessage(self.tr("Salvamento automático falhou: {}").format(e), 10_000)
            return None

    def _apagar_automatico(self, base: Path | None = None) -> None:
        arquivo.automatico(base or self._base_do_automatico()).unlink(missing_ok=True)

    # ------------------------------------------------------------------ apoio

    @staticmethod
    def _abrir_fonte(caminho: Path, **opcoes):
        """Abre uma captura com os perfis de sonda da pasta das configurações."""
        return abrir_fonte(caminho, sondas_dir=preferencias.pasta("sondas"), **opcoes)

    def _pasta_inicial(self) -> str:
        """Onde os diálogos de abrir começam: a pasta do projeto aberto; sem ele, a pasta dos dados escolhida nas
        configurações; sem ela, a do recente mais novo; senão, a padrão (``$DADOS`` ou a pessoal)."""
        if self.projeto.caminho is not None:
            return str(self.projeto.caminho.parent)
        escolhida = preferencias.pasta_escolhida("dados")
        if escolhida is not None and escolhida.is_dir():
            return str(escolhida)
        recentes = self.recentes()
        return str(recentes[0].parent) if recentes else str(preferencias.pasta_padrao("dados"))

    def _erro(self, texto: str) -> None:
        from .componentes.toast import Toast

        log.warning("%s", texto)
        Toast.mostrar(self.janela, texto, "erro", 8000)

    def _aviso(self, texto: str) -> None:
        from .componentes.toast import Toast

        Toast.mostrar(self.janela, texto, "info")
