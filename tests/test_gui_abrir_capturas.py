"""Abrir capturas e o painel do projeto (F1.4): as tarefas em segundo plano, a pirâmide e o CRC conferidos, a árvore
(conferida pelo ``QAbstractItemModelTester`` do Qt a cada mudança), o inspetor do cabeçalho, os avisos e o abrir
pelo Ctrl+O, pelo arrastar e soltar e pelos recentes. Sem tela."""

import threading

import numpy as np
import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from capturas_sinteticas import escrever_bin  # noqa: E402
from dialogos_falsos import DialogosFalsos  # noqa: E402
from PySide6.QtCore import QMimeData, QPoint, Qt, QUrl  # noqa: E402
from PySide6.QtGui import QDropEvent  # noqa: E402
from PySide6.QtTest import QAbstractItemModelTester  # noqa: E402
from sh_analyzer_gui.app import criar_aplicacao  # noqa: E402
from sh_analyzer_gui.areas.analise.arvore import PAPEL_CORES, PAPEL_DETALHE, PAPEL_TIPO, ArvoreDoProjeto  # noqa: E402
from sh_analyzer_gui.componentes.toast import Toast  # noqa: E402
from sh_analyzer_gui.dados.captura import abrir_fonte  # noqa: E402
from sh_analyzer_gui.dados.piramide import Cancelado  # noqa: E402
from sh_analyzer_gui.janela import JanelaPrincipal  # noqa: E402
from sh_analyzer_gui.modelo.comandos import AdicionarFonte, AdicionarVista, MudarTracos, RemoverFonte  # noqa: E402
from sh_analyzer_gui.modelo.objetos import FonteDoProjeto, Projeto, Vista  # noqa: E402
from sh_analyzer_gui.servicos.fontes import ServicoDeFontes  # noqa: E402
from sh_analyzer_gui.servicos.tarefas import GerenciadorDeTarefas  # noqa: E402


def captura(pasta, nome="a.bin", versao=9, n=20_000):
    pasta.mkdir(parents=True, exist_ok=True)
    t = np.arange(n) / 200_000
    return escrever_bin(pasta / nome, [np.sin(2 * np.pi * 60 * t), 0.5 * np.cos(2 * np.pi * 60 * t)],
                        canais=(0, 1), versao=versao)


# ------------------------------------------------------------------ tarefas


def test_uma_tarefa_roda_avisa_o_progresso_e_termina(qtbot):
    tarefas = GerenciadorDeTarefas()
    progresso = []

    def contar(avisar, cancelado):
        for i in range(5):
            avisar((i + 1) / 5)
        return "pronto"

    entrou = []
    tarefas.tarefaEntrou.connect(entrou.append)
    with qtbot.waitSignal(tarefas.tarefaSaiu, timeout=5000):
        tarefa = tarefas.iniciar("contar", contar, ao_progredir=lambda _t, f: progresso.append(f))
    assert entrou == [tarefa] and tarefa.estado == "concluida" and tarefa.resultado == "pronto"
    qtbot.waitUntil(lambda: progresso and progresso[-1] == 1.0)
    assert tarefas.ativas == ()


def test_cancelar_e_falhar(qtbot):
    tarefas = GerenciadorDeTarefas()
    comecou = threading.Event()

    def esperar(avisar, cancelado):
        comecou.set()
        while not cancelado():
            pass
        raise Cancelado

    tarefa = tarefas.iniciar("esperar", esperar)
    assert comecou.wait(5)
    with qtbot.waitSignal(tarefa.terminou, timeout=5000):
        tarefa.cancelar()
    assert tarefa.estado == "cancelada"

    # Uma conta de frequência do motor, cancelada, também termina "cancelada" (e não "falhou"): o Cancelado é um só.
    from supraharmonicos import api

    def welch(avisar, cancelado):
        comecou.set()
        while not cancelado():
            pass
        return api.espectro(np.zeros(100_000), 100_000.0, progresso=avisar, cancelado=cancelado)

    comecou.clear()
    tarefa = tarefas.iniciar("welch", welch)
    assert comecou.wait(5)
    with qtbot.waitSignal(tarefa.terminou, timeout=5000):
        tarefa.cancelar()
    assert tarefa.estado == "cancelada" and Cancelado is api.Cancelado

    # Um erro do motor falha a tarefa com o motivo; outra exceção é um defeito (servicos/erros.py).
    def estragado(avisar, cancelado):
        raise api.ErroSHAN("arquivo estragado")

    with qtbot.waitSignal(tarefas.tarefaSaiu, timeout=5000):
        tarefa = tarefas.iniciar("estragado", estragado)
    assert tarefa.estado == "falhou" and tarefa.erro == "arquivo estragado" and not tarefa.inesperado

    def quebrar(avisar, cancelado):
        raise ValueError("um defeito")

    with qtbot.waitSignal(tarefas.tarefaSaiu, timeout=5000):
        tarefa = tarefas.iniciar("quebrar", quebrar)
    assert tarefa.estado == "falhou" and tarefa.inesperado and tarefa.erro == "erro inesperado (ValueError: um defeito)"
    tarefas.iniciar("esperar de novo", esperar)
    assert tarefas.encerrar(5000)                                       # cancela e espera


# ------------------------------------------------------------------ o serviço das capturas


@pytest.fixture
def servico(qapp, tmp_path):
    tarefas = GerenciadorDeTarefas()
    yield ServicoDeFontes(tarefas)
    tarefas.encerrar()


def test_a_captura_ganha_a_piramide_e_o_crc_conferido(servico, tmp_path, qtbot):
    projeto = Projeto()
    servico.acompanhar(projeto)
    fonte = FonteDoProjeto(abrir_fonte(captura(tmp_path)))
    estados = []
    fonte.estadoMudou.connect(lambda f: estados.append((f.progresso_da_piramide, f.integridade)))
    projeto.pilha.push(AdicionarFonte(projeto, fonte))
    qtbot.waitUntil(lambda: fonte.integridade == "confere", timeout=10_000)
    assert len(fonte.piramides) == 2 and fonte.progresso_da_piramide is None
    assert estados[0] == (0.0, "pendente") and (None, "conferindo") in estados
    # Desfazer e refazer a abertura não refaz o trabalho.
    projeto.pilha.undo()
    projeto.pilha.redo()
    assert servico.tarefas.ativas == ()


def test_o_crc_que_nao_confere_e_a_captura_sem_crc(servico, tmp_path, qtbot):
    projeto = Projeto()
    servico.acompanhar(projeto)
    caminho = captura(tmp_path, "alterada.bin")
    dados = bytearray(caminho.read_bytes())
    dados[-5] ^= 0x40
    caminho.write_bytes(bytes(dados))
    alterada = FonteDoProjeto(abrir_fonte(caminho))
    antiga = FonteDoProjeto(abrir_fonte(captura(tmp_path, "v3.bin", versao=3)))
    for fonte in (alterada, antiga):
        projeto.pilha.push(AdicionarFonte(projeto, fonte))
    try:
        qtbot.waitUntil(lambda: alterada.integridade == "nao_confere" and antiga.integridade == "sem_crc",
                        timeout=10_000)
    except Exception:
        pytest.fail(f"alterada: {alterada.integridade}, pirâmide {alterada.piramides is not None}, progresso "
                    f"{alterada.progresso_da_piramide}; antiga: {antiga.integridade}, pirâmide "
                    f"{antiga.piramides is not None}, progresso {antiga.progresso_da_piramide}; tarefas "
                    f"{servico.tarefas.ativas}")


# ------------------------------------------------------------------ a árvore


def test_a_arvore_segue_o_projeto_sem_quebrar_o_contrato_do_modelo(qapp, tmp_path):
    projeto = Projeto()
    modelo = ArvoreDoProjeto(projeto)
    QAbstractItemModelTester(modelo, QAbstractItemModelTester.FailureReportingMode.Fatal)
    assert modelo.rowCount() == 2 and modelo.rowCount(modelo.index(0, 0)) == 0
    a = FonteDoProjeto(abrir_fonte(captura(tmp_path, "a.bin")))
    b = FonteDoProjeto(abrir_fonte(captura(tmp_path, "b.bin")))
    for fonte in (a, b):
        projeto.pilha.push(AdicionarFonte(projeto, fonte))
    grupo_fontes = modelo.index(0, 0)
    assert modelo.rowCount(grupo_fontes) == 2 and grupo_fontes.data(PAPEL_DETALHE) == "2"
    indice_a = modelo.index(0, 0, grupo_fontes)
    assert indice_a.data() == "a.bin" and "400 kS/s · 2 canais" in indice_a.data(PAPEL_DETALHE)
    canal = modelo.index(1, 0, indice_a)
    assert canal.data() == "canal 1" and canal.data(PAPEL_TIPO) == "canal" and canal.data(PAPEL_CORES) == []

    vista = Vista("Tempo")
    projeto.pilha.push(AdicionarVista(projeto, vista))
    from sh_analyzer_gui.areas.analise.area import AreaDeAnalise  # noqa: F401  (o plotar é testado na janela)
    from sh_analyzer_gui.dados.receita import ReceitaDoTraco
    from sh_analyzer_gui.modelo.comandos import AdicionarTraco
    from sh_analyzer_gui.modelo.objetos import Traco

    traco = Traco(ReceitaDoTraco(a.id, 1, "V", 0))
    projeto.pilha.push(AdicionarTraco(vista, traco))
    assert canal.data(PAPEL_CORES) == [0] and modelo.index(0, 0, modelo.index(1, 0)).data(PAPEL_DETALHE) == "1 traço"
    projeto.pilha.push(MudarTracos([traco], cor=4))
    assert canal.data(PAPEL_CORES) == [4]

    projeto.pilha.push(RemoverFonte(projeto, a))                         # tira a fonte e o traço dela
    assert modelo.rowCount(grupo_fontes) == 1 and modelo.index(0, 0, grupo_fontes).data() == "b.bin"
    projeto.pilha.undo()
    assert modelo.rowCount(grupo_fontes) == 2 and modelo.index(0, 0, grupo_fontes).data() == "a.bin"
    for _ in range(projeto.pilha.count()):
        projeto.pilha.undo()
    assert modelo.rowCount(grupo_fontes) == 0 and modelo.rowCount(modelo.index(1, 0)) == 0


# ------------------------------------------------------------------ a janela


@pytest.fixture
def janela(qapp, config_limpa):
    criar_aplicacao([], tema="escuro")
    j = JanelaPrincipal()
    j.controle.dialogos = DialogosFalsos()
    j.show()
    yield j
    j.projeto.pilha.setClean()
    j.close()
    j.deleteLater()


def test_abrir_uma_captura_na_janela(janela, tmp_path, qtbot):
    (fonte,) = janela.controle.abrir_capturas([captura(tmp_path)])
    assert janela.projeto.fontes == (fonte,) and janela.projeto.pilha.undoText() == "Abrir a.bin"
    qtbot.waitUntil(lambda: fonte.integridade == "confere", timeout=10_000)
    painel = janela.painel_projeto
    assert painel.pilha.currentWidget() is painel.arvore
    assert janela.inspetor.currentWidget() is janela.inspetor.da_fonte       # a captura aberta fica selecionada
    valores = janela.inspetor.da_fonte.valores
    assert valores["Captura/Cabeçalho"] == "v9" and valores["Canais/Canal 0"].startswith("tensão")
    assert "CRC das amostras conferido" in janela.inspetor.da_fonte.estado_integridade.text()
    assert janela.status_fonte.text().startswith("a.bin · 400 kS/s · 2 canais · cabeçalho v9 · pirâmide pronta")
    assert janela.status_integridade.text() == "✓ integridade"
    assert janela.controle.recentes_capturas()[0] == (tmp_path / "a.bin").resolve()

    janela.controle.abrir_capturas([tmp_path / "a.bin"])                      # de novo: não entra
    assert len(janela.projeto.fontes) == 1
    assert any("já está aberta" in t.rotulo.text() for t in janela.findChildren(Toast))
    estragado = tmp_path / "estragado.bin"
    estragado.write_bytes(b"\x00" * 100)
    assert janela.controle.abrir_capturas([estragado]) == []
    assert any("Não foi possível abrir estragado.bin" in t.rotulo.text() for t in janela.findChildren(Toast))


def test_plotar_um_canal_cria_a_vista_num_passo_so(janela, tmp_path):
    (fonte,) = janela.controle.abrir_capturas([captura(tmp_path)])
    contagem = janela.projeto.pilha.count()
    with_signal = []
    janela.painel_projeto.canalAtivado.connect(lambda f, n: with_signal.append((f, n)))
    modelo = janela.painel_projeto.modelo
    indice = janela.painel_projeto.proxy.mapFromSource(modelo.indice_do_canal(fonte, 1))
    janela.painel_projeto._duplo_clique(indice)
    assert with_signal == [(fonte, 1)]
    (vista,) = janela.projeto.vistas
    (traco,) = vista.tracos
    assert (traco.receita.canal, traco.receita.cor, traco.nome) == (1, 0, "canal 1 · a")
    assert janela.projeto.pilha.count() == contagem + 1 and janela.projeto.pilha.undoText() == "Plotar canal 1 · a"
    janela.area.plotar_canal(fonte, 0)
    assert [t.receita.cor for t in vista.tracos] == [0, 1] and len(janela.projeto.vistas) == 1
    janela.projeto.pilha.undo()
    janela.projeto.pilha.undo()
    assert janela.projeto.vistas == ()                                   # um desfazer tira o traço e a vista


def test_os_avisos_da_captura_vao_para_o_painel_e_saem_com_ela(janela, tmp_path):
    caminho = captura(tmp_path)
    janela.controle.abrir_capturas([caminho])
    fonte = janela.projeto.fontes[0]
    avisos = fonte.fonte.captura.avisos
    assert [a for a, _ in janela.avisos.avisos] == list(avisos)
    if avisos:
        assert janela.avisos.lista.item(0).text().startswith("a.bin: ")
    janela.area.fechar_fonte(fonte)
    assert janela.projeto.fontes == () and janela.avisos.avisos == []
    janela.projeto.pilha.undo()
    assert [a for a, _ in janela.avisos.avisos] == list(avisos)


def test_ctrl_o_abre_capturas_e_projetos(janela, tmp_path):
    a, b = captura(tmp_path, "a.bin"), captura(tmp_path, "b.bin")
    janela.controle.dialogos = DialogosFalsos([a, b])
    janela.acoes["abrir"].trigger()
    assert [f.nome for f in janela.projeto.fontes] == ["a.bin", "b.bin"]
    assert janela.controle.salvar_como(tmp_path / "p.shproj")
    janela.controle.novo()
    janela.controle.dialogos = DialogosFalsos([tmp_path / "p.shproj"])
    janela.acoes["abrir"].trigger()
    assert janela.projeto.caminho == tmp_path / "p.shproj" and len(janela.projeto.fontes) == 2
    janela.controle.dialogos = DialogosFalsos([])                       # cancelado
    janela.acoes["abrir"].trigger()


def test_arrastar_e_soltar_uma_captura(janela, tmp_path):
    caminho = captura(tmp_path)
    dados = QMimeData()
    dados.setUrls([QUrl.fromLocalFile(str(caminho))])
    evento = QDropEvent(QPoint(10, 10), Qt.DropAction.CopyAction, dados, Qt.MouseButton.LeftButton,
                        Qt.KeyboardModifier.NoModifier)
    janela.dropEvent(evento)
    assert [f.nome for f in janela.projeto.fontes] == ["a.bin"]


def test_as_capturas_recentes_no_menu(janela, tmp_path):
    janela.controle.abrir_capturas([captura(tmp_path, "a.bin"), captura(tmp_path, "b.bin")])
    janela._preencher_recentes()
    assert [a.text() for a in janela.menu_capturas_recentes.actions()] == ["b.bin", "a.bin"]
    janela.projeto.pilha.setClean()
    janela.controle.novo()
    janela.menu_capturas_recentes.actions()[1].trigger()
    assert [f.nome for f in janela.projeto.fontes] == ["a.bin"]


def test_a_captura_ausente_no_painel_e_no_inspetor(janela, tmp_path):
    caminho = captura(tmp_path)
    janela.controle.abrir_capturas([caminho])
    assert janela.controle.salvar_como(tmp_path / "p.shproj")
    caminho.unlink()
    assert janela.controle.abrir(tmp_path / "p.shproj")
    (fonte,) = janela.projeto.fontes
    assert fonte.esta_ausente
    indice = janela.painel_projeto.modelo.indice_da_fonte(fonte)
    assert indice.data(PAPEL_DETALHE) == "ausente" and janela.painel_projeto.modelo.rowCount(indice) == 0
    janela.inspetor.mostrar("fonte", fonte)
    assert janela.status_fonte.text() == "a.bin: ausente"
    janela.painel_projeto.arvore.grab()                                  # o delegado pinta a ausente sem erro


def test_uma_tarefa_rapida_nao_perde_o_fim(qtbot):
    """Os ouvintes são ligados antes de a tarefa começar: uma tarefa que termina na hora não perde o ``terminou``
    (o erro: a conferência de uma captura sem CRC ficava "conferindo" para sempre). E o gerenciador ouve primeiro:
    no ``ao_terminar``, a tarefa já saiu das ativas (antes, às vezes a última ainda estava lá)."""
    tarefas = GerenciadorDeTarefas(threads=8)
    fins = []
    for k in range(200):
        tarefas.iniciar(f"rápida {k}", lambda _p, _c, k=k: k, mostrar=False,
                        ao_terminar=lambda t: fins.append((t.resultado, t in tarefas.ativas)))
    qtbot.waitUntil(lambda: len(fins) == 200, timeout=10_000)
    assert sorted(fins) == [(k, False) for k in range(200)] and tarefas.ativas == ()


def test_depois_de_encerrar_nenhuma_tarefa_comeca(qtbot):
    """Um temporizador atrasado (a medida da vista) não põe uma thread para rodar com a janela sendo apagada."""
    tarefas = GerenciadorDeTarefas()
    assert tarefas.encerrar()
    rodou = []
    tarefa = tarefas.iniciar("tarde demais", lambda _p, _c: rodou.append(True))
    qtbot.wait(50)
    assert tarefa.estado == "cancelada" and rodou == [] and tarefas.ativas == ()


def test_a_coleta_de_lixo_so_na_thread_da_interface(qapp):
    """A automática do Python roda em qualquer thread e apagava widgets fora da thread da interface (um
    segmentation fault). A aplicação a desliga e coleta num temporizador do Qt."""
    import gc

    criar_aplicacao([])
    assert not gc.isenabled() and qapp._coletor_de_lixo.timer.isActive()
    coletor = qapp._coletor_de_lixo
    criar_aplicacao([])
    assert qapp._coletor_de_lixo is coletor                              # um só por aplicação
