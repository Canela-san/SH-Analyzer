"""Os arquivos do projeto na janela (``sh_analyzer_gui.controle_do_projeto``, F1.3): salvar e abrir de volta, a
captura reencontrada pelo CRC ou ausente, as perguntas antes de perder trabalho, o salvamento automático e a
recuperação. Sem tela, com os diálogos respondidos pelo teste (``dialogos_falsos.py``)."""

import shutil

import numpy as np
import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from capturas_sinteticas import escrever_bin  # noqa: E402
from dialogos_falsos import DialogosFalsos  # noqa: E402
from sh_analyzer_gui.app import criar_aplicacao  # noqa: E402
from sh_analyzer_gui.configuracao import pasta_de_recuperacao  # noqa: E402
from sh_analyzer_gui.controle_do_projeto import NOME_SEM_TITULO, Dialogos, DialogoSemTela  # noqa: E402
from sh_analyzer_gui.dados import projeto as arq  # noqa: E402
from sh_analyzer_gui.dados.captura import abrir_fonte  # noqa: E402
from sh_analyzer_gui.dados.receita import ReceitaDoTraco  # noqa: E402
from sh_analyzer_gui.janela import JanelaPrincipal  # noqa: E402
from sh_analyzer_gui.modelo.comandos import AdicionarFonte, AdicionarTraco, AdicionarVista, MudarTracos  # noqa: E402
from sh_analyzer_gui.modelo.objetos import FonteDoProjeto, Traco, Vista  # noqa: E402


@pytest.fixture
def janela(qapp, config_limpa):
    """A janela, fechada aqui depois de limpar a pilha (o ``qtbot.addWidget`` a fecharia antes, perguntando se quer
    salvar)."""
    criar_aplicacao([], tema="escuro")
    j = JanelaPrincipal()
    j.controle.dialogos = DialogosFalsos()
    yield j
    j.projeto.pilha.setClean()
    j.close()
    j.deleteLater()


def captura(pasta, nome="a.bin", valor=0.0):
    pasta.mkdir(parents=True, exist_ok=True)
    return escrever_bin(pasta / nome, [np.full(4096, valor), np.full(4096, -valor)], canais=(1, 3), versao=9)


def montar_projeto(janela, caminho_da_captura):
    """Uma fonte, uma vista com dois traços (um mudado), tudo pela pilha."""
    p = janela.projeto
    fonte = FonteDoProjeto(abrir_fonte(caminho_da_captura))
    vista = Vista("Afundamento")
    a = Traco(ReceitaDoTraco(fonte.id, 1, "V_A", 0))
    b = Traco(ReceitaDoTraco(fonte.id, 3, "I_A", 1))
    for comando in (AdicionarFonte(p, fonte), AdicionarVista(p, vista), AdicionarTraco(vista, a),
                    AdicionarTraco(vista, b), MudarTracos([b], ganho=-2.0, faixa=1)):
        p.pilha.push(comando)
    return fonte, vista, a, b


def test_salvar_e_abrir_de_volta(janela, tmp_path):
    fonte, vista, a, b = montar_projeto(janela, captura(tmp_path / "dados"))
    janela.acoes["painel_inspetor"].trigger()                       # o layout vai junto com o projeto
    janela.controle.dialogos = DialogosFalsos(tmp_path / "projetos" / "rede")
    assert janela.controle.salvar()
    caminho = tmp_path / "projetos" / "rede.shproj"                 # a extensão entra sozinha
    assert caminho.is_file() and janela.projeto.caminho == caminho and not janela.projeto.modificado
    assert janela.windowTitle().startswith("rede[*]") and janela.barra.botao_projeto.text() == "rede"
    assert janela.controle.recentes()[0] == caminho.resolve()
    salvo = arq.abrir(caminho)
    assert salvo.fontes[0].caminho == "../dados/a.bin" and salvo.fontes[0].crc32_amostras is not None

    janela.acoes["painel_inspetor"].trigger()
    assert janela.controle.novo() and janela.projeto.vistas == ()
    assert janela.controle.abrir(caminho)
    p = janela.projeto
    assert [f.id for f in p.fontes] == [fonte.id] and not p.fontes[0].esta_ausente
    (v,) = p.vistas
    assert (v.id, v.nome) == (vista.id, "Afundamento")
    assert [(t.id, t.receita) for t in v.tracos] == [(a.id, a.receita), (b.id, b.receita)]
    assert not p.modificado and not janela.acoes["desfazer"].isEnabled()
    assert not janela.dock_inspetor.isVisible()                     # o layout do projeto voltou
    assert [a for a, origem in janela.avisos.avisos if origem == "projeto"] == []


def test_a_captura_movida_e_reencontrada_pelo_crc(janela, tmp_path):
    original = captura(tmp_path / "dados")
    montar_projeto(janela, original)
    caminho = tmp_path / "rede.shproj"
    assert janela.controle.salvar_como(caminho)
    (tmp_path / "arquivo" / "2026").mkdir(parents=True)
    shutil.move(original, tmp_path / "arquivo" / "2026" / "renomeada.bin")
    assert janela.controle.abrir(caminho)
    fonte = janela.projeto.fontes[0]
    assert not fonte.esta_ausente and fonte.caminho.name == "renomeada.bin"
    ((aviso, origem),) = [(a, o) for a, o in janela.avisos.avisos if o == "projeto"]
    assert aviso.nivel == "info" and "reencontrada pelo CRC" in aviso.texto


def test_a_captura_que_sumiu_fica_ausente_sem_perder_os_tracos(janela, tmp_path):
    original = captura(tmp_path / "dados")
    _, vista, a, b = montar_projeto(janela, original)
    caminho = tmp_path / "rede.shproj"
    assert janela.controle.salvar_como(caminho)
    original.unlink()
    assert janela.controle.abrir(caminho)
    fonte = janela.projeto.fontes[0]
    assert fonte.esta_ausente and fonte.nome == "a.bin" and fonte.canais == ()
    assert [t.receita for t in janela.projeto.vistas[0].tracos] == [a.receita, b.receita]
    ((aviso, _),) = [(a, o) for a, o in janela.avisos.avisos if o == "projeto"]
    assert aviso.nivel == "erro" and "não foi encontrada" in aviso.texto
    assert janela.painel_inferior.tabBar().tabButton(2, janela.painel_inferior.tabBar().ButtonPosition.RightSide)
    # Salvar de novo grava a fonte ausente como veio: nada se perde até a captura voltar.
    janela.projeto.pilha.resetClean()
    assert janela.controle.salvar()
    assert arq.abrir(caminho).fontes[0].caminho_absoluto == original.resolve().as_posix()


def test_perguntas_antes_de_perder_trabalho(janela, tmp_path):
    montar_projeto(janela, captura(tmp_path / "dados"))
    janela.controle.dialogos = d = DialogosFalsos(None)            # cancelar
    assert not janela.controle.novo() and janela.projeto.vistas
    assert d.perguntas == ["Mudanças não salvas"]
    janela.controle.dialogos = DialogosFalsos("salvar", None)       # salvar, e cancelar o "salvar como"
    assert not janela.controle.novo() and janela.projeto.vistas
    janela.controle.dialogos = DialogosFalsos("salvar", tmp_path / "salvo.shproj")
    assert janela.controle.novo() and (tmp_path / "salvo.shproj").is_file() and janela.projeto.vistas == ()
    montar_projeto(janela, captura(tmp_path / "dados"))
    janela.controle.dialogos = DialogosFalsos("descartar")
    assert janela.controle.novo() and janela.projeto.vistas == ()


def test_fechar_a_janela_com_mudancas_pergunta(janela, tmp_path):
    janela.show()
    montar_projeto(janela, captura(tmp_path / "dados"))
    janela.controle.dialogos = DialogosFalsos(None)
    assert not janela.close() and janela.isVisible()                # cancelado: a janela fica
    janela.controle.dialogos = DialogosFalsos("descartar")
    assert janela.close()


def test_salvamento_automatico_e_recuperacao(janela, tmp_path):
    montar_projeto(janela, captura(tmp_path / "dados"))
    caminho = tmp_path / "rede.shproj"
    assert janela.controle.salvar_como(caminho)
    assert janela.controle.salvar_automatico() is None              # sem mudanças, nada a gravar
    vista = janela.projeto.vistas[0]
    janela.projeto.pilha.push(AdicionarVista(janela.projeto, Vista("Depois de salvar")))
    auto = janela.controle.salvar_automatico()
    assert auto == arq.automatico(caminho) and len(arq.abrir(auto).vistas) == 2
    import os
    import time

    agora = time.time()
    os.utime(caminho, (agora - 60, agora - 60))                       # a "queda": o automático ficou mais novo
    janela.projeto.pilha.setClean()
    janela.controle.dialogos = d = DialogosFalsos("recuperar")
    assert janela.controle.abrir(caminho)
    assert d.perguntas == ["Recuperar o projeto"]
    assert [v.nome for v in janela.projeto.vistas] == [vista.nome, "Depois de salvar"]
    assert janela.projeto.modificado                                   # o recuperado ainda não está no principal
    janela.controle.dialogos = DialogosFalsos()
    assert janela.controle.salvar() and not auto.exists()


def test_recuperar_um_projeto_sem_titulo(janela, qtbot, tmp_path):
    montar_projeto(janela, captura(tmp_path / "dados"))
    auto = janela.controle.salvar_automatico()
    assert auto == arq.automatico(pasta_de_recuperacao() / NOME_SEM_TITULO)
    # A "queda": o aplicativo abre de novo com o automático lá.
    nova = JanelaPrincipal()
    qtbot.addWidget(nova)
    nova.controle.dialogos = DialogosFalsos("recuperar")
    assert nova.controle.oferecer_recuperacao()
    assert nova.projeto.caminho is None and nova.projeto.modificado
    assert [t.nome for t in nova.projeto.vistas[0].tracos] == ["V_A", "I_A"]
    nova.controle.dialogos = DialogosFalsos(tmp_path / "agora tem nome.shproj")
    assert nova.controle.salvar()
    assert not auto.exists()                                           # salvo com nome, a recuperação some
    nova.controle.dialogos = DialogosFalsos()
    assert not nova.controle.oferecer_recuperacao()


def test_descartar_apaga_o_automatico(janela, tmp_path):
    montar_projeto(janela, captura(tmp_path / "dados"))
    auto = janela.controle.salvar_automatico()
    janela.controle.dialogos = DialogosFalsos("descartar")
    assert janela.controle.novo() and not auto.exists()


def test_um_projeto_de_uma_versao_mais_nova_e_recusado(janela, tmp_path):
    caminho = tmp_path / "futuro.shproj"
    dados = arq.para_dict(arq.ProjetoSalvo())
    dados["versao"] = arq.VERSAO + 1
    import json

    caminho.write_text(json.dumps(dados), encoding="utf-8")
    anterior = janela.projeto
    assert not janela.controle.abrir(caminho)
    assert janela.projeto is anterior
    from sh_analyzer_gui.componentes.toast import Toast

    assert any("versão mais nova" in t.rotulo.text() for t in janela.findChildren(Toast))


def test_os_recentes_no_menu_do_projeto(janela, tmp_path):
    for nome in ("um", "dois"):
        janela.controle.novo()
        janela.projeto.pilha.push(AdicionarVista(janela.projeto, Vista(nome)))
        assert janela.controle.salvar_como(tmp_path / f"{nome}.shproj")
    (tmp_path / "um.shproj").unlink()
    janela._preencher_recentes()
    assert [a.text() for a in janela.menu_recentes.actions()] == ["dois"]     # o que sumiu não aparece
    assert [c.name for c in janela.controle.recentes()] == ["dois.shproj", "um.shproj"]


def test_sem_tela_um_dialogo_nao_previsto_vira_erro(janela):
    with pytest.raises(DialogoSemTela, match="sem tela"):
        Dialogos(janela).perguntar("x", "y", {"ok": "OK"}, "ok")
