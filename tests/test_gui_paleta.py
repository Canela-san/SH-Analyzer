"""A paleta de comandos e a lista dos atalhos (F1.8): a busca sem acentos nem maiúsculas, a ordem dos resultados,
achar e rodar uma ação pelo teclado, a ação desabilitada que não roda, e os atalhos com os gestos. Sem tela."""

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from dialogos_falsos import DialogosFalsos  # noqa: E402
from PySide6.QtCore import QEvent, Qt  # noqa: E402
from PySide6.QtGui import QAction, QKeyEvent  # noqa: E402
from sh_analyzer_gui.app import criar_aplicacao  # noqa: E402
from sh_analyzer_gui.componentes.paleta import buscar, normalizar, pontuar  # noqa: E402
from sh_analyzer_gui.janela import JanelaPrincipal  # noqa: E402


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


def tecla(widget, codigo):
    """Uma tecla pelo caminho de verdade (``sendEvent``), passando pelos filtros de evento."""
    from PySide6.QtWidgets import QApplication

    QApplication.sendEvent(widget, QKeyEvent(QEvent.Type.KeyPress, codigo, Qt.KeyboardModifier.NoModifier))


def test_normalizar_e_pontuar():
    assert normalizar("&Ação Única") == "acao unica"
    assert pontuar("salv", "salvar o projeto") == 4                      # começa com
    assert pontuar("proj", "salvar o projeto") == 3                      # uma palavra começa com
    assert pontuar("jeto", "salvar o projeto") == 2                      # contém
    assert pontuar("svpj", "salvar o projeto") == 1                      # as letras em ordem
    assert pontuar("xyz", "salvar o projeto") is None
    assert pontuar("", "qualquer") == 1


def test_buscar_ordena_e_nao_repete(qapp):
    acoes = [QAction(t) for t in ("Abrir projeto…", "Salvar o projeto como…", "Salvar o projeto", "Ação sem atalho",
                                  "")]
    acoes.append(acoes[0])                                                # a mesma ação duas vezes
    assert [r.texto for r in buscar(acoes, "salv")] == ["Salvar o projeto", "Salvar o projeto como…"]
    assert [r.texto for r in buscar(acoes, "PROJETO")][0] == "Abrir projeto…"
    assert [r.texto for r in buscar(acoes, "acao")] == ["Ação sem atalho"]
    assert len(buscar(acoes, "")) == 4                                    # sem a vazia e sem a repetida


def test_achar_e_rodar_uma_acao_pela_paleta(janela):
    janela.acoes["paleta"].trigger()
    paleta = janela.paleta
    assert paleta.isVisible() and paleta.campo.text() == ""
    paleta.campo.setText("nova vis")
    assert paleta.lista.currentItem().text() == "Nova vista"
    tecla(paleta.campo, Qt.Key.Key_Return)
    assert not paleta.isVisible() and [v.nome for v in janela.projeto.vistas] == ["Tempo"]
    janela.abrir_paleta()                                                 # a vista aberta traz as ações dela
    paleta.campo.setText("cursor")
    assert paleta.lista.currentItem().text() == "Cursores"
    tecla(paleta.campo, Qt.Key.Key_Return)
    vista = janela.area.widget_da_vista(janela.vista_ativa())
    assert vista.acao_cursores.isChecked() and vista.cursores is not None
    janela.abrir_paleta()
    paleta.campo.setText("painel")
    primeira = paleta.lista.currentRow()
    tecla(paleta.campo, Qt.Key.Key_Down)                                  # as setas andam na lista
    assert paleta.lista.currentRow() == primeira + 1
    tecla(paleta.campo, Qt.Key.Key_Escape)
    assert not paleta.isVisible()


def test_uma_acao_desabilitada_aparece_e_nao_roda(janela):
    janela.abrir_paleta()
    janela.paleta.campo.setText("desfazer")
    item = janela.paleta.lista.item(0)
    assert item.text().startswith("Desfazer") and not item.flags() & Qt.ItemFlag.ItemIsEnabled
    assert janela.paleta.acao_escolhida() is None and not janela.paleta.executar()


def test_a_lista_dos_atalhos(janela):
    dialogo = janela.mostrar_atalhos()
    linhas = dict(dialogo.linhas)
    assert linhas["Paleta de comandos"] == "Ctrl+K" and linhas["Salvar o projeto"] == "Ctrl+S"
    assert linhas["Mostrar ou recolher o painel: Projeto"] == "Ctrl+B"
    assert "Roda" in linhas.values() and "Ctrl + roda" in linhas.values()
    assert janela.acoes["atalhos"].shortcut().toString() == "Ctrl+/"
    dialogo.close()
