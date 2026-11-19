"""Os itens da placa conectada, os mesmos na saúde resumida da visão geral e no diagnóstico: a conexão (que só o
computador conhece) e os itens do ``sh_placa/diagnostico.py``, os problemas primeiro; e o que cada "Corrigir" roda."""

from __future__ import annotations

from sh_placa.atualizacao import roteiro_de_recarregar
from sh_placa.correcoes import comando_dos_pinos, roteiro_do_relogio
from sh_placa.diagnostico import ItemDoDiagnostico, itens_do_diagnostico

from ...servicos.conexao_da_placa import ConexaoDaPlaca
from ...servicos.saude_da_placa import SaudeDaPlaca
from .textos import caminho_curto, texto_do_enlace, traduzir

ORDEM_DOS_NIVEIS = {"erro": 0, "aviso": 1, "info": 2, "ok": 3}
TEXTOS_DAS_CORRECOES = {"pinos": "Corrigir…", "relogio": "Acertar…", "pru": "Recarregar…", "firmware": "Atualizar…",
                        "uenv": "Ajustar…"}
SEM_COMANDO = ("firmware", "uenv")
"""As correções que abrem uma página (a do firmware, na Manutenção), em vez de rodar um comando."""


def resumo_da_conexao(conexao: ConexaoDaPlaca) -> str:
    """"USB (ECM) · 192.168.6.2 · latência 1,1 ms · 6,6 MB/s · chave SSH do aplicativo"."""
    if conexao.simulada:
        return traduzir("o simulador, neste computador")
    caminho = conexao.detalhe_do_caminho or caminho_curto(conexao)
    host = conexao.destino.host if conexao.destino is not None else ""
    partes = [caminho, host if host != caminho else "", texto_do_enlace(conexao),
              traduzir("chave SSH do aplicativo") if conexao.autenticada_com == "chave" else traduzir("com a senha")]
    return " · ".join(x for x in partes if x)


def itens_da_placa(conexao: ConexaoDaPlaca, saude: SaudeDaPlaca) -> list[ItemDoDiagnostico]:
    """A conexão no topo e os itens do diagnóstico da saúde de agora, os problemas primeiro (vazio sem a saúde)."""
    e = saude.saude or conexao.estado_da_placa
    if e is None or not e.tem_diagnostico:
        return []
    itens = itens_do_diagnostico(e, saude.firmware_do_aplicativo)
    item_da_conexao = ItemDoDiagnostico("conexao", traduzir("Conexão"),
                                        "ok" if conexao.estado == "conectada" else "aviso", resumo_da_conexao(conexao))
    return [item_da_conexao, *sorted(itens, key=lambda i: ORDEM_DOS_NIVEIS[i.nivel])]


def comando_da_correcao(nome: str, saude: SaudeDaPlaca) -> str:
    """O que a correção ``nome`` roda na placa agora (o "Ver o comando"); vazio na que abre uma página."""
    if nome in SEM_COMANDO:
        return ""
    if nome == "pru":
        return roteiro_de_recarregar()
    if nome == "pinos":
        errados = saude.saude.pinos_errados if saude.saude is not None else []
        return comando_dos_pinos(errados) if errados else ""
    return roteiro_do_relogio()
