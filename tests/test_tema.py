"""Os tokens do tema (``sh_analyzer_gui.tema.tokens``): as contas de contraste e de daltonismo da seção 12 do
docs/gui-plan.md, e o CSS dos mockups igual aos tokens (uma fonte de verdade só). Sem Qt."""

import re
from pathlib import Path

import pytest
from sh_analyzer_gui.tema.cores import (
    CONTRASTE_GRAFICO,
    CONTRASTE_TEXTO,
    contraste,
    distancia,
    regras_da_paleta,
    rgb,
)
from sh_analyzer_gui.tema.tokens import TEMAS, cor_do_traco

CSS = Path(__file__).resolve().parents[1] / "docs" / "gui-mockups" / "tema.css"


@pytest.mark.parametrize("nome", sorted(TEMAS))
def test_textos_legiveis_sobre_a_superficie(nome):
    tema = TEMAS[nome]
    for papel in ("texto", "texto2", "mudo", "acento", "ok", "aviso", "erro"):
        c = contraste(getattr(tema, papel), tema.superficie)
        assert c >= CONTRASTE_TEXTO, f"{nome}: {papel} {c:.2f}:1"
    assert contraste(tema.acento_texto, tema.acento) >= CONTRASTE_TEXTO
    assert contraste(tema.destaque_texto, tema.destaque) >= CONTRASTE_TEXTO
    assert contraste(tema.eixo, tema.afundada) >= CONTRASTE_TEXTO


@pytest.mark.parametrize("nome", sorted(TEMAS))
def test_paleta_dos_tracos_passa_nas_regras(nome):
    tema = TEMAS[nome]
    assert len(tema.tracos) == 6
    for cor in tema.tracos:
        assert contraste(cor, tema.afundada) >= CONTRASTE_GRAFICO, f"{nome}: {cor}"
    for regra, d, minimo, par in regras_da_paleta(tema.tracos):
        assert d >= minimo, f"{nome}: {regra}: ΔE {d:.1f} < {minimo:g} {par}"


def test_o_css_dos_mockups_e_igual_aos_tokens():
    texto = CSS.read_text(encoding="utf-8")
    blocos = {"escuro": re.search(r':root,\s*\[data-tema="escuro"\]\s*\{(.*?)\n\}', texto, re.S).group(1),
              "claro": re.search(r'\[data-tema="claro"\]\s*\{(.*?)\n\}', texto, re.S).group(1)}
    for nome, bloco in blocos.items():
        css = dict(re.findall(r"--([a-z0-9-]+):\s*(#[0-9a-f]{6})\b", bloco))
        tema = TEMAS[nome]
        for chave, valor in tema.tokens.items():
            assert css.get(chave.replace("_", "-")) == valor, f"{nome}: --{chave.replace('_', '-')}"
        assert [css[f"t{i}"] for i in range(1, 7)] == list(tema.tracos)


def test_traco_7_repete_o_matiz_tracejado():
    tema = TEMAS["escuro"]
    assert cor_do_traco(0, tema) == (tema.tracos[0], False)
    assert cor_do_traco(6, tema) == (tema.tracos[0], True)
    assert cor_do_traco(13, tema) == (tema.tracos[1], True)


def test_as_contas():
    assert contraste("#000000", "#ffffff") == pytest.approx(21.0)
    assert contraste("#777777", "#777777") == pytest.approx(1.0)
    assert distancia("#ff0000", "#ff0000") == pytest.approx(0.0, abs=1e-9)
    assert distancia("#ff0000", "#00ff00", "deuteranopia") < distancia("#ff0000", "#00ff00")   # vermelho x verde
    with pytest.raises(ValueError):
        rgb("red")


def test_fontes_embutidas_tem_arquivos_e_licenca():
    """Cada fonte da lista está na pasta, com a licença; nenhum arquivo de fonte está na pasta sem estar na lista."""
    from sh_analyzer_gui.tema.fontes_embutidas import EMBUTIDAS, PAPEIS

    pasta = Path(__file__).resolve().parents[1] / "scripts" / "sh_analyzer_gui" / "recursos" / "fontes"
    listados = set()
    for fonte in EMBUTIDAS:
        assert fonte.papel in PAPEIS and fonte.tipo_de_licenca in ("OFL-1.1", "Apache-2.0", "MIT")
        licenca = (pasta / fonte.licenca).read_text(encoding="utf-8")
        assert "Copyright" in licenca and ("OPEN FONT LICENSE" in licenca or fonte.tipo_de_licenca != "OFL-1.1")
        for nome in fonte.arquivos:
            assert (pasta / nome).stat().st_size > 10_000, nome
            assert (pasta / nome).read_bytes()[:4] in (b"\x00\x01\x00\x00", b"OTTO", b"true"), f"{nome}: não é TTF/OTF"
            listados.add(nome)
    na_pasta = {p.name for p in pasta.iterdir() if p.suffix.lower() in (".ttf", ".otf")}
    assert na_pasta == listados, f"sem entrada em EMBUTIDAS: {sorted(na_pasta - listados)}"
    assert {f.papel for f in EMBUTIDAS} == set(PAPEIS)
