"""A interface gráfica (``supraharmonicos.gui``), sem tela: o Qt em ``offscreen``.

O que se confere é a ligação da janela com o resto do pacote, não o desenho: os controles viram a linha de comando
certa (a mesma que o ``adc_tool.py`` aceita), a análise roda fora da thread da janela e chega às figuras e às
tabelas, os erros de domínio viram mensagem (não traceback) e a exportação grava os mesmos arquivos da CLI.
Sem o PyQt6 (o extra ``gui``), o módulo inteiro é pulado."""

import json
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PyQt6.QtWidgets")

from capturas_sinteticas import FREQS_CAL, captura_producao, planta_h  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402
from supraharmonicos.gui import JanelaPrincipal, resumo_html  # noqa: E402
from supraharmonicos.opcoes_analise import montar_parser  # noqa: E402

pytestmark = pytest.mark.gui


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication(["pytest"])


@pytest.fixture(scope="module")
def ambiente(tmp_path_factory):
    base = tmp_path_factory.mktemp("gui")
    sondas = base / "sondas"
    sondas.mkdir()
    perfil = {"id": "sonda_teste", "tipo": "resposta_frequencia",
              "pontos": [{"freq_hz": float(f), "ganho": float(planta_h(f))} for f in FREQS_CAL]}
    (sondas / "sonda_teste.json").write_text(json.dumps(perfil), encoding="utf-8")
    captura_producao(base / "ok.bin", dur_s=0.3)      # 2 canais a 400 kS/s: o 1 é de corrente, com a sonda
    return base


@pytest.fixture
def janela(app, ambiente):
    j = JanelaPrincipal(silencioso=True)
    j.parametros.sondas_dir.setText(str(ambiente / "sondas"))
    yield j
    j.aguardar()
    j.close()


def _analisar(janela):
    assert janela.analisar(), janela.ultimo_erro
    assert janela.aguardar(120_000)
    return janela.resultado


def test_abrir_preenche_o_painel_e_o_comando_equivalente(janela, ambiente):
    assert janela.abrir(ambiente / "ok.bin")
    janela.aguardar()                                     # a captura é curta: a janela já a analisa ao abrir
    assert janela.parametros.canais == [0, 1] and janela.parametros.canais_exibir == [0, 1]
    resumo = janela.parametros.resumo.text()
    assert "Título" in resumo and "teste" in resumo and "sonda sonda_teste" in resumo and "confere" in resumo
    assert not janela.parametros.grupo_sem_cabecalho.isVisible()
    comando = janela.comando.text()
    assert comando.startswith("uv run scripts/adc_tool.py") and "ok.bin" in comando and "--sondas-dir" in comando
    assert janela.resultado is not None and janela.figura_principal.figura.axes
    assert "usando a frequência: 400000 Hz" in janela.console.toPlainText()


def test_controles_viram_as_flags_da_cli(janela, ambiente):
    janela.abrir(ambiente / "ok.bin")
    janela.aguardar()
    p = janela.parametros
    p.aplicar_preset("supraharmonicos")
    p.resolucao_welch.setValue(100)
    p.picos_db.setValue(-40)
    p.picos_min.setValue(1000)
    p.ganho.setText("1,10")
    p.inicio.setValue(100)
    janela.parametros._caixas_canais[0].setChecked(False)
    argv = p.argv()
    args = montar_parser().parse_args(argv)
    assert args.welch and args.fft is None and args.bandas_iec and args.picos == -40 and args.freq_min_picos == 1000
    assert args.filtro_passa_alta == 2000 and args.resolucao_welch == 100 and args.ganho == "1,10"
    assert args.inicio == 100 and args.canais_exibir == "1"
    assert "--bandas-iec" in janela.comando.text()


def test_analise_chega_as_figuras_e_as_tabelas(janela, ambiente):
    janela.abrir(ambiente / "ok.bin")
    janela.aguardar()
    p = janela.parametros
    p.grupo_fft.setChecked(True)
    p.harmonicos.setChecked(True)
    p.harmonicos_n.setValue(5)
    p.grupo_welch.setChecked(True)
    p.resolucao_welch.setValue(100)
    p.picos.setChecked(True)                 # sem o passa-alta: a --fft precisa da fundamental no sinal
    p.picos_db.setValue(-40)
    p.picos_min.setValue(1000)
    p.grupo_iec.setChecked(True)
    p.espectrograma.setChecked(True)
    res = _analisar(janela)
    assert janela.ultimo_erro is None
    assert set(res.resultados["canais"]) == {0, 1}
    assert len(janela.figura_principal.figura.axes) == 4                      # 2 canais x (tempo, espectro)
    assert janela.figura_espectrograma.figura.axes and janela.figura_iec.figura.axes
    assert janela.abas.isTabEnabled(1) and janela.abas.isTabEnabled(2) and janela.abas.isTabEnabled(3)
    assert janela.tabela_harmonicos.rowCount() == 5
    assert "THD" in janela.resumo_harmonicos.text()
    assert janela.tabela_picos.rowCount() >= 1
    assert janela.tabela_iec.rowCount() >= 1
    assert "Canal 1: correção de sonda aplicada (perfil 'sonda_teste'" in janela.console.toPlainText()


def test_erro_de_dominio_vira_mensagem_sem_traceback(janela, ambiente):
    janela.abrir(ambiente / "ok.bin")
    janela.aguardar()
    p = janela.parametros
    p.grupo_fft.setChecked(True)
    p.passa_alta.setChecked(True)
    p.passa_alta_hz.setValue(500)                      # tira a fundamental: a --fft não a acha
    p.freq_min.setValue(45)
    assert janela.analisar() and janela.aguardar()
    assert janela.ultimo_erro and "fundamental" in janela.ultimo_erro and "Traceback" not in janela.ultimo_erro
    assert janela.botao_analisar.isEnabled()


def test_arquivo_inexistente_nao_abre(janela, tmp_path):
    assert not janela.abrir(tmp_path / "nao_existe.bin")
    assert "não encontrado" in janela.ultimo_erro
    assert not janela.analisar() and "nenhuma captura aberta" in janela.ultimo_erro


def test_exportacao_grava_os_mesmos_arquivos_da_cli(janela, ambiente, tmp_path):
    janela.abrir(ambiente / "ok.bin")
    janela.aguardar()
    p = janela.parametros
    p.grupo_welch.setChecked(True)
    p.passa_alta.setChecked(True)
    p.passa_alta_hz.setValue(2000)
    _analisar(janela)
    escritos = janela._exportar(prefixo_csv=tmp_path / "r", arquivo_mat=tmp_path / "r.mat")
    nomes = {e.name for e in escritos}
    assert {"r_canal0_welch.csv", "r_canal1_welch.csv", "r_metadados.json", "r.mat"} <= nomes
    metadados = json.loads((tmp_path / "r_metadados.json").read_text(encoding="utf-8"))
    assert metadados["filtros"]["passa_alta_hz"] == 2000
    janela.salvar_figura(tmp_path / "g.png")
    assert (tmp_path / "g.png").stat().st_size > 1000
    assert janela.exportar_hdf5(tmp_path / "c.h5", incluir_tensao=True) and janela.aguardar()
    assert janela.ultimo_erro is None and (tmp_path / "c.h5").stat().st_size > 1000


def test_resumo_sem_cabecalho_pede_taxa_e_canais(tmp_path):
    assert "informe a taxa e os canais" in resumo_html(tmp_path / "antiga.bin", None, 0)
