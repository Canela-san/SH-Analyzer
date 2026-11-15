"""As configurações (``preferencias.py``, GE-05): cada uma gravada e aplicada na partida e na hora; o separador
decimal reescreve os números da tela; os prefixos do SI nos eixos; as unidades próprias; as pastas (dos dados, das
sondas, do cache); os limites do cache e o "limpar", que nunca apaga o que está aberto nem o que está sendo
construído. Sem tela."""

import os

import numpy as np
import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from capturas_sinteticas import escrever_bin  # noqa: E402
from dialogos_falsos import DialogosFalsos  # noqa: E402
from sh_analyzer_gui import controle_do_projeto, preferencias  # noqa: E402
from sh_analyzer_gui.app import criar_aplicacao  # noqa: E402
from sh_analyzer_gui.areas.analise.arvore import PAPEL_DETALHE  # noqa: E402
from sh_analyzer_gui.componentes import numeros  # noqa: E402
from sh_analyzer_gui.componentes.seletor_de_unidade import SeletorDeUnidade  # noqa: E402
from sh_analyzer_gui.configuracao import gravar, lembrar  # noqa: E402
from sh_analyzer_gui.dados import unidades  # noqa: E402
from sh_analyzer_gui.dados.cache import EXTENSAO, CacheDePiramides  # noqa: E402
from sh_analyzer_gui.dados.materializacao import CacheDeMaterializacoes  # noqa: E402
from sh_analyzer_gui.graficos.faixa import EixoDoTema, definir_prefixos_nos_eixos, prefixos_nos_eixos  # noqa: E402
from sh_analyzer_gui.janela import JanelaPrincipal  # noqa: E402
from sh_analyzer_gui.tema import aplicar  # noqa: E402
from sh_analyzer_gui.tema.aplicar import aparencia  # noqa: E402

FS = 200_000.0
MIB = 1024**2


@pytest.fixture(autouse=True)
def padroes_de_volta(qapp):
    """O separador, o movimento, os prefixos dos eixos e as unidades próprias são do processo: cada teste devolve os
    padrões."""
    yield
    numeros.definir_separador_decimal(",")
    aparencia().definir_movimento("sistema")
    definir_prefixos_nos_eixos(True)
    unidades.definir_proprias(())


@pytest.fixture
def app(qapp, config_limpa):
    return criar_aplicacao([], tema="escuro")


@pytest.fixture
def janela(app, qtbot, tmp_path):
    preferencias.mudar_pasta("cache", tmp_path / "cache")      # um cache só deste teste
    j = JanelaPrincipal()
    j.controle.dialogos = DialogosFalsos()
    j.resize(1400, 900)
    j.show()
    qtbot.waitExposed(j)
    yield j
    j.projeto.pilha.setClean()
    j.close()
    j.deleteLater()


def captura(pasta, nome="c.bin"):
    t = np.arange(40_000) / FS
    return escrever_bin(pasta / nome, [1.5 * np.sin(2 * np.pi * 50 * t), 0.25 * np.sin(2 * np.pi * 50 * t)],
                        fs_total=int(2 * FS), versao=9)


# ------------------------------------------------------------------ gravadas e aplicadas na partida

def test_o_separador_decimal_muda_a_escrita():
    assert numeros.formatar_si(2500, "Hz") == "2,5 kHz" and numeros.decimal("1.25 dB") == "1,25 dB"
    numeros.definir_separador_decimal(".")
    assert numeros.formatar_si(2500, "Hz") == "2.5 kHz" and numeros.formatar_duracao(4.2) == "4.2 s"
    assert numeros.decimal("1.25 dB") == "1.25 dB" and numeros.formatar_si(2500, "Hz", decimal=",") == "2,5 kHz"
    assert numeros.ler_numero("2,5k") == numeros.ler_numero("2.5k") == 2500       # a leitura aceita os dois
    with pytest.raises(ValueError):
        numeros.definir_separador_decimal(";")


def test_as_preferencias_gravadas_valem_na_partida(app):
    gravar("aparencia/movimento", "reduzido")
    gravar("numeros/separador_decimal", ".")
    preferencias.aplicar_na_partida()
    assert aparencia().movimento_reduzido and numeros.separador_decimal() == "."
    # Um valor inválido (um arquivo editado à mão) vale como o padrão, sem erro.
    gravar("aparencia/movimento", "aos saltos")
    gravar("numeros/separador_decimal", ";")
    preferencias.aplicar_na_partida()
    assert aparencia().movimento == "sistema" and numeros.separador_decimal() == ","


def test_o_movimento_segue_o_sistema_ou_a_escolha(app, monkeypatch):
    monkeypatch.setattr(aplicar, "movimento_reduzido_do_sistema", lambda: True)
    preferencias.mudar_movimento("sistema")
    assert aparencia().movimento_reduzido                               # o sistema pede
    preferencias.mudar_movimento("normal")
    assert not aparencia().movimento_reduzido and preferencias.movimento_salvo() == "normal"
    monkeypatch.setattr(aplicar, "movimento_reduzido_do_sistema", lambda: False)
    preferencias.mudar_movimento("reduzido")
    assert aparencia().movimento_reduzido and preferencias.movimento_salvo() == "reduzido"
    with pytest.raises(ValueError):
        preferencias.mudar_movimento("rápido")


def test_as_pastas(app, tmp_path, monkeypatch):
    monkeypatch.delenv("DADOS", raising=False)
    assert preferencias.pasta_escolhida("dados") is None and preferencias.pasta("dados") == preferencias.Path.home()
    monkeypatch.setenv("DADOS", str(tmp_path))                          # a variável $DADOS, se existir
    assert preferencias.pasta("dados") == tmp_path
    assert preferencias.pasta("sondas").name == "sondas" and preferencias.pasta("sondas").is_dir()
    assert preferencias.pasta("cache") == preferencias.pasta_padrao("cache")
    escolhida = tmp_path / "meu cache"
    preferencias.mudar_pasta("cache", escolhida)
    assert preferencias.pasta("cache") == escolhida and preferencias.pasta_do_cache("piramides") == \
        escolhida / "piramides"
    preferencias.mudar_pasta("cache", None)                             # de volta à padrão
    assert preferencias.pasta_escolhida("cache") is None
    with pytest.raises(ValueError):
        preferencias.mudar_pasta("figuras", tmp_path)


def test_os_limites_do_cache(app):
    assert preferencias.limite("piramides") == preferencias.LIMITES_PADRAO["piramides"]
    preferencias.mudar_limite("materializacoes", 2 * 1024 * MIB)
    assert preferencias.limite("materializacoes") == 2 * 1024 * MIB
    with pytest.raises(ValueError):
        preferencias.mudar_limite("piramides", 10 * MIB)                # abaixo do mínimo
    gravar("cache/limite_piramides_bytes", "muito")                     # inválido: o padrão
    assert preferencias.limite("piramides") == preferencias.LIMITES_PADRAO["piramides"]


def test_as_placas_conhecidas(app):
    from sh_placa.conhecidas import PlacaConhecida
    from sh_placa.destino import Destino

    assert preferencias.placas_conhecidas() == ()
    placas = (PlacaConhecida("2017BBBK382A", "Placa do laboratório", "SHA256:x",
                             (Destino("192.168.6.2"), Destino("lab", 2222, "eu", Destino("gw", 22, "canela"))), 5.0),)
    preferencias.mudar_placas_conhecidas(placas)
    assert preferencias.placas_conhecidas() == placas
    gravar(preferencias.CHAVE_DAS_PLACAS, "{não é json")                # estragado: nenhuma, sem erro
    assert preferencias.placas_conhecidas() == ()


# ------------------------------------------------------------------ as pastas na abertura

def test_as_capturas_abrem_com_a_pasta_das_sondas(janela, tmp_path, monkeypatch):
    sondas = tmp_path / "sondas"
    sondas.mkdir()
    preferencias.mudar_pasta("sondas", sondas)
    pedidos = []
    original = controle_do_projeto.abrir_fonte

    def abrir(caminho, **opcoes):
        pedidos.append(opcoes.get("sondas_dir"))
        return original(caminho, **opcoes)

    monkeypatch.setattr(controle_do_projeto, "abrir_fonte", abrir)
    caminho = captura(tmp_path)
    janela.controle.abrir_capturas([caminho])
    assert janela.controle.salvar_como(tmp_path / "p.shproj")
    assert janela.controle.abrir(tmp_path / "p.shproj")                 # reabrir o projeto também
    assert pedidos == [sondas, sondas]


def test_o_dialogo_de_abrir_comeca_na_pasta_dos_dados(janela, tmp_path, monkeypatch):
    monkeypatch.delenv("DADOS", raising=False)
    assert janela.controle._pasta_inicial() == str(preferencias.Path.home())
    recente = tmp_path / "recentes"
    recente.mkdir()
    lembrar(controle_do_projeto.CHAVE_DOS_RECENTES, str(recente / "p.shproj"))
    assert janela.controle._pasta_inicial() == str(recente)             # sem a escolhida, a do recente
    dados = tmp_path / "dados"
    dados.mkdir()
    preferencias.mudar_pasta("dados", dados)
    assert janela.controle._pasta_inicial() == str(dados)               # a escolhida vale mais que o recente


# ------------------------------------------------------------------ o cache

def test_limpar_e_o_limite_nunca_apagam_o_que_esta_aberto(janela, qtbot, tmp_path):
    (fonte,) = janela.controle.abrir_capturas([captura(tmp_path)])
    qtbot.waitUntil(lambda: fonte.piramides is not None, timeout=10_000)
    servico = janela.servico_de_fontes
    assert servico.cache.pasta == tmp_path / "cache" / "piramides"
    abertas = servico.piramides_abertas()
    assert len(abertas) == 2 and all(p.exists() for p in abertas)
    sobra = servico.cache.pasta / f"outra{EXTENSAO}"                    # a pirâmide de uma captura já fechada
    sobra.write_bytes(b"\0" * 4096)
    assert servico.cache.tamanho_bytes == sum(p.stat().st_size for p in abertas) + 4096
    assert servico.limpar_cache() == 4096
    assert not sobra.exists() and all(p.exists() for p in abertas)
    # O limite menor apaga na hora as menos usadas, menos as abertas.
    sobra.write_bytes(b"\0" * 4096)
    os.utime(sobra, (1, 1))
    servico.definir_cache(servico.cache.pasta, preferencias.LIMITE_MINIMO_BYTES)
    assert sobra.exists()                                               # cabe no limite
    servico.cache.limite_bytes = 1
    servico.cache.aparar(manter=servico.piramides_abertas())
    assert not sobra.exists() and all(p.exists() for p in abertas)
    # Outra pasta: um cache novo; o de antes fica como estava.
    antigo = servico.cache
    servico.definir_cache(tmp_path / "outro", preferencias.LIMITE_MINIMO_BYTES)
    assert servico.cache is not antigo and servico.cache.pasta == tmp_path / "outro"


def test_o_que_esta_sendo_construido_nao_e_apagado(tmp_path):
    piramides = CacheDePiramides(tmp_path / "p", limite_bytes=1)
    piramides.pasta.mkdir()
    caminho = piramides.caminho("chave", 0)
    with piramides.em_construcao.marcar([caminho]):
        caminho.write_bytes(b"\0" * 100)
        assert piramides.limpar() == 0 and caminho.exists()
        piramides.aparar()
        assert caminho.exists()
    assert piramides.limpar() == 100 and not caminho.exists()
    materializacoes = CacheDeMaterializacoes(tmp_path / "m", limite_bytes=1)
    materializacoes.pasta.mkdir()
    dados, piramide = materializacoes.caminhos("k")
    with materializacoes.em_construcao.marcar(["k"]):
        dados.write_bytes(b"\0" * 64)
        piramide.write_bytes(b"\0" * 32)
        assert materializacoes.limpar() == 0 and dados.exists()
    assert materializacoes.limpar() == 96 and not dados.exists() and not piramide.exists()


# ------------------------------------------------------------------ o separador na tela

def test_trocar_o_separador_reescreve_os_numeros_da_tela(janela, qtbot, tmp_path):
    (fonte,) = janela.controle.abrir_capturas([captura(tmp_path)])
    qtbot.waitUntil(lambda: fonte.piramides is not None, timeout=10_000)
    traco = janela.area.plotar_canal(fonte, 0)
    tempo = janela.area.widget_da_vista(janela.vista_ativa())
    tabela = janela.area.tabela_de_medidas
    qtbot.waitUntil(lambda: bool(tabela.medidas) and tabela.medidas[0].medidas is not None, timeout=10_000)
    rms = tabela.tabela.item(0, 3).text()
    assert rms == "1,061 V"
    eixo = tempo.faixas[traco.receita.faixa].getAxis("left")
    assert eixo.tickStrings([0.5, 1.0], 1.0, 0.5) == ["0,5", "1,0"]
    info = tempo.info.text()
    assert "," in info                                                  # −3,9999 m – 203,995 ms · …
    modelo = janela.painel_projeto.modelo
    detalhe = modelo.data(modelo.indice_da_fonte(fonte), PAPEL_DETALHE)
    assert "0,2 s" in detalhe

    preferencias.mudar_separador(".")
    assert tabela.tabela.item(0, 3).text() == "1.061 V"                 # a tabela, sem medir de novo
    assert eixo.tickStrings([0.5, 1.0], 1.0, 0.5) == ["0.5", "1.0"]
    assert "0.2 s" in modelo.data(modelo.indice_da_fonte(fonte), PAPEL_DETALHE)
    assert tempo.info.text() == info.replace(",", ".")
    assert preferencias.separador_salvo() == "."



def test_o_eixo_escolhe_o_prefixo_pela_faixa_visivel(app):
    eixo = EixoDoTema("left")
    eixo.definir_rotulo("tensão", "V")
    eixo.setRange(-0.002, 0.0015)
    assert eixo.rotulo == "tensão (mV)" and eixo.autoSIPrefixScale == pytest.approx(1e3)
    assert eixo.tickStrings([-0.001, 0.0005], eixo.autoSIPrefixScale, 0.0005) == ["−1,0", "0,5"]
    eixo.setRange(0, 250)
    assert eixo.rotulo == "tensão (V)" and eixo.autoSIPrefixScale == 1.0
    eixo.setRange(-25e3, 0)
    assert eixo.rotulo == "tensão (kV)"
    eixo.definir_rotulo("temperatura", "°C")                    # sem prefixo: nunca m°C
    eixo.setRange(0, 0.002)
    assert eixo.rotulo == "temperatura (°C)" and eixo.autoSIPrefixScale == 1.0
    eixo.definir_rotulo("tensão", "V")
    eixo.definir_rotulo("ordem")                               # sem unidade: os números voltam à escala 1
    assert eixo.rotulo == "ordem" and eixo.autoSIPrefixScale == 1.0
    tempo = EixoDoTema("bottom", expoente_maximo=0)
    tempo.definir_rotulo("tempo", "s")
    tempo.setRange(0, 3600)
    assert tempo.rotulo == "tempo (s)"                         # uma hora: 3600 s, não 3,6 ks
    tempo.setRange(0.0001, 0.004)
    assert tempo.rotulo == "tempo (ms)"
    definir_prefixos_nos_eixos(False)
    tempo.aplicar_tema(aparencia().tema)                       # o aviso da aparência refaz
    assert tempo.rotulo == "tempo (s)" and tempo.autoSIPrefixScale == 1.0


def test_os_prefixos_e_as_unidades_gravados_valem_na_partida(app):
    gravar(preferencias.CHAVE_DOS_PREFIXOS, "nao")
    gravar(preferencias.CHAVE_DAS_UNIDADES, '[{"simbolo": "ppm", "grandeza": "concentração", "prefixos": false}, '
                                            '{"simbolo": "V", "grandeza": "repetida"}, {"simbolo": "m s"}, 3, '
                                            '{"grandeza": "sem símbolo"}, {"simbolo": "Gy", "prefixos": true}]')
    preferencias.aplicar_na_partida()
    assert not prefixos_nos_eixos()
    assert [(u.simbolo, u.grandeza, u.prefixos) for u in unidades.proprias()] == \
        [("ppm", "concentração", False), ("Gy", "", True)]           # as inválidas e a do catálogo ficam de fora
    assert unidades.grandeza("mGy") == "" and unidades.procurar("mGy").a == pytest.approx(1e-3)
    preferencias.mudar_unidades(unidades.proprias()[:1])
    assert preferencias.unidades_salvas() == [unidades.propria("ppm", "concentração")]
    gravar(preferencias.CHAVE_DAS_UNIDADES, "{não é json")
    gravar(preferencias.CHAVE_DOS_PREFIXOS, "talvez")
    preferencias.aplicar_na_partida()
    assert unidades.proprias() == () and prefixos_nos_eixos()


@pytest.mark.parametrize("simbolo, grandeza, trecho", [
    ("mA", "", r"catálogo \(corrente\)"), ("kPa", "", "catálogo"), ("°C", "", "catálogo"), ("", "", "vazia"),
    ("ppm", "x" * 41, "40"),
])
def test_uma_unidade_propria_invalida(simbolo, grandeza, trecho):
    with pytest.raises(unidades.UnidadeInvalida, match=trecho):
        unidades.propria(simbolo, grandeza)


# ------------------------------------------------------------------ a tela de configurações

def test_a_tela_troca_o_tema_as_fontes_e_o_movimento(janela, qtbot):
    dialogo = janela.abrir_configuracoes()
    qtbot.waitExposed(dialogo)
    assert [dialogo.secoes.item(i).text() for i in range(dialogo.secoes.count())] == \
        ["Aparência", "Números", "Unidades", "Pastas", "Cache"]
    assert dialogo.tema.escolhida == 1                                  # escuro (o do teste)
    dialogo.tema.escolher(2)
    assert not aparencia().tema.escuro and preferencias.tema_salvo() == "claro"
    janela.acoes["alternar_tema"].trigger()                             # pela barra: a tela acompanha
    assert dialogo.tema.escolhida == 1 and aparencia().tema.escuro
    caixa = dialogo.fontes["interface"]
    caixa.textActivated.emit("IBM Plex Sans")
    assert preferencias.ler_texto(preferencias.CHAVES_DAS_FONTES["interface"]) == "IBM Plex Sans"
    dialogo.movimento.escolher(1)
    assert aparencia().movimento_reduzido and preferencias.movimento_salvo() == "reduzido"


def test_a_tela_troca_o_separador_e_mostra_o_exemplo(janela, qtbot):
    dialogo = janela.abrir_configuracoes("numeros")
    assert dialogo.exemplo.text() == "2,5 kHz · 127,3 V · 1,5 mA · 4,2 s"
    dialogo.separador.escolher(1)
    assert dialogo.exemplo.text() == "2.5 kHz · 127.3 V · 1.5 mA · 4.2 s"
    assert preferencias.separador_salvo() == "." and numeros.separador_decimal() == "."


def test_a_tela_escolhe_as_pastas_e_volta_a_padrao(janela, qtbot, tmp_path):
    dialogo = janela.abrir_configuracoes("pastas")
    sondas = tmp_path / "minhas sondas"
    sondas.mkdir()
    janela.controle.dialogos = DialogosFalsos(str(sondas), None)
    dialogo._escolher_pasta("sondas")
    assert preferencias.pasta("sondas") == sondas and dialogo.campos_de_pasta["sondas"].text() == str(sondas)
    assert dialogo.botoes_de_padrao["sondas"].isEnabled()
    dialogo._escolher_pasta("sondas")                                   # cancelar não muda nada
    assert preferencias.pasta("sondas") == sondas
    dialogo.botoes_de_padrao["sondas"].click()
    assert preferencias.pasta_escolhida("sondas") is None and dialogo.campos_de_pasta["sondas"].text() == ""
    assert str(preferencias.pasta_padrao("sondas")) in dialogo.campos_de_pasta["sondas"].placeholderText()
    # A pasta do cache: os serviços passam a usá-la na hora.
    janela.controle.dialogos = DialogosFalsos(str(tmp_path / "outro cache"))
    dialogo._escolher_pasta("cache")
    assert janela.servico_de_fontes.cache.pasta == tmp_path / "outro cache" / "piramides"
    assert janela.materializacoes.cache.pasta == tmp_path / "outro cache" / "materializacoes"


def test_a_tela_do_cache_mostra_o_uso_muda_o_limite_e_limpa(janela, qtbot, tmp_path):
    (fonte,) = janela.controle.abrir_capturas([captura(tmp_path)])
    qtbot.waitUntil(lambda: fonte.piramides is not None, timeout=10_000)
    servico = janela.servico_de_fontes
    sobra = servico.cache.pasta / f"outra{EXTENSAO}"
    sobra.write_bytes(b"\0" * 2 * MIB)
    dialogo = janela.abrir_configuracoes("cache")
    assert dialogo.limites["piramides"].value() == preferencias.LIMITES_PADRAO["piramides"] // 1024**3
    assert dialogo.usos["piramides"].text() == f"em uso: {numeros.formatar_bytes(servico.cache.tamanho_bytes)}"
    dialogo.limites["materializacoes"].setValue(3)
    assert preferencias.limite("materializacoes") == 3 * 1024**3
    assert janela.materializacoes.cache.limite_bytes == 3 * 1024**3
    dialogo.botoes_de_limpar["piramides"].click()
    assert not sobra.exists() and all(p.exists() for p in servico.piramides_abertas())
    assert dialogo.usos["piramides"].text() == f"em uso: {numeros.formatar_bytes(servico.cache.tamanho_bytes)}"


def test_os_tamanhos_em_bytes():
    assert numeros.formatar_bytes(512) == "512 B"
    assert numeros.formatar_bytes(1536) == "1,5 KiB"
    assert numeros.formatar_bytes(4 * 1024**3) == "4 GiB"
    assert numeros.formatar_bytes(12.4 * 1024**3) == "12 GiB"
    assert numeros.formatar_bytes(0) == "0 B"


def test_a_tela_das_unidades(janela, qtbot):
    dialogo = janela.abrir_configuracoes("unidades")
    catalogo = dialogo.tabela_catalogo
    assert catalogo.rowCount() == len(unidades.CATALOGO)
    linha_c = next(i for i in range(catalogo.rowCount()) if catalogo.item(i, 0).text() == "°C")
    assert catalogo.item(linha_c, 1).text() == "temperatura" and catalogo.item(linha_c, 2).text() == "K, °F"
    seletor = SeletorDeUnidade()
    assert seletor.findText("ppm") == -1
    dialogo.novo_simbolo.setText(" ppm ")
    dialogo.nova_grandeza.setText("concentração")
    dialogo.adicionar_unidade.click()
    assert dialogo.tabela_unidades.rowCount() == 1 and dialogo.tabela_unidades.item(0, 0).text() == "ppm"
    assert unidades.grandeza("ppm") == "concentração" and preferencias.unidades_salvas()[0].simbolo == "ppm"
    assert dialogo.novo_simbolo.text() == ""
    seletor.showPopup()                                            # a lista se refaz com a nova
    assert seletor.findText("ppm") >= 0
    seletor.hidePopup()
    for simbolo, motivo in (("ppm", "já está nas suas"), ("mV", "catálogo")):
        dialogo.novo_simbolo.setText(simbolo)
        dialogo.novo_simbolo.returnPressed.emit()
        assert motivo in dialogo.motivo_unidade.text() and dialogo.tabela_unidades.rowCount() == 1
    dialogo.tabela_unidades.selectRow(0)
    assert dialogo.remover_unidade.isEnabled()
    dialogo.remover_unidade.click()
    assert dialogo.tabela_unidades.rowCount() == 0 and unidades.proprias() == ()
    assert preferencias.unidades_salvas() == []


def test_a_tela_desliga_os_prefixos_dos_eixos(janela, qtbot, tmp_path):
    (fonte,) = janela.controle.abrir_capturas([captura(tmp_path)])
    qtbot.waitUntil(lambda: fonte.piramides is not None, timeout=10_000)
    traco = janela.area.plotar_canal(fonte, 1)                    # 0,25 de pico
    tempo = janela.area.widget_da_vista(janela.vista_ativa())
    eixo = tempo.faixas[traco.receita.faixa].getAxis("left")
    qtbot.waitUntil(lambda: eixo.labelUnitPrefix == "m", timeout=5_000)
    texto, unidade = eixo.labelText, eixo.labelUnits
    assert eixo.rotulo == f"{texto} (m{unidade})"
    dialogo = janela.abrir_configuracoes("numeros")
    assert dialogo.prefixos.escolhida == 0
    dialogo.prefixos.escolher(1)
    assert eixo.rotulo == f"{texto} ({unidade})" and preferencias.prefixos_salvos() is False
    dialogo.prefixos.escolher(0)
    assert eixo.rotulo == f"{texto} (m{unidade})" and preferencias.prefixos_salvos() is True
