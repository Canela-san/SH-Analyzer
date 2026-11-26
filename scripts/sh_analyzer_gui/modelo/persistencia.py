"""Do modelo para o arquivo de projeto e de volta (docs/gui-plan.md, 7.3): :func:`descrever` faz o
``ProjetoSalvo`` (sem Qt, ``dados/projeto.py``) de um ``Projeto``, e :func:`montar` faz o ``Projeto`` de um
``ProjetoSalvo``, reabrindo as capturas.

Abrir um projeto não entra no desfazer: o projeto montado começa com a pilha limpa.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

import supraharmonicos.api as api

from ..dados.captura import Aviso, ErroSHAN, Fonte, abrir_fonte, crc_das_amostras
from ..dados.espectros import OPCOES_DO_TIPO
from ..dados.projeto import (
    FonteSalva,
    ProjetoSalvo,
    TracoSalvo,
    VistaSalva,
    caminho_relativo,
    localizar_fonte,
)
from .objetos import FonteDoProjeto, Projeto, Traco, Vista

if TYPE_CHECKING:
    from ..dados.proveniencia import FonteDaProveniencia


def fontes_da_proveniencia(projeto: Projeto) -> dict[str, FonteDaProveniencia]:
    """As capturas do projeto como a proveniência das exportações as diz: o caminho, o tamanho, o CRC e o cabeçalho
    (o de uma ausente, o que o projeto lembra dela)."""
    # Aqui dentro: a proveniência traz o Matplotlib, que o início do aplicativo não carrega.
    from ..dados.proveniencia import FonteDaProveniencia

    saida = {}
    for f in projeto.fontes:
        if f.esta_ausente:
            salva, cabecalho = f.origem, {}
        else:
            cabecalho = api.cabecalho_em_dict(f.fonte.captura)
            try:
                salva = descrever_fonte(f, f.caminho.parent)
            except OSError:                   # o arquivo sumiu depois de aberto
                salva = None
        saida[f.id] = FonteDaProveniencia(
            f.id, f.nome, salva.caminho_absoluto if salva is not None else str(Path(f.caminho).resolve()),
            salva.tamanho if salva is not None else None, salva.crc32_amostras if salva is not None else None,
            cabecalho)
    return saida


def descrever_fonte(fonte: FonteDoProjeto, pasta: Path) -> FonteSalva:
    """A fonte como vai para o arquivo; uma ausente vai como veio."""
    if fonte.fonte is None:
        return fonte.origem
    caminho = fonte.fonte.caminho.resolve()
    captura = fonte.fonte.captura
    pacote, membro = fonte.pacote or ("", "")
    return FonteSalva(id=fonte.id, caminho=caminho_relativo(caminho, pasta), caminho_absoluto=caminho.as_posix(),
                      tamanho=caminho.stat().st_size, crc32_amostras=captura.crc32_amostras,
                      formato=captura.formato, sem_cabecalho=captura.parametros, pacote=pacote, membro=membro)


def descrever_vista(vista: Vista) -> VistaSalva:
    """A vista como vai para o arquivo (e como fica no painel congelado de uma figura): os traços e as opções."""
    return VistaSalva(vista.id, vista.nome, vista.tipo, tuple(TracoSalvo(t.id, t.receita) for t in vista.tracos),
                      vista.opcoes.para_dict() if vista.opcoes is not None else {}, vista.anotacoes)


def descrever(projeto: Projeto, pasta: Path, *, layout: dict[str, str] | None = None,
              versao_do_aplicativo: str = "",
              janelas: Callable[[Vista], tuple[float, float] | None] | None = None,
              cursores: Callable[[Vista], tuple[float, float] | None] | None = None) -> ProjetoSalvo:
    """O projeto como vai para o arquivo; os caminhos das capturas ficam relativos a ``pasta`` (a do projeto).
    ``janelas(vista)`` e ``cursores(vista)``: o x que cada vista mostra e os cursores ligados dela (a Análise sabe),
    para ela voltar igual."""
    vistas = tuple(replace(descrever_vista(v), janela=janelas(v) if janelas is not None else None,
                           cursores=cursores(v) if cursores is not None else None) for v in projeto.vistas)
    return ProjetoSalvo(tuple(descrever_fonte(f, Path(pasta)) for f in projeto.fontes), vistas, dict(layout or {}),
                        versao_do_aplicativo, projeto.modelos_de_captura, projeto.figuras)


def montar(salvo: ProjetoSalvo, caminho: Path | None, pasta: Path, *,
           abrir: Callable[..., Fonte] = abrir_fonte,
           crc_de: Callable[[Path], int | None] = crc_das_amostras,
           pastas_extras: Iterable[Path] = ()) -> tuple[Projeto, list[Aviso]]:
    """O ``Projeto`` de ``salvo``, com as capturas reabertas, e os avisos do que não deu certo. ``caminho`` é o
    arquivo do projeto (``None`` para um sem título, recuperado), e ``pasta``, a base dos caminhos relativos.

    Uma captura que não é achada (nem pelo CRC) ou não abre entra **ausente**: os traços dela ficam no projeto, e o
    aviso diz qual é. Uma achada em outro lugar entra normal, com um aviso de onde estava."""
    projeto = Projeto(caminho)
    avisos: list[Aviso] = []
    for origem in salvo.fontes:
        local = localizar_fonte(origem, Path(pasta), crc_de, pastas_extras)
        fonte = None
        if local is None:
            avisos.append(Aviso("erro", f"{origem.nome}: a captura não foi encontrada (nem pelo CRC das amostras) "
                                        f"em {origem.caminho_absoluto}"))
        else:
            try:
                fonte = FonteDoProjeto(abrir(local, formato=origem.formato, parametros=origem.sem_cabecalho),
                                       origem.id)
                if origem.pacote:
                    fonte.pacote = (origem.pacote, origem.membro)
            except ErroSHAN as e:
                avisos.append(Aviso("erro", f"{origem.nome}: {e}"))
            else:
                if local.resolve() != Path(origem.caminho_absoluto).resolve() and \
                        local.resolve() != (Path(pasta) / origem.caminho).resolve():
                    avisos.append(Aviso("info", f"{origem.nome}: reencontrada pelo CRC em {local}"))
        projeto._inserir_fonte(fonte if fonte is not None else FonteDoProjeto.ausente(origem))
    for salva in salvo.vistas:
        vista = Vista(salva.nome, salva.tipo, salva.id,
                      OPCOES_DO_TIPO[salva.tipo].de_dict(salva.opcoes) if salva.tipo in OPCOES_DO_TIPO else None)
        for t in salva.tracos:
            vista._inserir(Traco(t.receita, t.id))
        vista._definir_anotacoes(salva.anotacoes)
        projeto._inserir_vista(vista)
    for modelo in salvo.modelos_de_captura:
        projeto._por_modelo(modelo)
    for figura in salvo.figuras:
        projeto._por_figura(figura)
    return projeto, avisos
