"""As rotinas do ``coletar.sh`` (a F4.6; docs/gui-plan.md, 11.5): os modos, as opções principais de cada um e a linha de
comando montada com elas, para rodar no terminal embutido. As pausas da bancada ("ligue o gerador e tecle Enter"), o
``sudo`` e as respostas ficam no terminal, como no laboratório.

**A tabela não é lida da ajuda do script:** a ajuda é feita para gente (duas opções numa linha, os padrões no meio do
texto). Ela traz as opções que se escolhem de uma rotina para outra; o resto vai nas "outras opções", e o script
valida tudo. ``tests/test_sh_placa_rotinas.py`` confere a tabela contra a ajuda de cada modo e roda os comandos
montados com ``--simular`` no ``coletar.sh`` do repositório.

**O pedido da Capturar** preenche só o que é a bancada (os canais, o canal da sonda, a grandeza, a sonda, a taxa, a
faixa e o SPI): o resto fica vazio, e vazio é o padrão do script, que já é o de uma boa análise.
"""

from __future__ import annotations

import shlex
from collections.abc import Mapping
from dataclasses import dataclass

from .agente import PASTA_DO_FIRMWARE
from .pedido import ErroDeUso, PedidoDeCaptura, _texto_da_faixa

TIPOS = ("texto", "escolha", "marca")
DO_PEDIDO = ("canais", "canal", "grandeza", "sonda", "grandezas", "sondas", "taxa", "faixa", "spi")
"""De onde uma opção tira o valor no pedido da Capturar (o primeiro canal, quando a opção é de um canal só)."""
FAIXAS = ("20.48", "10.24", "5.12")


@dataclass(frozen=True)
class Opcao:
    """Uma opção de um modo: ``flag`` (``--canal``), o rótulo e a ajuda na tela, o tipo (``marca`` não leva valor;
    ``escolha`` só aceita ``escolhas``, e o vazio, que é o padrão do script) e ``do_pedido`` (:data:`DO_PEDIDO`)."""

    flag: str
    rotulo: str
    ajuda: str
    tipo: str = "texto"
    escolhas: tuple[str, ...] = ()
    do_pedido: str = ""


@dataclass(frozen=True)
class Rotina:
    """Um modo do ``coletar.sh``: ``pausas``, se para e pede a bancada; ``simulavel`` e ``retomavel``, se aceita o
    ``--simular`` (o plano, o tempo e o espaço, sem capturar) e o ``--continuar`` (a última coleta, de onde parou)."""

    modo: str
    titulo: str
    resumo: str
    opcoes: tuple[Opcao, ...]
    pausas: bool = False
    simulavel: bool = False
    retomavel: bool = False

    def opcao(self, flag: str) -> Opcao:
        return next(o for o in self.opcoes if o.flag == flag)


_CANAIS = Opcao("--canais", "Canais", "os canais da captura, separados por vírgula (padrão: 1)", do_pedido="canais")
_SPI = Opcao("--spi", "SPI", "rapido (padrão) ou lenta", "escolha", ("rapido", "lenta"), do_pedido="spi")
_ESPERADO_VPP = Opcao("--esperado-vpp", "Pico a pico esperado (V)", "no pino do canal, para conferir o nível")
_CONTINUAR = "--continuar"
_SIMULAR = "--simular"

ROTINAS: tuple[Rotina, ...] = (
    Rotina("conferir", "Conferir a bancada",
           "~10 s: o firmware, os pinos e o ADC respondendo; o nível, o offset, o ruído e a faixa certa para o sinal.",
           (_CANAIS,
            Opcao("--faixa", "Faixa total (V)", "20.48 (padrão: não satura com nada), 10.24 ou 5.12", "escolha",
                  FAIXAS, do_pedido="faixa"),
            Opcao("--taxa", "Taxa total (S/s)", "padrão: 400000", do_pedido="taxa"),
            _SPI, _ESPERADO_VPP,
            Opcao("--esperado-hz", "Frequência esperada (Hz)", "a do sinal na entrada, para conferir"))),
    Rotina("calibrar", "Calibração por quadradas",
           "A cadeia (sonda + frontend + ADC) em magnitude e fase, por ondas quadradas: o script pede cada quadrada "
           "no gerador.",
           (Opcao("--grandeza", "Grandeza", "tensao (padrão) ou corrente", "escolha", ("tensao", "corrente"),
                  do_pedido="grandeza"),
            Opcao("--canal", "Canal", "o canal com a sonda (padrão: 1)", do_pedido="canal"),
            Opcao("--sonda", "Sonda", "o id da sonda, gravado no cabeçalho", do_pedido="sonda"),
            Opcao("--referencia", "Entrada pelo osciloscópio",
                  "pede, em cada quadrada, a forma de onda da entrada (na corrente, obrigatória)", "marca"),
            Opcao("--canal-referencia", "Canal de referência",
                  "dois canais juntos: a tensão num resistor do laço, a fase pela razão (sem o osciloscópio)"),
            _ESPERADO_VPP,
            Opcao("--faixas", "Faixas totais (V)", "separadas por vírgula (padrão: 20.48,5.12; na corrente, 5.12)"),
            Opcao("--segundos", "Segundos por captura", "padrão: 30")),
           pausas=True, simulavel=True, retomavel=True),
    Rotina("sonda", "Sonda por senoides",
           "A calibração ponto a ponto, por senoides: o ganho em baixa frequência (o K) e a conferência da curva do "
           "calibrar. O script pede cada frequência no gerador.",
           (Opcao("--taxa", "Taxa total (S/s)", "a taxa do ADC (1 a 500000), ex.: 102400 ou 400000", do_pedido="taxa"),
            Opcao("--canal-sonda", "Canal da sonda", "o canal calibrado (0 a 7); sem ele, o script pergunta",
                  do_pedido="canal"),
            Opcao("--grandeza", "Grandeza", "corrente (padrão) ou tensao", "escolha", ("corrente", "tensao"),
                  do_pedido="grandeza"),
            Opcao("--sonda", "Sonda", "o id da sonda (até 31 caracteres)", do_pedido="sonda"),
            Opcao("--pontos", "Pontos", "as frequências do plano (padrão: 20)"),
            Opcao("--ref-externa", "Referência no osciloscópio", "um canal: a cada ponto, o script pede a leitura RMS",
                  "marca"),
            Opcao("--canal-referencia", "Canal de referência", "dois canais: o segundo mede a tensão no shunt"),
            Opcao("--amplitude", "Amplitude", "a do gerador, com a unidade e o tipo (ex.: 500mVpp, 2Arms)")),
           pausas=True),
    Rotina("aliasing", "Aliasing em 3 taxas",
           "O mesmo sinal em 3 taxas, para separar os componentes reais das imagens.",
           (_CANAIS,
            Opcao("--grandeza", "Grandeza por canal", "C:G (ex.: 1:tensao), gravada no cabeçalho",
                  do_pedido="grandezas"),
            Opcao("--sonda", "Sonda por canal", "C:ID (ex.: 1:cadeia_tensao_fase), gravada no cabeçalho",
                  do_pedido="sondas"),
            Opcao("--faixa", "Faixa total (V)", "auto (padrão: a menor que comporta o pico), 20.48, 10.24 ou 5.12",
                  "escolha", ("auto", *FAIXAS)),
            Opcao("--taxas", "Taxas totais (S/s)", "separadas por vírgula (padrão: 400000,390625,320000)"),
            Opcao("--segundos", "Segundos por captura", "padrão: 10"), _SPI),
           simulavel=True, retomavel=True),
    Rotina("ruido", "Piso de ruído",
           "O ruído com a entrada em curto, nas 3 faixas do ADC: o script pede o curto antes de começar.",
           (_CANAIS,
            Opcao("--faixas", "Faixas totais (V)", "separadas por vírgula (padrão: 20.48,10.24,5.12)"),
            Opcao("--blocos", "Blocos por captura", "padrão: 4, ~10 s a 400 kS/s"), _SPI),
           pausas=True, simulavel=True, retomavel=True),
    Rotina("teto", "Teto da taxa",
           "A maior taxa com toda amostra na grade, por varredura, e a taxa de trabalho.",
           (_CANAIS,
            Opcao("--spi", "Modos do SPI", "separados por vírgula: rapido, lenta (padrão: os dois)"),
            Opcao("--blocos-confirmacao", "Blocos da confirmação", "a captura longa no teto (padrão: 10)")),
           simulavel=True),
    Rotina("bancada", "Campanha de bancada (T7)",
           "As varreduras de hardware: as esperas do CS, a taxa, a grade e o SPI; o script pede o curto e o gerador.",
           (Opcao("--validar", "Validar (E)", "capturas longas que cruzam 2³¹ ciclos da PRU", "marca"),
            Opcao("--limite", "Limite (L, M, N, Q, R)", "o limite com o SPI lento, 1 tick por vez", "marca"),
            Opcao("--grade", "Grade (G, H, K, J)", "a grade de tempo: longas, com o ARM ocupado, 2 canais", "marca"),
            Opcao("--spi", "SPI rápido (P, S, T, U)", "as fases A, B e C, 400 kS/s, o teto, o curto", "marca"),
            Opcao("--faixa", "Faixa total (V)", "20.48, 10.24 ou 5.12 (padrão: 5.12)", "escolha", FAIXAS)),
           pausas=True, simulavel=True, retomavel=True),
)
"""Os modos do ``coletar.sh``, na ordem da ajuda dele."""


def rotina(modo: str) -> Rotina:
    for r in ROTINAS:
        if r.modo == modo:
            return r
    raise ErroDeUso(f"o coletar.sh não tem o modo {modo!r} (use {', '.join(r.modo for r in ROTINAS)})")


def _do_pedido(origem: str, pedido: PedidoDeCaptura) -> str:
    canais = pedido.canais
    primeiro = canais[0] if canais else None
    if origem == "canais":
        return ",".join(str(c.numero) for c in canais)
    if primeiro is None:
        return ""
    if origem == "canal":
        return str(primeiro.numero)
    if origem == "grandeza":
        return primeiro.grandeza
    if origem == "sonda":
        return primeiro.sonda
    if origem == "grandezas":
        return ",".join(f"{c.numero}:{c.grandeza}" for c in canais)
    if origem == "sondas":
        return ",".join(f"{c.numero}:{c.sonda}" for c in canais if c.sonda)
    if origem == "taxa":
        return str(pedido.taxa_hz)
    if origem == "faixa":
        return _texto_da_faixa(primeiro.faixa_v)
    if origem == "spi":
        # Só o lento: o rápido é o padrão do script (como no comando do ler_adc), e as variantes rapido:a e :c, que
        # o script não conhece, são do ler_adc.
        return "lenta" if pedido.spi == "lenta" else ""
    raise ValueError(f"origem desconhecida no pedido: {origem!r}")


def valores_do_pedido(r: Rotina, pedido: PedidoDeCaptura) -> dict[str, str]:
    """O valor de cada opção de ``r`` que vem da bancada do pedido (as outras ficam fora: o padrão do script). Uma
    escolha que o modo não aceita (a grandeza temperatura na calibração) também fica fora."""
    valores = {}
    for o in r.opcoes:
        if not o.do_pedido:
            continue
        valor = _do_pedido(o.do_pedido, pedido)
        if valor and (o.tipo != "escolha" or valor in o.escolhas):
            valores[o.flag] = valor
    return valores


def argumentos(r: Rotina, valores: Mapping[str, str], *, outras: str = "", simular: bool = False,
               continuar: bool = False) -> list[str]:
    """Os argumentos do ``coletar.sh`` (o modo primeiro): as opções com valor, na ordem da tabela, as marcas ligadas
    (um valor qualquer não vazio), as ``outras`` (o texto do usuário, lido como o shell lê) e o ``--continuar`` e o
    ``--simular`` (só nos modos que os aceitam). :class:`ErroDeUso` se um valor não serve."""
    args = [r.modo]
    for o in r.opcoes:
        valor = str(valores.get(o.flag, "") or "").strip()
        if not valor:
            continue
        if o.tipo == "marca":
            args.append(o.flag)
        elif o.tipo == "escolha" and valor not in o.escolhas:
            raise ErroDeUso(f"{o.rotulo}: {valor!r} não é uma das opções ({', '.join(o.escolhas)})")
        else:
            args += [o.flag, valor]
    try:
        args += shlex.split(outras)
    except ValueError as e:
        raise ErroDeUso(f"Outras opções: {e} (as aspas abertas ficaram sem fechar?)") from None
    if continuar:
        if not r.retomavel:
            raise ErroDeUso(f"o modo {r.modo} não retoma uma coleta (--continuar)")
        args.append(_CONTINUAR)
    if simular:
        if not r.simulavel:
            raise ErroDeUso(f"o modo {r.modo} não tem o --simular")
        args.append(_SIMULAR)
    return args


def comando(r: Rotina, valores: Mapping[str, str], *, outras: str = "", simular: bool = False,
            continuar: bool = False, pasta_firmware: str = PASTA_DO_FIRMWARE) -> str:
    """A linha do terminal: ``cd ~/firmware && ./coletar.sh MODO ...``, cada argumento com as aspas do shell."""
    args = argumentos(r, valores, outras=outras, simular=simular, continuar=continuar)
    return f"cd ~/{shlex.quote(pasta_firmware)} && ./coletar.sh {shlex.join(args)}"


def ajuda(r: Rotina, pasta_firmware: str = PASTA_DO_FIRMWARE) -> str:
    """A linha que mostra a ajuda do modo, inteira, no terminal."""
    return f"cd ~/{shlex.quote(pasta_firmware)} && ./coletar.sh {shlex.quote(r.modo)} --help"
