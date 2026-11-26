"""O notebook do pacote reproduzível (``analise.ipynb``, sem Qt e sem o ``nbformat``): para quem continua a análise
no Jupyter a partir da figura.

1. **A figura**, refeita pelo ``refazer_figura.py`` do pacote (só NumPy, h5py e Matplotlib);
2. **os pontos da figura**, do ``dados.h5``, num dicionário de curvas (o eixo, o rótulo, ``x`` e ``y``);
3. **as amostras**, pela ``supraharmonicos.api`` (o motor do SH-Analyzer, do repositório): cada traço dos painéis
   com a receita dele (o canal, a cadeia, o ganho e o offset), e o espectro ou as bandas da vista com os mesmos
   parâmetros. Precisa das capturas: o caminho de cada uma vem da proveniência e se troca numa linha.

**A cadeia na api:** o filtro (``api.filtrar``), a correção de sonda (``api.aplicar_correcao_sonda``, com o perfil do
canal ou o escolhido) e o "remover DC" têm a mesma conta da interface. As outras etapas (derivar, integrar, o RMS
móvel, a envoltória, a frequência instantânea e a expressão) são da interface: a célula diz que ficaram de fora, e o
sinal sai sem elas.
"""

from __future__ import annotations

import json
from collections.abc import Mapping

from . import espectros as esp

ETAPAS_DA_API = ("filtro", "correcao_sonda", "remover_dc")


def _markdown(texto: str) -> dict:
    return {"cell_type": "markdown", "metadata": {}, "source": _linhas(texto)}


def _codigo(texto: str) -> dict:
    return {"cell_type": "code", "execution_count": None, "metadata": {}, "outputs": [], "source": _linhas(texto)}


def _linhas(texto: str) -> list[str]:
    linhas = texto.strip("\n").split("\n")
    return [linha + "\n" for linha in linhas[:-1]] + linhas[-1:]


def _etapa(etapa: Mapping, canal: int) -> tuple[str, bool]:
    """A linha da etapa na api e se ela tem equivalente."""
    tipo = etapa.get("tipo")
    if not etapa.get("ligada", True):
        return f"# a etapa {tipo} está desligada no traço", True
    if tipo == "filtro":
        cortes = tuple(float(c) for c in etapa["cortes"])
        return f"x = api.filtrar(x, taxa, {etapa['filtro']!r}, {cortes!r}, {int(etapa['ordem'])})", True
    if tipo == "correcao_sonda":
        if etapa.get("perfil"):
            return (f"x = api.aplicar_correcao_sonda(x, taxa, api.carregar_perfil(Path({etapa['perfil']!r})))  "
                    "# o perfil escolhido no traço"), True
        return (f"perfil = cap.canal({canal}).perfil  # o da captura (a sonda registrada nela)\n"
                "x = x if perfil is None else api.aplicar_correcao_sonda(x, taxa, perfil)"), True
    if tipo == "remover_dc":
        return "x = x - x.mean()", True
    return f"# a etapa {tipo!r} é da interface, sem equivalente na api: o sinal segue sem ela", False


def _parametros(vista: Mapping) -> str | None:
    """A conta da vista com os mesmos parâmetros, ou None (as outras vistas: só os sinais)."""
    opcoes = vista.get("opcoes") or {}
    try:
        if vista.get("tipo") == "espectro":
            p = esp.OpcoesDoEspectro.de_dict(opcoes).parametros
            return f"parametros = api.{p!r}\nresultado = api.espectro(x, taxa, parametros)"
        if vista.get("tipo") == "bandas":
            p = esp.OpcoesDasBandas.de_dict(opcoes).parametros
            return f"parametros = api.{p!r}\nresultado = api.bandas_iec(x, taxa, parametros)"
    except esp.OpcoesInvalidas:
        return None
    return None


def notebook(proveniencia: Mapping, nome_da_figura: str) -> str:
    """O ``analise.ipynb`` (nbformat 4) da figura descrita em ``proveniencia`` (a de ``proveniencia.da_figura``)."""
    celulas = [
        _markdown(f"""# {nome_da_figura}: continuar a análise

Este notebook acompanha o pacote reproduzível da figura, feito pelo SH-Analyzer
{(proveniencia.get('aplicativo') or {}).get('versao', '')}. Ele refaz a figura, abre os pontos dela e, com a
`supraharmonicos.api` (o motor do SH-Analyzer) e as capturas, refaz os sinais de cada traço com a mesma receita.

As seções 1 e 2 precisam só de NumPy, h5py e Matplotlib. A 3 precisa do pacote `supraharmonicos` (do repositório
do SH-Analyzer) e das capturas."""),
        _markdown("## 1. A figura"),
        _codigo("""import json
from pathlib import Path

import h5py
import matplotlib
import numpy as np
from matplotlib import rc_context

import refazer_figura as rf

rf.registrar_as_fontes(Path("fontes"))
with h5py.File("dados.h5", "r") as dados:
    with rc_context(rf._json(dados.attrs["rc"])):
        figura = rf.montar(dados)
figura"""),
        _markdown("""## 2. Os pontos da figura

Cada curva é a redução M4 das amostras (o primeiro, o mínimo, o máximo e o último ponto de cada coluna de pixels):
desenha o mesmo que todas elas. As unidades estão nos rótulos dos eixos."""),
        _codigo("""curvas = {}
with h5py.File("dados.h5", "r") as dados:
    for nome_do_eixo, eixo in dados["eixos"].items():
        for nome, linha in eixo.get("linhas", {}).items():
            rotulo = rf._texto(linha.attrs.get("rotulo", nome))
            curvas[(nome_do_eixo, rotulo)] = (linha["x"][()], linha["y"][()])
for (eixo, rotulo), (x, y) in curvas.items():
    print(f"eixo {eixo}: {rotulo!r}, {len(x)} pontos")"""),
    ]
    fontes = proveniencia.get("fontes") or []
    paineis = [p for p in proveniencia.get("paineis") or [] if p.get("vista")]
    if fontes and paineis:
        caminhos = "\n".join(f"    {f['id']!r}: Path({f['caminho']!r}),  # {f['nome']}" for f in fontes)
        celulas += [
            _markdown("""## 3. As amostras, pela `supraharmonicos.api`

Troque o caminho de cada captura pelo desta máquina. Cada traço sai na unidade física, com a cadeia dele e o
ganho e o offset do traço; nas vistas de espectro e de bandas, a conta usa os mesmos parâmetros da vista."""),
            _codigo(f"""from supraharmonicos import api

CAPTURAS = {{
{caminhos}
}}
capturas = {{}}


def captura(fonte):
    if fonte not in capturas:
        capturas[fonte] = api.abrir_captura(CAPTURAS[fonte])
    return capturas[fonte]


sinais, resultados = {{}}, {{}}"""),
        ]
        for painel in paineis:
            vista = painel["vista"]
            conta = _parametros(vista)
            for k, receita in enumerate(vista.get("tracos") or []):
                canal = int(receita.get("canal", 0))
                nome = receita.get("nome") or f"canal {canal}"
                linhas = [f"# painel {painel.get('rotulo', '')}: {vista.get('nome', '')}, traço {k + 1} ({nome})",
                          f"cap = captura({receita.get('fonte')!r})",
                          f"taxa = cap.canal({canal}).taxa_hz",
                          f"x = api.sinal_do_canal(cap, {canal})"]
                for etapa in receita.get("etapas") or []:
                    linhas.append(_etapa(etapa, canal)[0])
                ganho, offset = float(receita.get("ganho", 1.0)), float(receita.get("offset", 0.0))
                if ganho != 1.0 or offset != 0.0:
                    linhas.append(f"x = {ganho!r} * x + {offset!r}  # o ganho e o offset do traço")
                chave = f"{painel.get('rotulo', '')}/{nome}"
                linhas.append(f"sinais[{chave!r}] = x")
                if conta is not None:
                    linhas += [conta, f"resultados[{chave!r}] = resultado"]
                celulas.append(_codigo("\n".join(linhas)))
    caderno = {"cells": celulas, "metadata": {
        "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
        "language_info": {"name": "python"}}, "nbformat": 4, "nbformat_minor": 5}
    for i, celula in enumerate(caderno["cells"]):
        celula["id"] = f"celula-{i:02d}"
    return json.dumps(caderno, ensure_ascii=False, indent=1) + "\n"
