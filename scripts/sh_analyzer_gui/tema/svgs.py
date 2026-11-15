"""Os desenhos dos ícones (docs/gui-plan.md, 12.6), sem Qt: o caminho SVG de cada um (traço de 24 px no estilo do
Lucide, os mesmos dos mockups, ``docs/gui-mockups/desenho.js``) e o SVG inteiro numa cor. ``icones.py`` os desenha
nos botões; :func:`arquivo_svg` os põe em arquivo para o QSS, que só lê imagens de arquivos (a seta das caixas de
escolha, em ``aplicar.gerar_qss``).
"""

from __future__ import annotations

import atexit
import re
import shutil
import tempfile
from pathlib import Path

CAMINHOS = {
    "ponteiro": "M5 3l14 8-6 2-2 6z",
    "zoom": "M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14z M16 16l5 5 M11 8v6 M8 11h6",
    "mao": "M8 13V5.5a1.5 1.5 0 0 1 3 0V12 M11 11V4.5a1.5 1.5 0 0 1 3 0V12 M14 11.5V6a1.5 1.5 0 0 1 3 0v8a6 6 0 0 1-6 "
           "6h-1a6 6 0 0 1-5-2.7L3.5 14a1.5 1.5 0 0 1 2.5-1.7L8 15",
    "cursores": "M7 3v18 M17 3v18 M10 12h4 M10 12l1.6-1.6 M10 12l1.6 1.6 M14 12l-1.6-1.6 M14 12l-1.6 1.6",
    "regua": "M3 17L17 3l4 4L7 21z M7 13l2 2 M10 10l2 2 M13 7l2 2",
    "texto": "M4 7V5h16v2 M12 5v14 M9 19h6",
    "camadas": "M12 3l9 5-9 5-9-5z M3 13l9 5 9-5",
    "pasta": "M3 6.5A1.5 1.5 0 0 1 4.5 5H9l2 2h8.5A1.5 1.5 0 0 1 21 8.5v9a1.5 1.5 0 0 1-1.5 1.5h-15A1.5 1.5 0 0 1 3 17.5z",
    "arquivo": "M14 3H6.5A1.5 1.5 0 0 0 5 4.5v15A1.5 1.5 0 0 0 6.5 21h11a1.5 1.5 0 0 0 1.5-1.5V8z M14 3v5h5",
    "chip": "M7 7h10v10H7z M10 3v4 M14 3v4 M10 17v4 M14 17v4 M3 10h4 M3 14h4 M17 10h4 M17 14h4",
    "terminal": "M4 17l6-5-6-5 M12 19h8",
    "ajustes": "M4 6h9 M17 6h3 M4 12h3 M11 12h9 M4 18h11 M19 18h1 M15 4v4 M9 10v4 M17 16v4",
    "busca": "M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14z M16 16l5 5",
    "mais": "M12 5v14 M5 12h14",
    "x": "M6 6l12 12 M18 6L6 18",
    "olho": "M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12z M12 9a3 3 0 1 0 0 6 3 3 0 0 0 0-6z",
    "onda": "M2 12c2-6.5 4-6.5 6 0s4 6.5 6 0 4-6.5 6 0 2 4 2 4",
    "espectro": "M4 20V11 M9 20V4 M14 20v-8 M19 20v-5",
    "grade": "M4 4h7v7H4z M13 4h7v7h-7z M4 13h7v7H4z M13 13h7v7h-7z",
    "baixar": "M12 4v11 M7 10l5 5 5-5 M5 20h14",
    "enviar": "M12 20V9 M7 14l5-5 5 5 M5 4h14",
    "play": "M7 4l13 8-13 8z",
    "stop": "M6 6h12v12H6z",
    "girar": "M20 12a8 8 0 1 1-2.3-5.7 M20 4v5h-5",
    "ok": "M5 12.5l4.5 4.5L19 7",
    "alerta": "M12 3.5l9.5 16.5h-19z M12 10v4.5 M12 17.5v.2",
    "usb": "M12 3v13 M9.5 5.5L12 3l2.5 2.5 M12 12.5l-4-2V8 M12 14.5l4-2V10 M12 16.2a2.4 2.4 0 1 0 0 4.8 2.4 2.4 0 0 0 0-4.8z",
    "relogio": "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18z M12 7v5l3 2",
    "disco": "M3 13l3-8h12l3 8v5.5a1.5 1.5 0 0 1-1.5 1.5h-15A1.5 1.5 0 0 1 3 18.5z M3 13h18 M17 16.5h.2",
    "chave": "M15 3.5a5 5 0 0 0-4.6 6.9L3.5 17.3V20.5h3.2l6.9-6.9A5 5 0 0 0 20.5 9l-3 1-2.5-2.5 1-3z",
    "sol": "M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8z M12 2v2 M12 20v2 M4.9 4.9l1.4 1.4 M17.7 17.7l1.4 1.4 M2 12h2 M20 12h2 "
           "M4.9 19.1l1.4-1.4 M17.7 6.3l1.4-1.4",
    "lua": "M20 14.5A8.5 8.5 0 1 1 9.5 4a6.5 6.5 0 0 0 10.5 10.5z",
    "baixo": "M6 9l6 6 6-6",
    "direita": "M9 6l6 6-6 6",
    "esquerda": "M15 6l-6 6 6 6",
    "cima": "M6 15l6-6 6 6",
    "cadeado": "M6 11h12a1.5 1.5 0 0 1 1.5 1.5v7A1.5 1.5 0 0 1 18 21H6a1.5 1.5 0 0 1-1.5-1.5v-7A1.5 1.5 0 0 1 6 11z "
               "M8 11V7.5a4 4 0 0 1 8 0V11",
    "cadeado_aberto": "M6 11h12a1.5 1.5 0 0 1 1.5 1.5v7A1.5 1.5 0 0 1 18 21H6a1.5 1.5 0 0 1-1.5-1.5v-7A1.5 1.5 0 0 1 6 "
                      "11z M8 11V7.5a4 4 0 0 1 7.7-1.5",
    "igualar": "M4 10h16 M4 14h16 M12 2v5 M9.5 4.5L12 7l2.5-2.5 M12 22v-5 M9.5 19.5L12 17l2.5 2.5",
    "filtro": "M3 5h18l-7 8v6l-4 2v-8z",
    "desfazer": "M9 14L4 9l5-5 M4 9h10.5a5.5 5.5 0 0 1 0 11H11",
    "refazer": "M15 14l5-5-5-5 M20 9H9.5a5.5 5.5 0 0 0 0 11H13",
    "sonda": "M4 20l5.5-5.5 M9.5 14.5l2 2 7.5-7.5-2-2-7.5 7.5z M15.5 5.5l3 3",
    "pulso": "M3 12h4l3-8 4 16 3-8h4",
    "expandir": "M4 9V4h5 M20 9V4h-5 M4 15v5h5 M20 15v5h-5",
    "mira": "M12 4a8 8 0 1 0 0 16 8 8 0 0 0 0-16z M12 2v4 M12 18v4 M2 12h4 M18 12h4",
    "livro": "M5 4.5h11a3 3 0 0 1 3 3V20H8a3 3 0 0 1-3-3z M5 17a3 3 0 0 1 3-3h11",
    "raio": "M13 2L4 14h7l-1 8 9-12h-7z",
    "imagem": "M4 5h16v14H4z M4 16l5-5 4 4 3-3 4 4 M15 9h.2",
    "energia": "M12 3v8 M6.3 7a8 8 0 1 0 11.4 0",
    "copiar": "M8 8h11v12H8z M5 16V4h11",
    "escudo": "M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z M9 12l2 2 4-4",
    "pagina": "M6 3h9l4 4v14H6z M15 3v4h4",
    "link": "M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1 M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1",
}

_pasta_dos_arquivos: Path | None = None


def svg(nome: str, cor: str, espessura: float = 1.8) -> str:
    """O SVG do ícone ``nome`` na cor ``cor`` (``#rrggbb``)."""
    if nome not in CAMINHOS:
        raise KeyError(f"ícone desconhecido: {nome!r}")
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{cor}" '
            f'stroke-width="{espessura}" stroke-linecap="round" stroke-linejoin="round"><path d="{CAMINHOS[nome]}"/></svg>')


def arquivo_svg(nome: str, cor: str) -> Path:
    """O SVG do ícone ``nome`` na ``cor``, num arquivo da pasta temporária da sessão (criada no primeiro pedido e
    apagada na saída); o mesmo pedido devolve o mesmo arquivo, sem escrever de novo."""
    global _pasta_dos_arquivos
    if not re.fullmatch(r"#[0-9a-fA-F]{6}", cor):
        raise ValueError(f"cor inválida: {cor!r} (use #rrggbb)")
    texto = svg(nome, cor)
    if _pasta_dos_arquivos is None or not _pasta_dos_arquivos.is_dir():
        _pasta_dos_arquivos = Path(tempfile.mkdtemp(prefix="sh-analyzer-icones-"))
        atexit.register(shutil.rmtree, _pasta_dos_arquivos, ignore_errors=True)
    arquivo = _pasta_dos_arquivos / f"{nome}-{cor[1:].lower()}.svg"
    if not arquivo.is_file():
        arquivo.write_text(texto, encoding="utf-8")
    return arquivo
