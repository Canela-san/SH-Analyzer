"""O log e o erro inesperado (F2.8, GE-09): o log em rotação na pasta pedida; um defeito numa tarefa, num slot ou
noutra thread abre o diálogo (não modal, com os detalhes copiáveis e o caminho do log) e o aplicativo segue; um erro
esperado (o do motor, o de arquivo) fica no lugar dele, sem diálogo. Sem tela."""

import logging
import threading

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from dialogos_falsos import DialogosFalsos  # noqa: E402
from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402
from sh_analyzer_gui import registro  # noqa: E402
from sh_analyzer_gui.app import criar_aplicacao  # noqa: E402
from sh_analyzer_gui.janela import JanelaPrincipal  # noqa: E402
from sh_analyzer_gui.servicos import erros  # noqa: E402
from supraharmonicos import api  # noqa: E402


@pytest.fixture
def log_ligado(tmp_path):
    ligado = registro.ligar_o_log(tmp_path / "log", terminal=False, qt=False)
    yield ligado
    ligado.desligar()


@pytest.fixture
def janela(qapp, config_limpa, qtbot):
    criar_aplicacao([], tema="escuro")
    j = JanelaPrincipal()
    j.controle.dialogos = DialogosFalsos()
    j.show()
    qtbot.waitExposed(j)
    yield j
    j.projeto.pilha.setClean()
    j.close()
    j.deleteLater()


def dialogo_aberto(janela):
    return janela.dialogo_de_erro is not None and janela.dialogo_de_erro.isVisible()


def test_o_log_fica_na_pasta_e_gira(tmp_path, monkeypatch):
    monkeypatch.setenv(registro.VARIAVEL_DA_PASTA, str(tmp_path / "outra"))
    assert registro.pasta_do_log() == tmp_path / "outra"
    monkeypatch.setattr(registro, "TAMANHO_MAXIMO", 4000)
    ligado = registro.ligar_o_log(tmp_path / "log", terminal=False, qt=False)
    manipuladores = list(ligado._manipuladores)
    try:
        assert registro.caminho_do_log() == ligado.caminho == tmp_path / "log" / "sh-analyzer.log"
        assert "Python" in ligado.caminho.read_text(encoding="utf-8")           # a linha do ambiente, no começo
        interface = logging.getLogger("sh_analyzer_gui.teste")
        for i in range(400):
            interface.info("linha %d da interface", i)
        logging.getLogger("uma_biblioteca").info("o INFO de uma biblioteca não entra")
        logging.getLogger("uma_biblioteca").warning("o aviso de uma biblioteca entra")
        arquivos = sorted(p.name for p in (tmp_path / "log").glob("sh-analyzer.log*"))
        assert arquivos == ["sh-analyzer.log", *(f"sh-analyzer.log.{k}" for k in range(1, registro.COPIAS + 1))]
        assert all(p.stat().st_size <= 4000 for p in (tmp_path / "log").glob("sh-analyzer.log*"))
        atual = ligado.caminho.read_text(encoding="utf-8")
        assert "linha 399 da interface" in atual and "o aviso de uma biblioteca entra" in atual
        assert "não entra" not in atual
    finally:
        ligado.desligar()
    assert registro.caminho_do_log() is None
    assert manipuladores and not set(manipuladores) & set(logging.getLogger().handlers)


def test_uma_pasta_que_nao_se_cria_nao_impede_de_abrir(tmp_path):
    arquivo = tmp_path / "um_arquivo"
    arquivo.write_text("")
    ligado = registro.ligar_o_log(arquivo / "log", terminal=False, qt=False)     # dentro de um arquivo: não cria
    try:
        assert not ligado.no_arquivo and registro.caminho_do_log() is None
    finally:
        ligado.desligar()


def test_um_erro_repetido_nao_enche_o_log(caplog):
    def quebrar(i):
        raise ZeroDivisionError(f"divisão {i}")

    with caplog.at_level(logging.ERROR, logger=erros.__name__):
        for i in range(9):
            try:
                quebrar(i)
            except ZeroDivisionError as e:
                erros.relatar(e, "num teste")
    registros = [r for r in caplog.records if r.name == erros.__name__]
    assert [r.exc_info is not None for r in registros] == [True, False, False, False]   # a 1ª inteira; a 2ª, 4ª, 8ª
    assert "8ª vez" in registros[-1].getMessage() and "divisão 7" in registros[-1].getMessage()


def test_um_erro_numa_tarefa_abre_o_dialogo_e_o_aplicativo_segue(janela, qtbot, log_ligado):
    def quebrar(_progresso, _cancelado):
        return {}["chave que não existe"]

    tarefa = janela.tarefas.iniciar("Uma conta com defeito", quebrar)
    qtbot.waitUntil(lambda: dialogo_aberto(janela), timeout=5_000)
    assert tarefa.estado == "falhou" and tarefa.inesperado and "KeyError" in tarefa.erro
    d = janela.dialogo_de_erro
    assert not d.isModal()
    assert "KeyError" in d.resumo.text() and "na tarefa 'Uma conta com defeito'" in d.resumo.text()
    assert "Traceback" in d.detalhes.toPlainText() and "in quebrar" in d.detalhes.toPlainText()
    assert str(log_ligado.caminho) in d.log.text() and d.abrir_pasta.isVisible()
    d.copiar.click()
    assert QGuiApplication.clipboard().text() == d.texto() and "Python" in d.texto()
    assert "chave que não existe" in log_ligado.caminho.read_text(encoding="utf-8")   # a pilha foi para o log

    # O mesmo erro de novo: conta, não abre outro diálogo.
    janela.tarefas.iniciar("Uma conta com defeito", quebrar)
    qtbot.waitUntil(lambda: d.ocorrencias == 2, timeout=5_000)
    assert janela.dialogo_de_erro is d and "2 vezes" in d.resumo.text() and len(d.erros) == 1

    # O aplicativo segue: outra tarefa roda, e o trabalho continua.
    ok = janela.tarefas.iniciar("Uma conta boa", lambda _p, _c: 42)
    qtbot.waitUntil(lambda: ok.estado == "concluida", timeout=5_000)
    assert ok.resultado == 42 and janela.isVisible()

    # Fechado, o próximo erro abre um diálogo novo, só com ele.
    d.reject()
    assert janela.dialogo_de_erro is None
    janela.tarefas.iniciar("Outra conta com defeito", lambda _p, _c: 1 / 0)
    qtbot.waitUntil(lambda: dialogo_aberto(janela), timeout=5_000)
    assert janela.dialogo_de_erro is not d and janela.dialogo_de_erro.ocorrencias == 1
    assert "ZeroDivisionError" in janela.dialogo_de_erro.resumo.text()


def test_um_erro_esperado_fica_no_lugar_dele_sem_dialogo(janela, qtbot):
    def do_motor(_p, _c):
        raise api.ErroSHAN("o corte de 300 kHz passa da Nyquist")

    def de_arquivo(_p, _c):
        raise FileNotFoundError(2, "Arquivo não encontrado", "/sumiu.bin")

    tarefas = [janela.tarefas.iniciar("Motor", do_motor), janela.tarefas.iniciar("Arquivo", de_arquivo)]
    qtbot.waitUntil(lambda: all(t.estado == "falhou" for t in tarefas), timeout=5_000)
    qtbot.wait(50)                                       # o que estivesse na fila de eventos já teria chegado
    assert janela.dialogo_de_erro is None
    assert tarefas[0].erro == "o corte de 300 kHz passa da Nyquist" and not tarefas[0].inesperado
    assert "sumiu.bin" in tarefas[1].erro and not tarefas[1].inesperado


@pytest.mark.qt_no_exception_capture
def test_um_erro_num_slot_ou_noutra_thread_abre_o_dialogo(janela, qtbot):
    tirar = erros.instalar_ganchos()
    try:
        def slot_com_defeito():
            raise ValueError("um slot com defeito")

        QTimer.singleShot(0, slot_com_defeito)
        qtbot.waitUntil(lambda: dialogo_aberto(janela), timeout=5_000)
        d = janela.dialogo_de_erro
        assert "ValueError: um slot com defeito na thread da interface" in d.resumo.text()

        def thread_com_defeito():
            raise RuntimeError("uma thread com defeito")

        t = threading.Thread(target=thread_com_defeito, name="Trabalho")
        t.start()
        t.join()
        qtbot.waitUntil(lambda: d.diferentes == 2, timeout=5_000)
        assert "na thread Trabalho" in d.resumo.text() and "2 erros diferentes" in d.resumo.text()
        assert janela.isVisible()
    finally:
        tirar()
