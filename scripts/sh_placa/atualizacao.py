"""A atualização do firmware da placa (docs/gui-plan.md, 11.10; a F6.2): o ``firmware/`` deste aplicativo (ou uma
cópia anterior guardada na placa, ou o próprio código da placa, compilado de novo) vai para a placa, compila, é
instalado, carregado na PRU e conferido; se instalar, carregar ou conferir falha, a placa **volta sozinha** à cópia de
segurança e confere de novo.

**O firmware deste aplicativo** (:func:`firmware_do_aplicativo`): rodando do repositório, os arquivos do
``git ls-files firmware`` como estão na árvore de trabalho e a versão do ``git describe`` (com ``-dirty`` e a lista
das mudanças, se o ``firmware/`` tem mudanças não commitadas: a versão gravada em cada captura teria de apontar para um
código que não existe, e a interface avisa); no instalador, a pasta ``firmware/`` que vai junto, com a ``VERSAO``
gravada na construção.

**O plano** (:func:`planejar`): os arquivos novos, os mudados e os iguais, pelo hash (o agente o calcula na placa);
só os novos e os mudados vão pelo SFTP, e os iguais são copiados na placa. Os arquivos do código da placa que não
estão no firmware novo ficam (são listados: nada que não é do firmware é apagado).

**Na placa**, numa tarefa destacada (``tarefas.py``: o cabo pode cair no meio), com os passos:

1. ``preparar`` -- a pasta de preparação (``~/.sh-analyzer/preparo/<id>``), com os arquivos enviados e os iguais, cada
   um conferido pelo hash, e a ``VERSAO``;
2. ``compilar`` -- o ``make`` na preparação, como o usuário (no ambiente do terminal, como o ``setup`` do
   ``BeagleBone_Setup.sh``); **uma falha aqui não toca em nada**;
3. ``guardar`` -- a cópia de segurança em ``~/firmware-anteriores/<data>_<versão>/`` (o lugar do ``enviar``): o código
   da placa, os binários, a ``VERSAO`` e o firmware instalado na PRU (``am335x-pru0-fw.instalado``);
4. ``instalar`` -- os arquivos do código e os binários na pasta do firmware, um por um, cada um com o ``mv`` (quem lê
   nunca vê um arquivo pela metade); **nunca uma captura nem outro arquivo do usuário**;
5. ``carregar`` -- o ``fw_pru.out`` em ``/lib/firmware/am335x-pru0-fw`` (o sudo, com o ``install -m 0644``: o kernel
   lê o firmware com as credenciais de quem pede o ``start``, e um arquivo só do root dá o -13 na placa de verdade), os
   pinos (o ``config-pin``) e a PRU parada e ligada de novo (o ``state`` do remoteproc, que o grupo ``remoteproc``
   escreve sem o sudo);
6. ``conferir`` -- a versão, o firmware da PRU igual ao compilado, a PRU rodando e uma captura de um bloco com o
   ``ler_adc`` novo (o código 4, o ADC sem resposta, é um aviso: a placa de aquisição sem os 5 V não é culpa do
   firmware);
7. ``limpar`` -- a preparação e a captura da conferência apagadas.

Se 4, 5 ou 6 falha: ``voltar`` -- a cópia de segurança de volta (os arquivos e o firmware da PRU), os arquivos que a
versão nova trouxe tirados, e a conferência de novo. **Os códigos da tarefa:** 0, atualizada; 1, falhou antes de mudar
a placa; 2, voltou à versão anterior; 3, falhou e não conseguiu voltar (a placa precisa de alguém: a cópia está no
resultado).
"""

from __future__ import annotations

import hashlib
import logging
import re
import shlex
import subprocess
import sys
import time
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

from .agente import PASTA_DO_FIRMWARE, ClienteDoAgente, ErroDaPlaca
from .correcoes import com_sudo
from .tarefas import EstadoDaTarefa, TarefaNaPlaca, novo_id
from .versao import CAMINHOS_DO_FIRMWARE, RAIZ_DO_REPOSITORIO

if TYPE_CHECKING:                       # só a anotação: este módulo não carrega o asyncssh
    from .conexao import ConexaoSSH

log = logging.getLogger(__name__)

TIPO = "atualizar-firmware"
PASTA_DA_PREPARACAO = ".sh-analyzer/preparo"
PASTA_DAS_ANTERIORES = PASTA_DO_FIRMWARE + "-anteriores"
BINARIOS = ("ler_adc", "fw_pru.out")
PRU_INSTALADA_NA_COPIA = "am335x-pru0-fw.instalado"
FIRMWARE_DA_PRU = "/lib/firmware/am335x-pru0-fw"
PINOS = (("P9_31", "pruout"), ("P9_29", "pruout"), ("P9_30", "pruin"), ("P9_28", "pruout"))
"""Os pinos da PRU e os modos, na ordem do ``firmware/setup.sh`` (``tests/test_sh_placa_atualizacao.py`` confere)."""
TAXA_DA_CONFERENCIA = 400_000
PASSOS = (("enviar", "Enviar os arquivos"), ("preparar", "Preparar"), ("compilar", "Compilar"),
          ("guardar", "Guardar a cópia de segurança"), ("instalar", "Instalar"), ("carregar", "Carregar na PRU"),
          ("conferir", "Conferir"), ("limpar", "Concluir"), ("voltar", "Voltar à versão anterior"))
"""Os passos, na ordem, com o nome que a interface mostra (o ``enviar`` é do computador, antes da tarefa)."""
ATUALIZADA, FALHOU_ANTES, VOLTOU, FALHOU_AO_VOLTAR = 0, 1, 2, 3
DESFECHOS = {ATUALIZADA: "atualizada", FALHOU_ANTES: "falhou_antes", VOLTOU: "voltou",
             FALHOU_AO_VOLTAR: "falhou_ao_voltar"}
_COPIA = re.compile(r"^[A-Za-z0-9._-]{1,120}$")
_VERSAO = re.compile(r"[^A-Za-z0-9._-]")


# ------------------------------------------------------------------ o firmware que vai

@dataclass(frozen=True)
class ArquivoDoFirmware:
    caminho: str                          # relativo à pasta do firmware, com "/"
    conteudo: bytes
    executavel: bool = False

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.conteudo).hexdigest()


@dataclass(frozen=True)
class FirmwareParaEnviar:
    """O firmware que vai para a placa: a ``versao`` (gravada na ``VERSAO`` dela), de onde vem (``"repositorio"``,
    ``"pacote"``, ``"anterior"`` ou ``"placa"``), os arquivos do código (no repositório e no pacote, com o conteúdo;
    numa cópia da placa e na própria placa, só os caminhos e os hashes, que já estão lá) e as mudanças não
    commitadas (no repositório)."""

    versao: str
    origem: str
    arquivos: tuple[ArquivoDoFirmware, ...] = ()
    mudancas: tuple[str, ...] = ()
    pasta_na_placa: str | None = None            # "anterior" e "placa": de onde a placa copia (relativa ao home)
    hashes_na_placa: tuple[tuple[str, str], ...] = ()     # (caminho no firmware, caminho na pasta de origem)

    @property
    def sujo(self) -> bool:
        return bool(self.mudancas)

    @property
    def caminhos(self) -> tuple[str, ...]:
        if self.arquivos:
            return tuple(a.caminho for a in self.arquivos)
        return tuple(destino for destino, _origem in self.hashes_na_placa)


def _ler_pasta(pasta: Path) -> tuple[ArquivoDoFirmware, ...]:
    arquivos = []
    for caminho in sorted(pasta.rglob("*")):
        rel = caminho.relative_to(pasta).as_posix()
        if caminho.is_file() and rel != "VERSAO" and "__pycache__" not in rel:
            arquivos.append(ArquivoDoFirmware(rel, caminho.read_bytes(), bool(caminho.stat().st_mode & 0o111)))
    return tuple(arquivos)


def firmware_do_aplicativo(raiz: Path = RAIZ_DO_REPOSITORIO) -> FirmwareParaEnviar | None:
    """O ``firmware/`` deste aplicativo (ver o módulo); ``None`` fora de um repositório e sem a pasta do pacote."""
    pacote = Path(getattr(sys, "_MEIPASS", "")) / "firmware" if getattr(sys, "frozen", False) else None
    if pacote is not None and (pacote / "VERSAO").is_file():
        return FirmwareParaEnviar((pacote / "VERSAO").read_text(encoding="utf-8").strip() or "sem-versao", "pacote",
                                  _ler_pasta(pacote))
    try:
        lista = subprocess.run(["git", "-C", str(raiz), "ls-files", "-z", "--", "firmware"], capture_output=True,
                               timeout=10, check=True).stdout
        descricao = subprocess.run(["git", "-C", str(raiz), "describe", "--always"], capture_output=True, text=True,
                                   timeout=10, check=True).stdout.strip()
        status = subprocess.run(["git", "-C", str(raiz), "status", "--porcelain", "--", *CAMINHOS_DO_FIRMWARE],
                                capture_output=True, text=True, timeout=10, check=True).stdout
    except (OSError, subprocess.SubprocessError) as e:
        log.info("sem o firmware do repositório (%s)", e)
        return None
    arquivos = []
    for nome in sorted(x for x in lista.decode("utf-8", "replace").split("\0") if x):
        caminho = raiz / nome
        rel = PurePosixPath(nome).relative_to("firmware").as_posix()
        if rel == "VERSAO" or not caminho.is_file():
            continue                         # um arquivo apagado na árvore de trabalho não vai
        arquivos.append(ArquivoDoFirmware(rel, caminho.read_bytes(), bool(caminho.stat().st_mode & 0o111)))
    mudancas = tuple(linha[3:] for linha in status.splitlines() if linha.strip())
    return FirmwareParaEnviar(f"{descricao}-dirty" if mudancas else descricao, "repositorio", tuple(arquivos),
                              mudancas)


@dataclass(frozen=True)
class CopiaAnterior:
    """Uma cópia de segurança na placa (o ``anteriores`` do agente)."""

    nome: str
    versao: str | None
    bytes: int
    modificado: float | None
    arquivos: tuple[str, ...]
    codigo: bool                          # tem o código para compilar (o ler_adc.c e o Makefile)
    binarios: bool
    pru_instalada: bool

    @classmethod
    def do_agente(cls, d: dict) -> CopiaAnterior:
        return cls(str(d["nome"]), d.get("versao"), int(d.get("bytes") or 0), d.get("modificado"),
                   tuple(d.get("arquivos") or ()), bool(d.get("codigo")), bool(d.get("binarios")),
                   bool(d.get("pru_instalada")))


async def copias_anteriores(cliente: ClienteDoAgente) -> list[CopiaAnterior]:
    resposta = await cliente.chamar("anteriores")
    return [CopiaAnterior.do_agente(c) for c in resposta.get("copias") or ()]


def firmware_da_copia(copia: CopiaAnterior, subpastas: dict[str, str] | None = None) -> FirmwareParaEnviar:
    """O firmware de uma cópia anterior da placa, para voltar a ela. As do ``enviar`` guardam os arquivos das
    subpastas no alto (``comum.sh``, e não ``coleta/comum.sh``): ``subpastas`` diz onde cada nome vai (o do firmware
    deste aplicativo, :func:`subpastas_do_firmware`)."""
    if not copia.codigo:
        raise ValueError(f"a cópia {copia.nome} não tem o código do firmware (o ler_adc.c e o Makefile)")
    subpastas = subpastas or {}
    pares = []
    for rel in copia.arquivos:
        if rel in (*BINARIOS, "VERSAO", PRU_INSTALADA_NA_COPIA) or rel.endswith((".obj", ".map", ".o", ".bin")):
            continue
        destino = subpastas.get(rel, rel) if "/" not in rel else rel
        pares.append((destino, rel))
    return FirmwareParaEnviar(copia.versao or "sem-versao", "anterior", (), (),
                              f"{PASTA_DAS_ANTERIORES}/{copia.nome}", tuple(sorted(pares)))


def subpastas_do_firmware(firmware: FirmwareParaEnviar | None) -> dict[str, str]:
    """``{"comum.sh": "coleta/comum.sh", …}``: onde fica cada arquivo das subpastas do firmware deste aplicativo."""
    if firmware is None:
        return {}
    return {PurePosixPath(c).name: c for c in firmware.caminhos if "/" in c}


# ------------------------------------------------------------------ o plano

@dataclass(frozen=True)
class PlanoDeAtualizacao:
    firmware: FirmwareParaEnviar
    versao_da_placa: str | None
    novos: tuple[str, ...]                # não estão na placa
    mudados: tuple[str, ...]
    iguais: tuple[str, ...]
    sobrando: tuple[str, ...]             # do código da placa, fora do firmware novo (ficam)
    codigo_da_placa: tuple[str, ...]      # o que a cópia de segurança guarda
    bytes_a_enviar: int
    pru_igual: bool | None                # o firmware instalado na PRU é o compilado na placa

    @property
    def nada_muda(self) -> bool:
        """O código da placa é o que iria (pelo hash): o texto da versão não importa (o ``git describe`` muda a cada
        commit do repositório, mesmo sem mudança no firmware; como no ``versao.py``)."""
        return not self.novos and not self.mudados


async def planejar(cliente: ClienteDoAgente, firmware: FirmwareParaEnviar) -> PlanoDeAtualizacao:
    """Compara, pelo hash, o firmware que vai com o código da placa (o agente o calcula lá)."""
    placa = await cliente.chamar("firmware_arquivos")
    dela = {rel: (d or {}).get("sha256") for rel, d in (placa.get("arquivos") or {}).items() if d}
    binarios = placa.get("binarios") or {}
    instalada = (placa.get("pru_instalada") or {}).get("sha256")
    fw_pru = (binarios.get("fw_pru.out") or {}).get("sha256")
    pru_igual = None if not instalada or not fw_pru else instalada == fw_pru
    if firmware.origem in ("anterior", "placa"):
        caminhos = firmware.caminhos
        return PlanoDeAtualizacao(firmware, placa.get("versao"), (), (), caminhos,
                                  tuple(sorted(set(dela) - set(caminhos))), tuple(sorted(dela)), 0, pru_igual)
    novos, mudados, iguais = [], [], []
    for a in firmware.arquivos:
        if a.caminho not in dela:
            novos.append(a.caminho)
        elif dela[a.caminho] != a.sha256:
            mudados.append(a.caminho)
        else:
            iguais.append(a.caminho)
    vao = set(novos) | set(mudados)
    return PlanoDeAtualizacao(firmware, placa.get("versao"), tuple(novos), tuple(mudados), tuple(iguais),
                              tuple(sorted(set(dela) - {a.caminho for a in firmware.arquivos})), tuple(sorted(dela)),
                              sum(len(a.conteudo) for a in firmware.arquivos if a.caminho in vao), pru_igual)


# ------------------------------------------------------------------ o roteiro da placa

def _lista(nome: str, itens: Iterable[str]) -> str:
    return f"{nome}=(" + " ".join(shlex.quote(i) for i in itens) + ")\n"


def _versao_no_nome(versao: str | None) -> str:
    return _VERSAO.sub("", versao or "")[:64] or "sem-versao"


_ROTEIRO = r"""F="$HOME/{pasta}"
P="$HOME/{preparo}"
A="$HOME/{anteriores}"
ORIGEM="$HOME/{origem}"
R="${{SHAN_RAIZ:-}}"
RPROC="$R/sys/class/remoteproc/remoteproc1"
INSTALADO="$R{firmware_da_pru}"
VERSAO_NOVA={versao_nova}
VERSAO_ANTIGA={versao_antiga}
{listas}
C=
falhar() {{ passo "$1" falhou "$2"; exit {falhou_antes}; }}
ultimas() {{ tail -n 3 "$1" 2>/dev/null | tr '\n' ' ' | cut -c1-300; }}

# ---- preparar: a pasta da preparação com o código novo, conferido pelo hash
passo preparar comecou "a pasta da preparação"
if pgrep -x ler_adc > /dev/null 2>&1; then falhar preparar "uma captura está rodando (ler_adc): espere ela terminar"; fi
mkdir -p "$P" || falhar preparar "não deu para criar $P"
i=0
while [ "$i" -lt "${{#DESTINOS[@]}}" ]; do
    d=${{DESTINOS[$i]}}; o=${{ORIGENS[$i]}}
    mkdir -p "$P/$(dirname "$d")"
    cp -p "$ORIGEM/$o" "$P/$d" || falhar preparar "não deu para copiar $o para a preparação"
    i=$((i + 1))
done
if [ "${{#HASHES[@]}}" -gt 0 ]; then
    ( cd "$P" && printf '%s\n' "${{HASHES[@]}}" | sha256sum -c --quiet - ) \
        || falhar preparar "um arquivo chegou diferente do enviado (o cabo?): nada foi mudado na placa"
fi
printf '%s\n' "$VERSAO_NOVA" > "$P/VERSAO"
passo preparar ok "${{#CODIGO[@]}} arquivos"

# ---- compilar: como o usuário, no ambiente do terminal (o compilador da PRU vem dos perfis)
passo compilar comecou "make"
if [ -z "$R" ]; then
    _caminho=$PATH
    for f in /etc/profile "$HOME/.profile"; do if [ -r "$f" ]; then . "$f" > /dev/null 2>&1; fi; done
    linha=$(bash -ic 'printf "\nSH-ANALYZER|%s|%s|%s\n" "${{PRU_CGT:-}}" "${{PRU_C_DIR:-}}" "${{C_DIR:-}}"' 2>/dev/null \
            < /dev/null | grep '^SH-ANALYZER|' | tail -n 1)
    IFS='|' read -r _ i_cgt i_cdir i_c <<< "$linha"
    if [ -z "${{PRU_CGT:-}}" ] && [ -n "$i_cgt" ]; then export PRU_CGT="$i_cgt"; fi
    if [ -z "${{PRU_C_DIR:-}}" ] && [ -n "$i_cdir" ]; then export PRU_C_DIR="$i_cdir"; fi
    if [ -z "${{C_DIR:-}}" ] && [ -n "$i_c" ]; then export C_DIR="$i_c"; fi
    PATH="$_caminho:$PATH"
fi
( cd "$P" && make clean > /dev/null 2>&1; cd "$P" && make ) > "$P/.make.log" 2>&1
c=$?
cat "$P/.make.log"
[ "$c" -eq 0 ] || falhar compilar "o make falhou (código $c): $(ultimas "$P/.make.log") O firmware da placa não foi tocado."
[ -x "$P/ler_adc" ] && [ -f "$P/fw_pru.out" ] || falhar compilar "o make terminou sem o ler_adc e o fw_pru.out"
passo compilar ok "ler_adc e fw_pru.out"

# ---- guardar: a cópia de segurança (o código da placa, os binários, a VERSAO e o firmware instalado na PRU)
passo guardar comecou
C="$A/{carimbo}_$(printf '%s' "$VERSAO_ANTIGA" | tr -cd 'A-Za-z0-9._-' | cut -c1-64)"
[ -n "$VERSAO_ANTIGA" ] || C="${{C}}sem-versao"
mkdir -p "$C" || falhar guardar "não deu para criar a cópia em $C (o cartão está cheio?)"
for f in "${{DA_PLACA[@]}}" {binarios} VERSAO; do
    if [ -e "$F/$f" ]; then
        mkdir -p "$C/$(dirname "$f")"
        cp -p "$F/$f" "$C/$f" || falhar guardar "não deu para guardar $f (o cartão está cheio?)"
    fi
done
if [ -f "$INSTALADO" ]; then cp -p "$INSTALADO" "$C/{pru_na_copia}" || falhar guardar "não deu para guardar o firmware da PRU"; fi
resultado copia "$C"
passo guardar ok "$C"

# ---- daqui em diante a placa muda: uma falha volta à cópia
instalar() {{
    passo instalar comecou "${{#CODIGO[@]}} arquivos, os binários e a VERSAO"
    for f in "${{CODIGO[@]}}" {binarios} VERSAO; do
        mkdir -p "$F/$(dirname "$f")" || return 1
        cp -p "$P/$f" "$F/$f.shan-novo" && mv -f "$F/$f.shan-novo" "$F/$f" || {{ rm -f "$F/$f.shan-novo"; return 1; }}
    done
    passo instalar ok
}}
pru() {{   # pru start|stop|NOME: o state (ou o firmware) do remoteproc; sem o grupo remoteproc, pelo sudo
    alvo="$RPROC/state"; [ "$1" = start ] || [ "$1" = stop ] || alvo="$RPROC/firmware"
    printf '%s\n' "$1" | tee "$alvo" > /dev/null 2>&1 || printf '%s\n' "$1" | sudo -n tee "$alvo" > /dev/null
}}
carregar() {{   # carregar FW_PRU: instala, põe os pinos e liga a PRU de novo
    passo carregar comecou "{firmware_da_pru}"
    [ -d "$RPROC" ] || {{ passo carregar falhou "a PRU0 não existe ($RPROC): o overlay da PRU no /boot/uEnv.txt"; return 1; }}
    como_root install -m 0644 "$1" "$INSTALADO.shan-novo" && como_root mv -f "$INSTALADO.shan-novo" "$INSTALADO" \
        || {{ passo carregar falhou "não deu para instalar o firmware da PRU (o sudo?)"; return 1; }}
{pinos}    if [ "$(cat "$RPROC/state" 2>/dev/null)" = running ]; then pru stop; fi
    pru am335x-pru0-fw
    pru start || {{ passo carregar falhou "a PRU0 não ligou com o firmware novo ($(cat "$RPROC/state" 2>/dev/null))"; return 1; }}
    [ "$(cat "$RPROC/state" 2>/dev/null)" = running ] || {{ passo carregar falhou "a PRU0 ficou '$(cat "$RPROC/state")'"; return 1; }}
    passo carregar ok "a PRU0 rodando"
}}
conferir() {{   # conferir VERSAO: a versão, o firmware da PRU, a PRU e uma captura de um bloco
    passo conferir comecou "a versão, a PRU e uma captura de um bloco"
    [ "$(cat "$F/VERSAO" 2>/dev/null)" = "$1" ] || {{ passo conferir falhou "a VERSAO da placa não é $1"; return 1; }}
    cmp -s "$F/fw_pru.out" "$INSTALADO" || {{ passo conferir falhou "o firmware da PRU não é o compilado"; return 1; }}
    rm -f "$P/conferencia.bin" 2> /dev/null
    cd "$F" || {{ passo conferir falhou "a pasta $F sumiu"; return 1; }}
    como_root ./ler_adc {taxa} 0,1 --blocos 1 -o "$P/conferencia.bin" -t "Conferência da atualização" \
        > "$P/conferencia.txt" 2>&1         # no shell que validou o sudo (num subshell, a credencial não vale)
    c=$?
    cd "$HOME"
    cat "$P/conferencia.txt"
    como_root rm -f "$P/conferencia.bin"
    if [ "$c" -eq 4 ]; then
        passo conferir aviso "o firmware capturou, mas o ADC não respondeu: a placa de aquisição está sem os 5 V?"
        return 0
    fi
    [ "$c" -eq 0 ] || {{ passo conferir falhou "o ler_adc não capturou (código $c): $(ultimas "$P/conferencia.txt")"; return 1; }}
    passo conferir ok "o ler_adc capturou um bloco"
}}
voltar() {{
    passo voltar comecou "a cópia $C"
    ok=1
    for f in "${{NOVOS[@]}}"; do rm -f "$F/$f"; done
    ( cd "$C" && find . -type f ! -name {pru_na_copia} ) | while IFS= read -r f; do
        f=${{f#./}}
        mkdir -p "$F/$(dirname "$f")"
        cp -p "$C/$f" "$F/$f.shan-novo" && mv -f "$F/$f.shan-novo" "$F/$f" || echo "não voltou: $f" >&2
    done
    fw="$C/{pru_na_copia}"; [ -f "$fw" ] || fw="$F/fw_pru.out"
    if [ -f "$fw" ]; then carregar "$fw" || ok=0; else ok=0; fi
    if [ "$ok" -eq 1 ] && [ -f "$F/ler_adc" ]; then conferir "$(cat "$F/VERSAO" 2>/dev/null)" || ok=0; fi
    if [ "$ok" -eq 1 ]; then
        passo voltar ok "a placa voltou a $(cat "$F/VERSAO" 2>/dev/null)"
        resultado versao "$(cat "$F/VERSAO" 2>/dev/null)"
        rm -rf "$P"
        exit {voltou}
    fi
    passo voltar falhou "a placa não voltou sozinha: a cópia está em $C"
    exit {falhou_ao_voltar}
}}
instalar || voltar
carregar "$F/fw_pru.out" || voltar
conferir "$VERSAO_NOVA" || voltar

# ---- limpar
passo limpar comecou
rm -rf "$P"
resultado versao "$VERSAO_NOVA"
passo limpar ok "a placa está com $VERSAO_NOVA"
exit {atualizada}
"""


def roteiro_da_atualizacao(plano: PlanoDeAtualizacao, id_: str, carimbo: str | None = None) -> str:
    """O roteiro da tarefa (ver o módulo; a interface o mostra no "Ver o roteiro"). Os arquivos que vão pelo SFTP
    (os novos e os mudados) já estão na preparação quando ele roda (:func:`enviar`); os outros, ele copia da origem
    (a pasta do firmware, ou a cópia anterior). ``carimbo``: a data no nome da cópia de segurança, do relógio deste
    computador (o da placa pode estar errado: ela não tem bateria no relógio), como o ``enviar``."""
    carimbo = carimbo or time.strftime("%Y-%m-%d_%H%M%S")
    if not re.fullmatch(r"[0-9_-]{1,32}", carimbo):
        raise ValueError(f"carimbo inválido: {carimbo!r}")
    f = plano.firmware
    if f.origem in ("anterior", "placa"):
        pares = list(f.hashes_na_placa)
        origem = f.pasta_na_placa or PASTA_DO_FIRMWARE
        hashes: list[str] = []
    else:
        pares = [(c, c) for c in plano.iguais]
        origem = PASTA_DO_FIRMWARE
        hashes = [f"{a.sha256}  {a.caminho}" for a in f.arquivos]
    novos = [c for c in f.caminhos if c not in plano.codigo_da_placa]
    pinos = "".join(f"    config-pin {pino} {modo} > /dev/null || {{ passo carregar falhou \"o config-pin {pino} "
                    f"{modo} falhou\"; return 1; }}\n" for pino, modo in PINOS)
    listas = (_lista("CODIGO", f.caminhos) + _lista("DESTINOS", [d for d, _o in pares])
              + _lista("ORIGENS", [o for _d, o in pares]) + _lista("HASHES", hashes)
              + _lista("DA_PLACA", plano.codigo_da_placa) + _lista("NOVOS", novos))
    return _ROTEIRO.format(pasta=PASTA_DO_FIRMWARE, preparo=f"{PASTA_DA_PREPARACAO}/{id_}",
                           anteriores=PASTA_DAS_ANTERIORES, origem=origem, firmware_da_pru=FIRMWARE_DA_PRU,
                           versao_nova=shlex.quote(f.versao), versao_antiga=shlex.quote(plano.versao_da_placa or ""),
                           listas=listas, binarios=" ".join(BINARIOS), pru_na_copia=PRU_INSTALADA_NA_COPIA,
                           pinos=pinos, taxa=TAXA_DA_CONFERENCIA, atualizada=ATUALIZADA, falhou_antes=FALHOU_ANTES,
                           voltou=VOLTOU, falhou_ao_voltar=FALHOU_AO_VOLTAR, carimbo=carimbo)


async def enviar(conexao: ConexaoSSH, plano: PlanoDeAtualizacao, id_: str, ao_enviar=None) -> int:
    """Os arquivos novos e os mudados para a preparação na placa, pelo SFTP (``ao_enviar(feitos, total)`` a cada
    um); devolve os bytes enviados. A preparação começa vazia: um envio cortado se refaz do zero."""
    f = plano.firmware
    if f.origem in ("anterior", "placa"):
        return 0
    preparo = f"{PASTA_DA_PREPARACAO}/{id_}"
    r = await conexao.executar(f'rm -rf {shlex.quote(preparo)} && mkdir -p {shlex.quote(preparo)} && printf "%s" "$HOME"',
                               descricao="preparar a pasta da atualização do firmware")
    if r.codigo != 0 or not r.saida.startswith("/"):
        raise ErroDaPlaca(f"não deu para criar ~/{preparo} na placa: {(r.erro or r.saida).strip()[:200]}")
    absoluta = f"{r.saida.rstrip('/')}/{preparo}"   # o SFTP com o caminho inteiro (o do simulador não começa no home)
    vao = [a for a in f.arquivos if a.caminho in set(plano.novos) | set(plano.mudados)]
    sftp = await conexao.sftp()
    total = 0
    for i, a in enumerate(vao):
        destino = f"{absoluta}/{a.caminho}"
        pasta = str(PurePosixPath(destino).parent)
        await sftp.makedirs(pasta, exist_ok=True)
        async with sftp.open(destino, "wb") as arquivo:
            await arquivo.write(a.conteudo)
        await sftp.chmod(destino, 0o755 if a.executavel else 0o644)
        total += len(a.conteudo)
        if ao_enviar is not None:
            ao_enviar(i + 1, len(vao))
    conexao.registrar_fato(f"enviados {len(vao)} arquivo(s) do firmware {f.versao} para ~/{preparo} ({total} bytes)")
    return total


async def atualizar(conexao: ConexaoSSH, plano: PlanoDeAtualizacao, senha_do_sudo: str, *, id_: str | None = None,
                    ao_enviar=None) -> TarefaNaPlaca:
    """Envia o que muda e lança a tarefa da atualização (destacada; acompanhe com :meth:`TarefaNaPlaca.acompanhar`
    e leia o desfecho com :func:`desfecho`)."""
    id_ = id_ or novo_id(TIPO)
    await enviar(conexao, plano, id_, ao_enviar)
    titulo = {"anterior": f"Voltar o firmware a {plano.firmware.versao}",
              "placa": "Compilar e carregar de novo o firmware da placa"}.get(
        plano.firmware.origem, f"Atualizar o firmware para {plano.firmware.versao}")
    return await TarefaNaPlaca.lancar(conexao, TIPO, titulo, roteiro_da_atualizacao(plano, id_),
                                      senha_do_sudo=senha_do_sudo, id_=id_)


@dataclass(frozen=True)
class Desfecho:
    """Como a atualização terminou: :data:`DESFECHOS` (ou ``"interrompida"``, ``"rodando"``), a versão da placa no
    fim, a cópia de segurança e a frase do que aconteceu (o passo que falhou, com o porquê)."""

    estado: str
    versao: str | None
    copia: str | None
    mensagem: str
    aviso: str = ""


def desfecho(e: EstadoDaTarefa) -> Desfecho:
    copia, versao = e.resultado.get("copia"), e.resultado.get("versao")
    falha = next((p for p in reversed(e.passos) if p.estado == "falhou"), None)
    aviso = next((p.texto for p in e.passos if p.estado == "aviso"), "")
    por_que = f"{dict(PASSOS).get(falha.nome, falha.nome)}: {falha.texto}" if falha else ""
    if e.interrompida:
        ultimo = e.passos[-1].nome if e.passos else "preparar"
        return Desfecho("interrompida", versao, copia,
                        f"a atualização foi interrompida no passo {dict(PASSOS).get(ultimo, ultimo)} (a placa "
                        f"desligou ou reiniciou?)" + (f"; a cópia de segurança está em {copia}" if copia else ""))
    if not e.terminou:
        return Desfecho("rodando", versao, copia, "a atualização ainda roda na placa")
    estado = DESFECHOS.get(e.codigo, "falhou_antes")
    if estado == "atualizada":
        return Desfecho(estado, versao, copia, f"o firmware da placa é o {versao}", aviso)
    if estado == "voltou":
        return Desfecho(estado, versao, copia, f"o firmware novo falhou ({por_que}); a placa voltou a {versao}", aviso)
    if estado == "falhou_ao_voltar":
        return Desfecho(estado, versao, copia, f"o firmware novo falhou e a placa não voltou sozinha ({por_que}); a "
                                               f"cópia de segurança está em {copia}")
    return Desfecho(estado, versao, copia, f"nada mudou na placa ({por_que or f'código {e.codigo}'})")


# ------------------------------------------------------------------ as outras ações do firmware

_RECARREGAR = r"""R="${{SHAN_RAIZ:-}}"
RPROC="$R/sys/class/remoteproc/remoteproc1"
F="$HOME/{pasta}"
[ -d "$RPROC" ] || {{ echo "a PRU0 não existe ($RPROC): confira o overlay da PRU no /boot/uEnv.txt" >&2; exit 1; }}
[ -f "$F/fw_pru.out" ] || {{ echo "não há o $F/fw_pru.out: compile o firmware antes" >&2; exit 1; }}
sudo -n install -m 0644 "$F/fw_pru.out" "$R{firmware_da_pru}.shan-novo" && sudo -n mv -f "$R{firmware_da_pru}.shan-novo" "$R{firmware_da_pru}" || exit 1
{pinos}if [ "$(cat "$RPROC/state")" = running ]; then echo stop | tee "$RPROC/state" > /dev/null 2>&1 || echo stop | sudo -n tee "$RPROC/state" > /dev/null; fi
echo am335x-pru0-fw | tee "$RPROC/firmware" > /dev/null 2>&1 || echo am335x-pru0-fw | sudo -n tee "$RPROC/firmware" > /dev/null
echo start | tee "$RPROC/state" > /dev/null 2>&1 || echo start | sudo -n tee "$RPROC/state" > /dev/null
estado=$(cat "$RPROC/state")
[ "$estado" = running ] || {{ echo "a PRU0 ficou '$estado' depois do start" >&2; exit 1; }}
echo "a PRU0 rodando o $F/fw_pru.out"
"""


def roteiro_de_recarregar() -> str:
    """O "Recarregar a PRU" do diagnóstico (o passo do ``setup.sh``): o ``fw_pru.out`` compilado da pasta instalado
    em ``/lib/firmware`` (o sudo), os pinos e a PRU ligada de novo."""
    pinos = "".join(f"config-pin {pino} {modo} > /dev/null || exit 1\n" for pino, modo in PINOS)
    return com_sudo("true\n" + _RECARREGAR.format(pasta=PASTA_DO_FIRMWARE, firmware_da_pru=FIRMWARE_DA_PRU,
                                                   pinos=pinos))


async def recarregar_a_pru(conexao: ConexaoSSH, senha_do_sudo: str) -> str:
    from .correcoes import SAIDA_SEM_DIRETORIO, SAIDA_SENHA_RECUSADA, ErroDoSudo

    r = await conexao.executar(roteiro_de_recarregar(), entrada=senha_do_sudo + "\n", tempo_limite=60,
                               descricao="recarregar o firmware da PRU0 (sudo)")
    if r.codigo == SAIDA_SENHA_RECUSADA:
        raise ErroDoSudo("a placa recusou a senha do sudo", senha_recusada=True)
    if r.codigo == SAIDA_SEM_DIRETORIO:
        raise ErroDoSudo("a placa não deixou criar o diretório temporário em /dev/shm (onde a senha fica, na RAM)")
    if r.codigo != 0:
        raise ErroDaPlaca(f"a PRU não foi recarregada: {(r.erro or r.saida).strip()[-300:] or f'código {r.codigo}'}")
    return r.saida.strip()


async def apagar_copia(conexao: ConexaoSSH, nome: str) -> None:
    """Apaga uma cópia anterior do firmware (``~/firmware-anteriores/<nome>``)."""
    if not _COPIA.match(nome) or nome in (".", ".."):
        raise ValueError(f"nome de cópia inválido: {nome!r}")
    alvo = f"{PASTA_DAS_ANTERIORES}/{nome}"
    r = await conexao.executar(f"[ -d {shlex.quote(alvo)} ] && rm -rf -- {shlex.quote(alvo)}",
                               descricao=f"apagar a cópia anterior do firmware {nome}")
    if r.codigo != 0:
        raise ErroDaPlaca(f"não deu para apagar a cópia {nome} (código {r.codigo})")


def firmware_da_placa(plano_codigo: Iterable[str], versao: str | None) -> FirmwareParaEnviar:
    """O próprio código da placa, para compilar e carregar de novo (o ``setup.sh`` pelo aplicativo)."""
    caminhos = tuple(sorted(plano_codigo))
    return FirmwareParaEnviar(versao or "sem-versao", "placa", (), (), PASTA_DO_FIRMWARE,
                              tuple((c, c) for c in caminhos))
