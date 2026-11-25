# O teste com três pesquisadores (roteiro)

O teste "com pessoas" do plano (docs/gui-plan.md, seção 14, e o último item da Fase 7): três pesquisadores fazem as
jornadas da seção 1.2 no aplicativo instalado, sem ajuda, e o que travar vira correção antes da tag v1.0. Este roteiro
fica pronto na F7.12 (docs/gui-progress.md, 4h); o teste depende das três pessoas.

## 1. Quem e o quê

- **Os participantes:** três pessoas que analisam sinais da rede, de preferência uma de cada perfil: quem pesquisa
  supraharmônicos, quem trabalha com qualidade de energia e quem mexe em instrumentação de bancada. Ninguém que tenha
  visto o desenvolvimento da interface.
- **O que se mede**, em cada tarefa: o tempo; o resultado (**sozinho**, **com uma dica** ou **não fez**); os erros
  (um caminho errado que a pessoa percebeu e desfez); quantas vezes abriu a ajuda ("?" ou F1); e a nota de facilidade
  (a pergunta única, de 1 a 7, logo depois da tarefa). No fim, o questionário SUS (seção 5).
- **A meta** (docs/gui-plan.md, 1.2): cada jornada em até **5 ações** a partir da tela inicial, sem ler o manual.

## 2. Antes do teste

1. **O aplicativo:** o instalador da versão a testar, da CI dos instaladores (aba Actions, "Instaladores", o artefato
   do sistema da pessoa). Instalar numa conta sem o SH-Analyzer usado antes (ou renomear a pasta de configuração:
   `~/.config/SH-Analyzer` no Linux, `%APPDATA%\SH-Analyzer` no Windows), para a primeira execução ser a de verdade.
2. **Os dados**, numa pasta na área de trabalho:
   - **uma captura de campo** da tomada, com um afundamento ou um transitório visível (do arquivo do laboratório:
     uma das capturas de 18/11/2026, copiada, nunca a original);
   - **duas capturas do mesmo ponto** em dias diferentes (para comparar);
   - **um projeto** (`.shproj`) com uma figura pronta (para a tarefa do revisor).
3. **A gravação** da tela e da voz, só com o consentimento escrito da pessoa; nas anotações, um código (P1, P2, P3) no
   lugar do nome.
4. **A folha de cada participante** (seção 4) impressa ou numa planilha, e um cronômetro.

## 3. As tarefas

Ler cada tarefa em voz alta, entregar o papel com ela e pedir que a pessoa **pense em voz alta**. O moderador não
ajuda; se a pessoa parar por mais de 3 minutos, dá a dica escrita da tarefa (e anota "com uma dica"); se parar por
mais 3, encerra a tarefa ("não fez") e passa à próxima. O tempo conta do fim da leitura até a pessoa dizer "pronto".

| # | Jornada (1.2) | A tarefa, como é lida | Pronto quando | A dica (se travar) |
|---|---|---|---|---|
| T1 | Quem chega | "Abra o SH-Analyzer pela primeira vez e chegue ao espectro de uma captura." | O espectro aberto (a captura de exemplo serve) | "O cartão do canto da tela tem os passos." |
| T2 | Pesquisador | "Na captura de campo, ache o afundamento e mostre o espectro de 2 a 150 kHz dele." | O espectro de um trecho que contém o evento | "O menu Análises, ao lado das abas, tem Eventos." |
| T3 | Pesquisador | "Faça a figura IEEE de uma coluna com o tempo e o espectro do evento e exporte em PDF, com o pacote que refaz a figura." | O PDF e a pasta do pacote salvos | "A área Figuras, na barra da esquerda." |
| T4 | Pesquisador | "Diga a THD da tensão a cada 12 ciclos e quais janelas a norma deixa de fora." | A curva da THD e as janelas marcadas apontadas | "Análises → Qualidade de energia." |
| T5 | Pesquisador | "Mostre a função de transferência da tensão para a corrente e diga a coerência em 10 kHz e quanto se pode confiar no módulo." | A coerência lida e o intervalo de confiança mencionado | "Análises → Transferência; os cursores leem os valores." |
| T6 | Pesquisador | "Veja os ciclos da tensão sobrepostos, como num osciloscópio, disparando uma vez por ciclo." | O Instrumento com um disparo por ciclo (numa captura com supraharmônicos, com o Rejeitar AF) | "Análises → Instrumento; o disparo tem opções na barra." |
| T7 | Estudante na bancada | "Conecte à placa (a simulada serve), confira a captura antes e capture 1 minuto direto no computador; abra a captura no fim." | A captura aberta na Análise | "A área Aquisição, na barra da esquerda." |
| T8 | Orientador ou revisor | "Abra o projeto, compare as duas capturas do mesmo ponto e diga de onde vem cada curva da figura: a captura, o canal e o que foi feito com ele." | As duas na mesma vista; a captura, o canal e a cadeia de cada curva ditos | "O inspetor, à direita, mostra a captura e a cadeia do traço selecionado." |

**As ações contadas** (para a meta de 5): cada clique num menu, botão ou aba que leva adiante, cada arraste de
cursor e cada atalho. Não contam: a rolagem, mover o mouse, ler a ajuda.

## 4. A folha de cada participante

| Tarefa | Tempo (min:s) | Resultado (sozinho / dica / não fez) | Ações | Erros | Ajuda ("?", F1) | Facilidade (1–7) | O que travou (as palavras da pessoa) |
|---|---|---|---|---|---|---|---|
| T1 | | | | | | | |
| T2 | | | | | | | |
| T3 | | | | | | | |
| T4 | | | | | | | |
| T5 | | | | | | | |
| T6 | | | | | | | |
| T7 | | | | | | | |
| T8 | | | | | | | |

**A pergunta de facilidade**, depois de cada tarefa: "No geral, essa tarefa foi: 1 (muito difícil) … 7 (muito
fácil)?"

## 5. O questionário do fim (SUS)

De 1 (discordo totalmente) a 5 (concordo totalmente):

1. Eu usaria o SH-Analyzer com frequência.
2. Achei o SH-Analyzer mais complicado do que precisava ser.
3. Achei o SH-Analyzer fácil de usar.
4. Eu precisaria de ajuda de alguém técnico para conseguir usá-lo.
5. As funções do SH-Analyzer estão bem integradas.
6. Achei o SH-Analyzer inconsistente demais.
7. Imagino que a maioria das pessoas aprenderia a usá-lo depressa.
8. Achei o SH-Analyzer muito trabalhoso de usar.
9. Eu me senti confiante usando o SH-Analyzer.
10. Precisei aprender muita coisa antes de conseguir usá-lo.

**A nota:** nas ímpares, a resposta menos 1; nas pares, 5 menos a resposta; a soma vezes 2,5 (de 0 a 100). Acima de 68
é a média dos sistemas medidos com o SUS; a meta da v1.0 é **80 ou mais**.

E três perguntas abertas: "O que mais ajudou?", "O que mais atrapalhou?" e "Que análise faltou para o seu trabalho?".

## 6. Depois do teste

1. **Por tarefa**, nos três: quantos fizeram sozinhos, a mediana do tempo e das ações (contra a meta de 5), a mediana
   da facilidade.
2. **Cada problema** numa lista, com a gravidade (0: não é problema; 1: cosmético; 2: pequeno; 3: grande, atrasa
   muito; 4: impede a tarefa) e quantas pessoas o tiveram. Os de gravidade 3 e 4 viram tarefas antes da tag v1.0;
   os outros, a lista de depois da Fase 7 (docs/gui-plan.md).
3. **A nota SUS** de cada um e a média.
4. **O registro** na seção 5 de docs/gui-progress.md (os resultados medidos), com a data, a versão testada e o que
   mudou por causa do teste.
