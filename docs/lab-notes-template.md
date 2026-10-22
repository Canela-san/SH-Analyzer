# Anotações da bancada: AAAA-MM-DD

Modelo do caderno de uma ida ao laboratório (o [passo a passo](lab-procedure.md#passo-a-passo-da-próxima-ida-o-quadro-fixo-e-o-spi-rápido)
manda copiá-lo para `$DIA/anotacoes.md`). Preencha durante a sessão: o que não está nas capturas nem no
`terminal_bbb.txt` só existe aqui. Escreva a hora de cada coisa que der errado.

## Bancada

- BeagleBone alimentada por (USB do notebook, fonte de 5 V, outra porta):
- Notebook (na bateria ou no carregador):
- Placa de aquisição alimentada por:
- Gerador (modelo, canal, forma, frequência, amplitude em Vpp, carga High-Z, offset):
- Osciloscópio (modelo, ponta 10x?, onde está o terra):
- Versão do firmware (a linha `Firmware:` do `ler_adc`):
- Hora em que tudo foi ligado:

## Contador de frequência (o tom)

| Momento | Hora | Leitura (Hz) |
|---|---|---|
| Começo da sessão | | |
| Começo do T7c (etapa 6c) | | |
| Fim do T7c | | |
| Fim da sessão | | |

## Interferência da rede (etapa 1)

- SFDR e o maior espúrio da primeira `T7_bancada.bin`: ___ dBc em ___ Hz
- O que foi tentado, em ordem, e o resultado de cada tentativa:
- Situação final (limpa, ou com espúrio de ___ dBc em ___ Hz):

## Osciloscópio: CS e SCLK

| Esperas (S,H,A) | Taxa (kS/s) | Período do CS | CS baixo | CS alto | Foto |
|---|---|---|---|---|---|
| 200,100,100 | 100 | | | | `fotos/cs_padrao_100k.png` |
| (de trabalho) | (de trabalho) | | | | `fotos/cs_trabalho.png` |

## Grade de tempo (T7f)

- Folga da captura de conferência (`T7_bancada.bin`, linha `Grade de tempo (PRU)`): ___ ciclos
- Osciloscópio, gatilho na descida do CS, a próxima descida a 3,200 µs (persistência infinita):

| Firmware | Largura da faixa da próxima descida | Desvio-padrão do período | Foto |
|---|---|---|---|
| 22/10 (protocolo 2) | | | `fotos/cs_jitter_312k.png` |
| `v0.7` (se der tempo) | | | `fotos/cs_jitter_312k_v07.png` |

- A 1ª amostra atrasada da parte J (o teto com período constante): ___ ticks = ___ kS/s

## Decisões

- Menor conjunto de esperas que passou a 100 kS/s (etapa 4):
- Conjuntos que falharam e por quê (contador, SINAD, ruído):
- Esperas de trabalho (o dobro do menor, nunca menos que 6,2,6):
- Teto medido (a maior taxa que passou na etapa 5):
- Taxa de trabalho (a maior com ≥ 10 % de folga):

## Problemas e observações

| Hora | O que aconteceu (mensagem exata) | O que foi feito |
|---|---|---|
| | | |
