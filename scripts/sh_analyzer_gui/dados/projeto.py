"""O arquivo de projeto ``.shproj`` (docs/gui-plan.md, 7.3): JSON legível e versionado, com as receitas e nunca os
resultados.

* **O formato:** ``{"formato": "sh-analyzer-projeto", "versao": 1, ...}``. Uma versão nova lê as antigas; um arquivo
  de uma versão mais nova que esta é recusado com a mensagem de atualizar o aplicativo (nunca aberto pela metade).
* **As fontes** vão pelo caminho relativo à pasta do projeto (a pasta inteira pode mudar de lugar), pelo absoluto (o
  projeto pode mudar sem os dados) e pela identidade das amostras: o CRC do cabeçalho v9 e o tamanho. Se os dois
  caminhos falham, :func:`localizar_fonte` procura pelo CRC (PD-06).
* **A gravação é atômica** (um temporário na mesma pasta, renomeado no fim): uma queda no meio não estraga o projeto.
* **O salvamento automático** vai para um arquivo ao lado, ``projeto.shproj~``; ao salvar, ele some. Ao abrir, um
  automático mais novo que o principal é o sinal de uma queda, e o aplicativo pergunta se quer recuperá-lo.

Sem Qt. A tradução entre isto e o modelo observável fica em ``modelo/persistencia.py``.
"""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

from .receita import ReceitaDoTraco, ReceitaInvalida

FORMATO = "sh-analyzer-projeto"
VERSAO = 1
EXTENSAO = ".shproj"
SUFIXO_AUTOMATICO = "~"
TIPOS_DE_VISTA = ("tempo",)
"""Os tipos de vista que esta versão abre (o espectro e os outros entram nas próximas)."""
LIMITE_DA_BUSCA = 5000
"""Quantos arquivos a busca pelo CRC olha, no máximo (uma pasta enorme não trava a abertura)."""


class ProjetoInvalido(ValueError):
    """O arquivo não é um projeto que esta versão abre; a mensagem diz por quê, pronta para mostrar."""


@dataclass(frozen=True)
class FonteSalva:
    id: str
    caminho: str                       # relativo à pasta do projeto (com /), ou absoluto se não der
    caminho_absoluto: str
    tamanho: int                       # bytes do arquivo
    crc32_amostras: int | None = None  # o do cabeçalho v9; None nas versões anteriores
    formato: str = "uint16"

    @property
    def nome(self) -> str:
        return Path(self.caminho_absoluto or self.caminho).name


@dataclass(frozen=True)
class TracoSalvo:
    id: str
    receita: ReceitaDoTraco


@dataclass(frozen=True)
class VistaSalva:
    id: str
    nome: str
    tipo: str
    tracos: tuple[TracoSalvo, ...] = ()


@dataclass(frozen=True)
class ProjetoSalvo:
    fontes: tuple[FonteSalva, ...] = ()
    vistas: tuple[VistaSalva, ...] = ()
    layout: dict[str, str] = field(default_factory=dict)    # o estado da janela (base64), por nome
    versao_do_aplicativo: str = ""


# ------------------------------------------------------------------ caminhos


def caminho_relativo(alvo: Path, pasta: Path) -> str:
    """``alvo`` relativo a ``pasta``, com ``/``; o absoluto quando não há caminho relativo (outro disco no
    Windows)."""
    try:
        return Path(os.path.relpath(Path(alvo).resolve(), Path(pasta).resolve())).as_posix()
    except ValueError:
        return Path(alvo).resolve().as_posix()


def automatico(caminho: Path) -> Path:
    """O arquivo do salvamento automático de ``caminho`` (``projeto.shproj~``)."""
    caminho = Path(caminho)
    return caminho.with_name(caminho.name + SUFIXO_AUTOMATICO)


def recuperacao_pendente(caminho: Path) -> Path | None:
    """O salvamento automático de ``caminho``, se ele for mais novo que o principal (ou o principal não existir):
    sinal de que o aplicativo caiu com mudanças não salvas."""
    auto = automatico(caminho)
    if not auto.is_file():
        return None
    principal = Path(caminho)
    if principal.is_file() and principal.stat().st_mtime_ns >= auto.stat().st_mtime_ns:
        return None
    return auto


# ------------------------------------------------------------------ JSON


def para_dict(projeto: ProjetoSalvo) -> dict:
    return {
        "formato": FORMATO,
        "versao": VERSAO,
        "aplicativo": projeto.versao_do_aplicativo,
        "fontes": [asdict(f) for f in projeto.fontes],
        "vistas": [{"id": v.id, "nome": v.nome, "tipo": v.tipo,
                    "tracos": [{"id": t.id, **asdict(t.receita)} for t in v.tracos]} for v in projeto.vistas],
        "layout": dict(projeto.layout),
    }


def _campo(dados: dict, nome: str, tipo, onde: str):
    if nome not in dados:
        raise ProjetoInvalido(f"falta o campo {nome!r} em {onde}")
    valor = dados[nome]
    if not isinstance(valor, tipo) or (tipo is int and isinstance(valor, bool)):
        raise ProjetoInvalido(f"o campo {nome!r} em {onde} tem um valor inválido: {valor!r}")
    return valor


def de_dict(dados) -> ProjetoSalvo:
    """O projeto de um JSON já lido. Levanta :class:`ProjetoInvalido` com a mensagem pronta."""
    if not isinstance(dados, dict) or dados.get("formato") != FORMATO:
        raise ProjetoInvalido("este arquivo não é um projeto do SH-Analyzer")
    versao = _campo(dados, "versao", int, "o projeto")
    if versao > VERSAO:
        raise ProjetoInvalido(f"o projeto foi salvo por uma versão mais nova do SH-Analyzer (formato {versao}; esta "
                              f"abre até o {VERSAO}): atualize o aplicativo")
    if versao < 1:
        raise ProjetoInvalido(f"versão de projeto inválida: {versao}")

    fontes = []
    for i, f in enumerate(_campo(dados, "fontes", list, "o projeto")):
        onde = f"a fonte {i + 1}"
        if not isinstance(f, dict):
            raise ProjetoInvalido(f"{onde} não é um objeto")
        crc = f.get("crc32_amostras")
        if crc is not None and (not isinstance(crc, int) or isinstance(crc, bool)):
            raise ProjetoInvalido(f"o CRC de {onde} é inválido: {crc!r}")
        fontes.append(FonteSalva(id=_campo(f, "id", str, onde), caminho=_campo(f, "caminho", str, onde),
                                 caminho_absoluto=_campo(f, "caminho_absoluto", str, onde),
                                 tamanho=_campo(f, "tamanho", int, onde), crc32_amostras=crc,
                                 formato=f.get("formato", "uint16")))
    ids = [f.id for f in fontes]
    if len(set(ids)) != len(ids):
        raise ProjetoInvalido("duas fontes com o mesmo id")

    campos_da_receita = {f.name for f in fields(ReceitaDoTraco)}
    vistas = []
    for i, v in enumerate(_campo(dados, "vistas", list, "o projeto")):
        onde = f"a vista {i + 1}"
        if not isinstance(v, dict):
            raise ProjetoInvalido(f"{onde} não é um objeto")
        tracos = []
        for j, t in enumerate(_campo(v, "tracos", list, onde)):
            onde_t = f"o traço {j + 1} de {onde}"
            if not isinstance(t, dict):
                raise ProjetoInvalido(f"{onde_t} não é um objeto")
            desconhecidos = set(t) - campos_da_receita - {"id"}
            if desconhecidos:
                raise ProjetoInvalido(f"{onde_t} tem campos desconhecidos: {', '.join(sorted(desconhecidos))}")
            try:
                receita = ReceitaDoTraco(**{k: t[k] for k in campos_da_receita if k in t})
            except TypeError as e:
                raise ProjetoInvalido(f"{onde_t} está incompleto ({e})") from None
            except ReceitaInvalida as e:
                raise ProjetoInvalido(f"{onde_t}: {e}") from None
            if receita.fonte not in ids:
                raise ProjetoInvalido(f"{onde_t} aponta para uma fonte que não está no projeto")
            tracos.append(TracoSalvo(_campo(t, "id", str, onde_t), receita))
        nome, tipo = _campo(v, "nome", str, onde), _campo(v, "tipo", str, onde)
        if not nome.strip():
            raise ProjetoInvalido(f"{onde} está sem nome")
        if tipo not in TIPOS_DE_VISTA:
            raise ProjetoInvalido(f"{onde} é de um tipo que esta versão não abre ({tipo!r}): atualize o aplicativo")
        vistas.append(VistaSalva(id=_campo(v, "id", str, onde), nome=nome, tipo=tipo, tracos=tuple(tracos)))
    layout = dados.get("layout", {})
    if not isinstance(layout, dict) or not all(isinstance(k, str) and isinstance(x, str) for k, x in layout.items()):
        layout = {}                                       # o layout é só conforto: inválido, vale o padrão
    return ProjetoSalvo(tuple(fontes), tuple(vistas), layout, str(dados.get("aplicativo", "")))


# ------------------------------------------------------------------ arquivo


def gravar_atomico(caminho: Path, conteudo: bytes) -> None:
    """Grava num temporário da mesma pasta, com ``fsync``, e renomeia: o arquivo antigo só some quando o novo está
    inteiro no disco."""
    caminho = Path(caminho)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    descritor, temporario = tempfile.mkstemp(prefix=caminho.name + ".", suffix=".tmp", dir=caminho.parent)
    try:
        with os.fdopen(descritor, "wb") as f:
            f.write(conteudo)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporario, caminho)
    except BaseException:
        Path(temporario).unlink(missing_ok=True)
        raise


def salvar(projeto: ProjetoSalvo, caminho: Path) -> None:
    """Grava o projeto em ``caminho`` e apaga o salvamento automático dele (que ficou velho)."""
    texto = json.dumps(para_dict(projeto), ensure_ascii=False, indent=1)
    gravar_atomico(Path(caminho), (texto + "\n").encode("utf-8"))
    automatico(caminho).unlink(missing_ok=True)


def salvar_automatico(projeto: ProjetoSalvo, caminho: Path) -> Path:
    """Grava o salvamento automático de ``caminho`` (o principal fica como está) e devolve onde gravou."""
    destino = automatico(caminho)
    gravar_atomico(destino, json.dumps(para_dict(projeto), ensure_ascii=False).encode("utf-8"))
    return destino


def abrir(caminho: Path) -> ProjetoSalvo:
    """Lê um ``.shproj`` (ou o automático dele). Levanta :class:`ProjetoInvalido` (e ``OSError`` se o arquivo não
    abre)."""
    try:
        dados = json.loads(Path(caminho).read_text(encoding="utf-8"))
    except UnicodeDecodeError:
        raise ProjetoInvalido("este arquivo não é um projeto do SH-Analyzer (não é texto)") from None
    except json.JSONDecodeError as e:
        raise ProjetoInvalido(f"o projeto está estragado (JSON inválido na linha {e.lineno})") from None
    return de_dict(dados)


# ------------------------------------------------------------------ reencontrar as fontes


def _candidatos(pastas: Iterable[Path], tamanho: int, nome: str) -> list[Path]:
    """Os arquivos com o tamanho certo nas pastas (e subpastas), os de mesmo nome primeiro."""
    achados, olhados, vistos = [], 0, set()
    for pasta in pastas:
        if not pasta.is_dir():
            continue
        for raiz, subpastas, arquivos in os.walk(pasta):
            subpastas[:] = [s for s in subpastas if not s.startswith(".")]
            for nome_arq in arquivos:
                olhados += 1
                if olhados > LIMITE_DA_BUSCA:
                    return sorted(achados, key=lambda p: p.name != nome)
                caminho = Path(raiz) / nome_arq
                try:
                    if caminho.stat().st_size == tamanho and caminho.resolve() not in vistos:
                        vistos.add(caminho.resolve())
                        achados.append(caminho)
                except OSError:
                    continue
    return sorted(achados, key=lambda p: p.name != nome)


def localizar_fonte(fonte: FonteSalva, pasta_do_projeto: Path, crc_de: Callable[[Path], int | None],
                    pastas_extras: Iterable[Path] = ()) -> Path | None:
    """Onde está a captura de ``fonte``: o caminho relativo, o absoluto e, se os dois falham, a busca na pasta do
    projeto, na pasta antiga da captura e nas ``pastas_extras``, por um arquivo de mesmo tamanho e mesmo CRC
    (``crc_de`` lê o CRC do cabeçalho; quem chama passa a função da ``api``). Sem CRC no projeto (cabeçalho
    antes do v9), só vale o caminho: o tamanho sozinho não identifica uma captura."""
    pasta_do_projeto = Path(pasta_do_projeto)

    def confere(caminho: Path) -> bool:
        try:
            if not caminho.is_file() or caminho.stat().st_size != fonte.tamanho:
                return False
            return fonte.crc32_amostras is None or crc_de(caminho) == fonte.crc32_amostras
        except Exception:      # um arquivo que não se lê (sem cabeçalho, sem permissão) não é a captura procurada
            return False

    for caminho in (pasta_do_projeto / fonte.caminho, Path(fonte.caminho_absoluto)):
        if confere(caminho):
            return caminho
    if fonte.crc32_amostras is None:
        return None
    pastas = [pasta_do_projeto, Path(fonte.caminho_absoluto).parent, *map(Path, pastas_extras)]
    for candidato in _candidatos(pastas, fonte.tamanho, fonte.nome):
        if confere(candidato):
            return candidato
    return None
