"""Mini-simulador do subconjunto de assembly PRU (sintaxe TI ``clpru``) usado em ``firmware/spi_core.asm``.

Para que serve
    O assembly da PRU só roda no BeagleBone, e o ``clpru`` (compilador da TI) não existe no CI. Este módulo lê o
    ``spi_core.asm`` de verdade, expande os macros e executa as instruções num modelo simples (registradores de 32
    bits, memória compartilhada, contador de ciclos e os pinos SCLK/MOSI/CS em ``r30``). Com isso dá para conferir,
    sem hardware, a **lógica**: quais palavras de 16 bits seguem pelo MOSI em cada transação SPI (configuração do
    ADS8688), em que ordem, com quantos ciclos de SCLK, e se o laço principal grava amostras.

O contador de ciclos (``0x2200C``) TRAVA em 0xFFFFFFFF, como o da PRU de verdade (não dá a volta), e o instante de
cada descida do CS fica em ``instantes_cs`` -- dá para conferir a grade de tempo das amostras.

O que NÃO garante
    * Temporização real (cada instrução vale 1 ciclo; ``LBBO``/``SBBO`` custam mais na PRU de verdade).
    * Que o ``clpru`` aceita a sintaxe (o simulador é mais tolerante em alguns pontos). Compilar no BeagleBone
      (``make`` em ``firmware/``) continua obrigatório.
    * O comportamento do ADS8688: o MISO é um modelo mínimo (ver :class:`ModeloADC`).

Verificações estáticas feitas ao carregar: tamanho em instruções (a IMEM da PRU0 tem 2048) e alcance dos
desvios ``QB*`` (10 bits com sinal: +-511 instruções; desvios mais longos têm que usar ``JMP``).

Instruções suportadas: ``LDI MOV ADD SUB OR AND LSL LSR SET CLR NOP LBBO SBBO QBA QBBC QBBS QBEQ QBNE JMP``.
Uma instrução fora dessa lista levanta :class:`ErroSimulacao` -- amplie ``_EXECUTORES`` se precisar de outra.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

MASCARA32 = 0xFFFFFFFF
LIMITE_DESVIO_QB = 511          # QB*: deslocamento de 10 bits com sinal, em instruções
INSTRUCOES_IMEM_PRU = 2048      # 8 KB / 4 bytes

PINO_SCLK = 0
PINO_MOSI = 1
PINO_CS = 3
BIT_MISO_R31 = 2

ENDERECO_CONTADOR_CICLOS = 0x0002200C
ENDERECO_SHARED_RAM = 0x00010000


class ErroSimulacao(Exception):
    """Instrução não suportada, operando inválido ou limite de ciclos excedido."""


@dataclass
class Instrucao:
    mnemonico: str
    operandos: list[str]
    linha: int
    texto: str


@dataclass
class Transacao:
    """Uma transação SPI (CS baixo -> CS alto): palavra enviada pelo MOSI, amostrada na borda de descida do SCLK."""

    bits_mosi: list[int] = field(default_factory=list)

    @property
    def ciclos_sclk(self) -> int:
        return len(self.bits_mosi)

    @property
    def palavra16(self) -> int:
        """Os 16 primeiros bits (o comando), MSB primeiro."""
        valor = 0
        for bit in self.bits_mosi[:16]:
            valor = (valor << 1) | bit
        return valor


class ModeloADC:
    """MISO mínimo: devolve, bit a bit, uma palavra fixa por quadro de dados (só para o laço principal rodar).

    Nas 16 primeiras bordas o SDO fica em 0, como o ADS8688 de verdade (datasheet 8.4.1.1.4); ``ruido_no_quadro``
    (número do quadro, a partir de 0) põe um 1 nessa fase -- o que um reflexo na linha faria."""

    def __init__(self, palavra: int = 0x8000, ruido_no_quadro: set[int] | None = None) -> None:
        self.palavra = palavra
        self.ruido_no_quadro = ruido_no_quadro or set()
        self._indice = 0
        self._quadro = -1

    def novo_quadro(self) -> None:
        self._indice = 0
        self._quadro += 1

    def proximo_bit(self, clocks_no_quadro: int) -> int:
        if clocks_no_quadro < 16:
            return 1 if self._quadro in self.ruido_no_quadro and clocks_no_quadro == 7 else 0
        indice = clocks_no_quadro - 16
        return (self.palavra >> (15 - indice)) & 1 if indice < 16 else 0


# ---------------------------------------------------------------------------
# Leitura do fonte
# ---------------------------------------------------------------------------
_RE_ROTULO = re.compile(r"^([A-Za-z_][\w?]*):\s*(.*)$")


def _sem_comentario(linha: str) -> str:
    return linha.split(";", 1)[0].strip()


def _expandir(texto: str) -> list[tuple[int, str]]:
    """Expande ``.macro``/``.endm`` e devolve [(número_da_linha, linha)] só com rótulos e instruções."""
    macros: dict[str, list[tuple[int, str]]] = {}
    saida_bruta: list[tuple[int, str]] = []
    dentro: str | None = None
    corpo: list[tuple[int, str]] = []
    for numero, linha_original in enumerate(texto.splitlines(), start=1):
        linha = _sem_comentario(linha_original)
        if not linha:
            continue
        m = re.match(r"^(\w+)\s+\.macro\b", linha)
        if m:
            dentro, corpo = m.group(1), []
            continue
        if linha.startswith(".endm"):
            assert dentro is not None
            macros[dentro] = corpo
            dentro = None
            continue
        if dentro is not None:
            corpo.append((numero, linha))
        else:
            saida_bruta.append((numero, linha))

    saida: list[tuple[int, str]] = []
    contador = 0
    for numero, linha in saida_bruta:
        if linha.startswith("."):
            continue                                   # .global, .sect...
        if linha in macros:
            contador += 1
            for n_macro, l_macro in macros[linha]:
                saida.append((n_macro, l_macro.replace("?", f"__m{contador}")))
        else:
            saida.append((numero, linha))
    return saida


def carregar_programa(caminho: Path) -> tuple[list[Instrucao], dict[str, int]]:
    """Devolve (instruções, rótulo -> índice da instrução)."""
    instrucoes: list[Instrucao] = []
    rotulos: dict[str, int] = {}
    for numero, linha in _expandir(caminho.read_text(encoding="utf-8")):
        while True:
            m = _RE_ROTULO.match(linha)
            if not m:
                break
            nome, linha = m.group(1), m.group(2).strip()
            if nome in rotulos:
                raise ErroSimulacao(f"rótulo duplicado '{nome}' (linha {numero})")
            rotulos[nome] = len(instrucoes)
        if not linha:
            continue
        partes = linha.split(None, 1)
        operandos = [o.strip() for o in partes[1].split(",")] if len(partes) > 1 else []
        instrucoes.append(Instrucao(partes[0].upper(), operandos, numero, linha))
    return instrucoes, rotulos


# ---------------------------------------------------------------------------
# Máquina
# ---------------------------------------------------------------------------
_RE_REG = re.compile(r"^&?r(\d+)(?:\.(b[0-3]|w[0-2]))?$", re.IGNORECASE)
_CAMPOS = {"b0": (0, 8), "b1": (8, 8), "b2": (16, 8), "b3": (24, 8), "w0": (0, 16), "w1": (8, 16), "w2": (16, 16)}


class PRU:
    def __init__(self, caminho_asm: Path, memoria_inicial: dict[int, int] | None = None, adc: ModeloADC | None = None):
        self.instrucoes, self.rotulos = carregar_programa(caminho_asm)
        self.regs = [0] * 32
        self.memoria: dict[int, int] = {}
        for endereco, valor32 in (memoria_inicial or {}).items():
            self.escrever_mem(endereco, valor32, 4)
        self.regs[14] = ENDERECO_SHARED_RAM            # ABI do C: 1º argumento em r14
        self.pc = self.rotulos.get("ler_ads8688_asm", 0)
        self.ciclo = 0
        self.base_contador = 0
        self.adc = adc or ModeloADC()
        self.transacoes: list[Transacao] = []
        self.instantes_cs: list[int] = []               # ciclo de cada descida do CS (o instante da amostra)
        self.instantes_cs_sobe: list[int] = []          # ciclo de cada subida do CS (fim da transação)
        self.escritas_ddr: list[tuple[int, int]] = []
        self._atual: Transacao | None = None
        self._r30_anterior = 0
        self._clocks_quadro = 0
        self.violacoes_desvio: list[str] = []
        self._verificar_estaticamente()

    # -- verificações estáticas ---------------------------------------------
    @property
    def total_instrucoes(self) -> int:
        return len(self.instrucoes)

    def _verificar_estaticamente(self) -> None:
        for indice, ins in enumerate(self.instrucoes):
            if ins.mnemonico.startswith("QB") and ins.operandos:
                alvo = ins.operandos[0]
                if alvo not in self.rotulos:
                    raise ErroSimulacao(f"linha {ins.linha}: rótulo '{alvo}' não existe")
                distancia = self.rotulos[alvo] - indice
                if abs(distancia) > LIMITE_DESVIO_QB:
                    self.violacoes_desvio.append(
                        f"linha {ins.linha}: '{ins.texto}' salta {distancia:+d} instruções (limite +-{LIMITE_DESVIO_QB}); use JMP")

    # -- registradores -------------------------------------------------------
    def _decodificar(self, operando: str) -> tuple[int, int, int] | None:
        m = _RE_REG.match(operando)
        if not m:
            return None
        numero = int(m.group(1))
        campo = m.group(2)
        inicio, largura = _CAMPOS[campo.lower()] if campo else (0, 32)
        return numero, inicio, largura

    def _ler(self, operando: str) -> int:
        decod = self._decodificar(operando)
        if decod is None:
            return int(operando, 0) & MASCARA32
        numero, inicio, largura = decod
        valor = self.regs[numero] if numero != 31 else self._r31()
        return (valor >> inicio) & ((1 << largura) - 1)

    def _escrever(self, operando: str, valor: int) -> None:
        decod = self._decodificar(operando)
        if decod is None:
            raise ErroSimulacao(f"destino inválido: {operando}")
        numero, inicio, largura = decod
        mascara = ((1 << largura) - 1) << inicio
        self.regs[numero] = (self.regs[numero] & ~mascara & MASCARA32) | ((valor << inicio) & mascara)

    def _r31(self) -> int:
        miso = self.adc.proximo_bit(self._clocks_quadro)
        return (miso & 1) << BIT_MISO_R31

    # -- memória -------------------------------------------------------------
    def ler_mem(self, endereco: int, n: int) -> int:
        if endereco == ENDERECO_CONTADOR_CICLOS:
            return min(self.ciclo - self.base_contador, MASCARA32)     # trava em 0xFFFFFFFF, como na PRU
        return sum(self.memoria.get(endereco + i, 0) << (8 * i) for i in range(n))

    def escrever_mem(self, endereco: int, valor: int, n: int) -> None:
        if endereco == ENDERECO_CONTADOR_CICLOS:
            self.base_contador = self.ciclo - (valor & MASCARA32)
            return
        for i in range(n):
            self.memoria[endereco + i] = (valor >> (8 * i)) & 0xFF

    # -- pinos -----------------------------------------------------------------
    def _observar_pinos(self) -> None:
        r30 = self.regs[30]
        mudou = r30 ^ self._r30_anterior
        if mudou:
            cs_antes = (self._r30_anterior >> PINO_CS) & 1
            cs_agora = (r30 >> PINO_CS) & 1
            if mudou & (1 << PINO_CS):
                if cs_antes == 1 and cs_agora == 0:           # CS desceu: começa a transação
                    self.instantes_cs.append(self.ciclo)
                    self._atual = Transacao()
                    self._clocks_quadro = 0
                    self.adc.novo_quadro()
                elif cs_antes == 0 and cs_agora == 1 and self._atual is not None:
                    self.instantes_cs_sobe.append(self.ciclo)
                    self.transacoes.append(self._atual)
                    self._atual = None
            if mudou & (1 << PINO_SCLK) and not (r30 >> PINO_SCLK) & 1 and self._atual is not None:
                self._atual.bits_mosi.append((r30 >> PINO_MOSI) & 1)    # SDI é lido na borda de descida
                self._clocks_quadro += 1
        self._r30_anterior = r30

    # -- execução --------------------------------------------------------------
    def executar(self, max_transacoes: int | None = None, max_ciclos: int = 5_000_000) -> None:
        """Roda até ``max_transacoes`` transações SPI completas (ou ``max_ciclos``)."""
        while self.ciclo < max_ciclos:
            if max_transacoes is not None and len(self.transacoes) >= max_transacoes:
                return
            if self.pc >= len(self.instrucoes):
                raise ErroSimulacao("PC fora do programa")
            ins = self.instrucoes[self.pc]
            executor = _EXECUTORES.get(ins.mnemonico)
            if executor is None:
                raise ErroSimulacao(f"linha {ins.linha}: instrução não suportada: {ins.texto}")
            proximo = executor(self, ins)
            self.pc = self.pc + 1 if proximo is None else proximo
            self.ciclo += 1
            self._observar_pinos()
        raise ErroSimulacao(f"limite de {max_ciclos} ciclos excedido (PC na linha {self.instrucoes[self.pc].linha})")


def _alvo(maq: PRU, nome: str) -> int:
    return maq.rotulos[nome]


def _ex_ldi(m: PRU, i: Instrucao):
    destino, valor = i.operandos
    if m._decodificar(destino)[2] == 32:                 # LDI sem subcampo zera o resto do registrador
        m._escrever(destino, int(valor, 0) & 0xFFFF)
    else:
        m._escrever(destino, int(valor, 0))


def _ex_mov(m: PRU, i: Instrucao):
    m._escrever(i.operandos[0], m._ler(i.operandos[1]))


def _aritmetica(operacao):
    def executor(m: PRU, i: Instrucao):
        destino, a, b = i.operandos
        m._escrever(destino, operacao(m._ler(a), m._ler(b)) & MASCARA32)
    return executor


def _ex_set(m: PRU, i: Instrucao):
    destino, origem, bit = i.operandos
    m._escrever(destino, m._ler(origem) | (1 << m._ler(bit)))


def _ex_clr(m: PRU, i: Instrucao):
    destino, origem, bit = i.operandos
    m._escrever(destino, m._ler(origem) & ~(1 << m._ler(bit)))


def _ex_nop(m: PRU, i: Instrucao):
    return None


def _ex_lbbo(m: PRU, i: Instrucao):
    destino, base, deslocamento, n = i.operandos
    if m._decodificar(deslocamento) is not None:
        raise ErroSimulacao(f"linha {i.linha}: este simulador só aceita deslocamento imediato em LBBO")
    endereco = (m._ler(base) + int(deslocamento, 0)) & MASCARA32
    quantidade = int(n, 0)
    numero, inicio, _ = m._decodificar(destino)
    if quantidade > 4:                                   # vários registradores seguidos (LBBO &r9, ..., 12)
        if inicio or quantidade % 4:
            raise ErroSimulacao(f"linha {i.linha}: LBBO de vários registradores precisa de registrador inteiro e n múltiplo de 4")
        for k in range(quantidade // 4):
            m.regs[numero + k] = m.ler_mem(endereco + 4 * k, 4)
        return
    valor = m.ler_mem(endereco, quantidade)
    mascara = ((1 << (8 * quantidade)) - 1) << inicio
    m.regs[numero] = (m.regs[numero] & ~mascara & MASCARA32) | ((valor << inicio) & mascara)


def _ex_sbbo(m: PRU, i: Instrucao):
    origem, base, deslocamento, n = i.operandos
    if m._decodificar(deslocamento) is not None:
        raise ErroSimulacao(f"linha {i.linha}: este simulador só aceita deslocamento imediato em SBBO")
    endereco = (m._ler(base) + int(deslocamento, 0)) & MASCARA32
    quantidade = int(n, 0)
    numero, inicio, _ = m._decodificar(origem)
    if quantidade > 4:                                   # vários registradores seguidos (SBBO &r6, ..., 12)
        if inicio or quantidade % 4:
            raise ErroSimulacao(f"linha {i.linha}: SBBO de vários registradores precisa de registrador inteiro e n múltiplo de 4")
        for k in range(quantidade // 4):
            m.escrever_mem(endereco + 4 * k, m.regs[numero + k], 4)
        return
    valor = (m.regs[numero] >> inicio) & ((1 << (8 * quantidade)) - 1)
    m.escrever_mem(endereco, valor, quantidade)
    if endereco >= 0x90000000:
        m.escritas_ddr.append((endereco, valor))


def _desvio_se(condicao):
    def executor(m: PRU, i: Instrucao):
        alvo, a, b = i.operandos
        if condicao(m._ler(a), m._ler(b)):
            return _alvo(m, alvo)
    return executor


def _ex_qba(m: PRU, i: Instrucao):
    return _alvo(m, i.operandos[0])


def _ex_jmp(m: PRU, i: Instrucao):
    destino = i.operandos[0]
    if destino in m.rotulos:
        return m.rotulos[destino]
    return m._ler(destino)


_EXECUTORES = {
    "LDI": _ex_ldi,
    "MOV": _ex_mov,
    "ADD": _aritmetica(lambda a, b: a + b),
    "SUB": _aritmetica(lambda a, b: a - b),
    "OR": _aritmetica(lambda a, b: a | b),
    "AND": _aritmetica(lambda a, b: a & b),
    "LSL": _aritmetica(lambda a, b: a << (b & 31)),
    "LSR": _aritmetica(lambda a, b: a >> (b & 31)),
    "SET": _ex_set,
    "CLR": _ex_clr,
    "NOP": _ex_nop,
    "LBBO": _ex_lbbo,
    "SBBO": _ex_sbbo,
    "QBA": _ex_qba,
    "JMP": _ex_jmp,
    "QBBC": _desvio_se(lambda valor, bit: not (valor >> bit) & 1),
    "QBBS": _desvio_se(lambda valor, bit: (valor >> bit) & 1),
    "QBEQ": _desvio_se(lambda a, b: a == b),
    "QBNE": _desvio_se(lambda a, b: a != b),
}


# ---------------------------------------------------------------------------
# Atalho para os testes
# ---------------------------------------------------------------------------
# Offsets de struct shared_control (firmware/memoria_pru.h)
OFFSET_SAMPLE_PERIOD_TICKS = 0
OFFSET_BUFFER_0_ADDR = 16
OFFSET_BUFFER_1_ADDR = 20
OFFSET_CONFIG_READY = 24
OFFSET_AUTO_SEQ_MASK = 28
OFFSET_RANGE_SEL = 32
OFFSET_AMOSTRAS_ATRASADAS = 36
OFFSET_BUFFERS_SOBRESCRITOS = 40
OFFSET_QUADROS_PREAMBULO_RUIM = 44
OFFSET_ATRASO_CS_SETUP = 48     # + 4 = hold, + 8 = alto
OFFSET_BUFFER_0_READY = 8
OFFSET_BUFFER_1_READY = 12


def memoria_configurada(mascara: int, range_sel: int | None = None, periodo_ticks: int = 2000) -> dict[int, int]:
    """Shared RAM como o ``ler_adc`` a deixa antes de sinalizar ``config_ready``. ``range_sel=None`` não escreve o
    campo (útil para o spi_core.asm antigo, que não o conhece)."""
    mem = {
        ENDERECO_SHARED_RAM + OFFSET_SAMPLE_PERIOD_TICKS: periodo_ticks,
        ENDERECO_SHARED_RAM + OFFSET_BUFFER_0_ADDR: 0x9F000000,
        ENDERECO_SHARED_RAM + OFFSET_BUFFER_1_ADDR: 0x9F200000,
        ENDERECO_SHARED_RAM + OFFSET_CONFIG_READY: 1,
        ENDERECO_SHARED_RAM + OFFSET_AUTO_SEQ_MASK: mascara,
    }
    if range_sel is not None:
        mem[ENDERECO_SHARED_RAM + OFFSET_RANGE_SEL] = range_sel
    return mem
