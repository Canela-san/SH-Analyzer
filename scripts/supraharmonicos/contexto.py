"""Contexto de uma execução do ``adc_tool``: o que a captura É, resolvido uma vez.

Junta, na hierarquia explícito (CLI) > cabeçalho da captura > padrão
histórico (inclusive a faixa de entrada do ADC por canal, gravada no
cabeçalho v3), tudo o que os três modos (plotagem, conversão, exportação HDF5)
precisam saber sobre o arquivo de entrada: cabeçalho, canais, calibração por
canal, grandeza e sonda por canal.

Camada de aplicação: recebe o ``argparse.Namespace`` produzido por
``cli_adc_tool.montar_parser()`` (não importa o parser -- só lê os atributos).

Aqui também mora :func:`aplicar_correcao_sondas`: corrigir cada canal pelo perfil da sua sonda é aplicar o que o
contexto resolveu (grandeza, sonda, faixa e ganho de cada canal), e o ``adc_tool`` e o ``medir_captura`` a usam
igual -- sem que o segundo precise importar os modos do primeiro.

Depende de: ``cabecalho``, ``canais``, ``constantes``, ``erros``, ``sonda``.
"""

from __future__ import annotations

import argparse
import datetime
import logging
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .cabecalho import (
    CABECALHO_TAMANHO_TOTAL,
    CabecalhoArquivo,
    conferir_consistencia_cabecalho,
    contar_amostras_arquivo_bin,
    imprimir_resumo_cabecalho,
    ler_cabecalho,
)
from .canais import (
    analisar_lista_calibracao,
    analisar_lista_canais,
    resolver_faixas,
    resolver_offsets_por_canal,
    validar_subconjunto_canais,
)
from .constantes import CANAL_PADRAO, GRANDEZA_CORRENTE, GRANDEZA_NAO_USADA, GRANDEZA_PADRAO, GRANDEZA_TEMPERATURA
from .erros import ErroSHAN
from .sonda import (
    SONDAS_DIR_PADRAO,
    analisar_overrides_grandeza,
    analisar_overrides_perfil,
    aplicar_correcao_sonda,
    conferir_calibracao_perfil,
    conferir_idade_perfil,
    resolver_perfil_canal,
)

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ContextoCaptura:
    """Resultado de :func:`resolver_contexto` -- imutável, sem I/O além do que
    já foi feito para resolvê-lo."""

    caminho_entrada: Path | None
    cabecalho: CabecalhoArquivo | None
    offset_amostras: int                 # bytes a pular antes das amostras (0 sem cabeçalho)
    canais: list[int]                    # ordem do ciclo round-robin do arquivo
    canais_veio_do_cabecalho: bool
    canais_exibir: list[int]             # subconjunto de 'canais' (padrão: todos)
    faixas: list[float]                  # um por canal de 'canais', mesma ordem
    ganhos: list[float]
    offsets: list[float]
    faixas_confiaveis: list[bool]        # faixas[i] coincide com a faixa REAL do ADC gravada no cabeçalho v3
    overrides_grandeza: dict[int, int]   # --grandeza (canal -> código)
    overrides_perfil: dict[int, Path]    # --sonda-perfil (canal -> arquivo)
    sondas_dir: Path

    @property
    def num_canais(self) -> int:
        return len(self.canais)

    def indice_no_ciclo(self, canal: int) -> int:
        """Posição do canal no ciclo round-robin (= índice nas listas por canal)."""
        return self.canais.index(canal)

    def grandeza_do_canal(self, canal: int) -> int:
        """--grandeza explícito > cabeçalho v2 > padrão histórico (tensão)."""
        if canal in self.overrides_grandeza:
            return self.overrides_grandeza[canal]
        if self.cabecalho is not None and self.cabecalho.versao_cabecalho >= 2:
            idx = self.indice_no_ciclo(canal)
            if idx < len(self.cabecalho.grandeza_por_canal):
                g = self.cabecalho.grandeza_por_canal[idx]
                if g != GRANDEZA_NAO_USADA:
                    return g
        return GRANDEZA_PADRAO

    def sonda_id_do_canal(self, canal: int) -> str:
        """Id de sonda gravado no cabeçalho v2 ('' se não há)."""
        if self.cabecalho is not None and self.cabecalho.versao_cabecalho >= 2:
            idx = self.indice_no_ciclo(canal)
            if idx < len(self.cabecalho.sonda_id_por_canal):
                return self.cabecalho.sonda_id_por_canal[idx]
        return ""


def resolver_contexto(args: argparse.Namespace) -> ContextoCaptura:
    """Detecta o cabeçalho e resolve canais/calibração/grandeza/sonda.

    A detecção do cabeçalho vem ANTES de resolver --canais/-f, que podem cair
    de volta nos metadados dele quando não informados. O arquivo de ENTRADA
    muda conforme o modo: -c/--converter usa seu próprio caminho; plotagem e
    --export-hdf5 usam o posicional 'arquivo'. Só um '.bin' pode ter o
    cabeçalho -- um '.csv' nunca tem.

    Levanta ErroSHAN para qualquer flag/arquivo inválido."""
    caminho_entrada = args.converter if args.converter is not None else args.arquivo

    cabecalho: CabecalhoArquivo | None = None
    offset_amostras = 0
    if caminho_entrada is not None and caminho_entrada.suffix.lower() == ".bin" and caminho_entrada.exists():
        cabecalho = ler_cabecalho(caminho_entrada)
        if cabecalho is not None:
            offset_amostras = CABECALHO_TAMANHO_TOTAL

    # --canais: explícito (CLI) > cabeçalho da captura > padrão histórico.
    if args.canais is not None:
        canais = analisar_lista_canais(args.canais, "--canais")
        canais_veio_do_cabecalho = False
    elif cabecalho is not None:
        canais = _canais_do_cabecalho(cabecalho)
        canais_veio_do_cabecalho = True
    else:
        canais = analisar_lista_canais(CANAL_PADRAO, "--canais")
        canais_veio_do_cabecalho = False

    if args.canais_exibir is not None:
        canais_exibir = analisar_lista_canais(args.canais_exibir, "--canais-exibir")
        validar_subconjunto_canais(canais_exibir, canais)
    else:
        canais_exibir = canais

    # --faixa: digitada > faixa de entrada do ADC gravada no cabeçalho v3 > 20.48
    # (a de reset do ADC, para capturas v1/v2). O cabeçalho é indexado pela
    # POSIÇÃO no ciclo (mesma regra de grandeza_do_canal), então só vale se a
    # contagem de canais bate -- se não bater, conferir_consistencia_cabecalho
    # aborta mais adiante com a explicação.
    faixas_cabecalho = None
    if cabecalho is not None and len(cabecalho.lista_canais) == len(canais):
        faixas_cabecalho = cabecalho.faixa_adc_total_v_por_canal
    faixas, faixas_confiaveis = resolver_faixas(args.faixa, canais, args.formato, faixas_cabecalho)
    ganhos = analisar_lista_calibracao(args.ganho, len(canais), "--ganho")
    offsets = resolver_offsets_por_canal(args.offset, faixas, args.formato, len(canais))

    # --grandeza/--sonda-perfil: mesma hierarquia de 3 níveis, mas resolvida
    # por CANAL (não por posição), porque nem todo canal aparece nas flags.
    overrides_grandeza = analisar_overrides_grandeza(args.grandeza) if args.grandeza is not None else {}
    overrides_perfil = analisar_overrides_perfil(args.sonda_perfil) if args.sonda_perfil is not None else {}
    # Um canal que não está na captura era IGNORADO: '--sonda-perfil 5:...' numa captura dos canais 1 e 2 (erro
    # de digitação) saía sem correção nenhuma e sem aviso -- o resultado errado em silêncio.
    for flag, overrides in (("--grandeza", overrides_grandeza), ("--sonda-perfil", overrides_perfil)):
        fora = sorted(set(overrides) - set(canais))
        if fora:
            raise ErroSHAN(f"{flag}: canal {', '.join(map(str, fora))} não está na captura (canais: "
                           f"{', '.join(map(str, canais))}). Confira o número do canal.")
    sondas_dir = args.sondas_dir if args.sondas_dir is not None else SONDAS_DIR_PADRAO

    return ContextoCaptura(
        caminho_entrada=caminho_entrada,
        cabecalho=cabecalho,
        offset_amostras=offset_amostras,
        canais=canais,
        canais_veio_do_cabecalho=canais_veio_do_cabecalho,
        canais_exibir=canais_exibir,
        faixas=faixas,
        ganhos=ganhos,
        offsets=offsets,
        faixas_confiaveis=faixas_confiaveis,
        overrides_grandeza=overrides_grandeza,
        overrides_perfil=overrides_perfil,
        sondas_dir=sondas_dir,
    )


def _canais_do_cabecalho(cabecalho: CabecalhoArquivo) -> list[int]:
    """Lista de canais do cabeçalho, com as MESMAS regras de --canais (0-7, sem repetição, 1 a 8): um
    cabeçalho corrompido (0 canais, 0xFF...) viraria uma divisão por zero ou um canal inexistente lá na
    frente, em vez de uma mensagem."""
    try:
        return analisar_lista_canais(",".join(str(c) for c in cabecalho.lista_canais), "cabeçalho da captura")
    except ErroSHAN as e:
        crc = "" if cabecalho.crc32_valido else " O CRC-32 do cabeçalho também não confere: o arquivo deve estar corrompido."
        raise ErroSHAN(f"a lista de canais do cabeçalho é inválida ({e}){crc} Informe --canais (e -f) explicitamente.") from e


def anunciar_cabecalho(ctx: ContextoCaptura, formato: str) -> None:
    """Resumo do cabeçalho + conferência contra o arquivo (só se há cabeçalho)."""
    if ctx.cabecalho is None:
        return
    imprimir_resumo_cabecalho(ctx.cabecalho)
    n_amostras_arquivo = contar_amostras_arquivo_bin(ctx.caminho_entrada, formato, ctx.offset_amostras)
    conferir_consistencia_cabecalho(
        ctx.cabecalho, ctx.canais, ctx.canais_veio_do_cabecalho, n_amostras_arquivo, formato
    )


def aplicar_correcao_sondas(args: argparse.Namespace, ctx: ContextoCaptura,
                            por_canal_tensao: dict[int, np.ndarray],
                            fs_efetiva: float) -> dict[int, int]:
    """Correção dependente de frequência, canal a canal (modifica 'por_canal_tensao').

    Aplicada ANTES do filtro Butterworth opcional do usuário e de qualquer
    análise espectral, para que --fft/--welch/--picos/plot já operem sobre o
    sinal corrigido (ver sonda.aplicar_correcao_sonda). Devolve a grandeza de
    cada canal exibido (o gráfico usa para rotular os eixos)."""
    grandeza_por_canal_exibir = {canal: ctx.grandeza_do_canal(canal) for canal in ctx.canais_exibir}
    for canal in ctx.canais_exibir:
        grandeza = grandeza_por_canal_exibir[canal]
        sonda_id = ctx.sonda_id_do_canal(canal)
        # Uma sonda REGISTRADA (id no cabeçalho ou --sonda-perfil) vale para
        # qualquer grandeza de frequência (corrente, e também tensão -- ex.:
        # divisor/ponta com banda limitada). Corrente SEM sonda só avisa.
        sonda_registrada = bool(sonda_id) or canal in ctx.overrides_perfil
        if grandeza == GRANDEZA_TEMPERATURA:
            if sonda_registrada:
                log.warning(
                    f"canal {canal} é de temperatura -- a sonda "
                    f"registrada ('{sonda_id or ctx.overrides_perfil[canal]}') "
                    f"não é aplicada (correção por frequência não se aplica "
                    f"a temperatura; perfis 'polinomio'/'tabela' ainda não "
                    f"existem)."
                )
            continue
        if grandeza != GRANDEZA_CORRENTE and not sonda_registrada:
            continue
        prefixo = f"  Canal {canal}: " if ctx.num_canais > 1 else "  "
        if args.sem_correcao_sonda:
            log.info(f"{prefixo}--sem-correcao-sonda ativo -- usando só --ganho escalar (sem correção por frequência).")
            continue
        perfil = resolver_perfil_canal(canal, sonda_id, ctx.overrides_perfil, ctx.sondas_dir)
        if perfil is None:
            log.warning(
                f"canal {canal} é de corrente mas não tem sonda/perfil resolvido -- "
                f"usando só --ganho escalar (sem correção por frequência). "
                f"Registre a sonda na captura (--sonda em ler_adc) ou use "
                f"--sonda-perfil {canal}:ARQUIVO."
            )
            continue
        idx_canal = ctx.indice_no_ciclo(canal)
        conferir_calibracao_perfil(perfil, canal, args.formato, ctx.faixas[idx_canal], ctx.ganhos[idx_canal],
                                   faixa_confiavel=ctx.faixas_confiaveis[idx_canal])
        conferir_idade_perfil(perfil, canal, _data_da_captura(ctx))
        por_canal_tensao[canal] = aplicar_correcao_sonda(por_canal_tensao[canal], fs_efetiva, perfil)
        log.info(f"{prefixo}correção de sonda aplicada (perfil '{perfil.id}', {perfil.caminho})")
    return grandeza_por_canal_exibir


def _data_da_captura(ctx: ContextoCaptura) -> datetime.date | None:
    """Data (UTC) gravada no cabeçalho, para medir a idade do perfil de sonda na hora da captura (S8)."""
    if ctx.cabecalho is None or ctx.cabecalho.timestamp_unix <= 0:
        return None
    return datetime.datetime.fromtimestamp(ctx.cabecalho.timestamp_unix, datetime.timezone.utc).date()
