"""Modo de exportação HDF5 (``.bin`` -> ``.h5``), sempre em blocos sobre o memmap, e a leitura de volta
(:func:`ler_hdf5`: as amostras brutas e a calibração com que foram exportadas, para a ``api`` abrir o ``.h5``).

``h5py`` é importado só quando a exportação (ou a leitura) é de fato usada
(dependência pesada para os demais modos).

Além das amostras, o arquivo leva tudo o que é preciso para usá-las sem o ``.bin`` nem este programa: os campos do
cabeçalho como atributos, o próprio cabeçalho, byte a byte (``/cabecalho_bruto``: 1024 bytes até a v8, 4096 na v9) e o perfil de cada sonda
registrada (``/sondas/canalN``: o JSON integral, os pontos e o hash do arquivo). Nada disso mexe nos datasets
de amostras: cada coisa é um atributo ou um dataset à parte.

Depende de: ``amostras``, ``canais``, ``cabecalho``, ``constantes``, ``erros``, ``sonda``."""

import hashlib
import logging
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .amostras import carregar_amostras_bin, converter_para_tensao, selecionar_intervalo
from .cabecalho import CabecalhoArquivo
from .canais import alinhar_ao_ciclo
from .constantes import FORMATOS_NUMPY, TAMANHO_CHUNK_PADRAO
from .erros import ErroSHAN
from .sonda import PerfilSonda

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 4.1 Modo de exportação HDF5
# ---------------------------------------------------------------------------

def exportar_hdf5(caminho_bin: Path, caminho_h5: Path, formato: str,
                   canais: list[int], cabecalho: CabecalhoArquivo | None,
                   faixas: list[float], ganhos: list[float], offsets: list[float],
                   incluir_tensao: bool, offset_amostras: int,
                   inicio: int, fim: int | None,
                   tamanho_chunk: int = TAMANHO_CHUNK_PADRAO,
                   grandeza_por_canal: list[int] | None = None,
                   sonda_id_por_canal: list[str] | None = None,
                   versao_codigo: str | None = None,
                   perfis_por_canal: dict[int, PerfilSonda] | None = None) -> tuple[int, int]:
    """Converte 'caminho_bin' para HDF5 em 'caminho_h5'.

    'grandeza_por_canal'/'sonda_id_por_canal' (opcionais, na mesma ordem de
    'canais'), quando informados, são gravados como atributos na raiz --
    mesmos valores já resolvidos pelo chamador (CLI > cabeçalho > padrão,
    ver grandeza_do_canal()/sonda_id_do_canal() em main()). NÃO alteram os
    dados exportados em si: a correção de sonda dependente de frequência
    (aplicar_correcao_sonda(), seção 2.1) não é aplicada aqui -- só no modo
    de plotagem. /tensao_v continua sendo a calibração --faixa/--ganho/
    --offset pura, sem correção de sonda, para qualquer canal. Ver
    docs/probe-correction-design.md, seção 6.3, para essa decisão de
    escopo (aplicar a correção também aqui exigiria repetir, em streaming
    por blocos, a mesma divisão espectral que hoje opera sobre o sinal
    inteiro de uma vez -- deixado como trabalho futuro).

    REGRA CRÍTICA DE MEMÓRIA: a gravação percorre o memmap em blocos de até
    'tamanho_chunk' amostras BRUTAS por vez -- em nenhum momento o array
    completo é materializado na RAM. Com SAMPLES_PER_BUFFER=1.048.576
    amostras por bloco de captura e --duracao/--blocos 0 permitindo captura
    indefinida do lado do firmware, um '.bin' de uma sessão de bancada longa
    pode facilmente passar de dezenas de GB -- carregar tudo de uma vez não
    é viável nem no notebook mais robusto. A fatia [inicio:fim] do memmap a
    cada iteração só toca as páginas do SO correspondentes àquele bloco
    (mesmo princípio de bin_para_csv, mais acima); np.asarray sobre essa
    fatia já limitada não força a leitura do arquivo inteiro.

    Layout do '.h5' resultante:
      /amostras   dataset 2D (n_amostras_por_canal, num_canais), dtype igual
                  a --formato (uint16/int16) -- RAW, sem calibração (mesma
                  filosofia "round-trip sem perdas" da conversão .bin<->.csv
                  existente). Coluna i = canal canais[i] (ver atributo
                  'canais_ordem' na raiz).
      /tensao_v   [só se incluir_tensao=True] dataset 2D igual, dtype
                  float32, já calibrado em Volts (mesmo cálculo de
                  converter_para_tensao usado no resto do script).
      attrs (raiz) metadados do cabeçalho da captura (se disponível, via
                  CabecalhoArquivo.para_attrs_hdf5, com a taxa que a PRU
                  gera em 'frequencia_pru_hz') + parâmetros de calibração
                  usados (faixa/ganho/offset por canal) + proveniência
                  (arquivo de origem, --formato, trecho exportado, versão
                  do código) + 'correcao_sonda_aplicada_por_canal' (sempre
                  0: quem abre o .h5 fora do adc_tool sabe que /tensao_v
                  NÃO foi corrigida pelo perfil da sonda).
      /cabecalho_bruto  [só com cabeçalho] os bytes (1024 até a v8, 4096 na v9) do cabeçalho do
                  .bin, como gravados (relê-se com a mesma especificação,
                  inclusive campos que esta versão não conheça).
      /sondas/canalN  [um grupo por canal com perfil resolvido, ver
                  'perfis_por_canal'] o JSON integral do perfil (atributo
                  'perfil_json'), os pontos (datasets freq_hz e ganho), o
                  SHA-256 do arquivo e como aplicar a correção.

    Retorna (n_amostras_por_canal_exportadas, num_canais).
    """
    try:
        import h5py
    except ImportError:
        raise ErroSHAN(
            "--export-hdf5 precisa da biblioteca 'h5py', que não está "
            "instalada neste Python. Instale com 'pip install h5py' (ou "
            "'pip install h5py --break-system-packages' conforme o seu "
            "ambiente), ou rode este script via 'uv run adc_tool.py ...' -- "
            "h5py já está declarado nas dependências inline (PEP 723) no "
            "topo do arquivo e seria instalado automaticamente nesse caso."
        )

    dtype = FORMATOS_NUMPY[formato]
    num_canais = len(canais)

    amostras = carregar_amostras_bin(caminho_bin, formato, offset=offset_amostras)
    # A coluna i do dataset é o canal canais[i]: o recorte precisa começar no início de um ciclo.
    _, inicio, fim, _total = selecionar_intervalo(amostras, alinhar_ao_ciclo(inicio, num_canais), fim)
    n_disponivel = fim - inicio

    n_linhas_total = n_disponivel // num_canais
    n_truncado = n_linhas_total * num_canais
    if n_truncado < n_disponivel:
        log.warning(
            f"{n_disponivel - n_truncado} amostra(s) no final do "
            f"recorte não completam um ciclo de {num_canais} canais e foram "
            f"descartadas na exportação HDF5."
        )
    if n_linhas_total == 0:
        raise ErroSHAN(
            f"nenhuma linha completa de {num_canais} canais disponível "
            f"para exportar ({n_disponivel} amostra(s) brutas na janela "
            f"selecionada)."
        )

    with h5py.File(caminho_h5, "w") as f5:
        # ---- attrs na raiz: cabeçalho + calibração + proveniência -------
        if cabecalho is not None:
            for chave, valor in cabecalho.para_attrs_hdf5().items():
                f5.attrs[chave] = valor
            if cabecalho.frequencia_pru_hz is not None:
                f5.attrs["frequencia_pru_hz"] = cabecalho.frequencia_pru_hz
        f5.attrs["arquivo_origem"] = caminho_bin.name
        f5.attrs["trecho_inicio_amostra_bruta"] = inicio
        f5.attrs["trecho_fim_amostra_bruta"] = inicio + n_truncado
        if versao_codigo:
            f5.attrs["versao_codigo"] = versao_codigo
        f5.attrs["correcao_sonda_aplicada_por_canal"] = np.zeros(num_canais, dtype=np.uint8)
        f5.attrs["offset_amostras_bytes"] = offset_amostras
        f5.attrs["formato_amostra"] = formato
        f5.attrs["canais_ordem"] = np.array(canais, dtype=np.uint8)
        f5.attrs["faixa_v_por_canal"] = np.array(faixas, dtype=np.float64)
        f5.attrs["ganho_por_canal"] = np.array(ganhos, dtype=np.float64)
        f5.attrs["offset_v_por_canal"] = np.array(offsets, dtype=np.float64)
        if grandeza_por_canal is not None:
            f5.attrs["grandeza_por_canal"] = np.array(grandeza_por_canal, dtype=np.uint8)
        if sonda_id_por_canal is not None:
            f5.attrs["sonda_id_por_canal"] = np.array(sonda_id_por_canal, dtype="S32")

        if cabecalho is not None and offset_amostras > 0:
            with open(caminho_bin, "rb") as f:
                bruto_cabecalho = np.frombuffer(f.read(offset_amostras), dtype=np.uint8)
            dataset_cabecalho = f5.create_dataset("cabecalho_bruto", data=bruto_cabecalho)
            dataset_cabecalho.attrs["descricao"] = (
                "Os bytes do cabeçalho do .bin de origem, como gravados pelo ler_adc (little-endian, "
                "formato em docs/project-context.md, versão no atributo 'cabecalho_versao')."
            )
        for canal, perfil in sorted((perfis_por_canal or {}).items()):
            _gravar_perfil(f5, canal, perfil)

        dataset_bruto = f5.create_dataset(
            "amostras", shape=(n_linhas_total, num_canais), dtype=dtype, chunks=True,
        )
        dataset_bruto.attrs["descricao"] = (
            "Amostras brutas (códigos do ADC, sem calibração). Linha = 1 "
            "instante de amostragem; coluna i = canal canais_ordem[i] (ver "
            "atributo na raiz)."
        )

        dataset_tensao = None
        if incluir_tensao:
            dataset_tensao = f5.create_dataset(
                "tensao_v", shape=(n_linhas_total, num_canais), dtype=np.float32, chunks=True,
            )
            dataset_tensao.attrs["descricao"] = (
                "Amostras calibradas em Volts (faixa/ganho/offset por canal "
                "-- ver atributos 'faixa_v_por_canal'/'ganho_por_canal'/"
                "'offset_v_por_canal' na raiz). float32. SEM correção de "
                "sonda por frequência (ver 'correcao_sonda_aplicada_por_canal' "
                "e 'sonda_id_por_canal' na raiz)."
            )
            dataset_tensao.attrs["correcao_sonda"] = "nenhuma"

        # Tamanho de bloco em LINHAS (amostras/canal) derivado do tamanho de
        # bloco em amostras BRUTAS (mesma unidade de --tamanho-chunk usada
        # em bin_para_csv, por consistência) -- garante que cada bloco lido
        # do memmap seja um múltiplo exato de num_canais, então nunca corta
        # uma "linha" ao meio entre duas iterações.
        linhas_por_bloco = max(1, tamanho_chunk // num_canais)
        amostras_por_bloco = linhas_por_bloco * num_canais

        linha_atual = 0
        for ini_bloco in range(inicio, inicio + n_truncado, amostras_por_bloco):
            fim_bloco = min(ini_bloco + amostras_por_bloco, inicio + n_truncado)

            # Único ponto por iteração onde um pedaço do memmap "materializa"
            # de verdade -- a fatia [ini_bloco:fim_bloco] só toca as páginas
            # do SO correspondentes A ESTE BLOCO; np.asarray sobre uma fatia
            # já delimitada não lê o arquivo inteiro (mesmo padrão já usado
            # em bin_para_csv, seção 4 acima).
            bloco_bruto = np.asarray(amostras[ini_bloco:fim_bloco])
            assert len(bloco_bruto) % num_canais == 0, (
                "bloco não fechado em um múltiplo de num_canais -- bug na "
                "lógica de particionamento em blocos (linhas_por_bloco)"
            )
            n_linhas_bloco = len(bloco_bruto) // num_canais
            matriz_bloco = bloco_bruto.reshape(n_linhas_bloco, num_canais)

            dataset_bruto[linha_atual: linha_atual + n_linhas_bloco, :] = matriz_bloco

            if incluir_tensao:
                tensao_bloco = np.empty((n_linhas_bloco, num_canais), dtype=np.float32)
                for i in range(num_canais):
                    tensao_bloco[:, i] = converter_para_tensao(
                        matriz_bloco[:, i], faixas[i], ganhos[i], formato, offsets[i]
                    )
                dataset_tensao[linha_atual: linha_atual + n_linhas_bloco, :] = tensao_bloco

            linha_atual += n_linhas_bloco

        assert linha_atual == n_linhas_total, (
            "número de linhas escritas não bate com n_linhas_total -- bug na "
            "lógica de particionamento em blocos"
        )

    return n_linhas_total, num_canais


def _gravar_perfil(f5, canal: int, perfil: PerfilSonda) -> None:
    """``/sondas/canalN``: o perfil inteiro, para quem abre o .h5 em outra ferramenta poder aplicar (ou auditar) a
    correção sem procurar o arquivo de sonda. Não aplicado a /tensao_v (atributo 'aplicado_em_tensao_v' = 0)."""
    grupo = f5.require_group("sondas").create_group(f"canal{canal}")
    grupo.attrs["id"] = perfil.id
    grupo.attrs["tipo"] = perfil.tipo
    grupo.attrs["arquivo_origem"] = str(perfil.caminho)
    grupo.attrs["aplicado_em_tensao_v"] = 0
    if perfil.data_calibracao is not None:
        grupo.attrs["data_calibracao"] = perfil.data_calibracao.isoformat()
    if perfil.texto_json is not None:
        grupo.attrs["perfil_json"] = perfil.texto_json
        grupo.attrs["sha256"] = hashlib.sha256(perfil.texto_json.encode("utf-8")).hexdigest()
    freqs, ganhos = perfil.pontos
    if perfil.tipo == "resposta_frequencia":
        grupo.create_dataset("freq_hz", data=freqs)
        grupo.create_dataset("ganho", data=ganhos)
        if perfil.faixa_freq_valida_hz is not None:
            grupo.attrs["faixa_freq_valida_hz"] = np.array(perfil.faixa_freq_valida_hz, dtype=np.float64)
        grupo.attrs["como_aplicar"] = (
            "FFT do sinal inteiro em Volts; cada componente de frequência f dividida por ganho(f); IFFT. "
            "ganho(f): PCHIP sobre (log10(freq_hz), 20*log10(ganho)), constante fora de [min, max] de freq_hz. "
            "Corrige só a amplitude, não a fase."
        )
    else:
        grupo.attrs["ganho"] = float(ganhos[0])
        grupo.attrs["como_aplicar"] = "sinal em Volts dividido por 'ganho'."


# ---------------------------------------------------------------------------
# 4.2 Leitura de um .h5 exportado
# ---------------------------------------------------------------------------

LIMITE_DO_HDF5_EM_MEMORIA = 2 << 30
"""Bytes de amostras que :func:`ler_hdf5` aceita: o ``/amostras`` é em blocos (``chunks``), sem um mapa direto no
arquivo como o memmap do ``.bin``, e vai inteiro para a memória. Um maior pede o ``.bin`` de origem."""

_ATRIBUTOS_DA_EXPORTACAO = ("canais_ordem", "formato_amostra", "faixa_v_por_canal", "ganho_por_canal",
                            "offset_v_por_canal")


@dataclass(frozen=True)
class ConteudoHdf5:
    """O que um ``.h5`` de :func:`exportar_hdf5` traz para usar as amostras de novo, como foi gravado: as listas por
    canal vão na ordem de ``canais`` (a da intercalação)."""

    amostras: np.ndarray           # (n_linhas * n_canais,): intercaladas como no .bin, em memória
    formato: str
    canais: list[int]
    faixas: list[float]            # o --faixa, o --ganho e o --offset com que as amostras foram exportadas
    ganhos: list[float]
    offsets: list[float]
    grandezas: list[int] | None    # as resolvidas na exportação (None num .h5 que não as grava)
    cabecalho_bruto: bytes | None  # o cabeçalho do .bin de origem, byte a byte (None num exportado de um legado)
    arquivo_origem: str
    trecho: tuple[int, int]        # [início, fim) em amostras brutas do .bin de origem
    versao_codigo: str | None
    taxa_total_hz: float | None = None   # a taxa gravada (os dados importados, importacao.gravar_como_captura)
    importado_de: str | None = None      # a origem dos dados importados (osciloscópio, WAV, COMTRADE...)


def ler_cabecalho_bruto(caminho: Path) -> bytes | None:
    """Só o ``/cabecalho_bruto`` de um ``.h5`` do ``--export-hdf5`` (None se ele não tem), sem ler as amostras."""
    import h5py

    with h5py.File(caminho, "r") as f5:
        dados = f5.get("cabecalho_bruto")
        return None if dados is None else bytes(np.asarray(dados[:], dtype=np.uint8))


def ler_hdf5(caminho: Path, *, limite_bytes: int = LIMITE_DO_HDF5_EM_MEMORIA) -> ConteudoHdf5:
    """Lê um ``.h5`` do ``adc_tool --export-hdf5``: o ``/amostras`` (os códigos do ADC, sem calibração) para a
    memória, os atributos da exportação e o ``/cabecalho_bruto``. Não usa o ``/tensao_v`` (float32, e sem a correção
    de sonda): a conversão para a unidade física é refeita dos códigos, como a do ``.bin``. Levanta :class:`ErroSHAN`
    para um arquivo que não é dessa exportação, ou com mais de ``limite_bytes`` de amostras."""
    import h5py

    try:
        with h5py.File(caminho, "r") as f5:
            dataset = f5.get("amostras")
            faltam = [nome for nome in _ATRIBUTOS_DA_EXPORTACAO if nome not in f5.attrs]
            if not isinstance(dataset, h5py.Dataset) or dataset.ndim != 2 or faltam:
                falta = ", ".join((["/amostras"] if not isinstance(dataset, h5py.Dataset) or dataset.ndim != 2
                                   else []) + faltam)
                raise ErroSHAN(f"'{caminho}' não é um .h5 do adc_tool --export-hdf5 (falta: {falta}).")
            attrs = f5.attrs
            formato = str(attrs["formato_amostra"])
            if formato not in FORMATOS_NUMPY or dataset.dtype != FORMATOS_NUMPY[formato]:
                raise ErroSHAN(f"'{caminho}': as amostras são {dataset.dtype}, e o formato gravado é {formato!r}.")
            canais = [int(c) for c in np.atleast_1d(attrs["canais_ordem"])]
            por_canal = {nome: [float(v) for v in np.atleast_1d(attrs[nome])]
                         for nome in ("faixa_v_por_canal", "ganho_por_canal", "offset_v_por_canal")}
            n_linhas, n_colunas = dataset.shape
            if len(canais) != n_colunas or any(len(v) != n_colunas for v in por_canal.values()):
                raise ErroSHAN(f"'{caminho}': {n_colunas} coluna(s) em /amostras, mas {len(canais)} canal(is) em "
                               f"'canais_ordem'.")
            if n_linhas == 0:
                raise ErroSHAN(f"'{caminho}' não tem amostras.")
            if dataset.size * dataset.dtype.itemsize > limite_bytes:
                raise ErroSHAN(f"'{caminho}': {dataset.size * dataset.dtype.itemsize / 1e9:.1f} GB de amostras, mais "
                               f"do que cabe abrir na memória ({limite_bytes / 1e9:.1f} GB). Abra o .bin de origem "
                               f"('{attrs.get('arquivo_origem', '?')}').")
            grandezas = attrs.get("grandeza_por_canal")
            bruto = f5.get("cabecalho_bruto")
            inicio = int(attrs.get("trecho_inicio_amostra_bruta", 0))
            return ConteudoHdf5(
                amostras=np.asarray(dataset[()], dtype=FORMATOS_NUMPY[formato]).reshape(-1),
                formato=formato,
                canais=canais,
                faixas=por_canal["faixa_v_por_canal"],
                ganhos=por_canal["ganho_por_canal"],
                offsets=por_canal["offset_v_por_canal"],
                grandezas=None if grandezas is None else [int(g) for g in np.atleast_1d(grandezas)],
                cabecalho_bruto=None if bruto is None else np.asarray(bruto[()], dtype=np.uint8).tobytes(),
                arquivo_origem=str(attrs.get("arquivo_origem", "")),
                trecho=(inicio, int(attrs.get("trecho_fim_amostra_bruta", inicio + n_linhas * n_colunas))),
                versao_codigo=str(attrs["versao_codigo"]) if "versao_codigo" in attrs else None,
                taxa_total_hz=float(attrs["taxa_total_hz"]) if "taxa_total_hz" in attrs else None,
                importado_de=str(attrs["importado_de"]) if "importado_de" in attrs else None,
            )
    except FileNotFoundError:
        raise ErroSHAN(f"arquivo '{caminho}' não encontrado.") from None
    except OSError as e:
        raise ErroSHAN(f"'{caminho}' não é um HDF5 legível ({e}).") from None


def gravar_amostras_importadas(destino: Path, codigos: np.ndarray, *, faixas, offsets, grandezas,
                               taxa_total_hz: float, nomes, origem: str, versao_codigo: str = "") -> Path:
    """O ``.h5`` dos dados de fora (``importacao.gravar_como_captura``): os ``codigos`` ``int16`` (uma coluna por
    canal) no leiaute do ``--export-hdf5``, com a calibração de cada canal (ganho 1), a taxa total e a origem nos
    atributos (:func:`ler_hdf5` os devolve em ``taxa_total_hz`` e ``importado_de``). Gravado inteiro ou nada (um
    ``.parcial`` renomeado no fim)."""
    import h5py

    destino = Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)
    k = codigos.shape[1]
    temporario = destino.with_name(destino.name + ".parcial")
    with h5py.File(temporario, "w") as f5:
        f5.create_dataset("amostras", data=np.asarray(codigos, dtype="<i2"), chunks=True)
        a = f5.attrs
        a["formato_amostra"] = "int16"
        a["canais_ordem"] = np.arange(k, dtype=np.int64)
        a["faixa_v_por_canal"] = np.asarray(faixas, dtype=np.float64)
        a["ganho_por_canal"] = np.ones(k)
        a["offset_v_por_canal"] = np.asarray(offsets, dtype=np.float64)
        a["grandeza_por_canal"] = np.asarray(grandezas, dtype=np.int64)
        a["taxa_total_hz"] = float(taxa_total_hz)
        a["nomes_dos_canais"] = list(nomes)
        a["importado_de"] = origem
        a["arquivo_origem"] = origem
        a["trecho_inicio_amostra_bruta"] = 0
        a["trecho_fim_amostra_bruta"] = int(codigos.size)
        if versao_codigo:
            a["versao_codigo"] = versao_codigo
    temporario.replace(destino)
    return destino
