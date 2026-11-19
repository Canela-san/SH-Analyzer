"""As entradas automáticas do caderno de bancada (a F4.5; o plano, PD-09): as frases e as ligações com os serviços.

Cada fato vem de um sinal emitido na hora em que ele acontece (e não de comparar estados): os marcos da captura
(``CapturaDaPlaca.marco``), o fim de uma conferência (``ConferenciaDaPlaca.terminou``), uma transferência no estado
final (``TransferenciasDaPlaca.terminou``) e uma correção que terminou (``SaudeDaPlaca.corrigiu``). As frases usam o
que a tela mostra (o resumo do pedido, as linhas da conferência e do fim, com os mesmos números), com as linhas de
detalhe recuadas e marcadas como no ``conferir.sh``: ✓, ! e ✗.

Uma função de frase devolve ``None`` quando o fato não vai para o caderno (a transferência cancelada pelo usuário).
"""

from __future__ import annotations

from collections.abc import Iterable

from sh_placa.pedido import Problema, comando

from ...servicos.caderno import CadernoDaSessao
from ...servicos.captura_da_placa import CapturaDaPlaca
from ...servicos.conferencia_da_placa import ConferenciaDaPlaca
from ...servicos.saude_da_placa import Correcao, SaudeDaPlaca
from .ao_vivo import linhas_do_fim, titulo_do_fim
from .capturar import linhas_da_conferencia, resumo_do_pedido
from .formulario_de_captura import em_ordem, texto_do_problema
from .textos import traduzir

MARCAS = {"info": "✓", "aviso": "!", "erro": "✗"}


def linhas_marcadas(problemas: Iterable[Problema]) -> list[str]:
    """As linhas de detalhe de uma entrada: "- ✓ Canal 1: ...", os erros primeiro."""
    return [f"- {MARCAS.get(p.nivel, '·')} {texto_do_problema(p)}" for p in em_ordem(problemas)]


def _minuscula(frase: str) -> str:
    return frase[:1].lower() + frase[1:] if frase else frase


def frase_da_captura(marco: str, captura: CapturaDaPlaca) -> str | None:
    nome = f"`{captura.nome}`"
    if marco == "comecou":
        pedido = captura.pedido
        if pedido is None:
            return None
        titulo = f" (“{pedido.titulo}”)" if pedido.titulo else ""
        return "\n".join([traduzir("Captura {}{} iniciada: {}.").format(nome, titulo, resumo_do_pedido(pedido)),
                          f"`{comando(pedido)}`"])
    if marco == "caiu":
        return traduzir("A conexão caiu durante a captura {}: ela segue no cartão da placa.").format(nome)
    if marco == "retomada":
        return traduzir("A captura {}, no cartão, acompanhada de novo (a conexão voltou).").format(nome)
    if marco == "terminou" and captura.fim is not None:
        f = captura.fim
        detalhes = [p for p in linhas_do_fim(f, captura) if p.campo != "transferencia"]
        return "\n".join([f"{titulo_do_fim(f)} ({nome}).", *linhas_marcadas(detalhes)])
    if marco == "falhou":
        return traduzir("A captura {} não deu: {}").format(nome, captura.erro or traduzir("sem o motivo"))
    return None


def frase_da_conferencia(conferencia: ConferenciaDaPlaca) -> str | None:
    if conferencia.estado == "falhou":
        return traduzir("A conferência não deu: {}").format(conferencia.erro or traduzir("sem o motivo"))
    feita = conferencia.resultado
    if conferencia.estado != "feita" or feita is None:
        return None
    titulo = (traduzir("Conferência: pronto para capturar.") if feita.pronta else
              traduzir("Conferência: {} problema(s).").format(max(1, feita.problemas)))
    return "\n".join([titulo, *linhas_marcadas(linhas_da_conferencia(feita))])


def frase_da_transferencia(item) -> str | None:
    nome = f"`{item.captura.arquivo}`"
    como = {"crc32": traduzir("pelo CRC das amostras"), "sha256": traduzir("pelo SHA-256")}.get(item.como, item.como)
    if item.estado == "conferida":
        return traduzir("{} veio para o computador e confere {}: `{}`.").format(nome, como, item.local)
    if item.estado == "corrompida":
        return traduzir("A cópia de {} NÃO confere com a da placa ({}): a da placa fica lá.").format(
            nome, item.erro or como)
    if item.estado == "interrompida":
        return traduzir("A transferência de {} parou: a conexão caiu{}.").format(
            nome, f" ({item.erro})" if item.erro else "")
    if item.estado == "falhou":
        return traduzir("A transferência de {} não deu: {}").format(nome, item.erro or traduzir("sem o motivo"))
    return None


def frase_da_correcao(correcao: Correcao) -> str | None:
    feita = correcao.estado == "feita"
    if correcao.nome == "relogio":
        if feita:
            quando = traduzir(" ao conectar") if correcao.automatica else ""
            return traduzir("Relógio da placa acertado{}: {}").format(quando, _minuscula(correcao.mensagem))
        return traduzir("O acerto do relógio da placa não deu: {}").format(_minuscula(correcao.mensagem))
    if correcao.nome == "pinos":
        if feita:
            return traduzir("Pinos da PRU corrigidos: {}").format(_minuscula(correcao.mensagem))
        return traduzir("A correção dos pinos da PRU não deu: {}").format(_minuscula(correcao.mensagem))
    if correcao.nome == "pru":
        if feita:
            return traduzir("Firmware da PRU recarregado: {}").format(_minuscula(correcao.mensagem))
        return traduzir("O firmware da PRU não foi recarregado: {}").format(_minuscula(correcao.mensagem))
    return None


def frase_da_atualizacao(a) -> str | None:
    """O fim de uma atualização do firmware (``servicos/manutencao_da_placa.py``)."""
    d = a.desfecho
    if d is None:
        return traduzir("{}: não terminou ({})").format(traduzir(a.titulo), _minuscula(a.mensagem)) if a.mensagem \
            else None
    feita = {"placa": traduzir("Firmware da placa compilado e carregado de novo: {}"),
             "anterior": traduzir("Firmware da placa de volta a uma versão anterior: {}")}.get(
        a.origem, traduzir("Firmware da placa atualizado: {}"))
    texto = {"atualizada": feita,
             "voltou": traduzir("A atualização do firmware falhou, e a placa voltou à versão anterior: {}"),
             "falhou_antes": traduzir("A atualização do firmware não mudou a placa: {}"),
             "falhou_ao_voltar": traduzir("A atualização do firmware falhou e a placa não voltou sozinha: {}"),
             "interrompida": traduzir("A atualização do firmware foi interrompida: {}")}.get(d.estado)
    if texto is None:
        return None
    frase_ = texto.format(_minuscula(d.mensagem))
    if d.copia and d.estado != "falhou_antes":
        frase_ += traduzir(" (a cópia de antes: `{}`)").format(d.copia)
    if a.de_antes:
        frase_ = traduzir("Achada ao conectar, de antes desta conexão: {}").format(_minuscula(frase_))
    return frase_


def frase_da_rotina(rotina, comando: str) -> str:
    return traduzir("Rotina “{}” no terminal da placa:").format(traduzir(rotina.titulo)) + f"\n`{comando}`"


def frase_do_relatorio(relatorio: str) -> str:
    return traduzir("Relatório do diagnóstico:") + "\n\n" + relatorio.strip()


def ligar(caderno: CadernoDaSessao, *, captura: CapturaDaPlaca | None = None,
          conferencia: ConferenciaDaPlaca | None = None, transferencias=None,
          saude: SaudeDaPlaca | None = None, rotinas=None, manutencao=None) -> None:
    """Liga os sinais dos serviços às entradas automáticas de ``caderno``."""

    def registrar(frase: str | None) -> None:
        if frase:
            caderno.registrar(frase)

    if captura is not None:
        captura.marco.connect(lambda marco: registrar(frase_da_captura(marco, captura)))
    if conferencia is not None:
        conferencia.terminou.connect(lambda: registrar(frase_da_conferencia(conferencia)))
    if transferencias is not None:
        transferencias.terminou.connect(lambda item: registrar(frase_da_transferencia(item)))
    if saude is not None:
        saude.corrigiu.connect(lambda correcao: registrar(frase_da_correcao(correcao)))
    if rotinas is not None:
        rotinas.rotinaIniciada.connect(lambda rotina, comando: registrar(frase_da_rotina(rotina, comando)))
    if manutencao is not None:
        manutencao.atualizacaoTerminou.connect(lambda a: registrar(frase_da_atualizacao(a)))
