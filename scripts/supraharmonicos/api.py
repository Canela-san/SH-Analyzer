"""A API do motor para quem não é a linha de comando: a interface gráfica, um notebook, um script.

Ela não monta ``argparse.Namespace`` nem imprime nada. Abre uma captura com as mesmas regras do ``adc_tool``
(:func:`contexto.resolver_contexto_explicito`: o cabeçalho e os padrões históricos) e devolve o que cada canal é:

* as amostras como uma visão do memmap (nenhuma cópia: uma captura de horas abre em milissegundos);
* a conversão código -> unidade física, com a faixa do ADC, o ganho declarado na captura e o offset -- os mesmos
  números de ``amostras.converter_para_tensao`` na CLI;
* a grandeza, a sonda registrada e o perfil que corrige o canal (:func:`contexto.perfil_para_correcao`, a regra da
  CLI), sem aplicá-lo: quem chama decide quando corrigir (:func:`sinal_do_canal`). **Uma diferença deliberada da
  CLI:** se o perfil de um canal não pode ser usado (a sonda registrada sem o arquivo do perfil, um id inseguro), a
  CLI para com um erro; aqui a captura abre mesmo assim, o canal fica sem perfil e o problema vai para
  ``CanalDaCaptura.problema_sonda`` e para os avisos -- quem olha os dados crus não pode ser impedido por um canal;
* os avisos do motor (o que a CLI escreveria no terminal), como dados.

A interface gráfica só fala com o motor por aqui (``tests/test_arquitetura.py`` confere); a CLI continua nas
funções de sempre, e os testes de paridade (``tests/test_api.py``) conferem que as duas dão os mesmos números.

Depende de: ``amostras``, ``cabecalho``, ``constantes``, ``contexto``, ``erros``, ``sonda``.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .amostras import carregar_amostras_bin, converter_para_tensao
from .cabecalho import (
    CabecalhoArquivo,
    conferir_consistencia_cabecalho,
    conferir_crc_das_amostras,
    contar_amostras_arquivo_bin,
)
from .constantes import FORMATOS_NUMPY, NOMES_GRANDEZA
from .contexto import ContextoCaptura, perfil_para_correcao, resolver_contexto_explicito
from .erros import ErroSHAN
from .sonda import PerfilSonda, aplicar_correcao_sonda

LOGGER_DO_MOTOR = "supraharmonicos"


@dataclass(frozen=True)
class Aviso:
    """Um aviso do motor: ``nivel`` é ``"info"``, ``"aviso"`` ou ``"erro"``; ``texto``, a mensagem (a da CLI)."""

    nivel: str
    texto: str


@dataclass(frozen=True, eq=False)
class CanalDaCaptura:
    """Um canal de uma captura aberta."""

    numero: int                   # o canal do ADC (0 a 7)
    posicao: int                  # a posição na intercalação (a ordem crescente dos canais)
    amostras: np.ndarray          # os códigos do ADC: uma visão com passo dentro do memmap, sem cópia
    taxa_hz: float                # a taxa deste canal (a total dividida pelo número de canais)
    faixa_v: float                # o valor de --faixa (do cabeçalho v3, ou o padrão histórico)
    faixa_confiavel: bool         # a faixa é a REAL do ADC, gravada no cabeçalho (não uma suposição)
    ganho: float                  # unidades físicas por volt no pino (o declarado na captura, ou 1)
    offset_v: float               # o nível subtraído antes do ganho (a metade da faixa em uint16)
    grandeza: int                 # constantes.GRANDEZA_*
    sonda_id: str                 # a sonda registrada no cabeçalho ('' se nenhuma)
    perfil: PerfilSonda | None    # o perfil que corrige este canal (a regra da CLI), ou None
    formato: str
    problema_sonda: str = ""      # por que o perfil registrado não pôde ser usado ('' se não houve problema)

    @property
    def nome_grandeza(self) -> str:
        return NOMES_GRANDEZA.get(self.grandeza, "?")

    @property
    def escala(self) -> float:
        """Unidade física por código: ``valor = código * escala + deslocamento``."""
        return self.faixa_v / (32768.0 if self.formato == "int16" else 65536.0) * self.ganho

    @property
    def deslocamento(self) -> float:
        return -self.offset_v * self.ganho

    @property
    def duracao_s(self) -> float:
        return len(self.amostras) / self.taxa_hz


@dataclass(frozen=True, eq=False)
class Captura:
    """Uma captura aberta: o cabeçalho, todas as amostras (intercaladas, em memmap), os canais e os avisos."""

    caminho: Path
    cabecalho: CabecalhoArquivo
    formato: str
    amostras: np.ndarray
    canais: tuple[CanalDaCaptura, ...]
    avisos: tuple[Aviso, ...]
    contexto: ContextoCaptura

    def canal(self, numero: int) -> CanalDaCaptura:
        for c in self.canais:
            if c.numero == numero:
                return c
        raise ErroSHAN(f"o canal {numero} não está na captura (canais: "
                       f"{', '.join(str(c.numero) for c in self.canais)}).")


class _Coletor(logging.Handler):
    def __init__(self):
        super().__init__(logging.INFO)
        self.avisos: list[Aviso] = []

    def emit(self, registro: logging.LogRecord) -> None:
        nivel = "erro" if registro.levelno >= logging.ERROR else "aviso" if registro.levelno >= logging.WARNING else "info"
        self.avisos.append(Aviso(nivel, registro.getMessage()))


@contextmanager
def capturar_avisos() -> Iterator[list[Aviso]]:
    """Junta numa lista o que o motor diria no terminal (INFO e acima) enquanto o bloco roda."""
    logger = logging.getLogger(LOGGER_DO_MOTOR)
    coletor = _Coletor()
    nivel_antes = logger.level
    logger.addHandler(coletor)
    if logger.getEffectiveLevel() > logging.INFO:
        logger.setLevel(logging.INFO)
    try:
        yield coletor.avisos
    finally:
        logger.removeHandler(coletor)
        logger.setLevel(nivel_antes)


def abrir_captura(caminho: Path, *, formato: str = "uint16", sondas_dir: Path | None = None) -> Captura:
    """Abre um ``.bin`` com cabeçalho (v1 a v9), sem ler as amostras.

    Os canais, as faixas, os ganhos, as grandezas e as sondas vêm do cabeçalho, com os padrões históricos onde
    ele não diz (as mesmas regras do ``adc_tool`` sem flags). ``sondas_dir`` é onde procurar os perfis
    (``scripts/sondas`` por padrão). Levanta :class:`ErroSHAN` para um arquivo sem cabeçalho, vazio ou incoerente
    com o cabeçalho."""
    caminho = Path(caminho)
    if formato not in FORMATOS_NUMPY:
        raise ErroSHAN(f"formato desconhecido: {formato!r} (use 'uint16' ou 'int16').")
    if caminho.suffix.lower() != ".bin":
        raise ErroSHAN(f"{caminho.name}: a API abre só capturas .bin (o CSV continua no adc_tool).")
    with capturar_avisos() as avisos:
        ctx = resolver_contexto_explicito(caminho, formato=formato, sondas_dir=sondas_dir)
        if ctx.cabecalho is None:
            raise ErroSHAN(f"{caminho.name}: sem o cabeçalho do SH-Analyzer. Capturas do formato legado pedem os "
                           "canais e a taxa: use o adc_tool.py com --canais e -f.")
        n_amostras_arquivo = contar_amostras_arquivo_bin(caminho, formato, ctx.offset_amostras)
        conferir_consistencia_cabecalho(ctx.cabecalho, ctx.canais, ctx.canais_veio_do_cabecalho, n_amostras_arquivo,
                                        formato)
        amostras = carregar_amostras_bin(caminho, formato, ctx.offset_amostras)
        n_canais = ctx.num_canais
        n_por_canal = len(amostras) // n_canais        # um quadro final incompleto (arquivo cortado) fica de fora
        taxa = ctx.cabecalho.frequencia_hz / n_canais
        canais = []
        for posicao, numero in enumerate(ctx.canais):
            try:
                perfil, problema = perfil_para_correcao(ctx, numero, formato), ""
            except ErroSHAN as e:          # a CLI pararia aqui; a interface abre a captura e mostra o problema
                perfil, problema = None, str(e)
                avisos.append(Aviso("erro", problema))
            canais.append(CanalDaCaptura(
                numero=numero, posicao=posicao,
                amostras=amostras[posicao:n_por_canal * n_canais:n_canais],
                taxa_hz=taxa,
                faixa_v=ctx.faixas[posicao], faixa_confiavel=ctx.faixas_confiaveis[posicao],
                ganho=ctx.ganhos[posicao], offset_v=ctx.offsets[posicao],
                grandeza=ctx.grandeza_do_canal(numero), sonda_id=ctx.sonda_id_do_canal(numero),
                perfil=perfil, formato=formato, problema_sonda=problema,
            ))
    return Captura(caminho, ctx.cabecalho, formato, amostras, tuple(canais), tuple(avisos), ctx)


def sinal_do_canal(captura: Captura, canal: int, inicio: int = 0, fim: int | None = None, *,
                   corrigir_sonda: bool = False) -> np.ndarray:
    """As amostras ``[inicio, fim)`` de ``canal`` na unidade física (``float64``), como a CLI as calcula.

    Com ``corrigir_sonda``, aplica o perfil do canal (se houver) pela divisão espectral do motor, sobre o trecho
    pedido: num trecho curto, as bordas sentem a correção (é a mesma conta que o ``adc_tool --inicio --fim``
    faz)."""
    c = captura.canal(canal)
    codigos = np.asarray(c.amostras[inicio:fim])
    sinal = converter_para_tensao(codigos, c.faixa_v, c.ganho, c.formato, c.offset_v)
    if corrigir_sonda and c.perfil is not None:
        sinal = aplicar_correcao_sonda(sinal, c.taxa_hz, c.perfil)
    return sinal


def conferir_integridade(captura: Captura, *, progresso: Callable[[float], None] | None = None,
                         cancelado: Callable[[], bool] | None = None) -> bool | None:
    """As amostras conferidas contra o CRC-32 que o ``ler_adc`` gravou no cabeçalho v9 (o ``info`` da CLI): True se
    o arquivo é o que a captura gravou, False se foi corrompido, truncado ou alterado, None se o cabeçalho não traz o
    CRC (ou se ``cancelado()`` interrompeu). Lê o arquivo inteiro (~1 s por GiB): rode fora da thread da interface,
    com ``progresso(fração)``."""
    return conferir_crc_das_amostras(captura.caminho, captura.cabecalho, progresso=progresso, cancelado=cancelado)


def _talvez(valor, formato: str = "{}") -> str | None:
    return None if valor is None or valor == "" else formato.format(valor)


def descrever_cabecalho(captura: Captura) -> list[tuple[str, list[tuple[str, str]]]]:
    """O cabeçalho em seções de ``(rótulo, valor)`` para mostrar (o inspetor da interface): a captura, os canais, a
    integridade, a BeagleBone e a PRU. Só o que o cabeçalho traz: um campo de uma versão anterior fica de fora, em
    vez de aparecer como "?"."""
    cab = captura.cabecalho
    duracao = cab.duracao_real_segundos
    captura_secao = [
        ("Arquivo", captura.caminho.name),
        ("Tamanho", f"{captura.caminho.stat().st_size / 1e6:.1f} MB"),
        ("Cabeçalho", f"v{cab.versao_cabecalho}" + ("" if cab.crc32_valido else " (CRC do cabeçalho NÃO confere)")),
        ("Início (relógio da placa)", cab.timestamp_iso_utc),
        ("Duração", None if duracao is None else f"{duracao:.3f} s"),
        ("Taxa total", f"{cab.frequencia_hz} Hz"),
        ("Taxa medida", _talvez(cab.taxa_medida_hz, "{:.2f} Hz")),
        ("Amostras", f"{cab.total_amostras_gravadas}"),
        ("Título", _talvez(cab.titulo)),
        ("Descrição", _talvez(cab.descricao)),
        ("Identificador", _talvez(cab.id_captura)),
        ("Máquina", _talvez(cab.hostname)),
        ("Comando", _talvez(cab.linha_de_comando, "ler_adc {}")),
    ]
    canais = []
    for c in captura.canais:
        sonda = f", sonda {c.sonda_id}" if c.sonda_id else ""
        canais.append((f"Canal {c.numero}", f"{c.nome_grandeza}, faixa {c.faixa_v:g} V"
                                            f"{'' if c.faixa_confiavel else ' (suposta)'}, ganho {c.ganho:g}{sonda}"))
    canais += [(f"Sinal {i + 1}", linha) for i, linha in enumerate(cab.descrever_sinal_por_canal())]
    integridade = [("Problema", texto) for texto in cab.problemas_integridade]
    integridade += [("Grade", cab.descrever_grade()), ("SPI", cab.descrever_spi()),
                    ("CRC das amostras", _talvez(cab.crc32_amostras, "0x{:08X} (gravado)")),
                    ("Pior bloco", _talvez(cab.pior_bloco_ms, "{} ms"))]
    placa = [("Firmware", _talvez(cab.versao_firmware))]
    placa += [(f"Sistema {i + 1}", linha) for i, linha in enumerate(cab.descrever_sistema())]
    secoes = [("Captura", captura_secao), ("Canais", canais), ("Integridade", integridade), ("BeagleBone", placa)]
    return [(titulo, [(r, v) for r, v in linhas if v is not None]) for titulo, linhas in secoes]
