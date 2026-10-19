Gerador de funções: Siglent SDG 1032X - Easy pulse 30Mhz 150MSa/s (2 canais que podem ser usados em série para gerar uma onda com ruido) amplituda maxima de saída é 20V.

4 series Mixed signal Oscilloscope: Tektronix MSO46 500Mhz 6.25GS/s (6 canais)

Sonda de corrente: YHDC SCT013 100A:50mA 1506-1026

Multimetro 1: CEM DT-989 True RMS Multimeter (não sei a frequencia maxima)

Multimetro 2: Floke 289 True RMS Multimeter

Sonda de tensão do osciloscópio: Tektronix TPP0500B 500Mhz 300V CATII 3.9pF / 10Mohm

Sonda de corrente do osciloscópio: Tektronix TCP0030A (Range configurável de 5A ou 30A)

Resistores de bancada: 2 resistores de 22.12 ohms (400W 93V) - Os mesmos tem um conector central extra que muda para 10.92 ohms


================================================
T0
6. DC = 9.988
=================================================

T2
DC = 9.989
DC = 4.9924
DC = 0.0019
DC = -4.9924
DC = -9.988

T3
for taxa in 50000 55000 59000 92050 99100 89500 100000 102400 110000 115000 125000; do
  sudo ./ler_adc $taxa 1 --duracao 10s -o T4_fs_$taxa.bin -t "T4 fs $taxa"
done
