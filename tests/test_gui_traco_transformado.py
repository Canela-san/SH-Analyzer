"""O traço com transformações na vista de tempo (F2.3): a prévia enquanto a materialização roda, a troca para ela
quando fica pronta, nunca o canal cru no lugar do transformado, a materialização dividida e cancelada sem ninguém,
e as medidas do sinal transformado. Sem tela."""

import threading

import numpy as np
import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from capturas_sinteticas import escrever_bin  # noqa: E402
from dialogos_falsos import DialogosFalsos  # noqa: E402
from sh_analyzer_gui.app import criar_aplicacao  # noqa: E402
from sh_analyzer_gui.dados import materializacao as mat  # noqa: E402
from sh_analyzer_gui.dados.cadeia import Cadeia, Filtro, RemoverDC  # noqa: E402
from sh_analyzer_gui.janela import JanelaPrincipal  # noqa: E402
from sh_analyzer_gui.modelo.comandos import MudarTracos  # noqa: E402
from sh_analyzer_gui.servicos.medidas import PedidoDeMedida  # noqa: E402
from supraharmonicos import api  # noqa: E402

FS = 200_000.0
N = 400_000                                   # 2 s por canal: a janela inteira cabe na prévia
PA = Cadeia((Filtro("passa_altas", (1000.0,), 4),))


def captura(pasta):
    t = np.arange(N) / FS
    v = 0.2 + 3.0 * np.sin(2 * np.pi * 50 * t) + 0.05 * np.sin(2 * np.pi * 7_000 * t)
    return escrever_bin(pasta / "c.bin", [v, 0.5 * np.cos(2 * np.pi * 50 * t)], grandezas=(0, 1), versao=9)


class CacheLento(mat.CacheDeMaterializacoes):
    """Segura a materialização até ``liberar`` (para ver a prévia no lugar dela)."""

    def __init__(self, pasta, liberar: threading.Event):
        super().__init__(pasta)
        self.liberar = liberar

    def obter(self, *args, cancelado=None, **kwargs):
        while not self.liberar.wait(0.01):
            if cancelado is not None and cancelado():
                raise api.Cancelado()
        return super().obter(*args, cancelado=cancelado, **kwargs)


@pytest.fixture
def janela(qapp, config_limpa, qtbot, tmp_path):
    criar_aplicacao([], tema="escuro")
    j = JanelaPrincipal()
    j.controle.dialogos = DialogosFalsos()
    j.resize(1400, 900)
    j.show()
    qtbot.waitExposed(j)
    yield j
    j.projeto.pilha.setClean()
    j.close()
    j.deleteLater()


def plotar(janela, qtbot, tmp_path):
    (fonte,) = janela.controle.abrir_capturas([captura(tmp_path)])
    qtbot.waitUntil(lambda: fonte.piramides is not None, timeout=10_000)
    janela.area.plotar_canal(fonte, 0)
    vista = janela.vista_ativa()
    return fonte, vista, vista.tracos[0], janela.area.widget_da_vista(vista)


def transformado(fonte, cadeia):
    captura = fonte.fonte.captura
    contexto = mat.contexto_do_canal(captura.canal(0), mat.media_do_canal(captura.canal(0)))
    return cadeia.aplicar(api.sinal_do_canal(captura, 0), contexto).valores


def test_a_previa_e_depois_a_materializacao(janela, qtbot, tmp_path):
    liberar = threading.Event()
    janela.materializacoes.cache = CacheLento(tmp_path / "cache", liberar)
    fonte, vista, traco, w = plotar(janela, qtbot, tmp_path)
    cru = w.itens[traco].dados[0]
    antes = w.faixas[0].getViewBox().viewRange()
    janela.projeto.pilha.push(MudarTracos([traco], cadeia=PA))
    item = w.itens[traco]
    assert item.dados[0] is not cru                        # o canal cru sai na hora: nunca no lugar do transformado
    qtbot.waitUntil(lambda: traco in w._previas, timeout=10_000)
    previa = w._previas[traco]
    inteiro = transformado(fonte, PA)
    np.testing.assert_allclose(previa.amostras, inteiro[previa.inicio:previa.fim], rtol=1e-9,
                               atol=1e-9 * np.max(np.abs(inteiro)))
    assert item.dados[0] is previa.piramide and item.dados[2] == previa.inicio
    assert "PA 1 kHz" in w.chips[traco].resumo and w.chips[traco].progresso is not None
    estado = janela.materializacoes.estado_de(traco)
    assert estado.pronta is None

    liberar.set()
    qtbot.waitUntil(lambda: estado.pronta is not None, timeout=20_000)
    qtbot.waitUntil(lambda: item.dados[0] is estado.pronta.piramide, timeout=5_000)
    np.testing.assert_allclose(estado.pronta.amostras, inteiro, rtol=2 ** -23, atol=2 ** -23 * np.max(np.abs(inteiro)))
    assert w.chips[traco].progresso is None and traco not in w._previas
    # A vista fica onde estava (docs/gui-plan.md, 9.2): o passa-altas tirou os 3 V da rede, mas os 7 kHz que ficam
    # ainda estão dentro dela. O F ajusta o Y, se o usuário quiser.
    for eixo, faixa in zip(w.faixas[0].getViewBox().viewRange(), antes, strict=True):
        assert eixo == pytest.approx(faixa)

    janela.projeto.pilha.undo()                            # sem a cadeia: o canal cru de novo
    assert item.dados[0] is cru and janela.materializacoes.estado_de(traco) is None


def test_as_materializacoes_rodam_uma_de_cada_vez_e_a_que_espera_diz_na_fila(janela, qtbot, tmp_path):
    """Os dois canais com a mesma cadeia: duas materializações. A segunda espera a primeira (as duas juntas engasgavam
    o desenho), e o chip do traço e o painel de tarefas dizem "na fila" enquanto isso."""
    liberar = threading.Event()
    janela.materializacoes.cache = CacheLento(tmp_path / "cache", liberar)
    fonte, vista, traco0, w = plotar(janela, qtbot, tmp_path)
    traco1 = janela.area.plotar_canal(fonte, 1)
    janela.projeto.pilha.push(MudarTracos([traco0, traco1], cadeia=PA))
    estados = [janela.materializacoes.estado_de(t) for t in (traco0, traco1)]
    qtbot.waitUntil(lambda: sorted(e.tarefa.estado for e in estados) == ["esperando", "rodando"], timeout=5000)
    primeiro, segundo = sorted(estados, key=lambda e: e.na_fila)
    assert (primeiro.na_fila, segundo.na_fila) == (False, True)
    chip = {e: w.chips[t] for e, t in zip(estados, (traco0, traco1), strict=True)}
    assert "na fila" in chip[segundo].resumo and "na fila" not in chip[primeiro].resumo
    linhas = {linha.tarefa: linha for linha in janela.lista_de_tarefas.linhas}
    # O "começou" chega pela fila de eventos, depois de a tarefa já estar rodando na thread de trabalho.
    qtbot.waitUntil(lambda: linhas[primeiro.tarefa].na_fila.isHidden(), timeout=5000)
    assert not linhas[primeiro.tarefa].barra.isHidden()
    assert linhas[segundo.tarefa].barra.isHidden() and not linhas[segundo.tarefa].na_fila.isHidden()

    liberar.set()
    qtbot.waitUntil(lambda: all(e.pronta is not None for e in estados), timeout=20_000)
    assert all("na fila" not in chip[e].resumo for e in estados)


def test_a_materializacao_e_dividida_e_cancelada_sem_ninguem(janela, qtbot, tmp_path):
    liberar = threading.Event()
    janela.materializacoes.cache = CacheLento(tmp_path / "cache", liberar)
    fonte, *_ = plotar(janela, qtbot, tmp_path)
    servico = janela.materializacoes
    a = servico.acompanhar("a", fonte, 0, PA)
    b = servico.acompanhar("b", fonte, 0, Cadeia((*PA.etapas, RemoverDC(ligada=False))))
    assert a is b                                          # a etapa desligada não muda o resultado
    servico.largar("a")
    assert a.tarefa.ativa
    servico.largar("b")
    qtbot.waitUntil(lambda: a.tarefa.estado == "cancelada", timeout=5_000)
    liberar.set()


def test_as_medidas_sao_as_do_sinal_transformado(janela, qtbot, tmp_path):
    janela.materializacoes.cache = mat.CacheDeMaterializacoes(tmp_path / "cache")
    fonte, vista, traco, w = plotar(janela, qtbot, tmp_path)
    cadeia = Cadeia((RemoverDC(), Filtro("passa_baixas", (2000.0,), 4)))
    janela.projeto.pilha.push(MudarTracos([traco], cadeia=cadeia))
    estado = janela.materializacoes.estado_de(traco)
    qtbot.waitUntil(lambda: estado.pronta is not None, timeout=20_000)    # a média do canal já é conhecida
    servico = janela.area.servico_de_medidas
    qtbot.wait(400)                       # o pedido automático da vista (a janela visível) sai antes do nosso
    pedido = PedidoDeMedida(vista, 0.5, 1.5, True)
    with qtbot.waitSignal(servico.prontas, timeout=10_000, check_params_cb=lambda p, _m: p is pedido) as sinal:
        servico.medir(janela.projeto, pedido)
    (medida,) = [m for m in sinal.args[1] if m.traco is traco]
    inteiro = transformado(fonte, cadeia)
    esperado = api.medir_sinal(inteiro[100_000:300_000], FS)
    assert medida.medidas.rms == pytest.approx(esperado.rms, rel=1e-9)
    assert medida.medidas.media == pytest.approx(esperado.media, abs=1e-9)
    assert abs(medida.medidas.media) < 1e-3                # o DC do canal inteiro saiu (0,2 V)


def test_a_medida_de_uma_regiao_maior_que_a_previa_espera_a_vez(janela, qtbot, tmp_path, monkeypatch):
    """Num traço transformado, medir uma região maior que a prévia é uma conta do tamanho da materialização: o pedido
    vai para a fila das pesadas e espera a materialização que roda (as duas juntas engasgavam o desenho). Uma região
    pequena é medida na hora, ao lado dela."""
    from sh_analyzer_gui.servicos import medidas
    monkeypatch.setattr(medidas, "LIMITE_DA_PREVIA", 50_000)
    liberar = threading.Event()
    janela.materializacoes.cache = CacheLento(tmp_path / "cache", liberar)
    fonte, vista, traco, w = plotar(janela, qtbot, tmp_path)
    janela.projeto.pilha.push(MudarTracos([traco], cadeia=PA))
    estado = janela.materializacoes.estado_de(traco)
    qtbot.waitUntil(lambda: estado.tarefa.estado == "rodando", timeout=5000)
    servico = janela.area.servico_de_medidas
    qtbot.wait(400)                       # o pedido automático da vista (a janela visível) sai antes dos nossos

    pequena = PedidoDeMedida(vista, 0.5, 0.6, True)                     # 20 000 amostras
    with qtbot.waitSignal(servico.prontas, timeout=10_000, check_params_cb=lambda p, _m: p is pequena):
        tarefa = servico.medir(janela.projeto, pequena)
    assert not tarefa.pesada and estado.tarefa.estado == "rodando"     # medida com a materialização rodando

    grande = PedidoDeMedida(vista, 0.0, 2.0, True)                      # a captura inteira: 400 000 amostras
    tarefa = servico.medir(janela.projeto, grande)
    assert tarefa.pesada
    qtbot.wait(200)
    assert tarefa.estado == "esperando" and estado.pronta is None
    with qtbot.waitSignal(servico.prontas, timeout=20_000, check_params_cb=lambda p, _m: p is grande) as sinal:
        liberar.set()
    assert estado.pronta is not None                                    # a materialização terminou antes
    (medida,) = [m for m in sinal.args[1] if m.traco is traco]
    esperado = api.medir_sinal(transformado(fonte, PA), FS)
    assert medida.medidas.rms == pytest.approx(esperado.rms, rel=1e-9)
