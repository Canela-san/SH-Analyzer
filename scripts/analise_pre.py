# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "numpy",
# ]
# ///

import argparse
import sys
import numpy as np

ADC_MID_SCALE = 32768.0
V_RANGE_MAX = 10.24


def main():
    parser = argparse.ArgumentParser(
        description="Analisa o diagnostico_preambulo.bin (pares preambulo,dado por amostra)."
    )
    parser.add_argument("arquivo", nargs="?", default="diagnostico_preambulo.bin")
    args = parser.parse_args()

    try:
        bruto = np.fromfile(args.arquivo, dtype=np.uint16)
    except Exception as e:
        print(f"Erro ao ler '{args.arquivo}': {e}")
        sys.exit(1)

    if len(bruto) < 2:
        print("Arquivo vazio ou pequeno demais.")
        sys.exit(1)

    if len(bruto) % 2 != 0:
        print("Aviso: número ímpar de uint16 - descartando o último valor solto.")
        bruto = bruto[:-1]

    pares = bruto.reshape(-1, 2)
    preambulo = pares[:, 0]
    dado = pares[:, 1]

    n = len(preambulo)
    print(f"Total de amostras: {n}\n")

    print("=== PREÂMBULO (deveria ser sempre 0x0000, segundo o datasheet) ===")
    vals_pre, contagens_pre = np.unique(preambulo, return_counts=True)
    ordem = np.argsort(-contagens_pre)
    for v, c in zip(vals_pre[ordem][:10], contagens_pre[ordem][:10]):
        pct = 100.0 * c / n
        print(f"  0x{v:04X}  ->  {c:6d} amostras  ({pct:5.1f}%)")
    zeros_pct = 100.0 * np.count_nonzero(preambulo == 0) / n
    print(f"  Percentual exatamente igual a 0x0000: {zeros_pct:.1f}%\n")

    print("=== DADO (código bruto do ADC, 16 bits) ===")
    vals_dado, contagens_dado = np.unique(dado, return_counts=True)
    ordem_d = np.argsort(-contagens_dado)
    for v, c in zip(vals_dado[ordem_d][:10], contagens_dado[ordem_d][:10]):
        pct = 100.0 * c / n
        tensao = ((float(v) - ADC_MID_SCALE) / ADC_MID_SCALE) * V_RANGE_MAX
        print(f"  0x{v:04X}  ({tensao:+7.3f} V)  ->  {c:6d} amostras  ({pct:5.1f}%)")

    print("\n=== PRIMEIRAS 20 AMOSTRAS (preambulo, dado, dado em volts) ===")
    for i in range(min(20, n)):
        p = int(preambulo[i])
        d = int(dado[i])
        v = ((d - ADC_MID_SCALE) / ADC_MID_SCALE) * V_RANGE_MAX
        print(f"  [{i:3d}] preambulo=0x{p:04X}  dado=0x{d:04X} ({v:+.3f} V)")

    print("\n=== VEREDITO ===")
    if zeros_pct > 95:
        print("Preâmbulo praticamente sempre 0x0000: a comunicação SPI básica")
        print("parece OK (o ADC está 'ouvindo' CS/SCLK corretamente). O problema")
        print("está mais provavelmente na conversão em si: referência (REFIO),")
        print("alimentação do ADS8688, canal errado, ou o ADC em condição de")
        print("erro/saturação.")
    elif zeros_pct < 5:
        print("Preâmbulo quase NUNCA é 0x0000 (ex: sempre 0xFFFF ou outro valor")
        print("fixo): o MISO está sendo lido no mesmo estado o tempo todo,")
        print("independente da fase do protocolo. Isso aponta para hardware -")
        print("pull-up dominando a linha, fio desconectado/mal contatado, ou")
        print("o ADC sem alimentação/referência (SDO em alta impedância) - e")
        print("não para um bug de lógica no software.")
    else:
        print("Resultado misto - preâmbulo varia entre 0 e outros valores.")
        print("Pode indicar problema intermitente de sinal (capacitância do")
        print("cabo, optoacoplador na borda da velocidade suportada). Compare")
        print("com o teste de loopback (MOSI->MISO) para isolar melhor.")


if __name__ == "__main__":
    main()