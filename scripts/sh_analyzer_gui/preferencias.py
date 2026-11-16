"""As preferências do usuário (docs/gui-plan.md, GE-05): o tema e as fontes, o movimento, o separador decimal e os
prefixos dos eixos, as unidades próprias, as pastas e os limites do cache.

Cada uma é gravada na configuração (``configuracao.py``) quando muda e aplicada na partida
(:func:`aplicar_na_partida`, chamada pelo ``app.main``); a tela de configurações (``areas/configuracoes.py``) as
troca e as aplica na hora. Um valor gravado inválido (um arquivo editado à mão, de outra versão) vale como o padrão,
sem erro.

* **As pastas:** a dos dados (``$DADOS``: onde o diálogo de abrir começa sem um projeto aberto, e a base da pasta da
  sessão do dia, para onde vêm as capturas da placa: :func:`pasta_da_sessao`), a das sondas (onde
  os perfis das sondas registradas nas capturas são procurados ao abrir uma captura) e a do cache (as pirâmides e as
  materializações). Sem uma escolhida, vale a padrão (:func:`pasta_padrao`).
* **Os limites do cache** são dois, cada um com o seu uso: as pirâmides das capturas (a navegação) e as
  materializações (os traços transformados).
* **As unidades próprias** (``dados/unidades.py``) ficam gravadas como JSON: ``[{"simbolo", "grandeza",
  "prefixos"}]``.
* **As placas conhecidas** (``sh_placa/conhecidas.py``: as em que o usuário já conectou, pelo nº de série, com o nome,
  a chave de host, os endereços e se o relógio dela é acertado a cada conexão), também como JSON. A chave SSH do
  aplicativo e os hosts conhecidos ficam numa pasta ao lado da configuração (:func:`pasta_da_placa`).
"""

from __future__ import annotations

import datetime
import json
import os
from collections.abc import Iterable
from pathlib import Path

from PySide6.QtWidgets import QApplication
from sh_placa import conhecidas
from supraharmonicos.api import PASTA_DAS_SONDAS_PADRAO

from .componentes.numeros import SEPARADORES, definir_separador_decimal
from .configuracao import configuracoes, gravar, ler_texto
from .dados import cache as cache_de_piramides
from .dados import materializacao, unidades
from .graficos.faixa import definir_prefixos_nos_eixos
from .tema.aplicar import MODOS, MOVIMENTOS, aparencia
from .tema.fontes import escolher_fonte, familias_disponiveis

CHAVE_DO_TEMA = "aparencia/tema"
CHAVES_DAS_FONTES = {"interface": "aparencia/fonte_interface", "mono": "aparencia/fonte_mono"}
CHAVE_DO_MOVIMENTO = "aparencia/movimento"
CHAVE_DO_SEPARADOR = "numeros/separador_decimal"
CHAVE_DOS_PREFIXOS = "numeros/prefixos_nos_eixos"
CHAVE_DAS_UNIDADES = "unidades/proprias"
CHAVE_DAS_PLACAS = "placa/conhecidas"
PASTAS = ("dados", "sondas", "cache")
CHAVES_DAS_PASTAS = {nome: f"pastas/{nome}" for nome in PASTAS}
CACHES = ("piramides", "materializacoes")
CHAVES_DOS_LIMITES = {nome: f"cache/limite_{nome}_bytes" for nome in CACHES}
LIMITES_PADRAO = {"piramides": cache_de_piramides.LIMITE_PADRAO_BYTES,
                  "materializacoes": materializacao.LIMITE_PADRAO_BYTES}
LIMITE_MINIMO_BYTES = 256 * 1024**2
"""O menor limite aceito: abaixo dele, o cache quase não guardaria nada entre uma sessão e outra (o que está aberto
fica sempre, mesmo acima do limite)."""
VARIAVEL_DOS_DADOS = "DADOS"


# ------------------------------------------------------------------ o tema e as fontes

def tema_salvo() -> str:
    """O modo de tema gravado (``"sistema"``, ``"escuro"`` ou ``"claro"``); ``"sistema"`` se não houver um válido."""
    modo = ler_texto(CHAVE_DO_TEMA, "sistema")
    return modo if modo in MODOS else "sistema"


def mudar_tema(modo: str) -> None:
    aparencia().aplicar(modo)
    gravar(CHAVE_DO_TEMA, modo)


def alternar_tema() -> None:
    """Troca entre o escuro e o claro, e grava a escolha."""
    mudar_tema("claro" if aparencia().tema.escuro else "escuro")


def aplicar_fontes_salvas(app: QApplication | None = None) -> None:
    """Aplica as fontes gravadas que ainda existem; uma que sumiu fica no padrão, sem erro."""
    for papel, chave in CHAVES_DAS_FONTES.items():
        familia = ler_texto(chave)
        if familia and familia in familias_disponiveis(papel):
            escolher_fonte(papel, familia, app)


def mudar_fonte(papel: str, familia: str) -> None:
    """A fonte da interface vale na hora para a aplicação inteira; a dos números, para o que se redesenha com o
    aviso da aparência (os eixos dos gráficos)."""
    escolher_fonte(papel, familia)
    gravar(CHAVES_DAS_FONTES[papel], familia)
    if papel == "mono":
        aparencia().avisar()


# ------------------------------------------------------------------ o movimento e os números

def movimento_salvo() -> str:
    """``"sistema"`` (o padrão), ``"reduzido"`` ou ``"normal"``."""
    modo = ler_texto(CHAVE_DO_MOVIMENTO, "sistema")
    return modo if modo in MOVIMENTOS else "sistema"


def mudar_movimento(modo: str) -> None:
    aparencia().definir_movimento(modo)
    gravar(CHAVE_DO_MOVIMENTO, modo)


def separador_salvo() -> str:
    """O separador decimal gravado: ``","`` (o padrão) ou ``"."``."""
    separador = ler_texto(CHAVE_DO_SEPARADOR, ",")
    return separador if separador in SEPARADORES else ","


def mudar_separador(separador: str) -> None:
    """Troca o separador decimal da escrita de todos os números (a leitura aceita os dois) e avisa quem os mostra."""
    definir_separador_decimal(separador)
    gravar(CHAVE_DO_SEPARADOR, separador)
    aparencia().avisar()


def prefixos_salvos() -> bool:
    """Se os eixos escolhem o prefixo do SI pela faixa visível (o padrão: sim)."""
    return ler_texto(CHAVE_DOS_PREFIXOS, "sim") != "nao"


def mudar_prefixos_nos_eixos(ligados: bool) -> None:
    definir_prefixos_nos_eixos(ligados)
    gravar(CHAVE_DOS_PREFIXOS, "sim" if ligados else "nao")
    aparencia().avisar()


# ------------------------------------------------------------------ as unidades próprias

def unidades_salvas() -> list[unidades.Unidade]:
    """As unidades próprias gravadas; uma inválida (ou que entrou no catálogo numa versão nova) fica de fora."""
    try:
        dados = json.loads(ler_texto(CHAVE_DAS_UNIDADES, "[]") or "[]")
    except json.JSONDecodeError:
        return []
    lidas = []
    for d in dados if isinstance(dados, list) else ():
        try:
            lidas.append(unidades.propria(d["simbolo"], d.get("grandeza", ""), bool(d.get("prefixos", False))))
        except (KeyError, TypeError, AttributeError, unidades.UnidadeInvalida):
            continue
    return lidas


def mudar_unidades(lista: Iterable[unidades.Unidade]) -> None:
    """Troca as unidades próprias, grava e avisa quem escreve números e rótulos com elas."""
    unidades.definir_proprias(lista)
    gravar(CHAVE_DAS_UNIDADES, json.dumps([{"simbolo": u.simbolo, "grandeza": u.grandeza, "prefixos": u.prefixos}
                                           for u in unidades.proprias()], ensure_ascii=False))
    aparencia().avisar()


# ------------------------------------------------------------------ as placas conhecidas

def placas_conhecidas() -> tuple[conhecidas.PlacaConhecida, ...]:
    """As placas gravadas; uma estragada (um arquivo editado à mão, de outra versão) fica de fora, e as outras valem."""
    try:
        dados = json.loads(ler_texto(CHAVE_DAS_PLACAS, "[]") or "[]")
    except json.JSONDecodeError:
        return ()
    return conhecidas.de_lista(dados)


def mudar_placas_conhecidas(placas: Iterable[conhecidas.PlacaConhecida]) -> None:
    gravar(CHAVE_DAS_PLACAS, json.dumps(conhecidas.para_lista(placas), ensure_ascii=False))


def pasta_da_placa() -> Path:
    """A pasta da chave SSH do aplicativo (``id_ed25519``, só o dono lê) e dos hosts conhecidos (``known_hosts``, no
    formato do OpenSSH): ao lado do arquivo da configuração, em ``placa/`` (docs/gui-plan.md, 11.2)."""
    return Path(configuracoes().fileName()).parent / "placa"


# ------------------------------------------------------------------ as pastas

def pasta_padrao(nome: str) -> Path:
    """A pasta usada sem uma escolhida: a dos dados é a da variável ``$DADOS`` (se existir) ou a pessoal; a das
    sondas, a do SH-Analyzer; a do cache, a do sistema (``platformdirs``)."""
    if nome == "dados":
        variavel = os.environ.get(VARIAVEL_DOS_DADOS)
        return Path(variavel) if variavel and Path(variavel).is_dir() else Path.home()
    if nome == "sondas":
        return Path(PASTA_DAS_SONDAS_PADRAO)
    if nome == "cache":
        return cache_de_piramides.pasta_padrao().parent
    raise ValueError(f"pasta desconhecida: {nome!r} (use {', '.join(PASTAS)})")


def pasta_escolhida(nome: str) -> Path | None:
    """A pasta escolhida nas configurações, ou ``None`` (vale a padrão)."""
    if nome not in CHAVES_DAS_PASTAS:
        raise ValueError(f"pasta desconhecida: {nome!r} (use {', '.join(PASTAS)})")
    texto = ler_texto(CHAVES_DAS_PASTAS[nome]).strip()
    return Path(texto) if texto else None


def pasta(nome: str) -> Path:
    """A pasta em uso: a escolhida ou a padrão."""
    return pasta_escolhida(nome) or pasta_padrao(nome)


DADOS_DO_LABORATORIO = Path.home() / "Documents" / "sh-analyzer-data"
"""A pasta dos dados do laboratório sem uma escolhida nem o ``$DADOS``: a mesma do ``scripts/sessao_lab.sh``."""


def pasta_da_sessao(dia: datetime.date | None = None) -> Path:
    """A pasta da sessão do dia, para onde vêm as capturas da placa: ``<dados>/lab/AAAA-MM-DD``, a mesma do ``lab
    trazer``. ``<dados>`` é a pasta escolhida, senão o ``$DADOS``, senão a do ``sessao_lab.sh``."""
    variavel = os.environ.get(VARIAVEL_DOS_DADOS)
    base = pasta_escolhida("dados") or (Path(variavel) if variavel else DADOS_DO_LABORATORIO)
    return base / "lab" / (dia or datetime.date.today()).isoformat()


def mudar_pasta(nome: str, caminho: Path | None) -> None:
    """Escolhe a pasta ``nome``; ``None`` volta à padrão."""
    if nome not in CHAVES_DAS_PASTAS:
        raise ValueError(f"pasta desconhecida: {nome!r} (use {', '.join(PASTAS)})")
    gravar(CHAVES_DAS_PASTAS[nome], str(caminho) if caminho is not None else "")


def pasta_do_cache(nome: str) -> Path:
    """A pasta de um dos caches (``"piramides"`` ou ``"materializacoes"``) dentro da pasta do cache."""
    if nome not in CACHES:
        raise ValueError(f"cache desconhecido: {nome!r} (use {', '.join(CACHES)})")
    return pasta("cache") / nome


# ------------------------------------------------------------------ os limites do cache

def limite(nome: str) -> int:
    """O limite do cache ``nome`` em bytes (o gravado, ou o padrão se não houver um válido)."""
    if nome not in CHAVES_DOS_LIMITES:
        raise ValueError(f"cache desconhecido: {nome!r} (use {', '.join(CACHES)})")
    try:
        valor = int(ler_texto(CHAVES_DOS_LIMITES[nome]))
    except ValueError:
        return LIMITES_PADRAO[nome]
    return valor if valor >= LIMITE_MINIMO_BYTES else LIMITES_PADRAO[nome]


def mudar_limite(nome: str, limite_bytes: int) -> None:
    if nome not in CHAVES_DOS_LIMITES:
        raise ValueError(f"cache desconhecido: {nome!r} (use {', '.join(CACHES)})")
    if limite_bytes < LIMITE_MINIMO_BYTES:
        raise ValueError(f"o limite mínimo é de {LIMITE_MINIMO_BYTES // 1024**2} MiB")
    gravar(CHAVES_DOS_LIMITES[nome], str(int(limite_bytes)))


# ------------------------------------------------------------------ a partida

def aplicar_na_partida(app: QApplication | None = None) -> None:
    """O que vale antes da janela abrir: as fontes, o movimento, o separador decimal, os prefixos dos eixos e as
    unidades próprias (o tema vai na criação da aplicação; as pastas e os limites, quando a janela cria os
    serviços)."""
    aplicar_fontes_salvas(app)
    aparencia(app).definir_movimento(movimento_salvo())
    definir_separador_decimal(separador_salvo())
    definir_prefixos_nos_eixos(prefixos_salvos())
    unidades.definir_proprias(unidades_salvas())
