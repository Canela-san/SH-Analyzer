"""O caderno de bancada (F4.5): o formato do ``anotacoes.md`` (só acrescentar, sob o título da seção, sem mexer no
que o usuário escreveu, e a leitura das entradas, inclusive as escritas à mão), o caderno da sessão (as notas, o
arquivo mudado fora do aplicativo, o dia que vira, o disco que recusa), a coluna da seção Capturar, as frases das
entradas automáticas e a seção "Notas" do projeto, com o inspetor."""

from __future__ import annotations

import datetime
import os
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from capturas_sinteticas import escrever_bin  # noqa: E402
from PySide6.QtCore import QUrl  # noqa: E402
from PySide6.QtTest import QAbstractItemModelTester  # noqa: E402
from sh_analyzer_gui import preferencias  # noqa: E402
from sh_analyzer_gui.app import criar_aplicacao  # noqa: E402
from sh_analyzer_gui.areas.aquisicao import entradas_do_caderno as frases  # noqa: E402
from sh_analyzer_gui.areas.aquisicao.caderno import CadernoDeBancada  # noqa: E402
from sh_analyzer_gui.dados import caderno as formato  # noqa: E402
from sh_analyzer_gui.servicos.caderno import CadernoDaSessao  # noqa: E402
from sh_analyzer_gui.servicos.saude_da_placa import Correcao  # noqa: E402

RAIZ = Path(__file__).resolve().parents[1]
QUANDO = datetime.datetime(2026, 11, 18, 14, 10, 3)


def do_modelo(pasta: Path) -> Path:
    """O ``anotacoes.md`` como o ``lab`` o cria: o modelo do repositório com o dia no título."""
    pasta.mkdir(parents=True, exist_ok=True)
    arquivo = pasta / "anotacoes.md"
    modelo = (RAIZ / "docs" / "lab-notes-template.md").read_text(encoding="utf-8")
    arquivo.write_text(modelo.replace("AAAA-MM-DD", pasta.name), encoding="utf-8")
    return arquivo


# ------------------------------------------------------------------ o formato, sem Qt


def test_o_caderno_novo_tem_o_titulo_do_dia_e_a_secao(tmp_path):
    arquivo = tmp_path / "2026-11-18" / "anotacoes.md"
    e = formato.acrescentar(arquivo, "Captura `rede.bin` iniciada: 1 canal · 400 kS/s.", formato.AUTOMATICO, QUANDO)
    assert arquivo.read_text(encoding="utf-8") == (
        "# Anotações da bancada: 2026-11-18\n\n## Caderno de bancada\n\n"
        "- **14:10:03** · automático · Captura `rede.bin` iniciada: 1 canal · 400 kS/s.\n")
    assert (e.hora, e.autor, e.texto) == (datetime.time(14, 10, 3), "automático",
                                          "Captura `rede.bin` iniciada: 1 canal · 400 kS/s.")
    assert formato.ler(arquivo) == [e]


def test_o_arquivo_do_lab_so_ganha_linhas_no_fim(tmp_path):
    """O que o usuário escreveu fica byte a byte; a seção entra uma vez, e as entradas seguem sob ela."""
    arquivo = do_modelo(tmp_path / "2026-11-18")
    antes = arquivo.read_text(encoding="utf-8")
    formato.acrescentar(arquivo, "Ar-condicionado ligado às 14h05.", formato.VOCE, QUANDO)
    formato.acrescentar(arquivo, "Conferência: pronto para capturar.", formato.AUTOMATICO,
                        QUANDO + datetime.timedelta(seconds=40))
    depois = arquivo.read_text(encoding="utf-8")
    assert depois.startswith(antes) and depois.count(formato.TITULO) == 1
    assert [(e.hora_em_texto, e.autor) for e in formato.ler(arquivo)] == [("14:10:03", "você"),
                                                                          ("14:10:43", "automático")]


def test_uma_secao_do_usuario_depois_ganha_o_titulo_de_novo(tmp_path):
    arquivo = tmp_path / "anotacoes.md"
    formato.acrescentar(arquivo, "primeira", formato.VOCE, QUANDO)
    with open(arquivo, "a", encoding="utf-8") as f:
        f.write("\n## Decisões\n\n- a taxa de trabalho fica em 400 kS/s")           # sem a quebra de linha no fim
    formato.acrescentar(arquivo, "segunda", formato.VOCE, QUANDO)
    texto = arquivo.read_text(encoding="utf-8")
    assert texto.count(formato.TITULO) == 2
    assert texto.endswith("- a taxa de trabalho fica em 400 kS/s\n\n## Caderno de bancada\n\n"
                          "- **14:10:03** · você · segunda\n")
    assert [e.texto for e in formato.ler(arquivo)] == ["primeira", "segunda"]


def test_a_entrada_de_varias_linhas_volta_igual(tmp_path):
    """As linhas de detalhe (a conferência, o relatório do diagnóstico, com linhas vazias e títulos dentro) ficam
    recuadas: a leitura as junta na entrada, e um título recuado não conta como o último do arquivo."""
    relatorio = "Relatório do diagnóstico:\n\n# Diagnóstico da placa\n\n## PRU\n\n- ✓ rodando\n  - remoteproc1"
    arquivo = tmp_path / "anotacoes.md"
    formato.acrescentar(arquivo, relatorio, formato.AUTOMATICO, QUANDO)
    formato.acrescentar(arquivo, "depois", formato.VOCE, QUANDO)
    texto = arquivo.read_text(encoding="utf-8")
    assert "\n  # Diagnóstico da placa\n" in texto and texto.count(formato.TITULO) == 1
    (r, d) = formato.ler(arquivo)
    assert r.texto == relatorio and d.texto == "depois"


def test_as_entradas_escritas_a_mao_tambem_valem():
    texto = ("# Anotações\n\n- **9:05** · você · cabo trocado\n  pelo azul\nTexto solto depois.\n"
             "- **25:00** · você · hora impossível\n- **10:00** · alguém · outro autor\n"
             "- **10:30:15** · automático · a do aplicativo\n")
    entradas = formato.ler_texto(texto)
    assert [(e.hora_em_texto, e.texto) for e in entradas] == [("09:05:00", "cabo trocado\npelo azul"),
                                                              ("10:30:15", "a do aplicativo")]


def test_o_formato_recusa_a_entrada_sem_texto_e_o_autor_desconhecido():
    with pytest.raises(ValueError):
        formato.formatar("  \n", formato.VOCE, QUANDO)
    with pytest.raises(ValueError):
        formato.formatar("nota", "alguém", QUANDO)


def test_criar_poe_so_o_titulo_e_nao_mexe_no_que_existe(tmp_path):
    arquivo = tmp_path / "2026-11-18" / "anotacoes.md"
    assert formato.criar(arquivo, QUANDO)
    assert arquivo.read_text(encoding="utf-8") == "# Anotações da bancada: 2026-11-18\n\n"
    arquivo.write_text("meu texto\n", encoding="utf-8")
    assert not formato.criar(arquivo, QUANDO) and arquivo.read_text(encoding="utf-8") == "meu texto\n"


# ------------------------------------------------------------------ o caderno da sessão


class Relogio:
    def __init__(self):
        self.agora = QUANDO

    def __call__(self):
        self.agora += datetime.timedelta(seconds=1)
        return self.agora


@pytest.fixture
def sessao(qapp, tmp_path):
    criar_aplicacao([], tema="escuro")
    pasta = {"dia": tmp_path / "lab" / "2026-11-18"}
    c = CadernoDaSessao(lambda: pasta["dia"], relogio=Relogio())
    c.pasta = pasta
    yield c
    c.deleteLater()


def test_as_notas_e_as_entradas_automaticas_vao_para_o_arquivo(sessao, qtbot):
    with qtbot.waitSignal(sessao.mudou):
        assert sessao.anotar("Cabo do canal 1 trocado.")
    assert sessao.registrar("Captura `a.bin` iniciada.") and not sessao.anotar("   ")
    assert [(e.autor, e.texto) for e in sessao.entradas] == [("você", "Cabo do canal 1 trocado."),
                                                             ("automático", "Captura `a.bin` iniciada.")]
    assert formato.ler(sessao.caminho) == sessao.entradas and sessao.erro == ""


def test_o_arquivo_mudado_no_editor_e_lido_de_novo(sessao, qtbot):
    """O ``lab notas`` aberto: a gravação do editor (inclusive a que troca o arquivo, como o nvim) volta para a
    lista."""
    sessao.anotar("primeira")
    with open(sessao.caminho, "a", encoding="utf-8") as f:
        f.write("- **14:20:00** · você · escrita no editor\n")
    qtbot.waitUntil(lambda: len(sessao.entradas) == 2, timeout=5000)
    novo = sessao.caminho.with_suffix(".tmp")
    novo.write_text(sessao.caminho.read_text(encoding="utf-8") + "- **14:21:00** · você · gravada por troca\n",
                    encoding="utf-8")
    os.replace(novo, sessao.caminho)
    qtbot.waitUntil(lambda: len(sessao.entradas) == 3, timeout=5000)
    with open(sessao.caminho, "a", encoding="utf-8") as f:                       # e o observador segue o novo
        f.write("- **14:22:00** · você · e mais uma\n")
    qtbot.waitUntil(lambda: len(sessao.entradas) == 4, timeout=5000)
    assert sessao.entradas[-1].texto == "e mais uma"


def test_o_dia_que_vira_leva_ao_caderno_novo(sessao):
    sessao.anotar("de ontem")
    ontem = sessao.caminho
    sessao.pasta["dia"] = ontem.parent.parent / "2026-11-19"
    sessao._conferir_o_dia()
    assert sessao.entradas == [] and sessao.caminho.parent.name == "2026-11-19"
    sessao.anotar("de hoje")
    assert [e.texto for e in formato.ler(ontem)] == ["de ontem"]
    assert [e.texto for e in formato.ler(sessao.caminho)] == ["de hoje"]


def test_o_disco_que_recusa_nao_perde_a_nota(sessao, tmp_path, qtbot):
    """A pasta do dia que não dá para criar (um arquivo no lugar dela): a nota volta ``False``, com o motivo, e a
    coluna a deixa no campo."""
    bloqueio = tmp_path / "arquivo_no_lugar"
    bloqueio.write_text("x")
    sessao.pasta["dia"] = bloqueio / "2026-11-18"
    coluna = CadernoDeBancada(sessao, abrir_url=lambda _url: None)
    qtbot.addWidget(coluna)
    coluna.nota.setText("não pode sumir")
    coluna.anotar()
    assert sessao.erro.startswith("O caderno não foi gravado") and coluna.erro.text() == sessao.erro
    assert coluna.nota.text() == "não pode sumir" and sessao.entradas == []
    sessao.pasta["dia"] = tmp_path / "lab" / "2026-11-18"
    coluna.anotar()
    assert coluna.nota.text() == "" and sessao.erro == "" and coluna.erro.isHidden()
    assert len(coluna.lista.textos) == 1 and coluna.lista.textos[0].endswith(" · você · não pode sumir")


def test_a_coluna_mostra_a_mais_nova_em_cima_e_abre_o_arquivo(sessao, qtbot):
    abertos = []
    coluna = CadernoDeBancada(sessao, abrir_url=abertos.append)
    qtbot.addWidget(coluna)
    assert coluna.lista.textos == [] and "Nada ainda" in coluna.lista.toPlainText()
    coluna.abrir_no_editor()                                  # antes da primeira entrada: só o título do dia
    assert abertos == [QUrl.fromLocalFile(str(sessao.caminho))] and sessao.caminho.exists()
    assert sessao.entradas == []
    for texto in ("primeira", "segunda"):
        coluna.nota.setText(texto)
        coluna.nota.returnPressed.emit()
    assert [t.split(" · ")[-1] for t in coluna.lista.textos] == ["segunda", "primeira"]
    assert "anotacoes.md em" in coluna.onde.text() and coluna.onde.toolTip() == str(sessao.caminho)


# ------------------------------------------------------------------ as frases das entradas automáticas


def test_as_frases_da_correcao_e_da_transferencia(tmp_path):
    relogio = Correcao("relogio", "feita", "O relógio da placa estava 2,15 s adiantado; agora está certo.", True)
    assert frases.frase_da_correcao(relogio) == ("Relógio da placa acertado ao conectar: o relógio da placa estava "
                                                 "2,15 s adiantado; agora está certo.")
    assert frases.frase_da_correcao(Correcao("pinos", "falhou", "O config-pin falhou.")) == (
        "A correção dos pinos da PRU não deu: o config-pin falhou.")

    def item(estado, **extra):
        base = {"captura": SimpleNamespace(arquivo="rede.bin"), "local": tmp_path / "rede.bin", "como": "crc32",
                "erro": "", "estado": estado}
        return SimpleNamespace(**{**base, **extra})

    assert frases.frase_da_transferencia(item("conferida")) == (
        f"`rede.bin` veio para o computador e confere pelo CRC das amostras: `{tmp_path / 'rede.bin'}`.")
    assert "NÃO confere" in frases.frase_da_transferencia(item("corrompida", erro="o CRC difere"))
    assert "a conexão caiu" in frases.frase_da_transferencia(item("interrompida"))
    assert frases.frase_da_transferencia(item("cancelada")) is None


def test_as_linhas_de_detalhe_vem_com_a_marca_e_os_erros_primeiro():
    from sh_placa.pedido import Problema

    linhas = frases.linhas_marcadas([Problema("nivel", "info", "60 Hz", 1), Problema("faixa", "erro", "saturou", 0),
                                     Problema("disco", "aviso", "o cartão está quase cheio")])
    assert linhas == ["- ✗ Canal 0: saturou", "- ! O cartão está quase cheio", "- ✓ Canal 1: 60 Hz"]


# ------------------------------------------------------------------ a seção Notas do projeto e o inspetor


def test_a_secao_notas_mostra_os_cadernos_das_pastas_das_capturas(qapp, tmp_path):
    from sh_analyzer_gui.areas.analise.arvore import PAPEL_DETALHE, PAPEL_OBJETO, PAPEL_TIPO, ArvoreDoProjeto
    from sh_analyzer_gui.areas.analise.inspetor import Inspetor
    from sh_analyzer_gui.dados.captura import abrir_fonte
    from sh_analyzer_gui.modelo.comandos import AdicionarFonte, RemoverFonte
    from sh_analyzer_gui.modelo.objetos import FonteDoProjeto, Projeto

    def captura(pasta, nome):
        pasta.mkdir(parents=True, exist_ok=True)
        t = np.arange(4096) / 200_000
        return escrever_bin(pasta / nome, [np.sin(2 * np.pi * 60 * t)] * 2, canais=(0, 1))

    dia = tmp_path / "lab" / "2026-11-18"
    caderno = dia / "anotacoes.md"
    formato.acrescentar(caderno, "Captura `a.bin` iniciada.", formato.AUTOMATICO, QUANDO)
    formato.acrescentar(caderno, "Cabo trocado.", formato.VOCE, QUANDO)
    projeto = Projeto()
    modelo = ArvoreDoProjeto(projeto)
    QAbstractItemModelTester(modelo, QAbstractItemModelTester.FailureReportingMode.Fatal)
    notas = modelo.index(2, 0)
    assert notas.data() == "Notas" and modelo.rowCount(notas) == 0
    a = FonteDoProjeto(abrir_fonte(captura(dia, "a.bin")))
    b = FonteDoProjeto(abrir_fonte(captura(dia, "b.bin")))
    sem = FonteDoProjeto(abrir_fonte(captura(tmp_path / "sem_caderno", "c.bin")))
    for fonte in (a, b, sem):
        projeto.pilha.push(AdicionarFonte(projeto, fonte))
    assert modelo.notas == [caderno]                         # uma por pasta, e só as que têm o caderno
    nota = modelo.index(0, 0, notas)
    assert (nota.data(), nota.data(PAPEL_TIPO), nota.data(PAPEL_DETALHE)) == ("2026-11-18", "nota", "2 entradas")
    formato.acrescentar(caderno, "Mais uma.", formato.VOCE, QUANDO)
    modelo.atualizar_as_notas()
    assert modelo.index(0, 0, notas).data(PAPEL_DETALHE) == "3 entradas"

    inspetor = Inspetor()
    inspetor.mostrar("nota", nota.data(PAPEL_OBJETO))
    assert inspetor.currentWidget() is inspetor.do_caderno
    assert inspetor.do_caderno.lista.textos[0] == "14:10:03 · você · Mais uma."
    assert inspetor.do_caderno.titulo.text() == "Caderno de 2026-11-18"
    pedidos = []
    inspetor.do_caderno.abrirPedido.connect(pedidos.append)
    inspetor.do_caderno.abrir.click()
    assert pedidos == [caderno]

    for fonte in (a, b):
        projeto.pilha.push(RemoverFonte(projeto, fonte))
    assert modelo.notas == [] and modelo.rowCount(notas) == 0
    projeto.pilha.undo()
    assert modelo.notas == [caderno]


def test_o_caderno_se_esconde_e_volta_lembrado(qapp, config_limpa, tmp_path, qtbot):
    """A coluna na seção Capturar: o "x" a esconde, o "Caderno" do título a traz, e a escolha fica nas
    preferências."""
    from placas_de_teste import CofreFalso
    from sh_analyzer_gui.areas.aquisicao.capturar import Capturar
    from sh_analyzer_gui.servicos.conexao_da_placa import ConexaoDaPlaca
    from sh_analyzer_gui.servicos.conferencia_da_placa import ConferenciaDaPlaca
    from sh_analyzer_gui.servicos.placa import ServicoDaPlaca
    from sh_analyzer_gui.servicos.saude_da_placa import SaudeDaPlaca
    from sh_placa.descoberta import Descoberta

    criar_aplicacao([], tema="escuro")
    servico = ServicoDaPlaca()
    conexao = ConexaoDaPlaca(servico, descoberta=Descoberta([]), pasta=tmp_path / "aplicativo", cofre=CofreFalso())
    saude = SaudeDaPlaca(conexao)
    sessao = CadernoDaSessao(lambda: tmp_path / "sessao")

    def secao():
        s = Capturar(conexao, saude, ConferenciaDaPlaca(conexao, saude), pasta_do_destino=lambda: tmp_path / "sessao",
                     caderno=sessao)
        qtbot.addWidget(s)
        s.show()
        return s

    try:
        s = secao()
        assert s.caderno.isVisible() and not s.mostrar_o_caderno.isVisible()
        s.caderno.esconder.click()
        assert not s.caderno.isVisible() and s.mostrar_o_caderno.isVisible()
        assert not preferencias.caderno_visivel()
        assert not secao().caderno.isVisible()                      # a seção nova (o aplicativo aberto de novo)
        s.mostrar_o_caderno.click()
        assert s.caderno.isVisible() and preferencias.caderno_visivel()
    finally:
        conexao.encerrar()
        assert servico.encerrar()
