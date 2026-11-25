"""Confere o aplicativo empacotado por dentro (F7.12 em docs/gui-progress.md, 4h): roda **no executável do pacote**,
fazendo de Python (``sh_placa.como_python``), e não no Python de quem construiu:

    SHAN_COMO_PYTHON=1 PASTA/dist/sh-analyzer-gui/sh-analyzer-gui empacotamento/conferir_pacote.py

(o ``construir.sh`` faz isso depois de cada construção, e a CI dos instaladores também). Confere o que só falha no
pacote: um módulo que o PyInstaller não achou (todos são importados), os dados que vão junto (o guia, as sondas, o
firmware com a versão e o agente), o agente rodado pelo executável, a captura de exemplo aberta e medida pelo motor e
pelas contas da interface e, fora do Windows, uma conferência de um bloco na placa simulada, pelo SSH (o ``ler_adc``
simulado e o ``sudo`` dela rodando pelo executável). Sai com 0 se tudo passou; senão, com 1 e o que falhou.
"""

from __future__ import annotations

import asyncio
import importlib
import os
import pkgutil
import sys
import tempfile
import time
import traceback
from pathlib import Path

PACOTES = ("sh_analyzer_gui", "sh_placa", "supraharmonicos")
SECOES_DO_GUIA = ("primeiros-passos", "espectro", "qualidade", "transferencia", "instrumento", "aquisicao")


def conferir_modulos() -> str:
    """Todos os módulos dos três pacotes importam (o PyInstaller acha os imports do topo; os de dentro das funções,
    nem sempre)."""
    falhas, total = [], 0
    for nome in PACOTES:
        pacote = importlib.import_module(nome)
        for info in pkgutil.walk_packages(pacote.__path__, nome + "."):
            if ".prototipos" in info.name or info.name.endswith(".__main__"):
                continue                              # as bancadas de quem desenvolve; o __main__ abriria a janela
            total += 1
            try:
                importlib.import_module(info.name)
            except Exception as e:                    # noqa: BLE001 (a lista do que falhou é o resultado)
                falhas.append(f"{info.name}: {type(e).__name__}: {e}")
    if falhas:
        raise AssertionError("módulos que não importam:\n  " + "\n  ".join(falhas))
    return f"{total} módulos"


def conferir_dados() -> str:
    from sh_analyzer_gui import ajuda
    from sh_placa import agente, atualizacao, versao
    from supraharmonicos import api

    secoes = {s.id for s in ajuda.ler_guia()}
    faltam = [s for s in SECOES_DO_GUIA if s not in secoes]
    assert not faltam, f"o guia ({ajuda.caminho_do_guia()}) sem as seções {faltam}"
    sondas = sorted(p.name for p in Path(api.PASTA_DAS_SONDAS_PADRAO).glob("*.json"))
    assert "cadeia_tensao.json" in sondas, f"sem as sondas em {api.PASTA_DAS_SONDAS_PADRAO}: {sondas}"
    api.carregar_perfil_sonda(Path(api.PASTA_DAS_SONDAS_PADRAO) / "cadeia_tensao.json")
    fw = atualizacao.firmware_do_aplicativo()
    assert fw is not None and fw.origem == "pacote", f"o firmware do pacote não foi achado: {fw}"
    nomes = {a.caminho: a for a in fw.arquivos}
    for nome in ("ler_adc.c", "pru_main.c", "Makefile", "coletar.sh", "agente/shan_agente.py"):
        assert nome in nomes, f"o firmware do pacote sem o {nome}"
    assert nomes["coletar.sh"].executavel, "o coletar.sh do pacote sem a marca de executável"
    assert versao.firmware_do_aplicativo(None) == fw.versao
    assert agente.AGENTE.is_file(), f"sem o agente em {agente.AGENTE}"
    return f"{len(secoes)} seções do guia, {len(sondas)} sondas, o firmware {fw.versao} ({len(fw.arquivos)} arquivos)"


def conferir_agente() -> str:
    from sh_placa.agente import ClienteDoAgente, TransporteLocal

    with tempfile.TemporaryDirectory() as pasta:
        resposta = asyncio.run(ClienteDoAgente(TransporteLocal(Path(pasta), Path(pasta) / "firmware")).chamar("versao"))
    assert "protocolo" in resposta, resposta
    return f"o agente local respondeu (protocolo {resposta['protocolo']})"


def conferir_exemplo() -> str:
    """A captura de exemplo dos primeiros passos (a placa simulada grava), aberta e medida pelo motor (a f1, o
    espectro) e pelas contas da interface (a transferência entre a corrente e a tensão)."""
    from sh_analyzer_gui.componentes.primeiros_passos import gerar_exemplo
    from sh_analyzer_gui.dados import qualidade
    from supraharmonicos import api

    with tempfile.TemporaryDirectory() as pasta:
        captura = api.abrir_captura(gerar_exemplo(Path(pasta)))
        integridade = api.conferir_integridade(captura)
        tensao, corrente = api.sinal_do_canal(captura, 1), api.sinal_do_canal(captura, 0)
        taxa = captura.canal(1).taxa_hz
        medidas = api.medir_sinal(tensao, taxa)
        espectro = api.espectro(tensao, taxa)
        transferencia = qualidade.transferencia(corrente, tensao, taxa, 100.0)
        del captura                                   # o memmap, antes de a pasta sumir (no Windows, ele a prende)
    assert medidas.f1_hz is not None and abs(medidas.f1_hz - 60.0) < 0.05, f"a f1 do exemplo: {medidas.f1_hz}"
    assert len(espectro.freqs_hz) > 400 and len(transferencia.frequencias) > 900
    return (f"o exemplo: {len(tensao)} amostras a {taxa:g} Hz, {integridade}, f1 = {medidas.f1_hz:.3f} Hz, "
            f"{medidas.rms:.1f} V rms")


def conferir_placa_simulada() -> str:
    from sh_placa.conexao import ConexaoSSH
    from sh_placa.conferencia import conferir
    from sh_placa.pedido import Canal, PedidoDeCaptura
    from sh_placa.registro import RegistroDeAtividade
    from sh_placa.servidor_do_simulador import ServidorDoSimulador

    async def cenario(pasta: Path):
        async with ServidorDoSimulador(pasta / "placa", vazao_bytes_s=None) as placa:
            chave, hosts = placa.acesso()
            async with ConexaoSSH(placa.destino, chave=chave, hosts=hosts, registro=RegistroDeAtividade(),
                                  senha=placa.senha_do_sudo) as c:
                pedido = PedidoDeCaptura((Canal(1, faixa_v=10.24),), 400_000, duracao_s=60.0)
                return await conferir(c, pedido, pasta / "conferencias", senha_do_sudo=placa.senha_do_sudo)

    with tempfile.TemporaryDirectory() as pasta:
        feita = asyncio.run(cenario(Path(pasta)))
    assert feita.recebida.codigo == 0 and feita.conferencia.integra, (feita.recebida.codigo, feita.recebida.texto)
    canal = feita.conferencia.canais[0]
    return f"um bloco da placa simulada pelo SSH: o canal {canal.canal}, {canal.amostras} amostras, íntegro"


def _dizer(texto: str) -> None:
    sys.stdout.write(texto + "\n")
    sys.stdout.flush()


def main() -> int:
    if not getattr(sys, "frozen", False):
        sys.stderr.write("rode no executável do pacote, com SHAN_COMO_PYTHON=1 (ver o começo deste arquivo)\n")
        return 2
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    conferencias = [conferir_modulos, conferir_dados, conferir_agente, conferir_exemplo]
    if sys.platform != "win32":
        conferencias.append(conferir_placa_simulada)
    falhas = 0
    for conferencia in conferencias:
        inicio = time.perf_counter()
        try:
            resultado = conferencia()
        except Exception:                             # noqa: BLE001
            falhas += 1
            _dizer(f"✗ {conferencia.__name__}\n{traceback.format_exc()}")
        else:
            _dizer(f"✓ {conferencia.__name__}: {resultado} ({time.perf_counter() - inicio:.1f} s)")
    _dizer("o pacote confere" if not falhas else f"{falhas} conferência(s) falharam")
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(main())
