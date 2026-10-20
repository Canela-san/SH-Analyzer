"""Borda da CLI ``scripts/compactar_amostras.py``: arquivar capturas sem perdas num pacote ``.zpaq.tar``.

Comandos: ``compactar`` (o padrão), ``extrair``, ``listar`` e ``verificar``. A lógica (formato, compressores,
verificação) mora em :mod:`compactacao`; aqui ficam as flags e a interface (``rich``: tabelas, barras de
progresso com estimativa de tempo, confirmações).

Depende de: ``compactacao``, ``erros``.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import threading
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path, PurePosixPath

from rich import box
from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.progress_bar import ProgressBar
from rich.prompt import Confirm
from rich.spinner import Spinner
from rich.table import Table
from rich.text import Text

from .compactacao import (
    METODO_PADRAO,
    METODOS,
    SUFIXO_PARCIAL,
    TAMANHO_PECA_MAX,
    Entrada,
    Metodo,
    Observador,
    Pacote,
    Resultado,
    compactar,
    descobrir_entradas,
    localizar_zpaq,
    memoria_disponivel,
    planejar_processos,
    remover_originais,
)
from .erros import ErroSHAN, ErroUso

COMANDOS = ("compactar", "extrair", "listar", "verificar")
COR = "cyan"

NOMES_FASE = {
    "lendo": "Lendo e calculando SHA-256",
    "comprimindo": "Comprimindo",
    "verificando": "Verificando (descomprime tudo)",
    "extraindo": "Extraindo",
    "conferindo": "Conferindo as peças",
}


# ---------------------------------------------------------------------------
# Formatação (português: vírgula decimal, unidades do SI como nos gerenciadores de arquivos)
# ---------------------------------------------------------------------------
def fmt_bytes(n: float) -> str:
    for unidade, fator in (("TB", 1e12), ("GB", 1e9), ("MB", 1e6), ("kB", 1e3)):
        if abs(n) >= fator:
            v = n / fator
            return f"{v:.1f} {unidade}".replace(".", ",") if v < 100 else f"{v:.0f} {unidade}"
    return f"{int(n)} B"


def fmt_duracao(s: float) -> str:
    s = max(0, int(round(s)))
    if s < 60:
        return f"{s} s"
    if s < 3600:
        return f"{s // 60} min {s % 60:02d} s"
    return f"{s // 3600} h {s % 3600 // 60:02d} min"


def fmt_pct(x: float) -> str:
    return f"{x:.1f} %".replace(".", ",")


def fmt_taxa(original: int, comprimido: int) -> str:
    if original == 0:
        return "—"
    return f"{fmt_pct(100 * comprimido / original)}  ({original / max(comprimido, 1):.1f}× menor)".replace(".", ",")


def _resumo_captura(c: dict | None) -> str:
    if not c:
        return ""
    partes = []
    if c.get("frequencia_hz"):
        partes.append(f"{c['frequencia_hz'] / 1000:g} kS/s".replace(".", ","))
    canais = c.get("canais") or []
    if canais:
        partes.append(("canal " if len(canais) == 1 else "canais ") + ",".join(str(x) for x in canais))
    data = (c.get("data_utc") or "")[:16].replace("T", " ")
    if data and not data.startswith("inv"):
        partes.append(data)
    if c.get("titulo"):
        partes.append(f"“{c['titulo']}”")
    return " · ".join(partes)


# ---------------------------------------------------------------------------
# Painel de progresso (implementa o Observador de compactacao)
# ---------------------------------------------------------------------------
class Painel(Observador):
    """Barra geral + uma linha por processo ativo. O zpaq não informa o próprio progresso, então o de cada peça
    em andamento é ESTIMADO pela velocidade medida nas peças que já terminaram (ou por um palpite, no começo);
    a estimativa nunca passa de 97 % antes de a peça terminar de verdade."""

    def __init__(self, console: Console, metodo: Metodo | None):
        self.console = console
        self.metodo = metodo
        self._trava = threading.Lock()
        self._live: Live | None = None

    # -- chamadas do motor -----------------------------------------------------------------------
    def fase(self, nome: str, total_bytes: int, total_itens: int, processos: int) -> None:
        self.encerrar()
        with self._trava:
            self.nome = nome
            self.total_bytes, self.total_itens, self.processos = total_bytes, total_itens, processos
            self.feitos_bytes = self.feitos_itens = 0
            self.medidos_bytes, self.medidos_seg = 0, 0.0
            self.ativos: dict[object, tuple[str, int, float, Spinner]] = {}
            self.t0 = time.monotonic()
        if total_itens == 0:
            return
        self._live = Live(get_renderable=self._desenhar, console=self.console, refresh_per_second=6, transient=True)
        self._live.start()

    def inicio(self, chave, rotulo, tamanho) -> None:
        with self._trava:
            self.ativos[chave] = (rotulo, tamanho, time.monotonic(), Spinner("dots", style=COR))

    def fim(self, chave, tamanho, segundos) -> None:
        with self._trava:
            self.ativos.pop(chave, None)
            self.feitos_bytes += tamanho
            self.feitos_itens += 1
            self.medidos_bytes += tamanho
            self.medidos_seg += segundos

    def encerrar(self) -> None:
        if self._live is not None:
            self._live.stop()
            self._live = None
            decorrido = time.monotonic() - self.t0
            nome = NOMES_FASE.get(self.nome, self.nome)
            if self.feitos_itens < self.total_itens:      # Ctrl+C ou erro no meio da fase
                self.console.print(f"  [yellow]✘[/] {nome}: interrompido em {fmt_bytes(self.feitos_bytes)} de "
                                   f"{fmt_bytes(self.total_bytes)}")
                return
            taxa = self.feitos_bytes / decorrido if decorrido > 0 else 0
            self.console.print(f"  [green]✔[/] {nome}: {fmt_bytes(self.feitos_bytes)} em {fmt_duracao(decorrido)}"
                               + (f"  [dim]({fmt_bytes(taxa)}/s, {self.processos} processo(s))[/]" if decorrido > 2 else ""))

    # -- desenho ------------------------------------------------------------------------------------
    def _taxa_por_processo(self) -> float:
        if self.medidos_seg > 0 and self.medidos_bytes > 0:
            return self.medidos_bytes / self.medidos_seg
        if self.nome in ("comprimindo", "verificando", "extraindo") and self.metodo is not None:
            return self.metodo.taxa_estimada
        return 200e6

    def _desenhar(self):
        with self._trava:
            agora = time.monotonic()
            taxa = self._taxa_por_processo()
            linhas = []
            estimado = self.feitos_bytes
            for rotulo, tamanho, inicio, spinner in sorted(self.ativos.values(), key=lambda a: a[2]):
                frac = min(0.97, (agora - inicio) * taxa / max(tamanho, 1))
                estimado += frac * tamanho
                linhas.append((spinner, rotulo, tamanho, frac, agora - inicio))
            decorrido = agora - self.t0
            frac_total = min(1.0, estimado / max(self.total_bytes, 1))
            restante = max(self.total_bytes - estimado, 0)
            vazao = taxa * max(1, min(self.processos, len(self.ativos) or 1))
            if decorrido > 5 and estimado > 0:
                vazao = estimado / decorrido
            falta = f"faltam ~{fmt_duracao(restante / vazao)}" if vazao > 0 and estimado < self.total_bytes else ""

        topo = Table.grid(padding=(0, 1))
        topo.add_column(width=34, no_wrap=True)
        topo.add_column(ratio=1)
        topo.add_column(justify="right", no_wrap=True)
        topo.add_row(Text(NOMES_FASE.get(self.nome, self.nome), style="bold"),
                     ProgressBar(total=1.0, completed=frac_total, complete_style=COR, finished_style="green"),
                     Text(f"{fmt_pct(100 * frac_total):>7}"))
        info = (f"{fmt_bytes(estimado)} de {fmt_bytes(self.total_bytes)}  ·  {self.feitos_itens}/{self.total_itens} "
                f"concluído(s)  ·  {fmt_duracao(decorrido)}" + (f"  ·  {falta}" if falta else ""))
        ativos = Table.grid(padding=(0, 1))
        ativos.add_column(width=2)
        ativos.add_column(ratio=1, no_wrap=True, overflow="ellipsis")
        ativos.add_column(width=16)
        ativos.add_column(justify="right", no_wrap=True, width=20)
        for spinner, rotulo, tamanho, frac, t in linhas:
            ativos.add_row(spinner, Text(rotulo, style="dim"),
                           ProgressBar(total=1.0, completed=frac, complete_style="blue", width=16),
                           Text(f"{fmt_bytes(tamanho)} · {fmt_duracao(t)}", style="dim"))
        return Group(topo, Text("  " + info, style="dim"), ativos)


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------
def montar_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="compactar_amostras.py",
        description="Compactação SEM PERDAS das capturas do SH-Analyzer (.bin, .h5 e o que mais houver nas pastas) "
                    "num único pacote .zpaq.tar, com verificação bit a bit (SHA-256).",
        epilog="Exemplos:\n"
               "  uv run scripts/compactar_amostras.py Collected_Data\n"
               "  uv run scripts/compactar_amostras.py Collected_Data/lab -o lab_out2026.zpaq.tar --remover-originais\n"
               "  uv run scripts/compactar_amostras.py listar lab_out2026.zpaq.tar\n"
               "  uv run scripts/compactar_amostras.py extrair lab_out2026.zpaq.tar T7c_10min.bin -d /tmp/x\n"
               "  uv run scripts/compactar_amostras.py verificar lab_out2026.zpaq.tar\n"
               "Sem comando, o primeiro argumento é uma pasta e o comando é 'compactar'.",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="comando", metavar="{compactar,extrair,listar,verificar}")

    c = sub.add_parser("compactar", help="compacta pastas/arquivos num pacote (o padrão)",
                       description="Compacta tudo o que houver nas pastas dadas (recursivamente) num pacote .zpaq.tar. "
                                   "O pacote é relido e conferido inteiro antes de ganhar o nome final.")
    c.add_argument("caminhos", nargs="+", type=Path, metavar="PASTA_OU_ARQUIVO")
    c.add_argument("-o", "--saida", type=Path, help="pacote de saída (padrão: <pasta>_<data>.zpaq.tar aqui)")
    c.add_argument("--rapido", action="store_true",
                   help="xz -9e em vez de zpaq -m5: ~20x mais rápido, pacote ~40 %% maior; não precisa do zpaq")
    c.add_argument("--sem-verificar", action="store_true",
                   help="não reler/descomprimir o pacote no fim (metade do tempo; NÃO recomendado)")
    c.add_argument("--remover-originais", action="store_true",
                   help="depois de verificado, apaga os originais que continuam idênticos (pede confirmação)")
    c.add_argument("-y", "--sim", action="store_true", help="não pergunta nada (para scripts)")
    _flags_processos(c)
    c.add_argument("--memoria", type=float, metavar="GB",
                   help="memória máxima para os compressores (padrão: 70 %% da livre agora)")
    c.add_argument("--excluir", action="append", default=[], metavar="PADRÃO",
                   help="deixa de fora arquivos cujo nome/caminho casa com o padrão (repetível; ex.: '*.png')")
    c.add_argument("--tamanho-peca", type=float, metavar="MB", default=TAMANHO_PECA_MAX / 2**20,
                   help=argparse.SUPPRESS)

    e = sub.add_parser("extrair", help="restaura arquivos de um pacote",
                       description="Restaura os arquivos (todos, ou os que casarem com os padrões), conferindo o SHA-256 "
                                   "de cada um. Padrão: nome do arquivo, caminho, pasta ou curinga ('*100Hz*').")
    e.add_argument("pacote", type=Path)
    e.add_argument("arquivos", nargs="*", metavar="PADRÃO")
    e.add_argument("-d", "--destino", type=Path, default=Path("."), help="pasta de destino (padrão: a atual)")
    e.add_argument("--sobrescrever", action="store_true", help="substitui arquivos que já existem no destino")
    _flags_processos(e)

    ls = sub.add_parser("listar", help="mostra o conteúdo de um pacote (instantâneo)")
    ls.add_argument("pacote", type=Path)
    ls.add_argument("arquivos", nargs="*", metavar="PADRÃO")

    v = sub.add_parser("verificar", help="confere a integridade de um pacote",
                       description="Descomprime tudo (sem gravar nada) e confere o SHA-256 de cada arquivo.")
    v.add_argument("pacote", type=Path)
    v.add_argument("--rapido", action="store_true",
                   help="só confere o SHA-256 das peças comprimidas (segundos; detecta corrupção no disco)")
    _flags_processos(v)
    return p


def _flags_processos(p: argparse.ArgumentParser) -> None:
    p.add_argument("-j", "--processos", type=int, metavar="N",
                   help="compressores em paralelo (padrão: o que couber nos núcleos e na memória)")


def _normalizar_argv(argv: list[str]) -> list[str]:
    """``compactar_amostras.py PASTA`` = ``compactar_amostras.py compactar PASTA``."""
    if argv and argv[0] not in COMANDOS and argv[0] not in ("-h", "--help"):
        return ["compactar", *argv]
    return argv


# ---------------------------------------------------------------------------
# Comandos
# ---------------------------------------------------------------------------
def _titulo(console: Console, subtitulo: str) -> None:
    console.print()
    console.print(Panel(Text.assemble(("SH-Analyzer", f"bold {COR}"), "  ·  arquivamento sem perdas de capturas\n",
                                      (subtitulo, "dim")), box=box.ROUNDED, expand=False, padding=(0, 2)))


def _saida_padrao(caminhos: list[Path], metodo: Metodo) -> Path:
    base = caminhos[0].resolve().name if len(caminhos) == 1 else "capturas"
    data = datetime.now().strftime("%Y-%m-%d")
    candidato = Path(f"{base}_{data}.{metodo.codec}.tar")
    n = 2
    while candidato.exists() or candidato.with_name(candidato.name + SUFIXO_PARCIAL).exists():
        candidato = Path(f"{base}_{data}_{n}.{metodo.codec}.tar")
        n += 1
    return candidato


def _garantir_zpaq(console: Console, interativo: bool) -> None:
    if localizar_zpaq():
        return
    console.print("[yellow]O zpaq (o compressor mais forte) não está instalado.[/]")
    if interativo and shutil.which("apt-get") and Confirm.ask("Instalar agora com [bold]sudo apt install zpaq[/]?",
                                                               default=True, console=console):
        subprocess.run(["sudo", "apt-get", "install", "-y", "zpaq"], check=False)
        if localizar_zpaq():
            return
    raise ErroSHAN("o zpaq não está instalado: sudo apt install zpaq (para compactar sem ele: --rapido, que usa o xz).")


def cmd_compactar(args, console: Console) -> int:
    metodo = METODOS["rapido" if args.rapido else METODO_PADRAO]
    interativo = console.is_terminal and not args.sim
    if args.remover_originais and args.sem_verificar:
        raise ErroUso("--remover-originais exige a verificação (tire --sem-verificar).")
    if args.processos is not None and args.processos < 1:
        raise ErroUso("--processos precisa ser >= 1.")
    if args.tamanho_peca <= 0:
        raise ErroUso("--tamanho-peca precisa ser > 0.")
    tamanho_peca = max(2, int(args.tamanho_peca * 2**20) // 2 * 2)
    if metodo.codec == "zpaq":
        _garantir_zpaq(console, interativo)

    saida = args.saida if args.saida is not None else _saida_padrao(args.caminhos, metodo)
    saida = saida.resolve()
    if saida.is_dir():
        raise ErroUso(f"'{saida}' é uma pasta -- dê o nome do pacote (ex.: {saida / 'capturas.zpaq.tar'}).")
    if saida.exists():
        raise ErroUso(f"'{saida}' já existe -- escolha outro nome com -o.")

    entradas, avisos = descobrir_entradas(args.caminhos, args.excluir, ignorar=[saida])
    _titulo(console, metodo.descricao)
    for a in avisos:
        console.print(f"  [yellow]![/] {a}")
    if not entradas:
        raise ErroSHAN("nenhum arquivo para compactar.")

    total = sum(e.tamanho for e in entradas)
    maior_peca = min(max(e.tamanho for e in entradas), tamanho_peca)
    n_pecas = sum(max(1, -(-e.tamanho // tamanho_peca)) for e in entradas if e.tamanho)
    memoria = int(args.memoria * 1e9) if args.memoria else None
    processos, mem_proc = planejar_processos(metodo, maior_peca, n_pecas, memoria=memoria, pedidos=args.processos)

    # Espaço: as peças (até ~20 % do original) existem duas vezes por um instante (soltas e no tar), e a
    # verificação monta de volta, ao mesmo tempo, até um arquivo grande inteiro por processo.
    estimado = int(total * (0.13 if metodo.codec == "zpaq" else 0.2))
    maior = max(e.tamanho for e in entradas)
    precisa = 2 * estimado + 2 * maior + processos * 3 * maior_peca
    livre = shutil.disk_usage(saida.parent if saida.parent.exists() else Path.cwd()).free
    # Com todos os núcleos lógicos ocupados, cada processo anda ~30 % mais devagar (hyper-threading). A maior peça
    # roda inteira num processo só: com um arquivo grande, é ela que decide o tempo.
    por_processo = metodo.taxa_estimada * (0.7 if processos > (os.cpu_count() or 1) // 2 else 1.0)
    previsao = max(total / max(por_processo * processos, 1), maior_peca / max(por_processo, 1))

    plano = Table.grid(padding=(0, 2))
    plano.add_column(style="bold", no_wrap=True)
    plano.add_column()
    por_tipo = _contar_tipos(entradas)
    plano.add_row("Entrada", f"{', '.join(str(c) for c in args.caminhos)}  —  {len(entradas)} arquivo(s), {fmt_bytes(total)}")
    plano.add_row("", f"[dim]{por_tipo}[/]")
    plano.add_row("Saída", str(saida))
    plano.add_row("Método", f"{metodo.descricao}")
    plano.add_row("Processos", f"{processos} em paralelo  [dim](~{fmt_bytes(mem_proc)} de RAM cada; "
                               f"{fmt_bytes(memoria_disponivel())} livres; prioridade baixa)[/]")
    plano.add_row("Verificação", "[yellow]desligada[/]" if args.sem_verificar else
                  "completa: o pacote é relido, descomprimido e conferido (SHA-256) antes de ficar pronto")
    if args.remover_originais:
        plano.add_row("Originais", "[bold red]serão apagados[/] depois da verificação (pede confirmação)")
    plano.add_row("Previsão", f"~{fmt_duracao(previsao)} para comprimir"
                              + ("" if args.sem_verificar else f" + ~{fmt_duracao(previsao)} para verificar")
                              + "  [dim](Ctrl+C cancela sem deixar nada pela metade)[/]")
    console.print(plano)
    if livre < precisa:
        raise ErroSHAN(f"espaço livre insuficiente em '{saida.parent}': {fmt_bytes(livre)} livres, "
                       f"preciso de ~{fmt_bytes(precisa)}.")
    console.print()

    painel = Painel(console, metodo)
    try:
        res = compactar(entradas, saida, metodo=metodo, processos=processos, memoria_por_processo=mem_proc,
                        verificar=not args.sem_verificar, observador=painel, tamanho_peca=tamanho_peca)
    finally:
        painel.encerrar()
    _relatorio_compactacao(console, res)

    if args.remover_originais:
        _remover(console, res, args, interativo)
    return 0


def _contar_tipos(entradas: list[Entrada]) -> str:
    """Resumo do que foi encontrado, ANTES de ler os cabeçalhos (só pela extensão)."""
    cont = defaultdict(int)
    for e in entradas:
        cont[PurePosixPath(e.nome).suffix.lower() or "(sem extensão)"] += 1
    return "  ·  ".join(f"{n} {ext}" for ext, n in sorted(cont.items(), key=lambda kv: -kv[1]))


def _relatorio_compactacao(console: Console, res: Resultado) -> None:
    grupos: dict[str, list[Entrada]] = defaultdict(list)
    for e in res.entradas:
        grupos[str(PurePosixPath(e.nome).parent)].append(e)
    t = Table(box=box.SIMPLE_HEAD, show_edge=False, pad_edge=False, header_style="bold")
    t.add_column("Pasta")
    t.add_column("Arquivos", justify="right")
    t.add_column("Original", justify="right")
    t.add_column("Compactado", justify="right")
    t.add_column("% do original", justify="right")
    t.add_column("bit/amostra", justify="right", style="dim")
    for pasta, es in sorted(grupos.items()):
        orig = sum(e.tamanho for e in es)
        comp = sum(e.bytes_comprimidos for e in es)
        t.add_row(pasta, str(len(es)), fmt_bytes(orig), fmt_bytes(comp),
                  fmt_pct(100 * comp / orig) if orig else "—", _bits_por_amostra(es))
    console.print()
    console.print(t)

    linhas = Text()
    linhas.append(f"{res.saida}\n", style="bold")
    linhas.append(f"{fmt_bytes(res.bytes_originais)} → {fmt_bytes(res.bytes_pacote)}   ")
    linhas.append(fmt_taxa(res.bytes_originais, res.bytes_pacote), style="bold green")
    linhas.append(f"\n{len(res.entradas)} arquivo(s) · comprimido em {fmt_duracao(res.segundos_compressao)}")
    if res.segundos_verificacao is not None:
        linhas.append(f" · verificado em {fmt_duracao(res.segundos_verificacao)}\n")
        linhas.append("✔ todos os arquivos voltam idênticos, bit a bit (SHA-256 conferido)", style="green")
    else:
        linhas.append("\n! não verificado (--sem-verificar): rode 'verificar' antes de confiar nele", style="yellow")
    console.print(Panel(linhas, title="[bold green]Pacote pronto[/]", box=box.ROUNDED, expand=False, padding=(0, 2)))
    console.print(f"[dim]  Para restaurar: uv run scripts/compactar_amostras.py extrair {_citar(res.saida)}[/]")


def _bits_por_amostra(es: list[Entrada]) -> str:
    """Bits comprimidos por amostra das capturas SHAN da pasta (a medida natural para um ADC de 16 bits; os
    outros arquivos da pasta -- .csv, logs -- ficam de fora da conta)."""
    capturas = [e for e in es if e.captura is not None and e.tamanho > 1024]
    if not capturas:
        return ""
    amostras = sum((e.tamanho - 1024) // 2 for e in capturas)
    return f"{8 * sum(e.bytes_comprimidos for e in capturas) / max(amostras, 1):.2f}".replace(".", ",")


def _citar(p: Path) -> str:
    try:
        p = p.relative_to(Path.cwd())
    except ValueError:
        pass
    s = str(p)
    return f"'{s}'" if any(ch in s for ch in " '\"$&()") else s


def _remover(console: Console, res: Resultado, args, interativo: bool) -> None:
    total = sum(e.tamanho for e in res.entradas)
    console.print()
    console.print(f"[bold red]Apagar os {len(res.entradas)} originais ({fmt_bytes(total)})?[/] "
                  "O pacote foi verificado; cada original é conferido de novo (SHA-256) antes de ser apagado.")
    if not args.sim:
        if not interativo:
            raise ErroUso("--remover-originais sem terminal precisa de --sim (nada foi apagado).")
        if not Confirm.ask("Apagar?", default=False, console=console):
            console.print("  Nada foi apagado.")
            return
    apagados, liberados, avisos = remover_originais(res.entradas, args.caminhos)
    for a in avisos:
        console.print(f"  [yellow]![/] {a}")
    console.print(f"  [green]✔[/] {apagados} arquivo(s) apagado(s), {fmt_bytes(liberados)} liberados.")


def cmd_listar(args, console: Console) -> int:
    pacote = Pacote(args.pacote)
    indices = pacote.selecionar(args.arquivos)
    _cabecalho_pacote(console, pacote)
    t = Table(box=box.SIMPLE_HEAD, show_edge=False, pad_edge=False, header_style="bold")
    t.add_column("Arquivo", overflow="fold")
    t.add_column("Tamanho", justify="right", no_wrap=True)
    t.add_column("Compactado", justify="right", no_wrap=True)
    t.add_column("%", justify="right", no_wrap=True)
    t.add_column("Captura", style="dim", overflow="fold")
    for i in indices:
        e = pacote.entradas[i]
        t.add_row(e.nome, fmt_bytes(e.tamanho), fmt_bytes(e.bytes_comprimidos),
                  fmt_pct(100 * e.bytes_comprimidos / e.tamanho) if e.tamanho else "—", _resumo_captura(e.captura))
    console.print(t)
    if args.arquivos:
        console.print(f"  [dim]{len(indices)} de {len(pacote.entradas)} arquivo(s) casaram com o(s) padrão(ões).[/]")
        if not indices:
            return 1
    return 0


def _cabecalho_pacote(console: Console, pacote: Pacote) -> None:
    m = pacote.manifesto
    orig, comp = pacote.bytes_originais, pacote.caminho.stat().st_size
    texto = Text()
    texto.append(f"{pacote.caminho}\n", style="bold")
    texto.append(f"{len(pacote.entradas)} arquivo(s) · {fmt_bytes(orig)} → {fmt_bytes(comp)}  ")
    texto.append(fmt_taxa(orig, comp), style="green")
    texto.append(f"\ncriado em {m.get('criado_em', '?')} · {m['metodo'].get('programa', m['metodo']['codec'])}", style="dim")
    console.print()
    console.print(Panel(texto, box=box.ROUNDED, expand=False, padding=(0, 2)))


def cmd_verificar(args, console: Console) -> int:
    pacote = Pacote(args.pacote)
    _cabecalho_pacote(console, pacote)
    if pacote.codec == "zpaq" and not args.rapido:
        _garantir_zpaq(console, console.is_terminal)
    painel = Painel(console, METODOS.get(pacote.manifesto["metodo"].get("nome", ""), None))
    try:
        if args.rapido:
            falhas = pacote.verificar_rapido(painel)
        else:
            processos = _processos_leitura(pacote, args.processos)
            falhas = pacote.restaurar(None, None, processos, painel, fase="verificando").falhas
    finally:
        painel.encerrar()
    if falhas:
        _tabela_falhas(console, falhas)
        console.print(f"[bold red]✘ {len(falhas)} arquivo(s) com problema.[/] Use outra cópia do pacote para esses.")
        return 1
    if args.rapido:
        console.print("[green]✔ Todas as peças estão íntegras (SHA-256 das peças comprimidas).[/] "
                      "[dim]Para descomprimir e conferir cada arquivo, rode sem --rapido.[/]")
    else:
        console.print(f"[bold green]✔ Os {len(pacote.entradas)} arquivo(s) voltam idênticos aos originais "
                      "(SHA-256 conferido).[/]")
    return 0


def _processos_leitura(pacote: Pacote, pedidos: int | None) -> int:
    metodo = METODOS.get(pacote.manifesto["metodo"].get("nome", ""), METODOS[METODO_PADRAO])
    maior = max((p.tamanho for e in pacote.entradas for p in e.partes), default=1)
    n = sum(len(e.partes) for e in pacote.entradas)
    return planejar_processos(metodo, maior, n, pedidos=pedidos)[0]


def cmd_extrair(args, console: Console) -> int:
    pacote = Pacote(args.pacote)
    indices = pacote.selecionar(args.arquivos)
    _cabecalho_pacote(console, pacote)
    if not indices:
        raise ErroSHAN(f"nenhum arquivo do pacote casa com {' '.join(args.arquivos)!r} (veja com 'listar').")
    if pacote.codec == "zpaq":
        _garantir_zpaq(console, console.is_terminal)
    destino = args.destino.resolve()
    total = sum(pacote.entradas[i].tamanho for i in indices)
    console.print(f"  Extraindo [bold]{len(indices)}[/] arquivo(s) ({fmt_bytes(total)}) para [bold]{destino}[/]")
    livre = shutil.disk_usage(destino if destino.exists() else Path.cwd()).free
    if livre < 1.1 * total:
        raise ErroSHAN(f"espaço livre insuficiente em '{destino}': {fmt_bytes(livre)}, preciso de ~{fmt_bytes(total)}.")
    console.print()
    processos = _processos_leitura(pacote, args.processos)
    painel = Painel(console, METODOS.get(pacote.manifesto["metodo"].get("nome", ""), None))
    try:
        rel = pacote.restaurar(indices, destino, processos, painel, sobrescrever=args.sobrescrever)
    finally:
        painel.encerrar()
    for nome, motivo in rel.pulados:
        console.print(f"  [yellow]–[/] {nome}: [dim]{motivo}[/]")
    if rel.falhas:
        _tabela_falhas(console, rel.falhas)
    if rel.restaurados:
        console.print(f"  [green]✔[/] {len(rel.restaurados)} arquivo(s) restaurado(s), {fmt_bytes(rel.bytes)}, "
                      "conferidos pelo SHA-256 e com a data e as permissões originais.")
    if rel.pulados:
        console.print(f"  [yellow]{len(rel.pulados)} arquivo(s) pulado(s)[/] (já existiam no destino).")
    return 1 if rel.falhas else 0


def _tabela_falhas(console: Console, falhas: list[tuple[str, str]]) -> None:
    t = Table(box=box.SIMPLE_HEAD, show_edge=False, header_style="bold red")
    t.add_column("Arquivo com problema")
    t.add_column("O que houve")
    for nome, msg in falhas:
        t.add_row(nome, msg)
    console.print(t)


def _ajuda_inicial(console: Console) -> None:
    _titulo(console, "zpaq -m5 + desentrelaçamento dos canais · verificação bit a bit (SHA-256)")
    t = Table.grid(padding=(0, 2))
    t.add_column(style=f"bold {COR}", no_wrap=True)
    t.add_column()
    t.add_row("compactar PASTA...", "compacta tudo o que houver nas pastas num pacote .zpaq.tar (o comando padrão)")
    t.add_row("listar PACOTE", "mostra o que tem dentro (instantâneo)")
    t.add_row("extrair PACOTE [ARQ]", "restaura tudo, ou só os arquivos pedidos (nome, pasta ou curinga)")
    t.add_row("verificar PACOTE", "descomprime tudo e confere o SHA-256 de cada arquivo")
    console.print(t)
    console.print("\n[dim]Exemplo:[/] uv run scripts/compactar_amostras.py Collected_Data\n"
                  "[dim]Ajuda de um comando:[/] uv run scripts/compactar_amostras.py compactar -h")


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    console = Console(highlight=False)
    erro = Console(stderr=True, highlight=False)
    if not argv:
        _ajuda_inicial(console)
        return 0
    parser = montar_parser()
    # parse_known_args + sobras: 'extrair PACOTE -d DEST arq1 arq2' (padrões DEPOIS das opções) -- o argparse
    # sozinho não aceita um posicional nargs='*' depois de uma opção, e parse_intermixed_args não aceita subcomandos.
    args, sobras = parser.parse_known_args(_normalizar_argv(argv))
    if sobras:
        if args.comando in ("extrair", "listar") and not any(s.startswith("-") for s in sobras):
            args.arquivos.extend(sobras)
        else:
            parser.error(f"argumentos não reconhecidos: {' '.join(sobras)}")
    comandos = {"compactar": cmd_compactar, "extrair": cmd_extrair, "listar": cmd_listar, "verificar": cmd_verificar}
    try:
        return comandos[args.comando](args, console)
    except ErroUso as e:
        parser.error(str(e))
    except ErroSHAN as e:
        erro.print(f"[bold red]Erro:[/] {e}")
        return 1
    except KeyboardInterrupt:
        erro.print("\n[yellow]Interrompido.[/] Nada ficou pela metade: os temporários e o pacote parcial foram apagados.")
        return 130
    return 0
