"""Os textos da placa conectada, os mesmos em todo lugar: o cartão da barra lateral, o chip da barra superior, a barra
de status e a visão geral dizem o estado, o caminho e o enlace com as mesmas palavras."""

from __future__ import annotations

import time
from dataclasses import dataclass

from PySide6.QtCore import QCoreApplication

from ...componentes.numeros import formatar_si
from ...servicos.conexao_da_placa import ConexaoDaPlaca

CAMINHOS_CURTOS = {"usb": "USB", "lan": "LAN", "wan": "WAN", "simulador": "simulador"}
TAXA_DA_SAIDA_CONTINUA_HZ = 400_000
BYTES_POR_AMOSTRA = 2
FOLGA_DA_SAIDA_CONTINUA = 2
"""A saída contínua (docs/gui-plan.md, 11.6) pede o dobro do fluxo da captura: a 400 kS/s, de 16 bits, 1,6 MB/s."""


def traduzir(texto: str) -> str:
    """O texto na língua da interface (o contexto das traduções da Aquisição)."""
    return QCoreApplication.translate("Aquisicao", texto)


def frase(texto: str) -> str:
    """Um motivo do ``sh_placa`` ("a placa em … não respondeu") como frase: a maiúscula e o ponto."""
    texto = texto.strip()
    if not texto:
        return ""
    texto = texto[0].upper() + texto[1:]
    return texto if texto.endswith((".", "!", "?", ")")) else texto + "."


@dataclass(frozen=True)
class Resumo:
    nivel: str          # o do chip da barra superior: sem_placa, conectando, conectada, atencao ou erro
    titulo: str         # curto: "BeagleBone Black · USB", "Conectando…", "Sem conexão"
    detalhe: str        # a frase do que está acontecendo


def nome_da_placa(conexao: ConexaoDaPlaca) -> str:
    """O nome que o usuário vê: o da lista (o da placa conhecida, ou o que ela anuncia), senão o modelo que o agente
    diz, senão "BeagleBone"."""
    if conexao.placa is not None and conexao.placa.nome:
        return conexao.placa.nome
    estado = conexao.estado_da_placa
    return (estado.nome_da_placa if estado is not None else None) or "BeagleBone"


def caminho_curto(conexao: ConexaoDaPlaca) -> str:
    """"USB", "LAN", "WAN", "simulador"; num endereço digitado, o host."""
    tipo = conexao.tipo_do_caminho
    if tipo in CAMINHOS_CURTOS:
        return CAMINHOS_CURTOS[tipo]
    return conexao.destino.host if conexao.destino is not None else ""


def resumo(conexao: ConexaoDaPlaca) -> Resumo:
    estado = conexao.estado
    alvo = str(conexao.destino) if conexao.destino is not None else traduzir("o simulador")
    if estado == "conectando":
        return Resumo("conectando", traduzir("Conectando…"), traduzir("Conectando a {}…").format(alvo))
    if estado == "confirmar_host":
        pedido = conexao.destino_pedido or conexao.destino
        return Resumo("conectando", traduzir("Conectando…"),
                      traduzir("A primeira conexão com {}: confira a impressão digital.").format(pedido.conta))
    if estado == "pedir_senha":
        pedido = conexao.destino_pedido or conexao.destino
        return Resumo("conectando", traduzir("Conectando…"), traduzir("{} pede a senha.").format(pedido.conta))
    if estado == "conectada" and conexao.simulada:
        return Resumo("conectada", traduzir("Simulador"), traduzir("Conectada ao simulador, neste computador."))
    if estado == "conectada":
        nome = nome_da_placa(conexao)
        return Resumo("conectada", f"{nome} · {caminho_curto(conexao)}", traduzir("Conectada a {} ({}).").format(nome, alvo))
    if estado == "reconectando":
        return Resumo("atencao", traduzir("Reconectando…"),
                      traduzir("A conexão com {} caiu; tentando de novo sozinho.").format(nome_da_placa(conexao)))
    if estado == "bloqueada":
        bloqueio = conexao.bloqueio
        conta = bloqueio.destino.conta if bloqueio is not None else alvo
        return Resumo("erro", traduzir("Bloqueada"),
                      traduzir("A chave de host de {} mudou: a conexão foi bloqueada.").format(conta))
    if estado == "falhou":
        return Resumo("erro", traduzir("Sem conexão"), frase(conexao.motivo) or traduzir("A conexão falhou."))
    return Resumo("sem_placa", traduzir("Sem placa"), traduzir("Nenhuma placa conectada."))


def texto_da_latencia(latencia_ms: float) -> str:
    return formatar_si(latencia_ms / 1000, "s", 2)


def texto_da_vazao(bytes_s: float) -> str:
    return formatar_si(bytes_s, "B/s", 2)


def texto_do_enlace(conexao: ConexaoDaPlaca) -> str:
    """"latência 1 ms · 6,3 MB/s"; enquanto mede, "medindo o enlace…"; no simulador, "neste computador"."""
    if conexao.simulada:
        return traduzir("neste computador")
    if conexao.medindo_enlace:
        return traduzir("medindo o enlace…")
    enlace = conexao.enlace
    if enlace is None:
        return traduzir("o enlace não foi medido") if conexao.erro_do_enlace else ""
    partes = [traduzir("latência {}").format(texto_da_latencia(enlace.latencia_ms))]
    if enlace.vazao_bytes_s:
        partes.append(texto_da_vazao(enlace.vazao_bytes_s))
    return " · ".join(partes)


def vazao_da_saida_continua() -> float:
    """O que a saída contínua a 400 kS/s pede do enlace, com a folga (bytes/s)."""
    return TAXA_DA_SAIDA_CONTINUA_HZ * BYTES_POR_AMOSTRA * FOLGA_DA_SAIDA_CONTINUA


def texto_da_folga(bytes_s: float) -> tuple[str, bool]:
    """O que a vazão medida permite: ``(texto, dá?)``."""
    pede = vazao_da_saida_continua()
    taxa = formatar_si(TAXA_DA_SAIDA_CONTINUA_HZ, "S/s", 3)
    if bytes_s >= pede:
        return traduzir("dá para a saída contínua a {}").format(taxa), True
    return traduzir("menos que os {} da saída contínua a {}").format(texto_da_vazao(pede), taxa), False


def hora(instante: float) -> str:
    return time.strftime("%H:%M", time.localtime(instante))


def ha_quanto(instante: float | None, agora: float | None = None) -> str:
    """"agora", "há 5 min", "há 3 h", "há 2 dias", "em 12/11"; "nunca" sem instante."""
    if not instante:
        return traduzir("nunca")
    agora = time.time() if agora is None else agora
    segundos = max(0.0, agora - instante)
    if segundos < 60:
        return traduzir("agora")
    if segundos < 3600:
        return traduzir("há {} min").format(int(segundos // 60))
    if segundos < 86_400:
        return traduzir("há {} h").format(int(segundos // 3600))
    if segundos < 7 * 86_400:
        dias = int(segundos // 86_400)
        return traduzir("há 1 dia") if dias == 1 else traduzir("há {} dias").format(dias)
    return traduzir("em {}").format(time.strftime("%d/%m", time.localtime(instante)))
