"""O relatório da captura na janela ("Relatório da captura…", ``dados/relatorio.py``): os traços visíveis da vista
de tempo aberta (ou da que a vista aberta segue), cada um no trecho inteiro, com a cadeia dele; as contas numa
tarefa; a página gravada em HTML (as figuras dentro) ou em PDF (o ``QTextDocument`` do Qt, na thread da janela).
"""

from __future__ import annotations

import datetime
from pathlib import Path

import supraharmonicos.api as api
from PySide6.QtCore import QCoreApplication, QMarginsF, QSizeF, Qt, QUrl
from PySide6.QtGui import QImage, QPageLayout, QPageSize, QPdfWriter, QTextDocument

from ...componentes.numeros import decimal, formatar_campo, formatar_si, separador_decimal
from ...componentes.primeiros_passos import e_o_exemplo
from ...componentes.toast import Toast
from ...dados import espectros as esp
from ...dados import relatorio as rel
from ...dados.avisos import do_exemplo, do_importado, para_a_tela

FILTRO = "Página HTML (*.html);;PDF (*.pdf)"
MARGEM_MM = 18.0
LARGURA_UTIL_PT = (210.0 - 2 * MARGEM_MM) / 25.4 * 72
ALTURA_UTIL_PT = (297.0 - 2 * MARGEM_MM) / 25.4 * 72
INTEGRIDADES = {"confere": "confere", "nao_confere": "não confere", "sem_crc": "sem o CRC para conferir",
                "pendente": "não conferida ainda", "conferindo": "não conferida ainda", "erro": "erro ao conferir"}


def _numero_do_evento(valor: float, casas: int = 4) -> str:
    return decimal(f"{valor:.{casas}f}").replace("-", "−")


def _numero(valor: float, unidade: str, digitos: int) -> str:
    return formatar_si(valor, unidade, digitos)


def vista_de_tempo(area):
    """A vista de tempo do relatório: a aberta, ou a que a vista aberta segue, ou a primeira do projeto."""
    ativa = area.janela.vista_ativa()
    if ativa is not None and ativa.tipo != "tempo":
        ativa = next((v for v in area.projeto.vistas if v.id == getattr(ativa.opcoes, "vista_de_tempo", None)), None)
    return ativa or next((v for v in area.projeto.vistas if v.tipo == "tempo"), None)


def fonte_do_relatorio(fonte) -> rel.FonteDoRelatorio:
    captura = fonte.fonte.captura
    avisos = captura.avisos
    if e_o_exemplo(fonte.caminho):
        avisos = do_exemplo(avisos)
    elif getattr(captura.hdf5, "importado_de", None):
        avisos = do_importado(avisos)
    return rel.FonteDoRelatorio(fonte.nome, api.descrever_cabecalho(captura, formatar_campo),
                                INTEGRIDADES.get(fonte.integridade, fonte.integridade),
                                tuple(para_a_tela(a, separador_decimal()).texto for a in avisos))


def gerar(area, caminho: Path | None = None, *, notas: str = ""):
    """Pergunta onde gravar (sem ``caminho``) e põe as contas numa tarefa; devolve a tarefa, ou None (com o aviso
    do porquê)."""
    janela = area.janela
    vista = vista_de_tempo(area)
    tracos = [t for t in vista.tracos if t.receita.visivel] if vista is not None else []
    pedidos, fontes = [], {}
    for traco in tracos:
        r = traco.receita
        try:
            fonte = area.projeto.fonte(r.fonte)
        except KeyError:
            continue
        if fonte.esta_ausente:
            continue
        canal = fonte.canal(r.canal)
        estado = janela.materializacoes.estado_de(traco)
        pronta = estado.pronta.amostras if estado is not None and estado.pronta is not None else None
        trecho = esp.TrechoDoTraco(fonte.fonte.captura, r.canal, r.cadeia, janela.materializacoes.contexto(fonte, r.canal),
                                   0, len(canal.amostras), r.ganho, pronta, r.offset)
        unidade = r.unidade_de(canal.unidade)
        cadeia = r.cadeia.resumo()
        descricao = QCoreApplication.translate("Relatorio", "canal {} de {}, {}, {}").format(
            r.canal, fonte.nome, formatar_si(canal.taxa_hz, "S/s", 5),
            QCoreApplication.translate("Relatorio", "cadeia: {}").format(cadeia) if cadeia
            else QCoreApplication.translate("Relatorio", "sem transformações"))
        pedidos.append((trecho, traco.nome, unidade, descricao, canal.nome_grandeza == "tensão"))
        fontes.setdefault(fonte.id, fonte)
    if not pedidos:
        Toast.mostrar(janela, QCoreApplication.translate("Relatorio", "O relatório sai dos traços de uma vista de "
                                                         "tempo: plote um canal"), "aviso")
        return None
    if caminho is None:
        pasta = area.projeto.caminho.parent if area.projeto.caminho else Path.home()
        nome = Path(next(iter(fontes.values())).nome).stem
        caminho = janela.controle.dialogos.salvar_arquivo(
            QCoreApplication.translate("Relatorio", "Relatório da captura"), FILTRO, str(pasta / f"{nome}-relatorio.html"))
        if caminho is None:
            return None
    caminho = Path(caminho)
    if caminho.suffix.lower() not in (".html", ".htm", ".pdf"):
        caminho = caminho.with_name(caminho.name + ".html")
    fontes_do_relatorio = [fonte_do_relatorio(f) for f in fontes.values()]
    titulo = QCoreApplication.translate("Relatorio", "Relatório de {}").format(
        ", ".join(f.nome for f in fontes_do_relatorio))
    aplicativo = f"SH-Analyzer {QCoreApplication.applicationVersion() or 'dev'}"

    def trabalho(progresso, cancelado):
        secoes = []
        for k, (trecho, nome, unidade, descricao, tensao) in enumerate(pedidos):
            if cancelado():
                return None
            secoes.append(rel.calcular_traco(
                trecho, nome, unidade, descricao, tensao=tensao, numero=_numero_do_evento,
                separador=separador_decimal(),
                progresso=lambda f, k=k: progresso((k + f) / len(pedidos)), cancelado=cancelado))
        return rel.Relatorio(titulo, fontes_do_relatorio, secoes, aplicativo, datetime.datetime.now(), notas)

    def terminou(tarefa) -> None:
        if tarefa.estado == "falhou":
            Toast.mostrar(janela, QCoreApplication.translate("Relatorio", "O relatório não foi gerado: {}").format(
                tarefa.erro), "erro")
            return
        if tarefa.estado != "concluida" or tarefa.resultado is None:
            return
        try:
            gravar(tarefa.resultado, caminho)
        except OSError as e:
            Toast.mostrar(janela, QCoreApplication.translate("Relatorio", "O relatório não foi gravado: {}").format(e),
                          "erro")
            return
        area.relatorioGerado.emit(caminho)
        Toast.mostrar(janela, QCoreApplication.translate("Relatorio", "Relatório gravado: {}").format(caminho.name),
                      "sucesso")

    return janela.tarefas.iniciar(QCoreApplication.translate("Relatorio", "Relatório de {}").format(vista.nome),
                                  trabalho, "relatorio", pesada=True, ao_terminar=terminou)


def gravar(relatorio: rel.Relatorio, caminho: Path) -> Path:
    """Grava a página: em HTML (as figuras dentro, em base64) ou, com ``.pdf``, pelo ``QTextDocument`` em A4."""
    caminho = Path(caminho)
    if caminho.suffix.lower() != ".pdf":
        parcial = caminho.with_name(caminho.name + ".parcial")
        parcial.write_text(rel.em_html(relatorio, _numero), encoding="utf-8")
        parcial.replace(caminho)
        return caminho
    documento = QTextDocument()
    documento.setDocumentMargin(0)
    # A página do documento em pontos (a área útil do A4 com 18 mm de margem): o print_ a escala para a do PDF, e
    # as figuras cabem na largura.
    documento.setPageSize(QSizeF(LARGURA_UTIL_PT, ALTURA_UTIL_PT))
    for k, png in enumerate(rel.imagens(relatorio), start=1):
        documento.addResource(QTextDocument.ResourceType.ImageResource, QUrl(f"figura-{k}.png"),
                              QImage.fromData(png).scaledToWidth(int(LARGURA_UTIL_PT),
                                                                 Qt.TransformationMode.SmoothTransformation))
    documento.setHtml(rel.em_html(relatorio, _numero, para_o_qt=True))
    escritor = QPdfWriter(str(caminho))
    escritor.setTitle(relatorio.titulo)
    escritor.setCreator(relatorio.aplicativo)
    escritor.setResolution(96)
    escritor.setPageLayout(QPageLayout(QPageSize(QPageSize.PageSizeId.A4), QPageLayout.Orientation.Portrait,
                                       QMarginsF(MARGEM_MM, MARGEM_MM, MARGEM_MM, MARGEM_MM),
                                       QPageLayout.Unit.Millimeter))
    documento.print_(escritor)
    return caminho
