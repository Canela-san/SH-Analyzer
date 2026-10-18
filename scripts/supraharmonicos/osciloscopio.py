"""Forma de onda de um osciloscópio (``.m`` do MATLAB, ``.mat``, ``.csv``) e medida da senoide nela.

O osciloscópio é a referência independente do projeto: amostra a gigasamples por
segundo e mede a MESMA senoide que o ADC mede, então o que ele diz da amplitude e da
frequência vale para checar (e para construir) o perfil da sonda. Este módulo faz duas
coisas:

* :func:`ler_forma_de_onda` -- lê o arquivo que o osciloscópio salvou e devolve os
  valores e a taxa de amostragem. Não há um formato único de ``.m``/``.csv`` entre
  fabricantes, então o leitor é TOLERANTE: acha as variáveis numéricas do arquivo
  (``Y = [ ... ];``, ``t = [...]``, matriz ``[t v]``, números soltos depois de comentários
  ``%``), escolhe a forma de onda mais provável e deduz a taxa de amostragem de um vetor
  de tempo ou de escalares comuns (``Tinterval``, ``dt``, ``Fs``, ``XIncrement``...). Se
  não tiver certeza, para com uma mensagem que LISTA o que achou, e ``variavel``,
  ``variavel_tempo`` e ``fs`` resolvem na hora.
* :func:`medir_senoide` -- ajuste por mínimos quadrados de uma senoide (amplitude,
  frequência, fase e nível DC): o método de referência para medir um tom em metrologia
  (IEEE 1057), sem vazamento espectral e sem exigir um número inteiro de ciclos.

Vale tanto para um registro curto quanto para milhões de pontos: o ajuste usa só uma
fração das amostras (decimação por passo, sem filtro: o ruído branco do osciloscópio
não gera viés no tom) e a frequência é refinada por busca unidimensional.

Depende de: ``erros`` (e ``scipy.optimize`` / ``scipy.io``).
"""

import logging
import math
import re
import warnings
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from scipy.optimize import minimize_scalar

from .erros import ErroSHAN

log = logging.getLogger(__name__)

EXTENSOES_OSCILOSCOPIO = (".m", ".mat", ".csv", ".txt")
MIN_AMOSTRAS = 64                    # abaixo disso não é uma forma de onda
MAX_COLUNAS_MATRIZ = 8               # matriz mais larga que tempo + 4 canais é um vetor quebrado em linhas: vira vetor
MAX_AMOSTRAS_LEITURA = 1 << 24       # ~16 M amostras: o resto do registro não muda a medida e custaria só memória
MAX_AMOSTRAS_FFT = 1 << 23
MAX_AMOSTRAS_AJUSTE = 1 << 20        # pontos usados no ajuste de mínimos quadrados (registros maiores são decimados por passo)
CICLOS_MINIMOS = 3.0                 # com menos ciclos a frequência vem pouco confiável sem uma dica

NOMES_TEMPO = {"t", "time", "tempo", "x", "xdata", "xvalues", "tvec", "timevector", "timevec", "tempos", "horizontal"}
NOMES_PASSO = {"tinterval", "dt", "ts", "xincrement", "xinc", "sampleinterval", "deltat", "tstep", "timestep",
               "horizontalinterval", "samplingperiod", "sampleperiod", "tincrement"}
NOMES_TAXA = {"fs", "fsample", "samplerate", "samplingrate", "samplingfrequency", "samplefrequency", "srate",
              "samplefreq", "samplingfreq", "sampfreq", "sa", "sarate", "taxa", "taxaamostragem"}
NOMES_PREFERIDOS = ["y", "ch1", "channel1", "c1", "canal1", "volts", "voltage", "v", "signal", "data", "dados",
                    "wave", "waveform", "forma", "valores"]


def _normalizar(nome: str) -> str:
    return re.sub(r"[^a-z0-9]", "", nome.lower())


@dataclass
class FormaDeOnda:
    """Valores (na unidade salva pelo osciloscópio, já multiplicados por ``escala``) e taxa de amostragem."""
    valores: np.ndarray
    fs: float
    origem: str            # texto humano: 'variável "Y" de x.m (1 canal)'
    n_total: int           # amostras do registro (``valores`` pode ter só as primeiras MAX_AMOSTRAS_LEITURA)

    @property
    def duracao_s(self) -> float:
        return self.n_total / self.fs


# ---------------------------------------------------------------------------
# Leitura de cada formato -> {nome: array}
# ---------------------------------------------------------------------------

_RE_ATRIBUICAO = re.compile(r"(?:^|(?<=;))[ \t]*([A-Za-z_]\w*)(?:\([^)\n]*\))?[ \t]*=(?!=)[ \t]*", re.MULTILINE)
_RE_INICIO_MATRIZ = re.compile(r"(?:(?:single|double|int\d+|uint\d+)\s*\()?\s*\[")
_RE_ENVOLTORIO = re.compile(r"^(?:single|double|int\d+|uint\d+)\s*\(\s*(.*?)\s*\)$", re.DOTALL)
_RE_LINHA_NUMERICA = re.compile(r"^[\s\d.eE+\-,;:]+$")


def _numeros(texto: str) -> np.ndarray:
    """Todos os números de um trecho (separados por espaço, vírgula, ';' ou quebra de linha); lixo é ignorado."""
    limpo = texto.replace(",", " ").replace(";", " ")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            return np.fromstring(limpo, dtype=np.float64, sep=" ")
    except (ValueError, DeprecationWarning):
        valores = []
        for token in limpo.split():
            try:
                valores.append(float(token))
            except ValueError:
                continue
        return np.array(valores, dtype=np.float64)


def _como_matriz(bloco: str) -> np.ndarray:
    """Conteúdo de um ``[ ... ]`` do MATLAB como vetor ou matriz (linhas separadas por ';' ou quebra de linha)."""
    corpo = bloco.strip()
    primeira = re.split(r"[;\n]", corpo, maxsplit=1)[0]
    colunas = len(primeira.replace(",", " ").split()) or 1
    valores = _numeros(corpo)
    if colunas > 1 and valores.size % colunas == 0 and valores.size // colunas > 1:
        return valores.reshape(-1, colunas)
    return valores


def _escalar_matlab(expressao: str) -> float | None:
    """``1e-9``, ``single(1e-9)``... -> número; ``None`` se a expressão não é só um número."""
    expressao = expressao.strip()
    envolto = _RE_ENVOLTORIO.match(expressao)
    for candidato in ([envolto.group(1)] if envolto else []) + [expressao]:
        try:
            return float(candidato)
        except ValueError:
            continue
    return None


def ler_m(texto: str) -> dict[str, np.ndarray]:
    """Variáveis numéricas de um script MATLAB (``.m``): escalares e ``nome = [ ... ];`` (vetor ou matriz).
    Comentários (``%``) e continuações (``...``) são descartados; números soltos fora de atribuições,
    em linhas só de números, viram a variável ``dados`` (formato "cabeçalho comentado + colunas")."""
    texto = re.sub(r"%[^\n]*", "", texto)
    texto = re.sub(r"\.\.\.[^\n]*\n", " ", texto)
    variaveis: dict[str, np.ndarray] = {}
    trechos_soltos: list[str] = []
    pos = 0
    while (achado := _RE_ATRIBUICAO.search(texto, pos)) is not None:
        trechos_soltos.append(texto[pos:achado.start()])
        inicio = achado.end()
        matriz = _RE_INICIO_MATRIZ.match(texto, inicio)
        if matriz is not None:
            fecha = texto.find("]", matriz.end())
            if fecha < 0:
                pos = len(texto)
                break
            variaveis[achado.group(1)] = _como_matriz(texto[matriz.end():fecha])
            pos = fecha + 1
        else:
            fim = len(texto)
            for separador in (";", "\n"):
                k = texto.find(separador, inicio)
                if k >= 0:
                    fim = min(fim, k)
            valor = _escalar_matlab(texto[inicio:fim])
            if valor is not None:
                variaveis[achado.group(1)] = np.array([valor])
            pos = fim
    trechos_soltos.append(texto[pos:])
    linhas = [ln for ln in "\n".join(trechos_soltos).splitlines() if ln.strip() and _RE_LINHA_NUMERICA.match(ln)]
    if len(linhas) >= MIN_AMOSTRAS:
        variaveis.setdefault("dados", _como_matriz("\n".join(linhas)))
    return variaveis


def ler_mat(caminho: Path) -> dict[str, np.ndarray]:
    """Variáveis numéricas de um ``.mat`` (MATLAB v5/v7, via scipy). O v7.3 (HDF5) não é aberto aqui."""
    from scipy.io import loadmat
    try:
        bruto = loadmat(str(caminho), squeeze_me=True)
    except NotImplementedError:
        raise ErroSHAN(
            f"'{caminho.name}' é um .mat v7.3 (HDF5), que este leitor não abre: salve o arquivo como .m ou .csv, "
            f"ou como .mat versão 7 (save -v7 no MATLAB)."
        ) from None
    except Exception as e:
        raise ErroSHAN(f"não consegui ler '{caminho.name}' como .mat: {e}") from e
    return {k: np.atleast_1d(np.asarray(v)) for k, v in bruto.items()
            if not k.startswith("__") and isinstance(v, (np.ndarray, int, float, np.number))
            and np.asarray(v).dtype.kind in "fiu"}


def ler_csv(texto: str) -> dict[str, np.ndarray]:
    """Colunas numéricas de um CSV/TXT de osciloscópio: o bloco de linhas todas numéricas vira ``coluna0``,
    ``coluna1``... (ou os nomes do cabeçalho, se baterem em número); linhas ``rótulo,número`` antes dos
    dados (``Sample Interval,4e-09``) viram escalares."""
    linhas = [ln.strip() for ln in texto.splitlines() if ln.strip()]
    if not linhas:
        return {}
    separador = next((s for s in (";", "\t", ",") if s in linhas[len(linhas) // 2]), None)

    def campos(linha: str) -> list[str]:
        partes = linha.split(separador) if separador else linha.split()
        return [p.strip() for p in partes if p.strip() != "" or separador is None]

    def numeros(linha: str) -> list[float] | None:
        try:
            return [float(c.replace(",", ".") if separador == ";" else c) for c in campos(linha)]
        except ValueError:
            return None

    variaveis: dict[str, np.ndarray] = {}
    cabecalho: list[str] = []
    bloco: list[list[float]] = []
    for linha in linhas:
        valores = numeros(linha)
        if valores:
            bloco.append(valores)
            continue
        if bloco:
            break                                       # terminou o bloco de dados
        partes = campos(linha)
        cabecalho = partes
        if len(partes) == 2:
            try:
                variaveis[partes[0]] = np.array([float(partes[1])])
            except ValueError:
                pass
    if bloco:
        largura = len(bloco[0])
        bloco = [b for b in bloco if len(b) == largura]
        matriz = np.array(bloco, dtype=np.float64)
        nomes = cabecalho if len(cabecalho) == largura and len(set(cabecalho)) == largura else [f"coluna{i}" for i in range(largura)]
        for i, nome in enumerate(nomes):
            variaveis[nome] = matriz[:, i]
    return variaveis


def ler_variaveis(caminho: Path) -> dict[str, np.ndarray]:
    """Dicionário ``{nome: array}`` das variáveis numéricas do arquivo, pela extensão."""
    if not caminho.is_file():
        raise ErroSHAN(f"arquivo do osciloscópio '{caminho}' não encontrado.")
    sufixo = caminho.suffix.lower()
    if sufixo == ".mat":
        return ler_mat(caminho)
    texto = caminho.read_text(encoding="utf-8-sig", errors="replace")
    if sufixo == ".m":
        return ler_m(texto)
    if sufixo in (".csv", ".txt"):
        return ler_csv(texto)
    raise ErroSHAN(f"'{caminho.name}': formato não suportado (use {', '.join(EXTENSOES_OSCILOSCOPIO)}).")


# ---------------------------------------------------------------------------
# Escolha da forma de onda e da taxa de amostragem
# ---------------------------------------------------------------------------

def _crescente_uniforme(v: np.ndarray) -> bool:
    d = np.diff(v[: min(len(v), 100_000)])
    return len(d) > 2 and bool(np.all(d > 0)) and float(np.std(d) / np.mean(d)) < 1e-3


def _descrever(variaveis: dict[str, np.ndarray]) -> str:
    itens = []
    for nome, v in variaveis.items():
        forma = "x".join(str(d) for d in v.shape) if v.size > 1 else f"{float(v.ravel()[0]):g}"
        itens.append(f"{nome} ({forma})")
    return ", ".join(itens) if itens else "nenhuma variável numérica"


def _candidatos(variaveis: dict[str, np.ndarray]) -> list[tuple[str, int | None, np.ndarray, np.ndarray | None]]:
    """(nome, coluna, valores, tempo_da_matriz) de cada possível forma de onda."""
    achados = []
    for nome, v in variaveis.items():
        if v.size < MIN_AMOSTRAS:
            continue
        if v.ndim == 1 or min(v.shape) == 1:
            achados.append((nome, None, v.ravel(), None))
            continue
        if v.ndim == 2 and v.shape[0] < v.shape[1]:
            v = v.T
        if v.ndim != 2 or v.shape[1] > MAX_COLUNAS_MATRIZ:
            achados.append((nome, None, v.ravel(), None))
            continue
        tempo = v[:, 0] if _crescente_uniforme(v[:, 0]) else None
        for c in range(1 if tempo is not None else 0, v.shape[1]):
            achados.append((nome, c, v[:, c], tempo))
    return achados


def _procurar(variaveis: dict[str, np.ndarray], nome: str, o_que: str) -> str:
    if nome in variaveis:
        return nome
    por_norma = {_normalizar(k): k for k in variaveis}
    if _normalizar(nome) in por_norma:
        return por_norma[_normalizar(nome)]
    raise ErroSHAN(f"não achei a variável '{nome}' ({o_que}) no arquivo. Variáveis: {_descrever(variaveis)}.")


def _escalar(variaveis: dict[str, np.ndarray], nomes: set[str]) -> tuple[str, float] | None:
    for nome, v in variaveis.items():
        if v.size == 1 and _normalizar(nome) in nomes and math.isfinite(float(v.ravel()[0])) and float(v.ravel()[0]) > 0:
            return nome, float(v.ravel()[0])
    return None


def montar_forma_de_onda(variaveis: dict[str, np.ndarray], origem: str, variavel: str | None = None,
                         variavel_tempo: str | None = None, fs: float | None = None, escala: float = 1.0) -> FormaDeOnda:
    """Escolhe a forma de onda e a taxa de amostragem entre as ``variaveis`` lidas (ver o docstring do módulo).
    ``variavel`` pode ser ``nome`` ou ``nome:coluna`` (coluna a partir de 0, para matrizes com vários canais)."""
    tempo: np.ndarray | None = None
    if variavel:
        nome, _, coluna = variavel.partition(":")
        nome = _procurar(variaveis, nome.strip(), "forma de onda")
        v = variaveis[nome]
        if coluna.strip():
            if v.ndim != 2:
                raise ErroSHAN(f"'{nome}' não é uma matriz; tire o ':{coluna.strip()}'.")
            matriz = v.T if v.shape[0] < v.shape[1] else v
            c = int(coluna)
            if not 0 <= c < matriz.shape[1]:
                raise ErroSHAN(f"'{nome}' tem {matriz.shape[1]} colunas; a coluna {c} não existe (a primeira é 0).")
            valores, rotulo = matriz[:, c], f'variável "{nome}" coluna {c}'
            tempo = matriz[:, 0] if c != 0 and _crescente_uniforme(matriz[:, 0]) else None
        else:
            candidatos = _candidatos({nome: v})
            if not candidatos:
                raise ErroSHAN(f"'{nome}' tem só {v.size} ponto(s); uma forma de onda precisa de pelo menos {MIN_AMOSTRAS}.")
            if len(candidatos) != 1:
                raise ErroSHAN(f"'{nome}' tem vários canais; escolha um com '{nome}:COLUNA' (a primeira coluna é 0). "
                               f"Variáveis: {_descrever({nome: v})}.")
            _, _, valores, tempo = candidatos[0]
            rotulo = f'variável "{nome}"'
    else:
        candidatos = _candidatos(variaveis)
        if not candidatos:
            raise ErroSHAN(f"não achei nenhuma forma de onda (vetor com ao menos {MIN_AMOSTRAS} pontos) no arquivo. "
                           f"Variáveis: {_descrever(variaveis)}. Se os dados estão em contagens ou numa variável "
                           f"com outro formato, me mande as primeiras linhas do arquivo.")
        if len(candidatos) > 1:
            sem_tempo = [c for c in candidatos if _normalizar(c[0]) not in NOMES_TEMPO]
            candidatos = sem_tempo or candidatos
        if len(candidatos) > 1:
            preferidos = [c for c in candidatos if _normalizar(c[0]) in NOMES_PREFERIDOS]
            if len(preferidos) == 1:
                candidatos = preferidos
        if len(candidatos) > 1:
            lista = ", ".join(f"{n}" + (f":{c}" if c is not None else "") + f" ({len(v)} pts)" for n, c, v, _ in candidatos)
            raise ErroSHAN(f"há mais de uma forma de onda no arquivo ({lista}); escolha uma com --osc-var NOME "
                           f"(ou NOME:COLUNA para matrizes).")
        nome, coluna, valores, tempo = candidatos[0]
        rotulo = f'variável "{nome}"' + (f" coluna {coluna}" if coluna is not None else "")

    if variavel_tempo:
        tempo = variaveis[_procurar(variaveis, variavel_tempo, "tempo")].ravel()
    elif tempo is None:
        iguais = [v.ravel() for k, v in variaveis.items()
                  if _normalizar(k) in NOMES_TEMPO and v.size == len(valores) and _crescente_uniforme(v.ravel())]
        tempo = iguais[0] if iguais else None

    taxa, de_onde = fs, "--osc-fs"
    if taxa is None and tempo is not None and len(tempo) == len(valores) and len(tempo) > 2:
        passo = (tempo[-1] - tempo[0]) / (len(tempo) - 1)
        if passo > 0:
            taxa, de_onde = 1.0 / passo, "vetor de tempo"
            if float(np.std(np.diff(tempo[:100_000])) / passo) > 1e-3:
                log.warning("o vetor de tempo do osciloscópio não é uniforme; usando o passo médio.")
    if taxa is None and (achado := _escalar(variaveis, NOMES_TAXA)):
        taxa, de_onde = achado[1], f'"{achado[0]}"'
    if taxa is None and (achado := _escalar(variaveis, NOMES_PASSO)):
        taxa, de_onde = 1.0 / achado[1], f'1/"{achado[0]}"'
    if taxa is None or not math.isfinite(taxa) or taxa <= 0:
        raise ErroSHAN(f"não achei a taxa de amostragem do osciloscópio no arquivo (variáveis: {_descrever(variaveis)}). "
                       f"Informe com --osc-fs HZ (= 1/intervalo entre amostras).")
    valores = np.asarray(valores, dtype=np.float64) * escala
    n_total = len(valores)
    if not np.all(np.isfinite(valores[:MAX_AMOSTRAS_LEITURA])):
        raise ErroSHAN(f"{origem}: a forma de onda tem NaN/Inf.")
    return FormaDeOnda(valores[:MAX_AMOSTRAS_LEITURA], float(taxa),
                       f"{rotulo} de {origem}, {n_total} pts a {taxa:.6g} Hz (taxa: {de_onde})", n_total)


def ler_forma_de_onda(caminho: Path, variavel: str | None = None, variavel_tempo: str | None = None,
                      fs: float | None = None, escala: float = 1.0) -> FormaDeOnda:
    """Lê o arquivo do osciloscópio e devolve a forma de onda (valores * ``escala``) com a taxa de amostragem."""
    return montar_forma_de_onda(ler_variaveis(caminho), caminho.name, variavel, variavel_tempo, fs, escala)


def localizar_arquivo_osciloscopio(captura: Path, pasta: Path | None = None) -> Path | None:
    """Arquivo do osciloscópio "irmão" de uma captura: mesmo nome, extensão ``.m``/``.mat``/``.csv``/``.txt``,
    na pasta da captura (ou em ``pasta``). ``None`` se não existe."""
    base = pasta if pasta is not None else captura.parent
    for extensao in EXTENSOES_OSCILOSCOPIO:
        candidato = base / (captura.stem + extensao)
        if candidato.is_file():
            return candidato
    return None


# ---------------------------------------------------------------------------
# Medida da senoide: mínimos quadrados com busca de frequência
# ---------------------------------------------------------------------------

@dataclass
class TomMedido:
    freq_hz: float
    amplitude_pico: float
    offset: float
    residuo_rms: float       # o que sobra depois de tirar a senoide (ruído + distorção + quantização)
    n_amostras: int          # amostras do registro analisado
    ciclos: float            # ciclos do tom no registro

    @property
    def amplitude_pico_a_pico(self) -> float:
        return 2.0 * self.amplitude_pico

    @property
    def amplitude_rms(self) -> float:
        return self.amplitude_pico / math.sqrt(2.0)


def _frequencia_inicial(y: np.ndarray, fs: float, freq_dica: float | None) -> float:
    """Pico da FFT (janela de Hann + interpolação parabólica), restrito a ±50 % da dica se houver."""
    n = min(len(y), MAX_AMOSTRAS_FFT)
    janela = np.hanning(n)
    espectro = np.abs(np.fft.rfft((y[:n] - np.mean(y[:n])) * janela))
    freqs = np.fft.rfftfreq(n, 1.0 / fs)
    valido = freqs > 3.0 * fs / n
    if freq_dica is not None:
        valido &= (freqs > 0.5 * freq_dica) & (freqs < 1.5 * freq_dica)
    if not np.any(valido):
        raise ErroSHAN("registro curto demais para achar a frequência; informe a frequência aproximada.")
    k = int(np.argmax(np.where(valido, espectro, 0.0)))
    delta = 0.0
    if 0 < k < len(espectro) - 1 and min(espectro[k - 1], espectro[k], espectro[k + 1]) > 0:
        a, b, c = np.log(espectro[k - 1: k + 2])
        denominador = a - 2 * b + c
        delta = 0.5 * (a - c) / denominador if denominador != 0 else 0.0
    return float((k + max(-0.5, min(0.5, delta))) * fs / n)


def _ajuste_linear(y: np.ndarray, t: np.ndarray, w: float) -> tuple[float, float, float, float]:
    """(a, b, c, soma dos quadrados dos resíduos) do modelo a*cos(wt) + b*sin(wt) + c a frequência fixa ``w``."""
    cs, sn = np.cos(w * t), np.sin(w * t)
    n = len(y)
    m = np.array([[cs @ cs, cs @ sn, cs.sum()], [cs @ sn, sn @ sn, sn.sum()], [cs.sum(), sn.sum(), float(n)]])
    r = np.array([cs @ y, sn @ y, y.sum()])
    try:
        a, b, c = np.linalg.solve(m, r)
    except np.linalg.LinAlgError:
        return 0.0, 0.0, float(np.mean(y)), float(np.sum((y - np.mean(y)) ** 2))
    residuo = y - (a * cs + b * sn + c)
    return float(a), float(b), float(c), float(residuo @ residuo)


def medir_senoide(valores: np.ndarray, fs: float, freq_dica: float | None = None) -> TomMedido:
    """Amplitude (pico), frequência e nível DC da senoide dominante em ``valores`` (amostrados a ``fs`` Hz).

    A frequência inicial vem do pico da FFT (ou de ``freq_dica``, que também restringe a busca a ±50 %); o
    ajuste então varre a frequência numa faixa de ±1 bin em torno dela, resolvendo amplitude, fase e DC por
    mínimos quadrados lineares a cada passo (projeção de variável). Com menos de ~3 ciclos no registro a
    frequência só é confiável com uma dica próxima: o aviso diz isso."""
    y = np.asarray(valores, dtype=np.float64)
    if len(y) < MIN_AMOSTRAS:
        raise ErroSHAN(f"forma de onda com só {len(y)} amostras; preciso de pelo menos {MIN_AMOSTRAS}.")
    if not math.isfinite(fs) or fs <= 0:
        raise ErroSHAN("taxa de amostragem inválida.")
    y = y[:MAX_AMOSTRAS_FFT]
    ciclos_dica = len(y) / fs * freq_dica if freq_dica is not None else None
    if ciclos_dica is not None and ciclos_dica < CICLOS_MINIMOS:
        f0 = freq_dica                                   # sem ciclos para a FFT achar o pico: confia na dica
    else:
        f0 = _frequencia_inicial(y, fs, freq_dica)
    ciclos = len(y) / fs * f0
    if ciclos < 1.0:
        raise ErroSHAN(f"o registro do osciloscópio tem menos de 1 ciclo do tom ({ciclos:.2f}); grave um trecho mais longo.")
    if ciclos < CICLOS_MINIMOS:
        log.warning(f"só {ciclos:.1f} ciclo(s) no registro do osciloscópio; a amplitude é boa, mas a "
                    f"frequência fica pouco confiável (grave um trecho mais longo).")
    passo = max(1, math.ceil(len(y) / MAX_AMOSTRAS_AJUSTE))   # só decima se o registro passa do limite
    while abs(f0 * passo / fs - round(f0 * passo / fs)) < 1e-3 and passo > 1:
        passo += 1                                               # passo síncrono com o tom: todas as amostras na mesma fase
    amostras = len(y) // passo
    indices = np.arange(amostras) * passo
    ys = y[indices]
    t = (indices - indices.mean()) / fs                     # centrado: desacopla fase e frequência
    duracao = amostras * passo / fs
    largura = 1.0 / duracao                                 # ±1 bin da duração analisada
    resultado = minimize_scalar(lambda f: _ajuste_linear(ys, t, 2 * math.pi * f)[3],
                                bounds=(max(f0 - largura, 1e-9), min(f0 + largura, fs / 2.0)),
                                method="bounded", options={"xatol": 1e-6 * largura})
    freq = float(resultado.x)
    a, b, c, soma = _ajuste_linear(ys, t, 2 * math.pi * freq)
    return TomMedido(freq_hz=freq, amplitude_pico=math.hypot(a, b), offset=c,
                     residuo_rms=math.sqrt(soma / len(ys)), n_amostras=len(y), ciclos=len(y) / fs * freq)


# ---------------------------------------------------------------------------
# Flags compartilhadas pelas linhas de comando
# ---------------------------------------------------------------------------

def adicionar_argumentos_osciloscopio(grupo) -> None:
    """Acrescenta ao grupo de argumentos ``--osc-*`` (os mesmos em ``medir_captura`` e ``gerar_perfil_sonda``)."""
    grupo.add_argument("--osc-var", type=str, default=None, metavar="NOME[:COL]",
                       help="Variável do arquivo do osciloscópio com a forma de onda (ou NOME:COLUNA para matrizes com "
                            "vários canais; a primeira coluna é 0). Padrão: detectada.")
    grupo.add_argument("--osc-tempo", type=str, default=None, metavar="NOME",
                       help="Variável com o vetor de tempo (padrão: detectada; serve para deduzir a taxa de amostragem).")
    grupo.add_argument("--osc-fs", type=float, default=None, metavar="HZ",
                       help="Taxa de amostragem do osciloscópio, se o arquivo não a traz (= 1/intervalo entre amostras).")
    grupo.add_argument("--osc-escala", type=float, default=1.0, metavar="FATOR",
                       help="Multiplica os valores do osciloscópio (ex.: 10 para uma ponta 10x não compensada no "
                            "instrumento; padrão 1).")
    grupo.add_argument("--osc-unidade", choices=["V", "A"], default="V",
                       help="Unidade dos valores do osciloscópio depois de --osc-escala: 'V' (padrão) é a tensão no ponto "
                            "onde o --ganho do canal é aplicado (a grandeza física é V * ganho); 'A' já é a grandeza "
                            "física do canal (ex.: tensão no shunt dividida pela resistência, via --osc-escala).")


def ler_forma_de_onda_dos_args(caminho: Path, args) -> FormaDeOnda:
    """:func:`ler_forma_de_onda` com as opções ``--osc-*`` de ``args``."""
    if args.osc_escala <= 0 or not math.isfinite(args.osc_escala):
        raise ErroSHAN("--osc-escala precisa ser positivo.")
    if args.osc_fs is not None and args.osc_fs <= 0:
        raise ErroSHAN("--osc-fs precisa ser positivo.")
    return ler_forma_de_onda(caminho, args.osc_var, args.osc_tempo, args.osc_fs, args.osc_escala)
