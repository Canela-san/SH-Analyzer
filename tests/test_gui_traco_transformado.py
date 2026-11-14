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
    # O Y da faixa ajustado ao traço transformado (o passa-altas tirou os 3 V da rede).
    y0, y1 = w.faixas[0].getViewBox().viewRange()[1]
    assert y1 - y0 < 1.0

    janela.projeto.pilha.undo()                            # sem a cadeia: o canal cru de novo
    assert item.dados[0] is cru and janela.materializacoes.estado_de(traco) is None


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
    with qtbot.waitSignal(servico.prontas, timeout=10_000) as sinal:
        servico.medir(janela.projeto, PedidoDeMedida(vista, 0.5, 1.5, True))
    (medida,) = [m for m in sinal.args[1] if m.traco is traco]
    inteiro = transformado(fonte, cadeia)
    esperado = api.medir_sinal(inteiro[100_000:300_000], FS)
    assert medida.medidas.rms == pytest.approx(esperado.rms, rel=1e-9)
    assert medida.medidas.media == pytest.approx(esperado.media, abs=1e-9)
    assert abs(medida.medidas.media) < 1e-3                # o DC do canal inteiro saiu (0,2 V)
