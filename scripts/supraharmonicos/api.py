"""A API do motor para quem não é a linha de comando: a interface gráfica, um notebook, um script.

Ela não monta ``argparse.Namespace`` nem imprime nada. Abre uma captura com as mesmas regras do ``adc_tool``
(:func:`contexto.resolver_contexto_explicito`: o cabeçalho e os padrões históricos) e devolve o que cada canal é:

* as amostras como uma visão do memmap (nenhuma cópia: uma captura de horas abre em milissegundos); o ``.csv`` e o
  ``.h5`` do ``adc_tool`` vão para a memória, e o que não tem o cabeçalho pede a taxa e os canais
  (:class:`ParametrosSemCabecalho`, os ``-f`` e ``--canais`` da CLI);
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

**A frequência** (o espectro, os picos, o espectrograma, as bandas da IEC 61000-4-7 e os harmônicos): cada conta
recebe o sinal já na unidade física (``sinal_do_canal``, ou o de um traço com a sua cadeia de transformações), a
taxa e os parâmetros num dataclass imutável, e devolve o resultado noutro, com os avisos do motor. Os números são os
do ``adc_tool --fft``, ``--welch``, ``--picos``, ``--agrupar-bandas``, ``--espectrograma``, ``--bandas-iec`` e
``--harmonicos`` sobre o mesmo trecho (``tests/test_api.py`` confere). As contas longas (o Welch, o espectrograma e as
bandas de uma captura inteira) aceitam ``progresso(fração)`` e ``cancelado()``; cancelada, a conta levanta
:class:`Cancelado`.

**Os filtros e a sonda** (a cadeia de transformações de um traço): o Butterworth de fase zero da CLI
(``--filtro-passa-alta``, ``--filtro-passa-baixa``) e também a passa-faixa e a rejeita-faixa, validados com o motivo;
a correção de sonda (``aplicar_correcao_sonda``) e a carga de um perfil escolhido.

Depende de: ``amostras``, ``bandas_iec``, ``cabecalho``, ``canais``, ``constantes``, ``contexto``, ``erros``,
``espectro``, ``filtros``, ``fundamental``, ``harmonicos``, ``hdf5``, ``metricas_captura``, ``sonda``.
"""

from __future__ import annotations

import logging
import math
import threading
import zlib
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, fields
from pathlib import Path

import numpy as np

from .amostras import carregar_amostras_bin, carregar_colunas_csv, converter_para_tensao
from .bandas_iec import (
    FREQ_MIN_IEC_HZ,
    LARGURA_BANDA_IEC_HZ,
    BandasIEC,
    agregar_iec,
    calcular_bandas_iec,
    ciclos_por_janela_iec,
    janelas_dos_cruzamentos,
)
from .cabecalho import (
    CabecalhoArquivo,
    conferir_consistencia_cabecalho,
    conferir_crc_das_amostras,
    contar_amostras_arquivo_bin,
    interpretar_cabecalho,
    ler_cabecalho,
)
from .canais import analisar_lista_canais, faixa_cli_do_total_v
from .constantes import (
    CORTE_SUPRAHARMONICOS_PADRAO,
    DISTANCIA_MINIMA_PICOS_PADRAO,
    FORMATOS_NUMPY,
    JANELA_PADRAO_FFT,
    JANELA_PADRAO_WELCH,
    NOMES_GRANDEZA,
    ORDEM_FILTRO_PADRAO,
    RESOLUCAO_WELCH_PADRAO,
    SOBREPOSICAO_WELCH_PADRAO,
    TOLERANCIA_FAIXA_V,
    UNIDADE_GRANDEZA,
)
from .contexto import ContextoCaptura, perfil_para_correcao, resolver_contexto_explicito
from .erros import Cancelado as Cancelado  # a interface importa daqui
from .erros import ErroSHAN
from .espectro import (
    agrupar_em_bandas,
    calcular_espectro,
    calcular_espectro_welch,
    calcular_espectrograma,
    enbw_bins,
    encontrar_picos_espectro,
    resolver_nome_janela,
    rotulo_janela_completo,
    tamanho_segmento_welch,
)
from .filtros import aplicar_filtro_digital, projetar_filtro_sos
from .fundamental import cruzamentos_da_fundamental, recortar_ciclos_inteiros
from .harmonicos import TabelaHarmonicos, calcular_harmonicos
from .hdf5 import ler_cabecalho_bruto, ler_hdf5
from .metricas_captura import calcular_basicas
from .sonda import SONDAS_DIR_PADRAO, PerfilSonda, alcance_da_correcao, carregar_perfil_sonda
from .sonda import aplicar_correcao_sonda as aplicar_correcao_sonda  # a cadeia de transformações da interface usa

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
    taxa_hz: float                # a taxa deste canal: a total que a PRU gera (clock ÷ ticks, a do adc_tool), dividida
                                  # pelo número de canais
    faixa_v: float                # o valor de --faixa (do cabeçalho v3, ou o padrão histórico)
    faixa_confiavel: bool         # a faixa é a REAL do ADC, gravada no cabeçalho (não uma suposição)
    ganho: float                  # unidades físicas por volt no pino (o declarado na captura, ou 1)
    offset_v: float               # o nível subtraído antes do ganho (a metade da faixa em uint16)
    grandeza: int                 # constantes.GRANDEZA_*
    sonda_id: str                 # a sonda registrada no cabeçalho ('' se nenhuma)
    perfil: PerfilSonda | None    # o perfil que corrige este canal (a regra da CLI), ou None
    formato: str
    problema_sonda: str = ""      # por que o perfil registrado não pôde ser usado ('' se não houve problema)
    ganho_declarado: bool = False  # o ganho veio da captura (ler_adc --ganho): o valor está na unidade física

    @property
    def nome_grandeza(self) -> str:
        return NOMES_GRANDEZA.get(self.grandeza, "?")

    @property
    def unidade(self) -> str:
        """A unidade dos valores (``escala``): a da grandeza (A, °C...) quando o ganho foi declarado na captura;
        senão, V no pino do ADC (a regra da CLI: sem ``--ganho``, o valor é a tensão no pino)."""
        return UNIDADE_GRANDEZA.get(self.grandeza, "V") if self.ganho_declarado else "V"

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


TIPOS_DE_ARQUIVO = {".bin": "bin", ".csv": "csv", ".h5": "h5", ".hdf5": "h5"}
"""As extensões que :func:`abrir_captura` abre, e o tipo de cada uma."""


@dataclass(frozen=True)
class ParametrosSemCabecalho:
    """O que uma captura sem o cabeçalho do SH-Analyzer não diz (o ``.bin`` legado, o ``.csv`` do ``adc_tool``, o
    ``.h5`` exportado de um legado): a taxa **total**, a soma dos canais (o ``-f`` do ``adc_tool``), e os canais na
    ordem da intercalação (o ``--canais``), validados com as mensagens da CLI."""

    taxa_total_hz: float
    canais: tuple[int, ...]

    def __post_init__(self) -> None:
        taxa = self.taxa_total_hz
        if isinstance(taxa, bool) or not isinstance(taxa, (int, float)) or not math.isfinite(taxa) or taxa <= 0:
            raise ErroSHAN(f"a taxa total precisa ser um número positivo, em Hz (não {taxa!r}).")
        object.__setattr__(self, "taxa_total_hz", float(taxa))
        object.__setattr__(self, "canais", tuple(analisar_lista_canais(",".join(str(c) for c in self.canais),
                                                                       "canais")))

    @classmethod
    def de_texto(cls, taxa_total_hz: float, canais: str) -> ParametrosSemCabecalho:
        """Com os canais como na CLI (``"0,1"``)."""
        return cls(taxa_total_hz, tuple(analisar_lista_canais(canais, "canais")))

    @property
    def texto_dos_canais(self) -> str:
        return ",".join(str(c) for c in self.canais)


class CapturaSemCabecalho(ErroSHAN):
    """:func:`abrir_captura` precisa de ``parametros``: o arquivo não diz a taxa (e talvez os canais). Quem abre
    pergunta e abre de novo. Para perguntar: ``tipo`` (``"bin"``, ``"csv"`` ou ``"h5"``), ``canais`` (os que o
    arquivo diz, e então não se pergunta por eles; ou None) e ``n_amostras`` (as brutas, de todos os canais)."""

    def __init__(self, mensagem: str, *, tipo: str, canais: tuple[int, ...] | None = None,
                 n_amostras: int | None = None):
        super().__init__(mensagem)
        self.tipo = tipo
        self.canais = canais
        self.n_amostras = n_amostras


@dataclass(frozen=True)
class OrigemDoHdf5:
    """De onde veio um ``.h5`` do ``--export-hdf5``: o ``.bin``, o trecho em amostras brutas ``[início, fim)`` e a
    versão do código que exportou (None se não gravada)."""

    arquivo: str
    trecho: tuple[int, int]
    versao_codigo: str | None


@dataclass(frozen=True, eq=False)
class Captura:
    """Uma captura aberta: o cabeçalho (None sem ele), todas as amostras (intercaladas: em memmap no ``.bin``, em
    memória no ``.csv`` e no ``.h5``), os canais e os avisos. ``parametros``: a taxa e os canais informados a
    :func:`abrir_captura` (None quando o arquivo os diz); ``hdf5``: de onde veio um ``.h5``."""

    caminho: Path
    cabecalho: CabecalhoArquivo | None
    formato: str
    amostras: np.ndarray
    canais: tuple[CanalDaCaptura, ...]
    avisos: tuple[Aviso, ...]
    contexto: ContextoCaptura
    tipo: str = "bin"
    parametros: ParametrosSemCabecalho | None = None
    hdf5: OrigemDoHdf5 | None = None

    @property
    def crc32_amostras(self) -> int | None:
        """O CRC-32 que o ``ler_adc`` gravou das amostras **deste arquivo** (o ``.bin`` com o cabeçalho v9), ou None:
        o ``.h5`` traz o cabeçalho do ``.bin`` de origem, mas as amostras dele podem ser só um trecho."""
        return self.cabecalho.crc32_amostras if self.tipo == "bin" and self.cabecalho is not None else None

    def canal(self, numero: int) -> CanalDaCaptura:
        for c in self.canais:
            if c.numero == numero:
                return c
        raise ErroSHAN(f"o canal {numero} não está na captura (canais: "
                       f"{', '.join(str(c.numero) for c in self.canais)}).")


class _Coletor(logging.Handler):
    """Junta os registros da thread que o criou: duas contas em threads diferentes não trocam os avisos."""

    def __init__(self):
        super().__init__(logging.INFO)
        self.avisos: list[Aviso] = []
        self._thread = threading.get_ident()

    def emit(self, registro: logging.LogRecord) -> None:
        if registro.thread != self._thread:
            return
        nivel = "erro" if registro.levelno >= logging.ERROR else "aviso" if registro.levelno >= logging.WARNING else "info"
        self.avisos.append(Aviso(nivel, registro.getMessage()))


_trava_dos_avisos = threading.Lock()
_coletas_abertas = 0
_nivel_antes_das_coletas = logging.NOTSET


@contextmanager
def capturar_avisos() -> Iterator[list[Aviso]]:
    """Junta numa lista o que o motor diria no terminal (INFO e acima) enquanto o bloco roda, só os da thread que
    chamou. O nível do logger do motor desce para INFO na primeira coleta aberta e volta ao de antes na última (as
    contas rodam em várias threads ao mesmo tempo)."""
    global _coletas_abertas, _nivel_antes_das_coletas
    logger = logging.getLogger(LOGGER_DO_MOTOR)
    coletor = _Coletor()
    with _trava_dos_avisos:
        if _coletas_abertas == 0:
            _nivel_antes_das_coletas = logger.level
            if logger.getEffectiveLevel() > logging.INFO:
                logger.setLevel(logging.INFO)
        _coletas_abertas += 1
        logger.addHandler(coletor)
    try:
        yield coletor.avisos
    finally:
        with _trava_dos_avisos:
            logger.removeHandler(coletor)
            _coletas_abertas -= 1
            if _coletas_abertas == 0:
                logger.setLevel(_nivel_antes_das_coletas)


PASTA_DAS_SONDAS_PADRAO: Path = SONDAS_DIR_PADRAO
"""Onde :func:`abrir_captura` procura os perfis de sonda sem ``sondas_dir`` (a interface a mostra nas
configurações, e o usuário pode trocar)."""


def abrir_captura(caminho: Path, *, formato: str | None = None, sondas_dir: Path | None = None,
                  parametros: ParametrosSemCabecalho | None = None) -> Captura:
    """Abre uma captura com as regras do ``adc_tool``:

    * o ``.bin`` com o cabeçalho (v1 a v9), sem ler as amostras (memmap): os canais, as faixas, os ganhos, as
      grandezas e as sondas vêm do cabeçalho, com os padrões históricos onde ele não diz (o ``adc_tool`` sem flags);
    * o ``.bin`` legado (sem o cabeçalho) e o ``.csv`` do ``adc_tool -c`` pedem ``parametros``, a taxa e os canais
      (os ``-f`` e ``--canais`` da CLI); o resto, os padrões da CLI. A coluna 'canal' do ``.csv``, quando há, diz os
      canais e a ordem deles, e um ``.csv`` que começa no meio de um ciclo é alinhado pelo índice das amostras;
    * o ``.h5`` do ``adc_tool --export-hdf5``: as amostras brutas, a calibração com que foram exportadas e o
      cabeçalho do ``.bin`` de origem (a taxa); um exportado de um legado pede só a taxa.

    Sem ``parametros`` onde eles faltam, levanta :class:`CapturaSemCabecalho`, com o que o arquivo diz para
    perguntar; com eles onde o arquivo já diz, :class:`ErroSHAN` (nunca dois valores para a mesma coisa).
    ``formato``: o das amostras, ``"uint16"`` (o padrão) ou ``"int16"``; o ``.h5`` diz o dele. ``sondas_dir`` é onde
    procurar os perfis (:data:`PASTA_DAS_SONDAS_PADRAO`, por padrão). Levanta :class:`ErroSHAN` para um arquivo
    vazio, incoerente ou de outro tipo."""
    caminho = Path(caminho)
    if formato is not None and formato not in FORMATOS_NUMPY:
        raise ErroSHAN(f"formato desconhecido: {formato!r} (use 'uint16' ou 'int16').")
    tipo = TIPOS_DE_ARQUIVO.get(caminho.suffix.lower())
    if tipo is None:
        raise ErroSHAN(f"{caminho.name}: '{caminho.suffix or '(sem extensão)'}' não é uma captura que o SH-Analyzer "
                       f"abre (.bin, .csv ou .h5).")
    if not caminho.is_file():
        raise ErroSHAN(f"arquivo '{caminho}' não encontrado.")
    abrir = {"bin": _abrir_bin, "csv": _abrir_csv, "h5": _abrir_hdf5}[tipo]
    with capturar_avisos() as avisos:
        ctx, amostras, formato, taxa_total, declarados, hdf5 = abrir(caminho, formato, sondas_dir, parametros)
        canais = _canais_da_captura(caminho, ctx, amostras, formato, taxa_total, declarados, avisos)
    return Captura(caminho, ctx.cabecalho, formato, amostras, canais, tuple(avisos), ctx, tipo, parametros, hdf5)


def abrir_ao_vivo(caminho: Path, blocos: int, *, sondas_dir: Path | None = None) -> Captura:
    """O que já chegou de uma captura em curso: o ``.parcial`` da saída contínua (``sh_placa.captura``), com o
    cabeçalho provisório e os ``blocos`` primeiros blocos inteiros (os que as linhas de progresso já contaram; o que
    vem depois pode estar pela metade). Os canais são os do :func:`abrir_captura`, com as unidades, as faixas, os
    ganhos e as sondas do cabeçalho; os campos de fim dele ainda não valem (a captura não acabou). Levanta
    :class:`ErroSHAN` sem o cabeçalho, com ``blocos`` < 1 ou com menos amostras no arquivo que esses blocos."""
    caminho = Path(caminho)
    if blocos < 1:
        raise ErroSHAN(f"{caminho.name}: o ao vivo precisa de pelo menos um bloco inteiro (pedidos {blocos}).")
    if not caminho.is_file() or ler_cabecalho(caminho) is None:
        raise ErroSHAN(f"{caminho.name}: não é uma captura do ler_adc em curso (sem o cabeçalho do SH-Analyzer).")
    with capturar_avisos() as avisos:
        ctx = resolver_contexto_explicito(caminho, formato="uint16", sondas_dir=sondas_dir)
        cab = ctx.cabecalho
        n = blocos * cab.samples_per_buffer
        todas = carregar_amostras_bin(caminho, "uint16", ctx.offset_amostras)
        if len(todas) < n:
            raise ErroSHAN(f"{caminho.name}: {len(todas)} amostras no arquivo, menos que os {blocos} bloco(s) de "
                           f"{cab.samples_per_buffer}.")
        amostras = todas[:n]
        canais = _canais_da_captura(caminho, ctx, amostras, "uint16", _taxa_do_cabecalho(cab),
                                    _declarados(cab, ctx.num_canais), avisos)
    return Captura(caminho, cab, "uint16", amostras, canais, tuple(avisos), ctx, "bin", None, None)


def _canais_da_captura(caminho: Path, ctx: ContextoCaptura, amostras, formato: str, taxa_total: float,
                       declarados: list[bool], avisos: list[Aviso]) -> tuple[CanalDaCaptura, ...]:
    """Os canais das amostras intercaladas (as visões de cada um, sem cópia). Um quadro final incompleto (um arquivo
    cortado) fica de fora; um perfil de sonda que não serve vira um aviso, e o canal abre sem ele."""
    n_canais = ctx.num_canais
    n_por_canal = len(amostras) // n_canais
    if n_por_canal == 0:
        raise ErroSHAN(f"{caminho.name}: {len(amostras)} amostra(s), menos que um ciclo dos {n_canais} canais.")
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
            taxa_hz=taxa_total / n_canais,
            faixa_v=ctx.faixas[posicao], faixa_confiavel=ctx.faixas_confiaveis[posicao],
            ganho=ctx.ganhos[posicao], offset_v=ctx.offsets[posicao],
            grandeza=ctx.grandeza_do_canal(numero), sonda_id=ctx.sonda_id_do_canal(numero),
            perfil=perfil, formato=formato, problema_sonda=problema,
            ganho_declarado=declarados[posicao],
        ))
    return tuple(canais)


def crc32_das_amostras(caminho: Path) -> int | None:
    """O CRC-32 que o ``ler_adc`` gravou das amostras de um ``.bin`` (cabeçalho v9), lendo só o cabeçalho (sem abrir a
    captura); None num ``.bin`` sem ele ou de uma versão anterior, e em outro tipo de arquivo. Serve para reencontrar
    uma captura que mudou de lugar."""
    caminho = Path(caminho)
    if TIPOS_DE_ARQUIVO.get(caminho.suffix.lower()) != "bin":
        return None
    cabecalho = ler_cabecalho(caminho)
    return None if cabecalho is None else cabecalho.crc32_amostras


def _sem_parametros_se_tem_cabecalho(caminho: Path, parametros: ParametrosSemCabecalho | None) -> None:
    if parametros is not None:
        raise ErroSHAN(f"{caminho.name} tem o cabeçalho do SH-Analyzer: a taxa e os canais vêm dele.")


def _taxa_do_cabecalho(cab: CabecalhoArquivo) -> float:
    """A taxa total que a PRU de fato gera (clock ÷ ticks), como no adc_tool: a pedida difere dela quando 200 MHz ÷
    taxa não é inteiro (102,4 kHz pedidos são 102.406,55 Hz, +64 ppm)."""
    return cab.frequencia_pru_hz or float(cab.frequencia_hz)


def _declarados(cab: CabecalhoArquivo | None, n_canais: int) -> list[bool]:
    """Se o ganho de cada canal foi declarado na captura (ler_adc --ganho, cabeçalho v9)."""
    ganhos = cab.ganho_por_canal if cab is not None and len(cab.lista_canais) == n_canais else ()
    return [i < len(ganhos) and bool(ganhos[i]) for i in range(n_canais)]


def _abrir_bin(caminho: Path, formato: str | None, sondas_dir: Path | None,
               parametros: ParametrosSemCabecalho | None):
    formato = formato or "uint16"
    if ler_cabecalho(caminho) is None:
        n_amostras = contar_amostras_arquivo_bin(caminho, formato, 0)
        if n_amostras == 0:
            raise ErroSHAN(f"'{caminho}' está vazio (0 amostras).")      # nada a perguntar
        if parametros is None:
            raise CapturaSemCabecalho(f"{caminho.name}: sem o cabeçalho do SH-Analyzer (o formato legado). Diga a "
                                      "taxa total e os canais.", tipo="bin", n_amostras=n_amostras)
        ctx = resolver_contexto_explicito(caminho, formato=formato, canais_texto=parametros.texto_dos_canais,
                                          sondas_dir=sondas_dir)
        amostras = carregar_amostras_bin(caminho, formato, 0)
        return ctx, amostras, formato, parametros.taxa_total_hz, [False] * ctx.num_canais, None
    _sem_parametros_se_tem_cabecalho(caminho, parametros)
    ctx = resolver_contexto_explicito(caminho, formato=formato, sondas_dir=sondas_dir)
    n_amostras_arquivo = contar_amostras_arquivo_bin(caminho, formato, ctx.offset_amostras)
    conferir_consistencia_cabecalho(ctx.cabecalho, ctx.canais, ctx.canais_veio_do_cabecalho, n_amostras_arquivo,
                                    formato)
    amostras = carregar_amostras_bin(caminho, formato, ctx.offset_amostras)
    return (ctx, amostras, formato, _taxa_do_cabecalho(ctx.cabecalho), _declarados(ctx.cabecalho, ctx.num_canais),
            None)


def _intercalacao_do_csv(caminho: Path, canal: np.ndarray, amostra: np.ndarray | None) -> tuple[tuple[int, ...], int]:
    """(os canais na ordem da intercalação, quantas linhas do começo pular para o primeiro ciclo começar no primeiro
    canal), pela coluna 'canal' de um '.csv' do ``adc_tool -c`` e pela 'amostra' (o índice da amostra bruta no
    '.bin' de origem: um '.csv' convertido com ``--inicio`` pode começar no meio de um ciclo)."""
    n_canais = len(np.unique(canal))
    if amostra is not None and len(amostra) > 1 and not np.all(np.diff(amostra) == 1):
        amostra = None                                  # mexido à mão: as linhas valem pela ordem, como na CLI
    posicao = (amostra if amostra is not None else np.arange(len(canal))) % n_canais
    ordem = np.empty(n_canais, dtype=np.int64)
    for p in range(n_canais):
        linhas = np.flatnonzero(posicao == p)
        if not len(linhas):
            raise ErroSHAN(f"{caminho.name}: a coluna 'canal' tem {n_canais} canais e menos linhas que um ciclo.")
        ordem[p] = canal[linhas[0]]
    if not np.array_equal(canal, ordem[posicao]):
        raise ErroSHAN(f"{caminho.name}: a coluna 'canal' não segue um ciclo dos canais "
                       f"{', '.join(map(str, ordem))} (o arquivo foi mexido?).")
    return tuple(int(c) for c in ordem), int(-posicao[0] % n_canais)


def _abrir_csv(caminho: Path, formato: str | None, sondas_dir: Path | None,
               parametros: ParametrosSemCabecalho | None):
    formato = formato or "uint16"
    colunas = carregar_colunas_csv(caminho, formato)
    do_arquivo, pular = (None, 0) if colunas.canal is None else \
        _intercalacao_do_csv(caminho, colunas.canal, colunas.amostra)
    if parametros is None:
        raise CapturaSemCabecalho(f"{caminho.name}: um .csv não tem o cabeçalho do SH-Analyzer. Diga a taxa total"
                                  + (" e os canais." if do_arquivo is None else "."), tipo="csv", canais=do_arquivo,
                                  n_amostras=len(colunas.valores))
    if do_arquivo is not None and parametros.canais != do_arquivo:
        raise ErroSHAN(f"{caminho.name}: a coluna 'canal' diz os canais {', '.join(map(str, do_arquivo))}, não "
                       f"{', '.join(map(str, parametros.canais))}.")
    ctx = resolver_contexto_explicito(caminho, formato=formato, canais_texto=parametros.texto_dos_canais,
                                      sondas_dir=sondas_dir)
    return ctx, colunas.valores[pular:], formato, parametros.taxa_total_hz, [False] * ctx.num_canais, None


def _abrir_hdf5(caminho: Path, formato: str | None, sondas_dir: Path | None,
                parametros: ParametrosSemCabecalho | None):
    conteudo = ler_hdf5(caminho)
    if formato is not None and formato != conteudo.formato:
        raise ErroSHAN(f"{caminho.name}: as amostras do .h5 são {conteudo.formato}, não {formato}.")
    formato, canais = conteudo.formato, tuple(conteudo.canais)
    cab = None if conteudo.cabecalho_bruto is None else interpretar_cabecalho(conteudo.cabecalho_bruto, caminho)
    if cab is None:
        if parametros is None:
            raise CapturaSemCabecalho(f"{caminho.name}: exportado de um .bin sem o cabeçalho do SH-Analyzer. Diga a "
                                      "taxa total.", tipo="h5", canais=canais, n_amostras=len(conteudo.amostras))
        if parametros.canais != canais:
            raise ErroSHAN(f"{caminho.name}: o .h5 diz os canais {', '.join(map(str, canais))}, não "
                           f"{', '.join(map(str, parametros.canais))}.")
        taxa_total = parametros.taxa_total_hz
    else:
        _sem_parametros_se_tem_cabecalho(caminho, parametros)
        taxa_total = _taxa_do_cabecalho(cab)
    # A calibração é a da exportação (o --faixa, o --ganho e o --offset dela, ou os do cabeçalho); a faixa é a real
    # do ADC onde coincide com a que o cabeçalho registra (a regra de resolver_faixas).
    reais = cab.faixa_adc_total_v_por_canal if cab is not None and len(cab.lista_canais) == len(canais) else ()
    confiaveis = [i < len(reais) and reais[i] is not None
                  and abs(faixa_cli_do_total_v(reais[i], formato) - faixa) <= TOLERANCIA_FAIXA_V
                  for i, faixa in enumerate(conteudo.faixas)]
    ctx = ContextoCaptura(
        caminho_entrada=caminho, cabecalho=cab, offset_amostras=0, canais=list(canais),
        canais_veio_do_cabecalho=False, canais_exibir=list(canais), faixas=conteudo.faixas, ganhos=conteudo.ganhos,
        offsets=conteudo.offsets, faixas_confiaveis=confiaveis,
        overrides_grandeza={} if conteudo.grandezas is None else dict(zip(canais, conteudo.grandezas)),
        overrides_perfil={}, sondas_dir=sondas_dir if sondas_dir is not None else SONDAS_DIR_PADRAO)
    # O ganho está na unidade física se a captura o declarou ou se a exportação usou um --ganho.
    declarados = [d or g != 1.0 for d, g in zip(_declarados(cab, len(canais)), conteudo.ganhos)]
    origem = OrigemDoHdf5(conteudo.arquivo_origem, conteudo.trecho, conteudo.versao_codigo)
    return ctx, conteudo.amostras, formato, taxa_total, declarados, origem


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
    o arquivo é o que a captura gravou, False se foi corrompido, truncado ou alterado, None se não há o CRC para
    conferir (sem o cabeçalho, até a v8, um ``.h5`` de só um trecho da captura) ou se ``cancelado()`` interrompeu. Lê
    as amostras inteiras (~1 s por GiB): rode fora da thread da interface, com ``progresso(fração)``.

    Num ``.h5`` com a captura inteira, confere as amostras dele (as do ``.bin``, byte a byte, se nada mudou)."""
    cab = captura.cabecalho
    if cab is None or cab.crc32_amostras is None:
        return None
    if captura.tipo == "bin":
        return conferir_crc_das_amostras(captura.caminho, cab, progresso=progresso, cancelado=cancelado)
    if captura.hdf5 is None or captura.hdf5.trecho != (0, cab.total_amostras_gravadas):
        return None
    dados = memoryview(np.ascontiguousarray(captura.amostras, dtype=FORMATOS_NUMPY[captura.formato])).cast("B")
    crc, bloco = 0, 1 << 24
    for inicio in range(0, len(dados), bloco):
        if cancelado is not None and cancelado():
            return None
        crc = zlib.crc32(dados[inicio:inicio + bloco], crc)
        if progresso is not None:
            progresso(min(1.0, (inicio + bloco) / len(dados)))
    return crc == cab.crc32_amostras


def _talvez(valor, formato: str = "{}") -> str | None:
    return None if valor is None or valor == "" else formato.format(valor)


_NOMES_DOS_TIPOS = {"bin": ".bin", "csv": ".csv do adc_tool", "h5": ".h5 do adc_tool --export-hdf5"}


def descrever_cabecalho(captura: Captura) -> list[tuple[str, list[tuple[str, str]]]]:
    """O cabeçalho em seções de ``(rótulo, valor)`` para mostrar (o inspetor da interface): a captura, os canais, a
    integridade, a BeagleBone e a PRU. Só o que o cabeçalho traz: um campo de uma versão anterior fica de fora, em
    vez de aparecer como "?". Sem o cabeçalho, o que se sabe: o arquivo, a taxa e os canais informados ao abrir; num
    ``.h5``, também de onde ele veio."""
    cab = captura.cabecalho
    captura_secao = [("Arquivo", captura.caminho.name),
                     ("Tamanho", f"{captura.caminho.stat().st_size / 1e6:.1f} MB")]
    if captura.tipo != "bin":
        captura_secao.append(("Tipo", _NOMES_DOS_TIPOS[captura.tipo]))
    if captura.hdf5 is not None:
        inicio, fim = captura.hdf5.trecho
        captura_secao += [("Exportado de", _talvez(captura.hdf5.arquivo)),
                          ("Trecho exportado", f"amostras brutas {inicio} a {fim}"),
                          ("Exportado por", _talvez(captura.hdf5.versao_codigo))]
    canais = []
    for c in captura.canais:
        sonda = f", sonda {c.sonda_id}" if c.sonda_id else ""
        canais.append((f"Canal {c.numero}", f"{c.nome_grandeza}, faixa {c.faixa_v:g} V"
                                            f"{'' if c.faixa_confiavel else ' (suposta)'}, ganho {c.ganho:g}{sonda}"))
    if cab is None:
        parametros = captura.parametros
        captura_secao += [("Cabeçalho", "nenhum: a taxa e os canais foram informados ao abrir"),
                          ("Taxa total", f"{parametros.taxa_total_hz:g} Hz"),
                          ("Amostras", f"{len(captura.amostras)}")]
        secoes = [("Captura", captura_secao), ("Canais", canais)]
        return [(titulo, [(r, v) for r, v in linhas if v is not None]) for titulo, linhas in secoes]
    duracao = cab.duracao_real_segundos
    origem = " (do .bin de origem)" if captura.tipo != "bin" else ""
    captura_secao += [
        ("Cabeçalho", f"v{cab.versao_cabecalho}{origem}"
                      + ("" if cab.crc32_valido else " (CRC do cabeçalho NÃO confere)")),
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
    canais += [(f"Sinal {i + 1}", linha) for i, linha in enumerate(cab.descrever_sinal_por_canal())]
    integridade = [("Problema", texto) for texto in cab.problemas_integridade]
    integridade += [("Grade", cab.descrever_grade()), ("SPI", cab.descrever_spi()),
                    ("CRC das amostras", _talvez(cab.crc32_amostras, "0x{:08X} (gravado)")),
                    ("Pior bloco", _talvez(cab.pior_bloco_ms, "{} ms"))]
    placa = [("Firmware", _talvez(cab.versao_firmware))]
    placa += [(f"Sistema {i + 1}", linha) for i, linha in enumerate(cab.descrever_sistema())]
    secoes = [("Captura", captura_secao), ("Canais", canais), ("Integridade", integridade), ("BeagleBone", placa)]
    return [(titulo, [(r, v) for r, v in linhas if v is not None]) for titulo, linhas in secoes]


def cabecalho_em_dict(captura: Captura) -> dict:
    """O cabeçalho inteiro, campo a campo, num dicionário que vai direto para o ``json.dumps`` (copiar o cabeçalho,
    guardá-lo junto de um resultado): o arquivo e o tipo dele, cada campo do ``CabecalhoArquivo`` (``None`` onde a
    versão do arquivo não grava), as tuplas como listas, e os derivados que a CLI mostra (o início em ISO 8601, a taxa
    da PRU, a duração real). Os números saem como estão no cabeçalho, sem arredondar. Sem o cabeçalho, os
    ``parametros`` informados ao abrir; num ``.h5``, também de onde ele veio (``hdf5``)."""
    cab = captura.cabecalho
    dados: dict = {"arquivo": captura.caminho.name, "tipo": captura.tipo, "formato_amostras": captura.formato}
    if captura.hdf5 is not None:
        dados["hdf5"] = {"arquivo_origem": captura.hdf5.arquivo, "trecho": list(captura.hdf5.trecho),
                         "versao_codigo": captura.hdf5.versao_codigo}
    if captura.parametros is not None:
        dados["parametros"] = {"taxa_total_hz": captura.parametros.taxa_total_hz,
                               "canais": list(captura.parametros.canais)}
    if cab is None:
        return dados
    for campo in fields(cab):
        dados[campo.name] = _para_json(getattr(cab, campo.name))
    dados["timestamp_iso_utc"] = cab.timestamp_iso_utc
    dados["frequencia_pru_hz"] = _para_json(cab.frequencia_pru_hz)
    dados["duracao_real_segundos"] = _para_json(cab.duracao_real_segundos)
    return dados


def cabecalho_para_hdf5(captura: Captura) -> tuple[dict, bytes] | None:
    """O cabeçalho da captura como o ``--export-hdf5`` o grava: os atributos (os do cabeçalho, a frequência da PRU e
    o arquivo de origem) e os bytes dele (o ``/cabecalho_bruto``). Para quem exporta um trecho da captura noutro
    leiaute (a exportação dos dados da interface). None sem o cabeçalho."""
    cab = captura.cabecalho
    if cab is None:
        return None
    atributos = dict(cab.para_attrs_hdf5())
    if cab.frequencia_pru_hz is not None:
        atributos["frequencia_pru_hz"] = cab.frequencia_pru_hz
    atributos["arquivo_origem"] = captura.hdf5.arquivo if captura.hdf5 is not None else captura.caminho.name
    if captura.tipo == "h5":
        bruto = ler_cabecalho_bruto(captura.caminho) or b""
    else:
        with open(captura.caminho, "rb") as f:
            bruto = f.read(cab.tamanho_cabecalho)
    return atributos, bruto


def _para_json(valor):
    """Um valor do cabeçalho no que o JSON aceita: as tuplas viram listas, os escalares do numpy viram os do Python,
    os bytes viram hexadecimal e um número não finito vira ``None`` (o JSON não tem NaN)."""
    if isinstance(valor, (tuple, list)):
        return [_para_json(v) for v in valor]
    if isinstance(valor, np.generic):
        valor = valor.item()
    if isinstance(valor, bytes):
        return valor.hex()
    if isinstance(valor, float) and not math.isfinite(valor):
        return None
    return valor


FREQ_MIN_FUNDAMENTAL = 45.0       # a busca da fundamental do adc_tool (--freq-min, --freq-max)
FREQ_MAX_FUNDAMENTAL = 65.0


@dataclass(frozen=True)
class MedidasDaRegiao:
    """As medidas de um trecho de um canal, na unidade do canal (com o ganho e o offset de quem chamou)."""

    n_amostras: int
    duracao_s: float
    media: float
    rms: float                    # com o DC
    rms_ac: float                 # sem o DC (o desvio padrão)
    minimo: float
    maximo: float
    pico_a_pico: float
    pico: float                   # o maior valor absoluto
    f1_hz: float | None           # a fundamental pelos cruzamentos por zero; None sem uma fundamental no trecho
    problema_f1: str = ""         # por que não há f1 ('' se há)


def medir_regiao(captura: Captura, canal: int, inicio: int, fim: int, *, corrigir_sonda: bool = False,
                 ganho: float = 1.0, offset: float = 0.0, freq_min: float = FREQ_MIN_FUNDAMENTAL,
                 freq_max: float = FREQ_MAX_FUNDAMENTAL, fundamental: bool = True) -> MedidasDaRegiao:
    """As medidas das amostras ``[inicio, fim)`` de ``canal`` (nunca do desenho): a média, os RMS, os extremos e a
    fundamental, pelas mesmas contas da CLI (``metricas_captura.calcular_basicas`` e
    ``fundamental.cruzamentos_da_fundamental``, a busca do ``--fft``). ``ganho`` e ``offset`` são os do traço,
    aplicados depois da conversão do canal. Levanta ``ErroSHAN`` com menos de 2 amostras; um trecho sem fundamental
    só deixa ``f1_hz`` vazio, com o motivo. Com ``fundamental=False``, a f1 não é calculada (ela é a conta cara:
    ~1 s a cada 4 M amostras, contra ~0,02 s das outras)."""
    c = captura.canal(canal)
    sinal = sinal_do_canal(captura, canal, inicio, fim, corrigir_sonda=corrigir_sonda) * ganho + offset
    return medir_sinal(sinal, c.taxa_hz, freq_min=freq_min, freq_max=freq_max, fundamental=fundamental)


def medir_sinal(sinal, taxa_hz: float, *, freq_min: float = FREQ_MIN_FUNDAMENTAL,
                freq_max: float = FREQ_MAX_FUNDAMENTAL, fundamental: bool = True) -> MedidasDaRegiao:
    """As medidas de :func:`medir_regiao` sobre um sinal já na unidade física (o de um traço com a sua cadeia de
    transformações, por exemplo). Levanta ``ErroSHAN`` com menos de 2 amostras."""
    sinal = np.asarray(sinal, dtype=np.float64)
    basicas = calcular_basicas(sinal, taxa_hz)
    if not fundamental:
        f1, problema = None, "a fundamental não foi calculada neste trecho"
    else:
        try:
            _, f1, problema = *cruzamentos_da_fundamental(sinal, taxa_hz, freq_min, freq_max), ""
        except ErroSHAN as e:
            f1, problema = None, str(e)
    return MedidasDaRegiao(
        n_amostras=basicas.n_amostras, duracao_s=basicas.duracao_s, media=basicas.media, rms=basicas.rms_total,
        rms_ac=basicas.rms_ac, minimo=basicas.minimo, maximo=basicas.maximo, pico_a_pico=basicas.pico_a_pico,
        pico=max(abs(basicas.minimo), abs(basicas.maximo)), f1_hz=f1, problema_f1=problema)


_aquecido = threading.Event()
_trava_do_aquecimento = threading.Lock()


def aquecer() -> None:
    """Importa agora os módulos que as contas importam sob demanda (o SciPy da fundamental, do espectro, dos filtros,
    da sonda e da exportação). A interface chama isto em segundo plano logo depois de abrir (a primeira medida não paga
    a importação, ~1,5 s com o GIL preso) e **no começo de toda tarefa**: duas threads importando o SciPy ao mesmo
    tempo podem cair no deadlock das travas de importação do Python (``_DeadlockError`` em ``scipy.linalg``), e a
    conta de uma delas falhava. Com a trava, só uma importa, e as outras esperam; depois da primeira vez, custa nada."""
    if _aquecido.is_set():
        return
    with _trava_do_aquecimento:
        if _aquecido.is_set():
            return
        import scipy.fft  # noqa: F401
        import scipy.interpolate  # noqa: F401
        import scipy.io  # noqa: F401
        import scipy.optimize  # noqa: F401
        import scipy.signal  # noqa: F401
        import scipy.signal.windows  # noqa: F401
        _aquecido.set()


# ---------------------------------------------------------------------------
# A frequência: o espectro, os picos, o espectrograma, as bandas IEC e os harmônicos
# ---------------------------------------------------------------------------

KAISER_BETA_PADRAO = 8.6          # o padrão do --kaiser-beta
METODOS_DO_ESPECTRO = ("fft", "welch")
MODOS_DO_ESPECTRO = ("tom", "ruido")
ESCALAS_DO_ESPECTRO = ("db", "linear", "rms", "dbc")
ORDEM_MAXIMA_IEC = 40             # a IEC 61000-4-7 define o THD até a ordem 40

Progresso = Callable[[float], None]
Cancelar = Callable[[], bool]


def _sinal_float(sinal) -> np.ndarray:
    return np.asarray(sinal, dtype=np.float64)


def _validar_fundamental(freq_min: float, freq_max: float) -> None:
    if not (math.isfinite(freq_min) and math.isfinite(freq_max) and 0 < freq_min < freq_max):
        raise ErroSHAN(f"a busca da fundamental precisa de 0 < mínimo < máximo (recebido {freq_min:g} a "
                       f"{freq_max:g} Hz).")


def _validar_taxa(taxa_hz: float) -> None:
    if not (math.isfinite(taxa_hz) and taxa_hz > 0):
        raise ErroSHAN(f"a taxa de amostragem precisa ser positiva (recebido {taxa_hz!r} Hz).")


@dataclass(frozen=True)
class ParametrosEspectro:
    """Como calcular um espectro (os padrões são os do ``adc_tool``).

    * ``metodo``: ``"welch"`` (a média de segmentos: o ruído e os supraharmônicos, ``--welch``) ou ``"fft"`` (um
      segmento só, ``--fft``);
    * ``janela``: o nome (``retangular``, ``hann``, ``blackmanharris``, ``flattop``, ``kaiser``); None é a padrão do
      método: a retangular na FFT sincronizada (os harmônicos caem exatamente nos bins), a Hann no Welch e na FFT sem
      sincronizar;
    * ``modo``: ``"tom"`` (a amplitude de pico corrigida pelo ganho coerente da janela, em dB re 1 unidade) ou
      ``"ruido"`` (a densidade espectral de potência, em dB re unidade²/Hz), o ``--modo-espectro``;
    * ``resolucao_hz`` e ``sobreposicao``: o segmento do Welch (``--resolucao-welch``, ``--sobreposicao-welch``);
    * ``sincronizar``: a FFT recorta o trecho num número inteiro de ciclos da fundamental, alinhado ao primeiro
      cruzamento por zero (o ``--fft`` da CLI faz sempre assim); ``n_ciclos`` limita aos N primeiros (None: todos);
      a fundamental é buscada entre ``freq_min_fundamental`` e ``freq_max_fundamental``;
    * ``largura_bandas_hz``: também o espectro agrupado em bandas dessa largura (``--agrupar-bandas``)."""

    metodo: str = "welch"
    janela: str | None = None
    kaiser_beta: float = KAISER_BETA_PADRAO
    modo: str = "tom"
    resolucao_hz: float = RESOLUCAO_WELCH_PADRAO
    sobreposicao: float = SOBREPOSICAO_WELCH_PADRAO
    sincronizar: bool = True
    n_ciclos: int | None = None
    freq_min_fundamental: float = FREQ_MIN_FUNDAMENTAL
    freq_max_fundamental: float = FREQ_MAX_FUNDAMENTAL
    largura_bandas_hz: float | None = None

    @property
    def sincronizada(self) -> bool:
        return self.metodo == "fft" and self.sincronizar

    @property
    def janela_canonica(self) -> str:
        """O nome canônico da janela (o padrão do método, se ``janela`` é None). Levanta ``ErroSHAN`` para um nome
        desconhecido."""
        padrao = JANELA_PADRAO_FFT if self.sincronizada else JANELA_PADRAO_WELCH
        return resolver_nome_janela(self.janela or padrao)

    def validar(self, taxa_hz: float) -> None:
        """Confere os parâmetros para um sinal amostrado a ``taxa_hz``; levanta ``ErroSHAN`` com o motivo."""
        _validar_taxa(taxa_hz)
        if self.metodo not in METODOS_DO_ESPECTRO:
            raise ErroSHAN(f"método de espectro desconhecido: {self.metodo!r} (use 'fft' ou 'welch').")
        if self.modo not in MODOS_DO_ESPECTRO:
            raise ErroSHAN(f"modo de espectro desconhecido: {self.modo!r} (use 'tom' ou 'ruido').")
        janela = self.janela_canonica
        if janela == "kaiser" and not (math.isfinite(self.kaiser_beta) and self.kaiser_beta >= 0):
            raise ErroSHAN(f"o beta da janela Kaiser precisa ser >= 0 (recebido {self.kaiser_beta:g}).")
        if self.metodo == "welch":
            if not (math.isfinite(self.resolucao_hz) and self.resolucao_hz > 0):
                raise ErroSHAN(f"a resolução do Welch precisa ser positiva (recebido {self.resolucao_hz:g} Hz).")
            if not 0.0 <= self.sobreposicao < 1.0:
                raise ErroSHAN(f"a sobreposição do Welch precisa estar em [0, 1) (recebido {self.sobreposicao:g}).")
            if taxa_hz / self.resolucao_hz < 16:
                raise ErroSHAN(f"a resolução de {self.resolucao_hz:g} Hz dá um segmento de Welch menor que 16 "
                               f"amostras a {taxa_hz:g} Hz: use uma resolução menor.")
        if self.sincronizada:
            _validar_fundamental(self.freq_min_fundamental, self.freq_max_fundamental)
            if self.n_ciclos is not None and self.n_ciclos < 1:
                raise ErroSHAN(f"o número de ciclos da FFT precisa ser >= 1 (recebido {self.n_ciclos}).")
        if self.largura_bandas_hz is not None and not (math.isfinite(self.largura_bandas_hz)
                                                      and self.largura_bandas_hz > 0):
            raise ErroSHAN(f"a largura das bandas precisa ser positiva (recebido {self.largura_bandas_hz:g} Hz).")


@dataclass(frozen=True, eq=False)
class Espectro:
    """Um espectro de um lado: ``db[i]`` é o nível em ``freqs_hz[i]``, na convenção de ``parametros.modo`` (a mesma
    das colunas ``amplitude_db*`` e ``psd_db*`` do ``adc_tool --exportar``)."""

    freqs_hz: np.ndarray
    db: np.ndarray
    parametros: ParametrosEspectro
    taxa_hz: float
    janela: str                   # o nome canônico da janela usada
    rotulo_janela: str            # o nome para mostrar ("Hann", "Kaiser (beta=8.6)")
    n_amostras: int               # as amostras usadas (na FFT sincronizada, as dos ciclos inteiros)
    inicio_local: int             # onde elas começam no sinal recebido (a FFT sincronizada pula até um cruzamento)
    n_segmentos: int              # os segmentos médios (1 na FFT)
    enbw_bins: float              # a largura de banda equivalente de ruído da janela, em bins
    f0_hz: float | None = None    # a fundamental que sincronizou a FFT
    n_ciclos: int | None = None   # os ciclos inteiros da FFT sincronizada
    centros_bandas_hz: np.ndarray | None = None    # com ``largura_bandas_hz``: os centros das bandas
    db_bandas: np.ndarray | None = None            # e o nível RMS de cada uma, em dB re 1 unidade
    avisos: tuple[Aviso, ...] = ()

    @property
    def resolucao_hz(self) -> float:
        """O espaçamento entre os bins."""
        return float(self.freqs_hz[1] - self.freqs_hz[0]) if len(self.freqs_hz) > 1 else self.taxa_hz

    def rotulo(self, unidade: str, *, bandas: bool = False) -> str:
        """O rótulo do eixo, como o do gráfico da CLI: ``Magnitude (dBV)``, ``PSD (dB re A²/Hz)``, ``Nível RMS por
        banda de 200 Hz (dBV)``."""
        if bandas:
            return f"Nível RMS por banda de {self.parametros.largura_bandas_hz:g} Hz (dB{unidade})"
        return f"Magnitude (dB{unidade})" if self.parametros.modo == "tom" else f"PSD (dB re {unidade}²/Hz)"

    def piso(self, freq_min: float = CORTE_SUPRAHARMONICOS_PADRAO, freq_max: float | None = None) -> float:
        """O piso de ruído entre ``freq_min`` e ``freq_max`` (a Nyquist, por padrão): a mediana dos níveis dos bins,
        em ``db``. A mediana não sente os picos (os tons ocupam poucos bins), e é a mesma em dB e na escala linear.
        NaN sem bins na faixa."""
        freq_max = self.taxa_hz / 2.0 if freq_max is None else freq_max
        dentro = (self.freqs_hz >= freq_min) & (self.freqs_hz <= freq_max)
        return float(np.median(self.db[dentro])) if np.any(dentro) else math.nan

    def nivel_em(self, frequencia_hz: float) -> float:
        """O nível (em ``db``) do bin mais perto de ``frequencia_hz``."""
        return float(self.db[int(np.argmin(np.abs(self.freqs_hz - frequencia_hz)))])

    def niveis(self, escala: str = "db", *, referencia_hz: float | None = None) -> np.ndarray:
        """Os níveis numa escala:

        * ``"db"``: os de ``db`` (os da CLI);
        * ``"linear"``: no modo tom, a amplitude de pico (na unidade do sinal); no modo ruído, a PSD (unidade²/Hz);
        * ``"rms"``: no modo tom, o valor RMS do tom de cada bin (o pico ÷ √2; o DC é o próprio nível);
        * ``"dbc"``: em dB relativos ao bin de ``referencia_hz`` (por padrão a fundamental que sincronizou a FFT, ou,
          sem ela, o bin mais alto fora do DC)."""
        if escala not in ESCALAS_DO_ESPECTRO:
            raise ErroSHAN(f"escala desconhecida: {escala!r} (use {', '.join(ESCALAS_DO_ESPECTRO)}).")
        if escala == "db":
            return self.db.copy()
        tom = self.parametros.modo == "tom"
        if escala == "linear":
            return 10.0 ** (self.db / (20.0 if tom else 10.0))
        if escala == "rms":
            if not tom:
                raise ErroSHAN("o valor RMS por bin só existe no modo tom (no modo ruído, cada bin é uma densidade).")
            rms = 10.0 ** (self.db / 20.0) / math.sqrt(2.0)
            rms[0] *= math.sqrt(2.0)
            return rms
        if referencia_hz is None:
            referencia_hz = self.f0_hz
        if referencia_hz is None:
            referencia = float(np.max(self.db[1:])) if len(self.db) > 1 else float(self.db[0])
        else:
            referencia = self.nivel_em(referencia_hz)
        return self.db - referencia


def espectro(sinal, taxa_hz: float, parametros: ParametrosEspectro = ParametrosEspectro(), *,
             progresso: Progresso | None = None, cancelado: Cancelar | None = None) -> Espectro:
    """O espectro de ``sinal`` (na unidade física, amostrado a ``taxa_hz``), pelas contas do ``adc_tool --fft`` e
    ``--welch`` (``espectro.calcular_espectro``, ``calcular_espectro_welch``).

    O Welch lê o sinal um lote de segmentos por vez: ``sinal`` pode ser um memmap de uma captura inteira, com
    ``progresso`` e ``cancelado``. A FFT é um segmento só, e o trecho inteiro vai para a memória. Levanta ``ErroSHAN``
    para parâmetros inválidos, um trecho curto demais ou, na FFT sincronizada, um trecho sem a fundamental."""
    p = parametros
    p.validar(taxa_hz)
    janela = p.janela_canonica
    f0 = n_ciclos = None
    inicio = 0
    with capturar_avisos() as avisos:
        if p.metodo == "fft":
            trecho = _sinal_float(sinal)
            if p.sincronizar:
                trecho, inicio, _, f0, n_ciclos = recortar_ciclos_inteiros(
                    trecho, taxa_hz, p.freq_min_fundamental, p.freq_max_fundamental, p.n_ciclos)
            if len(trecho) < 2:
                raise ErroSHAN(f"a FFT precisa de pelo menos 2 amostras (o trecho tem {len(trecho)}).")
            freqs, db = calcular_espectro(trecho, taxa_hz, janela, p.kaiser_beta, p.modo)
            n_amostras, n_segmentos, n_janela = len(trecho), 1, len(trecho)
        else:
            freqs, db, n_segmentos = calcular_espectro_welch(
                sinal, taxa_hz, janela, p.kaiser_beta, p.resolucao_hz, p.sobreposicao, p.modo,
                progresso=progresso, cancelado=cancelado)
            n_amostras, n_janela = len(sinal), tamanho_segmento_welch(taxa_hz, p.resolucao_hz)
        enbw = enbw_bins(janela, n_janela, p.kaiser_beta)
        centros = db_bandas = None
        if p.largura_bandas_hz is not None:
            centros, db_bandas = agrupar_em_bandas(freqs, db, p.largura_bandas_hz, p.modo, enbw=enbw)
    return Espectro(freqs, db, p, float(taxa_hz), janela, rotulo_janela_completo(janela, p.kaiser_beta), n_amostras,
                    inicio, n_segmentos, enbw, f0, n_ciclos, centros, db_bandas, tuple(avisos))


@dataclass(frozen=True)
class Pico:
    """Um pico do espectro, refinado por interpolação parabólica entre os bins."""

    frequencia_hz: float
    db: float


def picos(espectro_: Espectro, limiar_db: float, *, freq_min: float = CORTE_SUPRAHARMONICOS_PADRAO,
          freq_max: float | None = None, distancia_minima_hz: float = DISTANCIA_MINIMA_PICOS_PADRAO,
          maximo: int | None = None, proeminencia_db: float | None = None) -> tuple[Pico, ...]:
    """Os picos de ``espectro_`` acima de ``limiar_db`` entre ``freq_min`` e ``freq_max`` (a Nyquist, por padrão),
    afastados de pelo menos ``distancia_minima_hz``: o ``--picos`` da CLI (``espectro.encontrar_picos_espectro``),
    com os mesmos padrões. ``maximo``: só os N mais altos. ``proeminencia_db``: só os que sobem pelo menos isso acima do
    vale que os separa de um pico maior (o ombro de um pico, ou o ruído, não contam). Em ordem de frequência."""
    nyquist = espectro_.taxa_hz / 2.0
    freq_max = nyquist if freq_max is None else freq_max
    if not freq_min < freq_max:
        raise ErroSHAN(f"a busca dos picos precisa de mínimo < máximo (recebido {freq_min:g} a {freq_max:g} Hz).")
    if not distancia_minima_hz >= 0:
        raise ErroSHAN(f"a distância mínima entre os picos não pode ser negativa ({distancia_minima_hz:g} Hz).")
    if maximo is not None and maximo < 1:
        raise ErroSHAN(f"o número de picos precisa ser >= 1 (recebido {maximo}).")
    achados = [Pico(a["frequencia_hz"], a["amplitude_db"]) for a in encontrar_picos_espectro(
        espectro_.freqs_hz, espectro_.db, freq_min, freq_max, limiar_db, distancia_minima_hz, proeminencia_db)]
    if maximo is not None and len(achados) > maximo:
        achados = sorted(sorted(achados, key=lambda pico: -pico.db)[:maximo], key=lambda pico: pico.frequencia_hz)
    return tuple(achados)


@dataclass(frozen=True)
class ParametrosEspectrograma:
    """O espectrograma (``--espectrograma``): os segmentos do Welch (``janela`` None é a Hann), reunidos em até
    ``max_colunas`` colunas, cada uma a média da potência dos seus segmentos."""

    janela: str | None = None
    kaiser_beta: float = KAISER_BETA_PADRAO
    modo: str = "tom"
    resolucao_hz: float = RESOLUCAO_WELCH_PADRAO
    sobreposicao: float = SOBREPOSICAO_WELCH_PADRAO
    max_colunas: int = 600

    @property
    def janela_canonica(self) -> str:
        return resolver_nome_janela(self.janela or JANELA_PADRAO_WELCH)

    def validar(self, taxa_hz: float) -> None:
        ParametrosEspectro("welch", self.janela, self.kaiser_beta, self.modo, self.resolucao_hz,
                           self.sobreposicao).validar(taxa_hz)
        if self.max_colunas < 1:
            raise ErroSHAN(f"o espectrograma precisa de pelo menos 1 coluna (recebido {self.max_colunas}).")


@dataclass(frozen=True, eq=False)
class Espectrograma:
    """``db[k, i]``: o nível da coluna ``k`` (centrada em ``tempos_s[k]``, desde o início do sinal recebido) na
    frequência ``freqs_hz[i]``, na convenção de ``parametros.modo``."""

    tempos_s: np.ndarray
    freqs_hz: np.ndarray
    db: np.ndarray
    parametros: ParametrosEspectrograma
    taxa_hz: float
    janela: str
    rotulo_janela: str


def espectrograma(sinal, taxa_hz: float, parametros: ParametrosEspectrograma = ParametrosEspectrograma(), *,
                  progresso: Progresso | None = None, cancelado: Cancelar | None = None) -> Espectrograma:
    """O espectro ao longo do tempo (``espectro.calcular_espectrograma``, o ``--espectrograma`` da CLI). Lê o sinal
    um lote de segmentos por vez (``sinal`` pode ser um memmap)."""
    p = parametros
    p.validar(taxa_hz)
    janela = p.janela_canonica
    tempos, freqs, matriz = calcular_espectrograma(sinal, taxa_hz, janela, p.kaiser_beta, p.resolucao_hz,
                                                   p.sobreposicao, p.modo, p.max_colunas,
                                                   progresso=progresso, cancelado=cancelado)
    return Espectrograma(tempos, freqs, matriz, p, float(taxa_hz), janela,
                         rotulo_janela_completo(janela, p.kaiser_beta))


@dataclass(frozen=True)
class ParametrosBandasIEC:
    """As bandas da IEC 61000-4-7, anexo B (``--bandas-iec``; ver ``bandas_iec``): de ``freq_min`` a ``freq_max``
    (a Nyquist, por padrão), de ``largura_hz`` cada, em janelas de 200 ms. ``sincronizar``: janelas de 10 ou 12
    ciclos da fundamental medida (``--bandas-iec-sincronizar``); ``agregar``: também as séries de ~3 s e de 10 min
    (``--bandas-iec-agregar``)."""

    freq_min: float = FREQ_MIN_IEC_HZ
    freq_max: float | None = None
    largura_hz: float = LARGURA_BANDA_IEC_HZ
    sincronizar: bool = False
    agregar: bool = False
    freq_min_fundamental: float = FREQ_MIN_FUNDAMENTAL
    freq_max_fundamental: float = FREQ_MAX_FUNDAMENTAL

    def validar(self, taxa_hz: float) -> None:
        _validar_taxa(taxa_hz)
        if not (math.isfinite(self.largura_hz) and self.largura_hz > 0):
            raise ErroSHAN(f"a largura das bandas precisa ser positiva (recebido {self.largura_hz:g} Hz).")
        nyquist = taxa_hz / 2.0
        maximo = nyquist if self.freq_max is None else min(self.freq_max, nyquist)
        if self.freq_min < 0 or maximo - self.freq_min < self.largura_hz:
            raise ErroSHAN(f"nenhuma banda de {self.largura_hz:g} Hz cabe entre {self.freq_min:g} e {maximo:g} Hz "
                           f"(Nyquist: {nyquist:g} Hz).")
        if self.sincronizar:
            _validar_fundamental(self.freq_min_fundamental, self.freq_max_fundamental)


@dataclass(frozen=True, eq=False)
class ResultadoBandasIEC:
    """As bandas (``bandas_iec.BandasIEC``: os níveis de cada banda em cada janela e as estatísticas) e o que as
    produziu."""

    bandas: BandasIEC
    parametros: ParametrosBandasIEC
    janelas_descartadas: int = 0      # sincronizadas: as que não tinham os ciclos dentro de ±0,03 %
    avisos: tuple[Aviso, ...] = ()


def bandas_iec(sinal, taxa_hz: float, parametros: ParametrosBandasIEC = ParametrosBandasIEC(), *, referencia=None,
               progresso: Progresso | None = None, cancelado: Cancelar | None = None) -> ResultadoBandasIEC:
    """As bandas de ``sinal`` pela IEC 61000-4-7, anexo B: as contas do ``adc_tool --bandas-iec``
    (``bandas_iec.calcular_bandas_iec`` e ``agregar_iec``).

    Sincronizadas, as janelas seguem a fundamental de ``referencia`` (por padrão o próprio sinal). A CLI usa o
    primeiro canal de tensão: a tensão da rede sempre tem a fundamental, e uma corrente pode não ter. As janelas
    são lidas uma a uma (``sinal`` pode ser um memmap), com ``progresso`` e ``cancelado``."""
    p = parametros
    p.validar(taxa_hz)
    limites = ciclos = f0 = None
    descartadas = 0
    with capturar_avisos() as avisos:
        if p.sincronizar:
            ref = _sinal_float(sinal if referencia is None else referencia)
            cruzamentos, f0 = cruzamentos_da_fundamental(ref, taxa_hz, p.freq_min_fundamental, p.freq_max_fundamental)
            ciclos = ciclos_por_janela_iec(f0)
            limites, descartadas = janelas_dos_cruzamentos(cruzamentos, ciclos)
            if len(limites) < 1:
                raise ErroSHAN(f"as bandas sincronizadas precisam de pelo menos {ciclos} ciclos completos e estáveis "
                               f"da fundamental no trecho; há {len(cruzamentos) - 1} ciclo(s).")
            if descartadas:
                avisos.append(Aviso("aviso", f"{descartadas} janela(s) descartada(s) por não terem {ciclos} ciclos "
                                             "dentro de ±0,03 % (a borda do trecho, ou um salto de fase ou uma falta "
                                             "de tensão; a IEC 61000-4-30 manda sinalizar esses intervalos)."))
        resultado = calcular_bandas_iec(sinal, taxa_hz, p.freq_min, p.freq_max, p.largura_hz, limites=limites,
                                        ciclos_por_janela=ciclos, f0_hz=f0, progresso=progresso, cancelado=cancelado)
        if p.agregar:
            resultado = agregar_iec(resultado)
            if not resultado.agregados:
                avisos.append(Aviso("aviso", f"o trecho tem {len(resultado.tempos_s)} janela(s); um intervalo de "
                                             "150/180 ciclos (~3 s) precisa de 15. Nenhuma série agregada."))
    return ResultadoBandasIEC(resultado, p, descartadas, tuple(avisos))


@dataclass(frozen=True)
class ParametrosHarmonicos:
    """A tabela dos harmônicos (``--fft --harmonicos N``): as ordens 1 a ``ordem_maxima`` num trecho recortado em
    ciclos inteiros da fundamental (``n_ciclos`` None: todos os ciclos completos do trecho)."""

    ordem_maxima: int = ORDEM_MAXIMA_IEC
    n_ciclos: int | None = None
    freq_min_fundamental: float = FREQ_MIN_FUNDAMENTAL
    freq_max_fundamental: float = FREQ_MAX_FUNDAMENTAL

    def validar(self, taxa_hz: float) -> None:
        _validar_taxa(taxa_hz)
        _validar_fundamental(self.freq_min_fundamental, self.freq_max_fundamental)
        if self.ordem_maxima < 1:
            raise ErroSHAN(f"a ordem máxima dos harmônicos precisa ser >= 1 (recebido {self.ordem_maxima}).")
        if self.n_ciclos is not None and self.n_ciclos < 1:
            raise ErroSHAN(f"o número de ciclos precisa ser >= 1 (recebido {self.n_ciclos}).")


@dataclass(frozen=True, eq=False)
class ResultadoHarmonicos:
    """A tabela (``harmonicos.TabelaHarmonicos``: cada ordem com a componente, o grupo, o subgrupo e a fase, e o THD,
    o THDG e o THDS) e o trecho de ciclos inteiros que a produziu, ``[inicio_local, fim_local)`` no sinal recebido."""

    tabela: TabelaHarmonicos
    parametros: ParametrosHarmonicos
    inicio_local: int
    fim_local: int
    avisos: tuple[Aviso, ...] = ()


def harmonicos(sinal, taxa_hz: float, parametros: ParametrosHarmonicos = ParametrosHarmonicos()) -> ResultadoHarmonicos:
    """Os harmônicos de ``sinal`` pela IEC 61000-4-7 (``harmonicos.calcular_harmonicos``), da janela retangular
    sincronizada pelos cruzamentos por zero: as contas do ``adc_tool --fft --harmonicos``. Levanta ``ErroSHAN`` se o
    trecho não tem a fundamental."""
    p = parametros
    p.validar(taxa_hz)
    with capturar_avisos() as avisos:
        trecho, inicio, fim, f0, n_ciclos = recortar_ciclos_inteiros(
            _sinal_float(sinal), taxa_hz, p.freq_min_fundamental, p.freq_max_fundamental, p.n_ciclos)
        tabela = calcular_harmonicos(trecho, taxa_hz, f0, n_ciclos, p.ordem_maxima)
    return ResultadoHarmonicos(tabela, p, inicio, fim, tuple(avisos))


# ---------------------------------------------------------------------------
# Os filtros e a sonda: a cadeia de transformações de um traço
# ---------------------------------------------------------------------------

TIPOS_DE_FILTRO = {"passa_baixas": "low", "passa_altas": "high", "passa_faixa": "bandpass", "rejeita_faixa": "bandstop"}
"""Os filtros Butterworth, pelo nome da interface, e o tipo do SciPy de cada um."""
ORDEM_MAXIMA_DO_FILTRO = 10


def validar_filtro(tipo: str, cortes, ordem: int, taxa_hz: float) -> tuple[float, ...]:
    """Confere um filtro para um sinal a ``taxa_hz`` e devolve os cortes como uma tupla: um (passa-baixas,
    passa-altas) ou dois, o inferior e o superior (passa-faixa, rejeita-faixa), entre 0 e a Nyquist. Levanta
    ``ErroSHAN`` com o motivo."""
    _validar_taxa(taxa_hz)
    if tipo not in TIPOS_DE_FILTRO:
        raise ErroSHAN(f"filtro desconhecido: {tipo!r} (use {', '.join(TIPOS_DE_FILTRO)}).")
    try:
        cortes = tuple(float(c) for c in np.atleast_1d(np.asarray(cortes, dtype=float)))
    except (TypeError, ValueError):
        raise ErroSHAN(f"cortes inválidos para o filtro: {cortes!r}.") from None
    esperados = 2 if tipo in ("passa_faixa", "rejeita_faixa") else 1
    if len(cortes) != esperados:
        raise ErroSHAN(f"o filtro {tipo.replace('_', '-')} tem {esperados} corte(s), não {len(cortes)}.")
    nyquist = taxa_hz / 2.0
    for corte in cortes:
        if not (math.isfinite(corte) and 0.0 < corte < nyquist):
            raise ErroSHAN(f"o corte de {corte:g} Hz precisa ficar entre 0 e a Nyquist do canal ({nyquist:g} Hz).")
    if esperados == 2 and not cortes[0] < cortes[1]:
        raise ErroSHAN(f"o corte inferior ({cortes[0]:g} Hz) precisa ser menor que o superior ({cortes[1]:g} Hz).")
    if not (isinstance(ordem, int) and not isinstance(ordem, bool) and 1 <= ordem <= ORDEM_MAXIMA_DO_FILTRO):
        raise ErroSHAN(f"a ordem do filtro precisa ser um inteiro de 1 a {ORDEM_MAXIMA_DO_FILTRO} (recebido {ordem!r}).")
    return cortes


def projetar_filtro(tipo: str, cortes, ordem: int, taxa_hz: float) -> np.ndarray:
    """O Butterworth em seções de 2ª ordem (a forma que o ``sosfilt`` do SciPy recebe), já validado."""
    cortes = validar_filtro(tipo, cortes, ordem, taxa_hz)
    return projetar_filtro_sos(taxa_hz, TIPOS_DE_FILTRO[tipo], cortes[0] if len(cortes) == 1 else cortes, ordem)


def filtrar(sinal, taxa_hz: float, tipo: str, cortes, ordem: int = ORDEM_FILTRO_PADRAO) -> np.ndarray:
    """``sinal`` filtrado pelo Butterworth de fase zero (``sosfiltfilt``), como o ``--filtro-passa-alta`` e o
    ``--filtro-passa-baixa`` do ``adc_tool`` (``filtros.aplicar_filtro_digital``) com ``--ordem-filtro``."""
    cortes = validar_filtro(tipo, cortes, ordem, taxa_hz)
    return aplicar_filtro_digital(_sinal_float(sinal), taxa_hz, TIPOS_DE_FILTRO[tipo],
                                  cortes[0] if len(cortes) == 1 else cortes, ordem)


def carregar_perfil(caminho: Path) -> PerfilSonda:
    """Um perfil de sonda (o ``.json`` do ``gerar_perfil_sonda``) escolhido pelo usuário. Levanta ``ErroSHAN`` para
    um arquivo que falta ou que não é um perfil."""
    return carregar_perfil_sonda(Path(caminho))


def margem_da_correcao_sonda(perfil: PerfilSonda, taxa_hz: float, tolerancia: float = 1e-9) -> int:
    """As amostras de cada lado que um trecho corrigido em pedaços precisa para que o miolo saia como a correção do
    sinal inteiro (``sonda.alcance_da_correcao``): ~16 000 a 200 kS/s para uma sonda de 1 polo em 30 kHz."""
    _validar_taxa(taxa_hz)
    return alcance_da_correcao(perfil, taxa_hz, tolerancia)
