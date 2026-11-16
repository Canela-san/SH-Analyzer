"""O diagnóstico da placa item a item (docs/gui-plan.md, 11.9; a F3.6) e o relatório em Markdown.

**Os itens** (:func:`itens_do_diagnostico`) são as linhas da tabela 11.9 do plano: o relógio, o firmware, a PRU0, a
memória dos buffers, os pinos, os overlays, o cartão, o sistema e as ferramentas. Cada um junta os problemas da placa
(as conferências do agente, pelo código) e os do computador (o relógio e o firmware), com o pior nível, uma linha
com os fatos (o que foi lido, e não só o que deu errado: um item "ok" também diz por quê) e, nos dois corrigíveis
daqui (:mod:`sh_placa.correcoes`), qual "Corrigir" cabe. Um código que este aplicativo não conhece (de um agente mais
novo) vai para "Outras conferências", em vez de sumir.

**O relatório** (:func:`relatorio`) é o registro do estado da placa antes de um ensaio: o cabeçalho, cada item, os
problemas com a correção e o registro de atividade. A interface o copia ou salva; a Fase 4 o põe no caderno.

Os números saem com a vírgula decimal, como no resto do aplicativo. Só a biblioteca padrão.
"""

from __future__ import annotations

import time
from collections.abc import Iterable
from dataclasses import dataclass

from .estado import NIVEIS, EstadoDaPlaca, Problema
from .registro import Entrada

TAXA_DE_REFERENCIA_HZ = 400_000
CATEGORIAS = (
    ("relogio", "Relógio", ("relogio", "relogio_sem_ntp")),
    ("firmware", "Firmware", ("firmware_diferente", "nao_compilado", "compilacao_antiga", "pru_desatualizada",
                              "versao_desconhecida")),
    ("pru", "PRU0", ("pru_em_outro_remoteproc", "pru_ausente", "pru_outro_nucleo", "pru_com_falha",
                     "pru_outro_firmware")),
    ("memoria_dos_buffers", "Memória dos buffers", ("mem_496m", "mem_desconhecida", "mem_496m_no_proximo_boot",
                                                    "ram_sobre_os_buffers")),
    ("pinos", "Pinos da PRU", ("pinos", "pinos_desconhecidos")),
    ("overlays", "Overlays e uEnv.txt", ("overlay_da_pru", "audio_hdmi", "audio_hdmi_no_proximo_boot", "uenv_ausente",
                                         "kernel_trocado", "uenv_estranho")),
    ("disco", "Cartão", ("disco_cheio", "disco", "capturas")),
    ("sistema", "Sistema", ("temperatura", "carga", "memoria")),
    ("ferramentas", "Ferramentas", ("ferramentas",)),
)
"""``(chave, título, códigos)``, na ordem da tabela 11.9. ``tests/test_sh_placa_diagnostico.py`` confere que todo
código que o agente pode emitir tem um item."""
NIVEIS_DOS_ITENS = ("erro", "aviso", "info", "ok")
ESTADOS_DA_PRU = {"running": "rodando", "offline": "parada (o normal entre capturas)", "crashed": "parada com falha",
                  "suspended": "suspensa"}


@dataclass(frozen=True)
class ItemDoDiagnostico:
    chave: str
    titulo: str
    nivel: str                              # "ok", "info", "aviso" ou "erro"
    resumo: str                             # os fatos lidos, numa linha
    problemas: tuple[Problema, ...] = ()
    correcao: str | None = None             # o "Corrigir" daqui: "relogio" ou "pinos"


def _decimal(valor: float, casas: int) -> str:
    return f"{valor:.{casas}f}".replace(".", ",")


def _bytes(n: float) -> str:
    """"512 MiB", "1,1 GiB": as unidades binárias, com até três algarismos (como a interface)."""
    unidades, i = ("B", "KiB", "MiB", "GiB", "TiB"), 0
    while abs(n) >= 1024 and i < len(unidades) - 1:
        n /= 1024
        i += 1
    return f"{n:.0f} {unidades[i]}" if i == 0 or abs(n) >= 10 else f"{_decimal(n, 1)} {unidades[i]}"


def duracao(segundos: float) -> str:
    """"40 s", "12 min", "2 h 14", "3 dias"."""
    if segundos < 60:
        return f"{segundos:.0f} s"
    if segundos < 3600:
        return f"{segundos // 60:.0f} min"
    if segundos < 2 * 86_400:
        return f"{segundos // 3600:.0f} h {segundos % 3600 // 60:02.0f}"
    return f"{segundos // 86_400:.0f} dias"


def _lista(itens: list[str]) -> str:
    return itens[0] if len(itens) == 1 else ", ".join(itens[:-1]) + " e " + itens[-1]


def _resumo_do_relogio(e: EstadoDaPlaca, agora: float | None) -> str:
    relogio = e.relogio
    if relogio is None:
        return "sem a hora da placa"
    partes = [f"{_decimal(relogio.diferenca_s(agora), 2).replace('-', '−')} s do computador"]
    if relogio.incerteza_s is not None:
        partes[0] += f" (±{_decimal(relogio.incerteza_s, 2)} s)"
    partes.append(f"sincronizado ({relogio.fonte})" if relogio.sincronizado else "sem NTP")
    return " · ".join(partes)


def _resumo_do_firmware(e: EstadoDaPlaca, versao_do_aplicativo: str | None) -> str:
    versao = e.versao_do_firmware
    if versao is None:
        return "sem o VERSAO na pasta do firmware"
    partes = [versao]
    if versao_do_aplicativo:
        partes.append("o deste aplicativo" if versao == versao_do_aplicativo
                      else f"o deste aplicativo é {versao_do_aplicativo}")
    compilado = e.firmware_compilado
    if compilado is not None:
        partes.append("ler_adc compilado" if compilado else "ler_adc sem compilar")
    return " · ".join(partes)


def _resumo_da_pru(e: EstadoDaPlaca) -> str:
    pru = e.pru
    if not pru:
        return "sem a PRU0 no remoteproc"
    partes = [ESTADOS_DA_PRU.get(pru.get("estado"), str(pru.get("estado") or "estado desconhecido"))]
    if pru.get("firmware"):
        partes.append(str(pru["firmware"]))
    if e.protocolo_da_pru is not None:
        partes.append(f"protocolo {e.protocolo_da_pru}")
    return " · ".join(partes)


def _resumo_da_memoria(e: EstadoDaPlaca) -> str:
    agora, proximo = e.mem_496m
    if agora is None:
        return "o /proc/cmdline não deu para ler"
    partes = ["mem=496M no boot de agora" if agora else "sem o mem=496M no boot de agora"]
    if proximo is not None:
        partes.append("e no próximo" if proximo == agora else ("no próximo, sim" if proximo else "no próximo, não"))
    return " ".join(partes)


def _resumo_dos_pinos(e: EstadoDaPlaca) -> str:
    pinos = e.pinos
    if not pinos:
        return "os pinmux não deu para ler (o cape universal está ligado?)"
    errados = e.pinos_errados
    if errados:
        return "; ".join(f"{p} em {pinos[p][0]} (a PRU pede {pinos[p][1]})" for p in errados)
    por_modo: dict[str, list[str]] = {}
    for pino, (modo, _esperado) in sorted(pinos.items()):
        por_modo.setdefault(str(modo), []).append(pino)
    return "; ".join(f"{_lista(p)} em {modo}" for modo, p in por_modo.items())


def _resumo_dos_overlays(e: EstadoDaPlaca) -> str:
    da_pru = [o for o in e.overlays if o.startswith("AM335X-PRU")]
    partes = [_lista(da_pru) if da_pru else "sem o overlay da PRU"]
    if not any("HDMI" in o for o in e.overlays):
        partes.append("sem o áudio do HDMI")
    return " · ".join(partes)


def _resumo_do_disco(e: EstadoDaPlaca) -> str:
    disco = e.disco_bytes
    if disco is None:
        return "o espaço livre não deu para ler"
    livre, total = disco
    partes = [f"{_bytes(livre)} livres de {_bytes(total)}"]
    minutos = e.minutos_de_captura_no_disco
    if minutos is not None:
        partes.append(f"≈ {minutos:.0f} min de captura a 400 kS/s")
    capturas = e.capturas_na_placa
    if capturas:
        partes.append(f"{capturas[0]} captura(s), {_bytes(capturas[1])}")
    return " · ".join(partes)


def _resumo_do_sistema(e: EstadoDaPlaca) -> str:
    partes = []
    if e.temperatura_c is not None:
        partes.append(f"{e.temperatura_c:.0f} °C")
    if e.carga is not None:
        partes.append(f"carga {_decimal(e.carga, 2)}")
    if e.memoria_disponivel_bytes is not None:
        partes.append(f"{_bytes(e.memoria_disponivel_bytes)} de memória livres")
    if e.ligada_s is not None:
        partes.append(f"ligada há {duracao(e.ligada_s)}")
    return " · ".join(partes) or "sem os números do sistema"


def _resumo_das_ferramentas(e: EstadoDaPlaca) -> str:
    ferramentas = e.ferramentas
    faltam = [n for n, onde in ferramentas.items() if not onde]
    if faltam:
        return f"faltam {_lista(faltam)}"
    return _lista(list(ferramentas)) if ferramentas else "não conferidas"


RESUMOS = {"pru": _resumo_da_pru, "memoria_dos_buffers": _resumo_da_memoria, "pinos": _resumo_dos_pinos,
           "overlays": _resumo_dos_overlays, "disco": _resumo_do_disco, "sistema": _resumo_do_sistema,
           "ferramentas": _resumo_das_ferramentas}
"""O resumo de cada item; o do relógio e o do firmware precisam da hora e da versão do aplicativo."""


def itens_do_diagnostico(estado: EstadoDaPlaca, versao_do_aplicativo: str | None = None,
                         agora: float | None = None) -> list[ItemDoDiagnostico]:
    """Os itens da tabela 11.9 para a ``saude`` ``estado``: cada um com o pior nível dos problemas dele (ou "ok"),
    os fatos numa linha e o "Corrigir" que cabe. ``ValueError`` na resposta do ``estado`` (sem as conferências)."""
    problemas = estado.diagnostico(versao_do_aplicativo, agora)
    por_categoria: dict[str, list[Problema]] = {chave: [] for chave, _t, _c in CATEGORIAS}
    categoria_do_codigo = {codigo: chave for chave, _t, codigos in CATEGORIAS for codigo in codigos}
    outros: list[Problema] = []
    for p in problemas:
        chave = categoria_do_codigo.get(p.codigo)
        (por_categoria[chave] if chave else outros).append(p)
    itens = []
    for chave, titulo, _codigos in CATEGORIAS:
        dela = por_categoria[chave]
        if chave == "relogio":
            resumo = _resumo_do_relogio(estado, agora)
        elif chave == "firmware":
            resumo = _resumo_do_firmware(estado, versao_do_aplicativo)
        else:
            resumo = RESUMOS[chave](estado)
        correcao = None
        if chave == "pinos" and any(p.codigo == "pinos" for p in dela) and estado.pinos_errados:
            correcao = "pinos"
        elif chave == "relogio" and estado.relogio is not None and (dela or not estado.relogio.sincronizado):
            correcao = "relogio"
        itens.append(ItemDoDiagnostico(chave, titulo, _pior(dela), resumo, tuple(dela), correcao))
    if outros:
        itens.append(ItemDoDiagnostico("outros", "Outras conferências", _pior(outros),
                                       f"{len(outros)} conferência(s) que este aplicativo não conhece",
                                       tuple(outros)))
    return itens


def _pior(problemas: Iterable[Problema]) -> str:
    niveis = {p.nivel for p in problemas}
    return next((n for n in NIVEIS if n in niveis), "ok")


ROTULOS = {"ok": "OK", "info": "Info", "aviso": "Aviso", "erro": "Erro"}


def relatorio(estado: EstadoDaPlaca, versao_do_aplicativo: str | None = None, *, conexao: str = "",
              registro: Iterable[Entrada] = (), agora: float | None = None, aplicativo: str = "") -> str:
    """O relatório do diagnóstico em Markdown: o cabeçalho da placa, o resumo, cada item, os problemas com a correção
    e o registro de atividade (``registro``; os últimos 50 comandos e fatos). ``conexao``: o caminho e o enlace, como
    a interface os escreve; ``aplicativo``: o nome e a versão de quem gerou."""
    agora = time.time() if agora is None else agora
    itens = itens_do_diagnostico(estado, versao_do_aplicativo, agora)
    linhas = ["# Diagnóstico da placa", ""]
    placa = estado.nome_da_placa + (f", nº {estado.serie}" if estado.serie else "")
    linhas.append(f"- **Placa:** {placa}")
    sistema = " · ".join(x for x in (estado.sistema, f"kernel {estado.kernel}" if estado.kernel else "") if x)
    if sistema:
        linhas.append(f"- **Sistema:** {sistema}")
    if conexao:
        linhas.append(f"- **Conexão:** {conexao}")
    rodape = time.strftime("%d/%m/%Y %H:%M", time.localtime(agora)) + " (a hora do computador)"
    linhas.append(f"- **Conferido em:** {rodape}" + (f", pelo {aplicativo}" if aplicativo else ""))
    erros = [p for i in itens for p in i.problemas if p.nivel == "erro"]
    avisos = [p for i in itens for p in i.problemas if p.nivel == "aviso"]
    linhas += ["", "## Resumo", ""]
    if erros:
        linhas.append(f"**Não está pronta para capturar:** {len(erros)} erro(s) e {len(avisos)} aviso(s).")
    else:
        linhas.append("**Pronta para capturar**" + (f", com {len(avisos)} aviso(s)." if avisos else "."))
    linhas += ["", "| | Item | O que foi lido |", "|---|---|---|"]
    for item in itens:
        linhas.append(f"| {ROTULOS[item.nivel]} | {item.titulo} | {item.resumo.replace('|', '/')} |")
    problemas = [(i, p) for i in itens for p in i.problemas]
    if problemas:
        linhas += ["", "## Problemas", ""]
        for item, p in problemas:
            linhas.append(f"- **{ROTULOS[p.nivel]} ({item.titulo}):** {p.texto}")
            if p.correcao:
                linhas.append(f"  - Correção: {p.correcao}")
    entradas = list(registro)[-50:]
    if entradas:
        linhas += ["", "## Registro de atividade", "", "```"]
        linhas += [e.em_texto() for e in entradas]
        linhas.append("```")
    return "\n".join(linhas) + "\n"
