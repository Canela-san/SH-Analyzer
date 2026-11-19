"""A proveniência (docs/gui-plan.md, 10.4), sem Qt: de onde veio uma figura exportada (e, depois, uma exportação de
dados e o pacote reproduzível). Vai nos metadados da figura (o ``Subject`` do PDF, a ``Description`` do SVG e do PNG,
a ``ImageDescription`` do TIFF, um comentário no EPS e no PGF) e, na F5.5, no ``proveniencia.json``.

O que diz:

* **o aplicativo** e a versão dele, e quando a figura saiu;
* **a figura:** o nome, o modelo de página e o tamanho, o idioma;
* **cada painel:** o rótulo, a vista (o nome, o tipo, as opções), se está congelado, os limites, e a receita de cada
  traço (o canal, o ganho, o offset, o deslocamento, as transformações), como o ``.shproj`` a guarda;
* **as capturas** que os painéis usam: o caminho, o tamanho, o CRC das amostras e o cabeçalho resumido (a versão, o
  firmware, a placa, o início, a duração, os canais, a taxa e a integridade).

As capturas vêm de quem tem o projeto aberto (:class:`FonteDaProveniencia`): aqui não se abre arquivo nenhum.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone

from .desenho_da_figura import vista_do_painel
from .figura import Figura
from .projeto import VistaSalva

FORMATO = "sh-analyzer-proveniencia"
VERSAO = 1
CAMPOS_DO_CABECALHO = (
    "arquivo", "tipo", "formato_amostras", "versao_cabecalho", "versao_firmware", "placa", "titulo", "descricao",
    "timestamp_iso_utc", "duracao_real_segundos", "lista_canais", "grandeza_por_canal", "ganho_por_canal",
    "sonda_id_por_canal", "frequencia_hz", "taxa_medida_hz", "total_amostras_gravadas", "blocos_gravados",
    "crc32_amostras", "amostras_atrasadas", "buffers_sobrescritos", "quadros_preambulo_ruim", "linha_de_comando",
    "parametros", "hdf5")
"""O cabeçalho resumido: o que identifica a captura e diz se ela é íntegra (o inteiro está no arquivo dela)."""


@dataclass(frozen=True)
class FonteDaProveniencia:
    id: str
    nome: str
    caminho: str
    tamanho: int | None = None
    crc32_amostras: int | None = None
    cabecalho: dict = field(default_factory=dict)          # o de ``api.cabecalho_em_dict``, inteiro ou resumido


def resumo_do_cabecalho(cabecalho: Mapping) -> dict:
    return {campo: cabecalho[campo] for campo in CAMPOS_DO_CABECALHO if campo in cabecalho}


def da_figura(figura: Figura, vistas: Mapping[str, VistaSalva], fontes: Mapping[str, FonteDaProveniencia], *,
              aplicativo: str, momento: datetime | None = None) -> dict:
    """A proveniência de ``figura`` desenhada com ``vistas``: só as capturas que algum painel usa entram."""
    momento = momento or datetime.now(timezone.utc).astimezone()
    rotulos = figura.rotulos()
    paineis, usadas = [], []
    for painel in figura.em_ordem():
        vista = vista_do_painel(painel, vistas)
        item: dict = {"id": painel.id, "rotulo": rotulos[painel.id], "congelado": painel.congelado is not None,
                      "limites_x": list(painel.limites_x) if painel.limites_x else None,
                      "limites_y": list(painel.limites_y) if painel.limites_y else None, "vista": None}
        if vista is not None:
            item["vista"] = {"id": vista.id, "nome": vista.nome, "tipo": vista.tipo, "opcoes": dict(vista.opcoes),
                             "tracos": [t.receita.para_dict() for t in vista.tracos]}
            for t in vista.tracos:
                if t.receita.fonte not in usadas:
                    usadas.append(t.receita.fonte)
        paineis.append(item)
    return {
        "formato": FORMATO, "versao": VERSAO,
        "aplicativo": {"nome": "SH-Analyzer", "versao": aplicativo},
        "gerado_em": momento.isoformat(timespec="seconds"),
        "figura": {"id": figura.id, "nome": figura.nome, "modelo": figura.modelo, "pagina": figura.pagina.nome,
                   "largura_mm": figura.largura_mm, "altura_mm": figura.altura_mm, "idioma": figura.idioma},
        "paineis": paineis,
        "fontes": [_fonte(fontes[f]) for f in usadas if f in fontes],
    }


def _fonte(f: FonteDaProveniencia) -> dict:
    return {"id": f.id, "nome": f.nome, "caminho": f.caminho, "tamanho": f.tamanho,
            "crc32_amostras": f.crc32_amostras, "cabecalho": resumo_do_cabecalho(f.cabecalho)}


def em_texto(proveniencia: Mapping) -> str:
    """Numa linha de JSON (os metadados das figuras), com os acentos como estão."""
    return json.dumps(proveniencia, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
