"""Contexto de uma execução do ``adc_tool``: o que a captura É, resolvido uma vez.

Junta, na hierarquia explícito (CLI) > cabeçalho da captura > padrão
histórico (inclusive a faixa de entrada do ADC por canal, gravada no
cabeçalho v3), tudo o que os três modos (plotagem, conversão, exportação HDF5)
precisam saber sobre o arquivo de entrada: cabeçalho, canais, calibração por
canal, grandeza e sonda por canal.

Camada de aplicação: recebe o ``argparse.Namespace`` produzido por
``cli_adc_tool.montar_parser()`` (não importa o parser -- só lê os atributos).

Depende de: ``cabecalho``, ``canais``, ``constantes``, ``erros``, ``sonda``.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

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
from .constantes import CANAL_PADRAO, GRANDEZA_NAO_USADA, GRANDEZA_PADRAO
from .erros import ErroSHAN
from .sonda import (
    SONDAS_DIR_PADRAO,
    analisar_overrides_grandeza,
    analisar_overrides_perfil,
)


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
