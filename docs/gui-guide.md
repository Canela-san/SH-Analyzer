# Guia do SH-Analyzer (a interface gráfica)

Este é o guia da interface: o que cada painel e cada vista faz, e como ler os números. O "?" de cada painel e de cada
vista abre a seção dela aqui, dentro do aplicativo, e o F1 abre a da vista à frente. As ferramentas de linha de
comando (o `ler_adc`, o `adc_tool`, o `medir_captura`, o `compactar_amostras`) estão no `docs/user-guide.md`: a
interface usa as mesmas contas, e os números saem iguais.

Cada seção começa com `## Título {#identificador}`; o identificador é o que os botões "?" pedem.

## Primeiros passos {#primeiros-passos}

Na primeira vez, o cartão **Primeiros passos** leva do nada à primeira medida, numa captura de exemplo:

1. **Abrir a captura de exemplo.** Ela é gerada na hora, na pasta do cache (`exemplos/`), pela placa simulada: 2,6 s
   da bancada do projeto a 400 kS/s, com a corrente de uma carga não linear no canal 0 e a tensão da tomada no
   canal 1, com os supraharmônicos de um inversor fotovoltaico (16 kHz), de drivers de LED (~40 kHz) e de uma
   comunicação pela rede (72 kHz).
2. **Plotar a tensão.** O canal 1 vai para uma vista de tempo.
3. **Medir com os cursores.** O C liga os cursores A e B; a tabela de **Medidas** (embaixo) mostra os instantes, o
   Δt, e o RMS, a média e os extremos de cada traço entre eles.
4. **Abrir o espectro** (Ctrl+E) da vista, e procurar os supraharmônicos.
5. **Experimentar a aquisição** com a placa simulada, na área **Aquisição**.

Cada passo se marca sozinho quando é feito, também com uma captura sua no lugar do exemplo. O cartão volta pela
paleta (Ctrl+K, "Primeiros passos") ou pelo botão daqui.

## A janela {#janela}

A barra de cima tem as três áreas (**Análise**, **Figuras** e **Aquisição**), a busca (a paleta de comandos, Ctrl+K:
toda ação do aplicativo está lá, com o atalho), o chip da placa, desfazer e refazer, o tema e as configurações. Na
Análise, o painel do **Projeto** fica à esquerda (Ctrl+B), o **Inspetor** à direita (Ctrl+I) e o painel de baixo
(Ctrl+J) tem as **Medidas**, as **Tarefas** e os **Avisos**. As vistas ficam no centro, em abas ou numa grade (o
botão das disposições); o menu **Análises** do canto das abas abre as análises da vista à frente.

As contas longas rodam em segundo plano: a aba **Tarefas** mostra o progresso e cancela; a janela nunca trava.
Ctrl+/ lista todos os atalhos do teclado e do mouse.

## Abrir capturas e pacotes {#abrir}

Ctrl+O abre capturas (`.bin` do `ler_adc`, e o `.csv` e o `.h5` do `adc_tool`), projetos (`.shproj`) e pacotes do
`compactar` (`.zpaq.tar`); também dá para arrastar os arquivos para a janela, e o menu do projeto tem as capturas
recentes. Ao abrir, a interface confere o CRC das amostras (o cabeçalho v9 guarda o de todas): o resultado aparece no
Inspetor e na barra de baixo. Uma captura sem cabeçalho pede a taxa e os canais.

**Os pacotes** são extraídos para o cache dos pacotes numa tarefa (cada peça e cada arquivo conferidos pelo SHA-256 do
manifesto) e as capturas deles entram no projeto; abrir de novo o mesmo pacote usa o que já foi extraído. O limite e
o "Limpar" desse cache estão em Configurações → Cache. O projeto salvo lembra de qual pacote veio cada captura: se o
cache for limpo, ao abrir o projeto elas são extraídas de novo, sozinhas.

**Os dados de fora** (Ctrl+Shift+I, "Importar dados de fora…" no menu do projeto, ou arrastando o arquivo): um
registro de osciloscópio (`.csv`, `.txt`, `.m`, `.mat`), um CSV qualquer, um WAV ou um COMTRADE (o `.cfg` com o
`.dat`). No CSV, o assistente mostra as primeiras linhas com o separador e o decimal achados; "Escolher as colunas"
deixa marcar as colunas de valores (clique no título) e a de tempo, ou dizer a taxa. Cada canal ganha a grandeza
(tensão ou corrente) e a escala (a razão de uma ponta de prova, o fundo de escala de um WAV). A captura importada
fica ao lado do arquivo (`nome.importado.h5`) e funciona como qualquer outra: espectro, bandas, qualidade, figuras.
Os valores são guardados em 16 bits, com o pico a 80 % do fundo de escala (o erro fica ~96 dB abaixo do pico).

## O projeto {#projeto}

O painel do **Projeto** lista as fontes (as capturas abertas, com os canais) e as vistas. Arraste um canal para uma
vista, ou dê um duplo clique nele, para plotá-lo. O projeto (`.shproj`) guarda as fontes, as vistas, os traços com as
transformações, as anotações, as figuras e a disposição; Ctrl+S salva, e um salvamento automático recupera o
trabalho depois de uma queda. Uma captura que mudou de lugar é procurada pelo tamanho e pelo CRC. Uma que não foi
achada fica **ausente** (em vermelho), com os traços guardados: o clique direito nela, "Localizar a captura…", aponta
o arquivo (o CRC das amostras confere que é a mesma), e os traços voltam.

## O inspetor {#inspetor}

O **Inspetor** mostra o que está selecionado: de uma captura, o cabeçalho inteiro (a placa, o comando, as faixas, os
ganhos, a integridade); de um traço, o nome, a cor, a unidade, o ganho, o offset, o deslocamento no tempo e a
**cadeia de processamento** (as transformações, ver adiante). Os campos aceitam prefixos ("2,5k", "1,2 mV").

## A vista de tempo {#tempo}

A forma de onda de cada traço, desenhada da pirâmide da captura (a navegação é imediata, mesmo em capturas de horas:
o desenho mostra o mínimo e o máximo de cada pixel, sem perder um pico). A roda do mouse aproxima (em cima de um
eixo, só nele; com Shift, anda no tempo), arrastar desloca, Z faz o zoom em caixa, F ajusta tudo e Backspace volta
ao zoom anterior; Alt e arrastar um traço o desloca no tempo. Os traços podem ter escalas próprias, faixas
separadas ou sobrepostas e eixos ligados entre vistas.

**Os cursores** (C) marcam A e B: as Medidas trazem os instantes, o Δt, o 1/Δt e, de cada traço, os valores entre
eles. As setas andam com os cursores (Shift: dez passos). As análises ligadas a esta vista usam a captura inteira,
a janela visível ou o trecho dos cursores (o seletor "Captura / Janela / Cursores" de cada uma).

## As medidas {#medidas}

A aba **Medidas** mostra os números da vista à frente: na vista de tempo, os dos cursores; nas de frequência, os dos
cursores delas. Ctrl+C copia a tabela para a planilha com o separador decimal das configurações (a vírgula, em
português).

## As transformações e a expressão {#transformacoes}

A **cadeia** de um traço (no Inspetor) aplica, em ordem, as etapas: o ganho e o offset, os filtros (passa-baixas,
passa-altas, passa-faixa e rejeita-faixa, Butterworth de fase zero), remover o DC, a correção pela sonda (o perfil),
a derivada, a integral (com o corte que impede a deriva), o RMS móvel, a envoltória (Hilbert), a frequência
instantânea e a **expressão**. A prévia é calculada no trecho visível; a captura inteira é transformada em segundo
plano e guardada no cache.

**A expressão** faz uma conta amostra a amostra com o traço (`a`) e os canais da captura (`c0` a `c15`): `a - c1`,
`a * c1` (a potência instantânea), `sqrt(c0^2 + c1^2)`. Valem as quatro operações, a potência (`^`), `pi`, `e` e as
funções `abs`, `sqrt`, `exp`, `log`, `log10`, `sin`, `cos`, `tan`, `atan`, `sign`, `min`, `max`, `atan2` e `hypot`. A
conta é lida por um analisador próprio (nunca `eval`), e um erro diz o que e onde.

## O espectro {#espectro}

O espectro de cada traço da vista ligada. **A FFT** usa o trecho inteiro (com a janela escolhida, ou sincronizada
com a fundamental pela IEC 61000-4-7: 10/12 ciclos, retangular); **o Welch** faz a média de segmentos (a resolução e
a sobreposição escolhidas) e diz o **intervalo de confiança de 95 %** de cada bin (pelos graus de liberdade da janela
e da sobreposição: com mais segmentos, o intervalo estreita). O modo **tom** dá a amplitude de pico de um tom; o modo
**ruído**, a densidade espectral (unidade²/Hz).

Os picos (acima do piso) podem ser marcados. **O aviso de imagem**: o único anti-aliasing da cadeia é o passa-baixa
de 2ª ordem do ADS8688 (~15 kHz); acima de ~0,24 da taxa (96 kHz a 400 kS/s), uma entrada em fs − f chega ao espectro
menos de 20 dB abaixo de uma real em f, e um pico dali pode ser uma imagem. O **assistente de aliasing** separa.

**Comparar capturas:** ponha na vista de tempo o mesmo canal de duas capturas (antes e depois de ligar uma carga,
dois dias) e ligue a **Diferença**: os outros traços viram o nível deles menos o do primeiro, em dB, bin a bin (na
grade de cada um); o primeiro é o zero, e o rótulo do eixo diz para quem. **CENELEC** marca as faixas A (3 a
95 kHz), B (95 a 125 kHz), C (125 a 140 kHz) e D (140 a 148,5 kHz) da comunicação pela rede (EN 50065-1).

## As bandas IEC {#bandas}

As bandas de 200 Hz de 2 a 150 kHz (IEC 61000-4-7, anexo B) ao longo do tempo, num mapa ligado ao tempo, e a tabela
com o P95, o RMS, o máximo e o mínimo de cada banda. "Sincronizar" usa as janelas de 10/12 ciclos da fundamental
(IEC 61000-4-30) no lugar dos 200 ms fixos.

**O limite:** escolha uma curva no seletor ao lado de "Sincronizar" e a tabela ganha o limite e a **margem** de cada
banda (o limite menos a estatística escolhida, em dB; negativa, a banda passou, e a linha fica vermelha), o perfil
mostra a estatística por banda com o limite tracejado e um x nas que passam, e a informação diz quantas passaram e a
pior margem. **O programa não traz os valores das normas** (IEC 61000-2-2, IEC 61000-2-12, CISPR, EN 50065-1 são
publicações pagas): em "Editar as curvas…", digite os pontos da sua cópia, ou cole de uma planilha (a frequência e o
nível por linha; "9k" vale 9000), escolha a grandeza (tensão em dBµV, corrente em dBµA) e diga na **fonte** a
norma, a edição e a tabela. Entre os pontos, a reta em log f; dois pontos na mesma frequência fazem um degrau (vale
o menor); fora da curva, sem margem. As curvas ficam na pasta de dados do usuário (`limites/`), e o projeto guarda
uma cópia da escolhida, para abrir igual em outra máquina.

## O espectrograma {#espectrograma}

O espectro ao longo do tempo (o Welch de cada coluna), ligado à vista de tempo: os supraharmônicos que aparecem e
somem, as frequências que andam com a carga.

## Os harmônicos {#harmonicos}

Os harmônicos da fundamental (a FFT sincronizada da IEC 61000-4-7): de cada ordem, a amplitude, a porcentagem da
fundamental e a fase, e o THD; os cursores leem a ordem.

## O XY e a potência {#xy}

Um traço contra outro (o laço V × I, a histerese de um núcleo): a curva, ou a densidade quando o trecho tem muitas
amostras. Com a tensão no eixo horizontal e a corrente no vertical, a tabela traz **a potência pela IEEE 1459**: P, S,
o FP, a ativa, a reativa e a aparente da fundamental (P₁, Q₁, S₁), o cos φ₁, φ₁, a aparente não fundamental S_N e os
THD da tensão e da corrente, em ciclos inteiros da fundamental. Os dois traços ficam no mesmo instante (o
deslocamento de cada um vale) e precisam da mesma taxa.

## O histograma e as estatísticas {#histograma}

A distribuição dos valores do traço (as colunas em contagem linear ou logarítmica, e a curva acumulada) e a tabela:
a média, o RMS, o desvio-padrão, a assimetria, a curtose, os percentis 1, 5, 50, 95 e 99, o mínimo, o máximo e o fator
de crista. Sem cadeia, a contagem é a dos códigos do ADC (exata), com as amostras saturadas e a ocupação da faixa.

## Os eventos {#eventos}

A lista dos eventos do traço, num gráfico com uma linha por tipo (ligado ao tempo) e numa tabela; **um clique numa
linha mostra o evento na vista de tempo**. Os tipos:

* **afundamentos, elevações e interrupções** (o traço é uma tensão): o RMS de um ciclo, atualizado a cada meio ciclo,
  contra a referência (a dada, ou a mediana do trecho): abaixo de 90 %, de 5 % e acima de 110 %, com a histerese de
  2 % no fim (IEC 61000-4-30);
* **os picos de supraharmônicos**: as janelas de 200 ms em que o RMS de 2 a 9 kHz ou o de 9 a 150 kHz passa de 10
  vezes a mediana (as janelas com um degrau de tensão ficam de fora: o degrau espalha a fundamental pelo espectro);
* **a saturação** (as amostras no fundo de escala do ADC), **as descontinuidades** (um salto que não segue a forma
  de onda) e **o registro do `ler_adc`** (os buffers sobrescritos e as amostras atrasadas).

## A qualidade de energia {#qualidade}

Os índices em janelas de 10 ciclos (50 Hz) ou 12 (60 Hz), sincronizadas com a fundamental (IEC 61000-4-30): a
frequência, o RMS, o THD (até a 40ª), o fator K (até a 50ª), os fatores de crista e de forma, e o RMS de 2 a 9 kHz e
de 9 a 150 kHz. O gráfico mostra um índice ao longo do tempo e os agregados de 150/180 ciclos (~3 s); a tabela traz o
mínimo, a média, o P95, o P99 e o máximo de todos. **Marcar os eventos** faz a marcação da norma: as janelas com um
afundamento, uma elevação ou uma interrupção (o RMS de meio ciclo fora de 90 a 110 % da mediana) saem das
estatísticas e dos agregados (os círculos vazios no gráfico). Num traço de corrente, desligue a marcação. "Copiar
as janelas" leva todos os índices de cada janela para a planilha.

## A transferência {#transferencia}

A função de transferência H₁ = Pxy/Pxx do traço da vista (a entrada) para outro (a saída), pelo Welch: o ganho (dB)
e a fase com **o intervalo de confiança de 95 %** (a faixa: o círculo de confiança de Bendat e Piersol, com o ruído
na saída), e a **coerência** γ² (perto de 1: a saída vem da entrada; perto de 0: ruído ou não linearidade). A
resolução fina dá menos médias e um intervalo mais largo. Os cursores leem |H|, a fase e γ² em duas frequências.

## As métricas de bancada {#metricas}

As contas do `medir_captura` num traço, para caracterizar a cadeia com um sinal conhecido: o tom (a frequência e a
amplitude), o THD, o SINAD, o SNR, o ENOB (corrigido pelo fundo de escala), o SFDR, o ruído (em LSB), a densidade do
ruído, o jitter da amostragem, o salto de fase entre segmentos (uma amostra perdida aparece como ~1) e a saturação;
os harmônicos em dBc (os dobrados pela Nyquist, vazados). Meça o canal sem cadeia: com uma, os números descrevem o
traço, não o ADC.

## O assistente de aliasing {#aliasing}

Separa os picos reais das imagens com **duas a quatro capturas do mesmo sinal em taxas diferentes** (ex.: 400, 390,625
e 320 kS/s): um componente real fica no mesmo lugar em todas; uma imagem muda de lugar, e as posições dizem de onde
ela veio. Escolha as fontes abertas e o canal; a tabela diz, de cada componente, a entrada, onde ele aparece em cada
captura e o diagnóstico (real, imagem, ambíguo: uma taxa a mais decide). As amostras são as do pino do ADC.

## O Instrumento {#instrumento}

Os traços da vista sobrepostos no disparo de um deles, como num osciloscópio: 10 divisões de tempo e 8 de valor, o
tempo por divisão (automático: dois ciclos) e a escala por divisão e o offset de cada traço (automática: a série
1-2-5). O disparo tem a borda, o nível e a histerese (o ruído em cima do nível não dispara de novo). **Rejeitar AF**
procura o disparo no traço passado por um passa-baixa de 1 kHz, de ida e volta (sem atraso): a rede dispara uma vez
por ciclo mesmo com um surto de supraharmônicos por cima, que cruzaria o nível muitas vezes; os traços na tela não
mudam (para disparar num sinal acima de ~1 kHz, deixe-o desligado). **A persistência**
pinta cada traço mais forte onde mais amostras passaram; o **ciclo médio** vem por cima, e a tabela traz o RMS, o pico
a pico e a média dele, e a frequência e o desvio do período do disparo.

## Os perfis de sonda {#perfis}

Os perfis de sonda (o ganho e a fase da sonda, do frontend e do ADC, de ponta a ponta) com o Bode de cada um, e qual
perfil cada canal usa. A correção pela sonda entra na cadeia de um traço.

## Alinhar dois traços {#alinhar}

"Alinhar…" (no Inspetor ou no menu Análises) mede o atraso de um traço em relação a outro da mesma vista, pela
correlação cruzada ou pelos cruzamentos por zero, no trecho dos cursores ou na janela visível, e aplica o
deslocamento no tempo que os alinha (num passo de desfazer).

## As figuras {#figuras}

A área **Figuras** monta figuras para publicação: "Fazer uma figura com a vista" leva a vista à frente para uma
figura (os painéis podem ser congelados ou religados à vista); as páginas dão a largura de uma coluna da IEEE ou da
Elsevier, e os modelos de estilo guardam o seu; a figura é exportada em PDF, SVG, EPS, PGF (o LaTeX com as fontes do
documento), PNG ou TIFF, ou copiada. O **pacote reproduzível** (`.zip`) guarda a figura, os dados e o programa que a
redesenha. "Exportar os dados da vista…" grava os números em CSV, HDF5, WAV (ponto flutuante de 32 bits, nas
unidades; crus, os códigos em PCM de 16 bits) ou COMTRADE 1999 binário (o `.cfg` com o `.dat`), para abrir em outro
programa de qualidade de energia ou de áudio.

## O relatório da captura {#relatorio}

"Relatório da captura…" (Ctrl+Shift+R, também no menu do projeto) grava uma página com os traços visíveis da vista
de tempo aberta (ou da que a vista aberta segue), cada um no trecho inteiro e com a cadeia dele:

- de cada captura, o cabeçalho (o mesmo do inspetor), a integridade das amostras e os avisos;
- de cada traço, os índices de qualidade (as estatísticas das janelas de 10/12 ciclos, sem as marcadas), as 12
  bandas IEC de maior P95, os eventos e duas figuras (as bandas por frequência; o RMS e o THD no tempo);
- a proveniência: o canal, a captura e a cadeia de cada traço, a versão do aplicativo e a data.

Em `.html`, as figuras vão dentro da página (um arquivo só, que se abre no navegador e se imprime); em `.pdf`, sai em
A4. As contas rodam numa tarefa, como as das vistas, e os números seguem o separador decimal das configurações.

## A aquisição {#aquisicao}

A área **Aquisição** fala com a placa (pelo USB, pela rede local ou pelo simulador): a **Visão geral** (a placa, o
sistema e a saúde), **Capturar** (os canais, as grandezas, as sondas, as faixas, a taxa e a duração; o progresso e o
sinal ao vivo), as **Rotinas**, os **Arquivos** (as capturas da placa, trazidas para o computador), o **Terminal**, o
**Diagnóstico** e a **Manutenção** (o firmware, o sistema, o resgate). A placa simulada permite experimentar tudo sem
a placa de verdade.

## As configurações {#configuracoes}

O tema, a **densidade** (a compacta põe mais linhas na árvore e nas tabelas), o idioma dos números (o separador
decimal), os prefixos do SI nos eixos, as pastas (os dados, as sondas e o
cache) e o **cache**: as pirâmides, os traços transformados e os pacotes extraídos, cada um com o limite (passar dele
apaga os menos usados; o que está aberto fica) e o "Limpar".

**As atualizações:** ao abrir (no máximo uma vez por dia), o aplicativo pergunta ao GitHub qual é a última versão
publicada. Só isso vai na consulta, nada seu. Com uma versão nova, um aviso no canto de cima mostra a versão e as
**Novidades** e oferece:

- **no Windows**, o **Atualizar agora**: baixa o instalador, confere a soma SHA-256 publicada com ele, fecha o
  aplicativo (oferecendo salvar o projeto) e o abre de novo já atualizado;
- **no Linux instalado pelo apt**, nada a fazer aqui: a versão nova chega pelo Atualizador de Programas do sistema (ou
  `sudo apt upgrade`);
- **na pasta do `.tar.gz`**, o **Baixar**, que abre a página da versão.

**Pular esta versão** não avisa mais dela. A consulta pode ser desligada em Configurações → Atualizações, onde também
há o **Procurar agora**.
