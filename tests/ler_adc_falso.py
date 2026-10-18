#!/usr/bin/env python3
"""``ler_adc`` FALSO, só para testar ``firmware/calibrar_sonda.sh`` sem hardware.

Imita a interface de linha de comando do ``firmware/ler_adc.c`` (taxa, lista de canais,
``--blocos``, ``--grandeza``, ``--sonda``, ``-o``, ``-t``, ``-d``) e grava um ``.bin`` v2 sintético com
o mesmo formato (``capturas_sinteticas.montar_cabecalho``). A descrição (``-d``) vai para o cabeçalho
e, se trouxer ``ref: amp=...``, a amplitude do tom injetado é essa (o gerador "obedeceu" ao operador). Quem usa é ``test_calibrar_sonda.py``,
que o chama através de um pequeno wrapper ``sh`` (o script de calibração executa o binário direto).

Variáveis de ambiente:
    SIM_DIR   pasta de trabalho da simulação (obrigatória): guarda o contador de chamadas, o
              ``chamadas.log`` (uma linha por chamada, com a diretiva aplicada e os argumentos) e,
              opcionalmente, o arquivo ``cenario``.
    SIM_SPB   amostras BRUTAS por bloco (padrão 1048576, o SAMPLES_PER_BUFFER real). Os testes usam
              um valor menor para ficarem rápidos; o cabeçalho registra o valor usado, então o
              script confere tamanho e totais do mesmo jeito.

``cenario``: linha N = diretiva da N-ésima chamada (linhas ausentes ou vazias = ``ok``):
    ok               captura normal
    sat_sonda        sonda saturada (amplitude absurda)         sat_ref   idem no canal de referência
    sem_sinal_sonda  sonda sem sinal (só ruído)                 sem_sinal_ref   idem na referência
    fraco            sinal fraco nos dois canais (~6% da escala)
    freq_errada      tom 30% acima do pedido                    freq_leve       7% acima
    falha            nenhum arquivo, sai com 255                travar    dorme (para testar o timeout)
    truncar          arquivo pela metade (disco cheio), sai 0   erro_mas_arquivo   arquivo bom, sai 7
    cab_zero         cabeçalho final não reescrito (blocos_gravados=0) mas arquivo completo
    crc_ruim         CRC-32 do cabeçalho errado                 cab_v1    cabeçalho versão 1
    sonda_errada     id da sonda diferente do pedido            grandeza_tensao   sonda marcada como tensão
    sem_cabecalho    só amostras, sem o cabeçalho "SHAN"

A frequência "injetada na bancada" é a pedida no título (``Calibracao <F>Hz rep<N> ...``), como se
o operador tivesse obedecido à instrução do script. Sem ``-d`` (ou sem ``amp=``) o tom tem 1 de pico
(1 V no canal de referência, ``planta_h(f)`` V no da sonda); com ``amp=`` o tom da sonda é ``planta_h(f)``
vezes o PICO da amplitude (em V ou A, o número que o ``referencia.py`` calcula).
"""

import os
import struct
import sys
import time
import zlib
from pathlib import Path

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from capturas_sinteticas import montar_cabecalho, planta_h, volts_para_codigos  # noqa: E402
from supraharmonicos.referencia import extrair_referencia  # noqa: E402

OFFSET_BLOCOS = 68
OFFSET_CRC_V2 = 668
CODIGO_GRANDEZA = {"tensao": 0, "corrente": 1, "temperatura": 2}


def proxima_diretiva(sim: Path) -> tuple[int, str]:
    contador = sim / "contador"
    n = int(contador.read_text()) + 1 if contador.exists() else 1
    contador.write_text(str(n))
    arquivo = sim / "cenario"
    linhas = arquivo.read_text().splitlines() if arquivo.exists() else []
    diretiva = linhas[n - 1].strip() if n - 1 < len(linhas) else ""
    return n, diretiva or "ok"


def main(argv: list[str]) -> int:
    sim = Path(os.environ["SIM_DIR"])
    spb = int(os.environ.get("SIM_SPB", "1048576"))
    n, diretiva = proxima_diretiva(sim)
    with open(sim / "chamadas.log", "a", encoding="utf-8") as log:
        log.write(f"{n} {diretiva} :: {' '.join(argv)}\n")

    taxa = int(argv[0])
    canais = sorted(int(c) for c in argv[1].split(","))
    opcoes = dict(zip(argv[2::2], argv[3::2]))
    blocos = int(opcoes.get("--blocos", "1"))
    saida = opcoes["-o"]
    titulo = opcoes.get("-t", "")
    descricao = opcoes.get("-d", "")
    grandeza = dict(p.split(":") for p in opcoes["--grandeza"].split(",")) if "--grandeza" in opcoes else {}
    sonda = dict(p.split(":") for p in opcoes["--sonda"].split(",")) if "--sonda" in opcoes else {}
    grandezas = [CODIGO_GRANDEZA[grandeza.get(str(c), "tensao")] for c in canais]
    sondas = [sonda.get(str(c), "") for c in canais]

    if len(titulo.encode()) > 63:  # o ler_adc real REJEITA títulos acima de 63 bytes
        print(f"Erro: título com {len(titulo.encode())} bytes (máximo 63).", file=sys.stderr)
        return 255
    if diretiva == "falha":
        print("Erro: a PRU não respondeu (simulado).", file=sys.stderr)
        return 255
    if diretiva == "travar":
        time.sleep(1000)

    f_nominal = float(titulo.split()[1].removesuffix("Hz"))
    f = f_nominal * {"freq_errada": 1.3, "freq_leve": 1.07}.get(diretiva, 1.0)
    referencia = extrair_referencia(descricao)
    escala = referencia.amplitude.pico if referencia and referencia.amplitude else 1.0
    amp_ref, amp_sonda, ruido = 1.0, float(planta_h(f_nominal)) * escala, 1e-3
    if diretiva == "sat_sonda":
        amp_sonda = 6.0
    if diretiva == "sat_ref":
        amp_ref = 6.0
    if diretiva == "sem_sinal_sonda":
        amp_sonda = 0.0
    if diretiva == "sem_sinal_ref":
        amp_ref = 0.0
    if diretiva == "fraco":
        amp_ref, amp_sonda = 0.3, 0.3 * float(planta_h(f_nominal)) * escala

    k = len(canais)
    n_por_canal = blocos * spb // k
    rng = np.random.default_rng()  # sem semente: cada captura é diferente, como no hardware
    t = np.arange(n_por_canal) / (taxa / k)
    tom = np.sin(2 * np.pi * f * t + rng.uniform(0, 6.28))
    intercalado = np.empty(k * n_por_canal)
    for i, g in enumerate(grandezas):
        amplitude = amp_sonda if g == CODIGO_GRANDEZA["corrente"] else amp_ref
        intercalado[i::k] = amplitude * tom + rng.normal(0, ruido, n_por_canal)
    amostras = volts_para_codigos(intercalado).tobytes()

    if diretiva == "sonda_errada":
        sondas = [s and "outra_sonda" for s in sondas]
    if diretiva == "grandeza_tensao":
        grandezas = [0] * k
    versao = 1 if diretiva == "cab_v1" else 2
    cabecalho = bytearray(montar_cabecalho(n_por_canal, canais, grandezas, sondas, taxa, versao=versao, titulo=titulo,
                                         descricao=descricao))
    struct.pack_into("<I", cabecalho, 40, spb)  # samples_per_buffer
    if versao == 2:
        struct.pack_into("<Q", cabecalho, OFFSET_BLOCOS, 0 if diretiva == "cab_zero" else blocos)
        struct.pack_into("<I", cabecalho, OFFSET_CRC_V2, 0)
        crc = zlib.crc32(bytes(cabecalho))
        struct.pack_into("<I", cabecalho, OFFSET_CRC_V2, crc ^ 0xDEADBEEF if diretiva == "crc_ruim" else crc)

    if diretiva == "truncar":
        amostras = amostras[: len(amostras) // 2]
    with open(saida, "wb") as fh:
        if diretiva != "sem_cabecalho":
            fh.write(bytes(cabecalho))
        fh.write(amostras)
    print(f"Captura concluída ({diretiva}).")
    return 7 if diretiva == "erro_mas_arquivo" else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
