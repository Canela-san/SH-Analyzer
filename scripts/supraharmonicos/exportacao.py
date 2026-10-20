"""Exportação dos resultados da análise (``--exportar`` e ``--exportar-mat``).

Tudo o que a análise calcula sai em arquivos que outra ferramenta lê sem conhecer este programa, com os parâmetros
que o produziram -- o que um trabalho científico precisa para ser reproduzido:

* ``--exportar PREFIXO``: um CSV por resultado e por canal (``PREFIXO_canal1_welch.csv``, ``..._harmonicos.csv``,
  ``..._bandas_iec.csv``...), os picos de todos os canais em ``PREFIXO_picos.csv`` e os metadados em
  ``PREFIXO_metadados.json`` (arquivo e cabeçalho da captura, calibração de cada canal, janela, resolução, ENBW,
  filtros, correção de sonda, versões e o comando exato);
* ``--exportar-mat ARQUIVO.mat``: os mesmos dados numa estrutura ``sh`` do MATLAB/Octave (``sh.canal1.welch.f``,
  ``sh.metadados``...), lida por ``load``.

A estrutura de entrada (``resultados``) é montada por ``modos``: ``{"canais": {canal: {...}}, "picos": [...]}``,
com, por canal, as chaves que a análise pediu: ``fft``/``welch`` (``f``, ``db``), ``fft_bandas``/``welch_bandas``
(``f``, ``db``), ``harmonicos`` (:class:`TabelaHarmonicos`), ``bandas_iec`` (:class:`BandasIEC`) e
``espectrograma`` (``t``, ``f``, ``db``), além de ``unidade`` e ``modo``.

Depende de: ``erros``, ``harmonicos``, ``bandas_iec``. O SciPy só é carregado por ``--exportar-mat``."""

import csv
import dataclasses
import json
import math
from pathlib import Path

import numpy as np

from .bandas_iec import BandasIEC
from .erros import ErroSHAN
from .harmonicos import TabelaHarmonicos


def _num(v) -> str:
    if v is None:
        return ""
    v = float(v)
    return "" if math.isnan(v) else f"{v:.10g}"


def _colunas_nivel(modo: str, unidade: str, bandas: bool) -> tuple[str, str, object]:
    """(cabeçalho em dB, cabeçalho linear, conversão dB -> linear) conforme a normalização do espectro."""
    if bandas:
        return f"nivel_db{unidade}", f"rms_{unidade}", lambda db: 10 ** (db / 20.0)
    if modo == "ruido":
        return f"psd_db_{unidade}2_por_hz", f"psd_{unidade}2_por_hz", lambda db: 10 ** (db / 10.0)
    return f"amplitude_db{unidade}", f"amplitude_pico_{unidade}", lambda db: 10 ** (db / 20.0)


def _escrever_csv(caminho: Path, cabecalho: list[str], linhas) -> Path:
    with open(caminho, "w", newline="", encoding="utf-8") as f:
        escritor = csv.writer(f)
        escritor.writerow(cabecalho)
        escritor.writerows(linhas)
    return caminho


def exportar_csv(prefixo: Path, resultados: dict, metadados: dict) -> list[Path]:
    """Escreve os CSVs e o JSON de metadados com o prefixo dado; devolve os arquivos escritos."""
    prefixo = Path(prefixo)
    if prefixo.is_dir():
        raise ErroSHAN(f"--exportar '{prefixo}' é uma pasta: dê um prefixo de nome (ex.: {prefixo / 'analise'}).")
    prefixo.parent.mkdir(parents=True, exist_ok=True)
    escritos: list[Path] = []
    for canal, r in resultados["canais"].items():
        base = f"{prefixo}_canal{canal}"
        unidade, modo = r["unidade"], r["modo"]
        for chave in ("fft", "welch", "fft_bandas", "welch_bandas"):
            if chave not in r:
                continue
            bandas = chave.endswith("_bandas")
            col_db, col_lin, linear = _colunas_nivel(modo, unidade, bandas)
            f, db = r[chave]["f"], r[chave]["db"]
            escritos.append(_escrever_csv(Path(f"{base}_{chave}.csv"),
                                          ["centro_hz" if bandas else "frequencia_hz", col_db, col_lin],
                                          ((_num(a), _num(b), _num(linear(b))) for a, b in zip(f, db))))
        tabela: TabelaHarmonicos | None = r.get("harmonicos")
        if tabela is not None:
            escritos.append(_escrever_csv(
                Path(f"{base}_harmonicos.csv"),
                ["ordem", "frequencia_hz", f"rms_{unidade}", f"rms_grupo_{unidade}", "pct_fundamental", "fase_graus"],
                ((h.ordem, _num(h.frequencia_hz), _num(h.rms), _num(h.rms_grupo), _num(h.pct_fundamental),
                  _num(h.fase_graus)) for h in tabela.harmonicos)))
        iec: BandasIEC | None = r.get("bandas_iec")
        if iec is not None:
            est = iec.estatisticas()
            escritos.append(_escrever_csv(
                Path(f"{base}_bandas_iec.csv"),
                ["centro_hz", f"rms_{unidade}", f"maximo_{unidade}", f"p95_{unidade}", f"minimo_{unidade}"],
                ((_num(c), _num(est["rms"][i]), _num(est["maximo"][i]), _num(est["p95"][i]), _num(est["minimo"][i]))
                 for i, c in enumerate(iec.centros_hz))))
            escritos.append(_escrever_csv(
                Path(f"{base}_bandas_iec_serie.csv"),
                ["inicio_janela_s", *(f"banda_{c:g}hz_{unidade}" for c in iec.centros_hz)],
                ((_num(t), *(_num(v) for v in linha)) for t, linha in zip(iec.tempos_s, iec.niveis))))
        esp = r.get("espectrograma")
        if esp is not None:
            escritos.append(_escrever_csv(
                Path(f"{base}_espectrograma.csv"),
                ["tempo_s \\ frequencia_hz", *(_num(f) for f in esp["f"])],
                ((_num(t), *(_num(v) for v in linha)) for t, linha in zip(esp["t"], esp["db"]))))
    if resultados.get("picos"):
        escritos.append(_escrever_csv(
            Path(f"{prefixo}_picos.csv"), ["canal", "metodo", "frequencia_hz", "amplitude_db"],
            ((p["canal"], p["metodo"], _num(p["frequencia_hz"]), _num(p["amplitude_db"])) for p in resultados["picos"])))
    caminho_json = Path(f"{prefixo}_metadados.json")
    caminho_json.write_text(json.dumps(_para_json(metadados), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    escritos.append(caminho_json)
    return escritos


def _para_json(valor):
    """Converte numpy, dataclasses, Path e NaN em tipos que o JSON aceita."""
    if dataclasses.is_dataclass(valor) and not isinstance(valor, type):
        return _para_json(dataclasses.asdict(valor))
    if isinstance(valor, dict):
        return {str(k): _para_json(v) for k, v in valor.items()}
    if isinstance(valor, (list, tuple)):
        return [_para_json(v) for v in valor]
    if isinstance(valor, np.ndarray):
        return _para_json(valor.tolist())
    if isinstance(valor, (np.integer,)):
        return int(valor)
    if isinstance(valor, (float, np.floating)):
        return None if math.isnan(valor) or math.isinf(valor) else float(valor)
    if isinstance(valor, Path):
        return str(valor)
    return valor


def _para_mat(valor):
    """Converte para o que o ``scipy.io.savemat`` grava como struct/matriz/cell (None vira matriz vazia)."""
    if valor is None:
        return np.array([])
    if isinstance(valor, TabelaHarmonicos):
        h = valor.harmonicos
        return {"f0_hz": valor.f0_hz, "n_ciclos": valor.n_ciclos, "thd_pct": valor.thd_pct, "thdg_pct": valor.thdg_pct,
                "rms_total": valor.rms_total, "ordem": np.array([x.ordem for x in h], dtype=float),
                "f": np.array([x.frequencia_hz for x in h]), "rms": np.array([x.rms for x in h]),
                "rms_grupo": np.array([x.rms_grupo for x in h]), "pct_fundamental": np.array([x.pct_fundamental for x in h]),
                "fase_graus": np.array([x.fase_graus for x in h])}
    if isinstance(valor, BandasIEC):
        est = valor.estatisticas()
        return {"centros_hz": valor.centros_hz, "tempos_s": valor.tempos_s, "niveis": valor.niveis,
                "largura_hz": valor.largura_hz, "duracao_janela_s": valor.duracao_janela_s, **est}
    if isinstance(valor, dict):
        return {(f"canal{k}" if isinstance(k, int) else str(k)): _para_mat(v) for k, v in valor.items()}
    if isinstance(valor, (list, tuple)):
        if valor and all(isinstance(v, dict) for v in valor):
            return np.array([_para_mat(v) for v in valor], dtype=object)
        return np.array([_para_mat(v) for v in valor], dtype=object) if valor else np.array([])
    if isinstance(valor, Path):
        return str(valor)
    if isinstance(valor, bool):
        return int(valor)
    return valor


def exportar_mat(caminho: Path, resultados: dict, metadados: dict) -> Path:
    """Grava ``sh`` (resultados por canal + ``picos`` + ``metadados``) num ``.mat`` (formato 5, lido pelo MATLAB e Octave)."""
    from scipy.io import savemat  # sob demanda: só --exportar-mat paga o SciPy
    caminho = Path(caminho)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    estrutura = _para_mat({**{f"canal{c}": r for c, r in resultados["canais"].items()},
                           "picos": resultados.get("picos", []), "metadados": _para_json(metadados)})
    savemat(caminho, {"sh": estrutura}, long_field_names=True, do_compression=True)
    return caminho
