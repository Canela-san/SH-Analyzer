"""O assistente de pinos e overlays (docs/gui-plan.md, 11.10; a F6.4): o ``/boot/uEnv.txt`` da placa, lido, conferido
contra o que a PRU precisa e mudado **só no necessário**, com o diff, a cópia de segurança e a gravação atômica.

**Ler** (:func:`ler_o_uenv`): as linhas, cada uma reconhecida (vazia, comentário ou ``chave=valor``, a chave com
letras, números, ``_`` e ``.``); **uma linha que o assistente não reconhece faz ele recusar** (:class:`UenvEstranho`),
como uma chave que ele mudaria e que aparece ativa duas vezes, e o fim de linha do Windows: mexer num arquivo que ele
não entende poderia deixar a placa sem boot.

**Propor** (:func:`propor`): cada mudança com o porquê, a partir do que a placa tem (o kernel, os ``.dtbo`` da PRU em
``/lib/firmware``):

* ``overlays`` -- ``enable_uboot_overlays=1`` (sem ele, o u-boot não aplica overlay nenhum);
* ``audio`` -- ``disable_uboot_overlay_audio=1``: o áudio do HDMI usa o McASP0, que disputa P9_28, P9_29 e P9_31 com
  a PRU;
* ``pru`` -- ``uboot_overlay_pru=`` o overlay do remoteproc **do kernel que roda** (detectado em ``/lib/firmware``,
  não suposto), com a linha de outro overlay da PRU (o do UIO, o de outro kernel) comentada;
* ``cape`` -- ``enable_uboot_cape_universal=1`` (o ``config-pin`` dos pinos da PRU);
* ``mem`` -- ``mem=496M`` na linha do kernel (no ``optargs`` ou no ``cmdline``: os 16 MB do fim da DDR ficam para os
  buffers da PRU);
* ``video`` (opcional, desmarcada) -- ``disable_uboot_overlay_video=1``, que libera P8_27 a P8_46 (a placa fica sem
  o vídeo do HDMI).

Cada mudança mexe numa linha só: descomenta a linha comentada que já existe (as imagens da BeagleBoard trazem quase
todas), troca o valor da ativa, ou acrescenta uma linha perto das parecidas. As outras linhas ficam como estão.

**Gravar** (:func:`gravar`): pelo sudo, no mesmo comando de root: confere que o arquivo é o lido (pelo hash: ninguém o
mudou no meio), faz a cópia ``/boot/uEnv.txt.sh-analyzer-AAAAMMDD-HHMMSS`` (com a data deste computador), grava o novo
num arquivo ao lado e o troca com o ``mv`` (atômico), com o ``sync``; devolve o hash gravado, que tem de ser o do texto
novo. **Restaurar** uma cópia é gravá-la do mesmo jeito (a de agora também vira cópia). Vale no próximo boot.
"""

from __future__ import annotations

import difflib
import hashlib
import re
import shlex
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .agente import ErroDaPlaca
from .correcoes import SAIDA_SEM_DIRETORIO, SAIDA_SENHA_RECUSADA, ErroDoSudo, com_sudo

if TYPE_CHECKING:
    from .conexao import ConexaoSSH

CAMINHO = "/boot/uEnv.txt"
PREFIXO_DAS_COPIAS = "uEnv.txt.sh-analyzer-"
CHAVE = re.compile(r"^[A-Za-z0-9_.]+$")
MEM = "mem=496M"
SAIDA_MUDOU = 80
SAIDA_SEM_COPIA = 81
SAIDA_SEM_GRAVAR = 82
ORDEM = ("overlays", "audio", "pru", "cape", "mem", "video")
_COPIA = re.compile(r"^uEnv\.txt\.sh-analyzer-[0-9-]{1,40}$")


class UenvEstranho(ValueError):
    """O ``uEnv.txt`` tem o que o assistente não reconhece: ele não mexe (a mensagem diz onde)."""


@dataclass(frozen=True)
class Linha:
    texto: str                              # a linha como está, sem o fim
    tipo: str                               # "vazia", "comentario", "chave"
    chave: str = ""
    valor: str = ""
    comentada: str = ""                     # num comentário "#chave=valor": a chave (para descomentar)


def _ler_linha(texto: str) -> Linha:
    limpo = texto.strip()
    if not limpo:
        return Linha(texto, "vazia")
    if limpo.startswith("#"):
        dentro = limpo.lstrip("#").strip()
        chave, igual, _valor = dentro.partition("=")
        return Linha(texto, "comentario", comentada=chave.strip() if igual and CHAVE.match(chave.strip()) else "")
    chave, igual, valor = limpo.partition("=")
    if not igual or not CHAVE.match(chave.strip()):
        raise UenvEstranho(f"a linha {texto!r} não é comentário nem chave=valor")
    return Linha(texto, "chave", chave.strip(), valor.strip())


def ler_o_uenv(texto: str) -> list[Linha]:
    """As linhas do ``uEnv.txt``, cada uma reconhecida (``UenvEstranho`` na que não é: o assistente não mexe)."""
    if "\r" in texto:
        raise UenvEstranho("o arquivo tem o fim de linha do Windows (CR LF)")
    linhas = []
    for numero, linha in enumerate(texto.split("\n")[:-1] if texto.endswith("\n") else texto.split("\n"), 1):
        try:
            linhas.append(_ler_linha(linha))
        except UenvEstranho as e:
            raise UenvEstranho(f"linha {numero}: {e}") from None
    return linhas


def _texto(linhas: list[Linha]) -> str:
    return "".join(linha.texto + "\n" for linha in linhas)


def chaves(linhas: list[Linha]) -> dict[str, str]:
    """As chaves ativas (a última vale, como no u-boot)."""
    return {linha.chave: linha.valor for linha in linhas if linha.tipo == "chave"}


def overlay_sugerido(dtbos: list[str], kernel: str | None) -> str | None:
    """O overlay do remoteproc da PRU para o kernel que roda (``AM335X-PRU-RPROC-4-19-TI-00A0``), se a placa o tem
    (o mesmo critério do agente)."""
    m = re.match(r"(\d+)\.(\d+)", kernel or "")
    if not m:
        return None
    prefixo = f"AM335X-PRU-RPROC-{m.group(1)}-{m.group(2)}-TI"
    candidatos = [d for d in dtbos if d.upper().startswith(prefixo) and "PRUCAPE" not in d.upper()]
    return (prefixo + "-00A0") if (prefixo + "-00A0") in dtbos else (candidatos[0] if candidatos else None)


@dataclass(frozen=True)
class Mudanca:
    nome: str                               # ORDEM
    titulo: str
    porque: str
    necessaria: bool = True                 # marcada de saída; a opcional, desmarcada


# ------------------------------------------------------------------ as mudanças, linha a linha

def _ativas(linhas: list[Linha], chave: str) -> list[int]:
    return [i for i, linha in enumerate(linhas) if linha.tipo == "chave" and linha.chave == chave]


def _comentadas(linhas: list[Linha], chave: str, valor: str | None = None) -> list[int]:
    saida = []
    for i, linha in enumerate(linhas):
        if linha.tipo == "comentario" and linha.comentada == chave:
            if valor is None or linha.texto.strip().lstrip("#").strip().partition("=")[2].strip() == valor:
                saida.append(i)
    return saida


def _inserir_perto(linhas: list[Linha], nova: Linha, vizinhas: tuple[str, ...]) -> None:
    """Põe ``nova`` depois da última linha (ativa ou comentada) de uma das chaves ``vizinhas``; sem nenhuma, no fim."""
    perto = [i for i, linha in enumerate(linhas)
             if (linha.tipo == "chave" and linha.chave in vizinhas) or (linha.tipo == "comentario"
                                                                         and linha.comentada in vizinhas)]
    if perto:
        linhas.insert(perto[-1] + 1, nova)
    else:
        if linhas and linhas[-1].tipo != "vazia":
            linhas.append(Linha("", "vazia"))
        linhas.append(nova)


def _definir(linhas: list[Linha], chave: str, valor: str, vizinhas: tuple[str, ...]) -> None:
    """``chave=valor`` ativa: troca o valor da ativa, ou descomenta a comentada com esse valor, ou acrescenta."""
    nova = Linha(f"{chave}={valor}", "chave", chave, valor)
    ativas = _ativas(linhas, chave)
    if ativas:
        linhas[ativas[-1]] = nova
        return
    comentadas = _comentadas(linhas, chave, valor)
    if comentadas:
        linhas[comentadas[-1]] = nova
        return
    _inserir_perto(linhas, nova, (chave, *vizinhas))


def _comentar(linhas: list[Linha], i: int) -> None:
    linha = linhas[i]
    linhas[i] = Linha("#" + linha.texto, "comentario", comentada=linha.chave)


VIZINHAS_DOS_OVERLAYS = ("disable_uboot_overlay_emmc", "disable_uboot_overlay_video", "disable_uboot_overlay_audio",
                         "disable_uboot_overlay_wireless", "disable_uboot_overlay_adc")


def _mudar(linhas: list[Linha], nome: str, contexto: dict) -> None:
    if nome == "overlays":
        _definir(linhas, "enable_uboot_overlays", "1", ())
    elif nome == "audio":
        _definir(linhas, "disable_uboot_overlay_audio", "1", VIZINHAS_DOS_OVERLAYS)
    elif nome == "video":
        _definir(linhas, "disable_uboot_overlay_video", "1", VIZINHAS_DOS_OVERLAYS)
    elif nome == "cape":
        _definir(linhas, "enable_uboot_cape_universal", "1", ())
    elif nome == "pru":
        valor = f"/lib/firmware/{contexto['sugerido']}.dtbo"
        for i in _ativas(linhas, "uboot_overlay_pru"):
            if linhas[i].valor != valor:
                _comentar(linhas, i)
        if not any(linhas[i].valor == valor for i in _ativas(linhas, "uboot_overlay_pru")):
            _definir(linhas, "uboot_overlay_pru", valor, ())
    elif nome == "mem":
        for chave in ("optargs", "cmdline"):
            ativas = _ativas(linhas, chave)
            if ativas and re.search(r"(^|\s)mem=\S+", linhas[ativas[-1]].valor):
                i = ativas[-1]
                valor = re.sub(r"(^|\s)mem=\S+", lambda m: m.group(1) + MEM, linhas[i].valor, count=1)
                linhas[i] = Linha(f"{chave}={valor}", "chave", chave, valor)
                return
        ativas = _ativas(linhas, "cmdline")
        if ativas:
            i = ativas[-1]
            valor = (linhas[i].valor + " " + MEM).strip()
            linhas[i] = Linha(f"cmdline={valor}", "chave", "cmdline", valor)
        else:
            _definir(linhas, "optargs", MEM, ("cmdline", "uname_r"))


def _tem_mem(u: dict[str, str]) -> bool:
    return any(MEM in (u.get(chave) or "").split() for chave in ("optargs", "cmdline"))


def propor(texto: str, kernel: str | None, dtbos: list[str]) -> list[Mudanca]:
    """As mudanças que a PRU precisa neste ``uEnv.txt`` (as necessárias) e a opcional do vídeo (ver o módulo).
    ``UenvEstranho`` num arquivo que o assistente não reconhece."""
    linhas = ler_o_uenv(texto)
    for chave in ("enable_uboot_overlays", "disable_uboot_overlay_audio", "disable_uboot_overlay_video",
                  "uboot_overlay_pru", "enable_uboot_cape_universal", "optargs", "cmdline"):
        if len(_ativas(linhas, chave)) > 1:
            raise UenvEstranho(f"a chave {chave} está ativa em mais de uma linha (o assistente não escolhe qual vale)")
    u = chaves(linhas)
    mudancas = []
    if u.get("enable_uboot_overlays") != "1":
        mudancas.append(Mudanca("overlays", "Ligar os overlays do u-boot (enable_uboot_overlays=1)",
                                "Sem ele, o u-boot não aplica overlay nenhum: nem o da PRU."))
    if u.get("disable_uboot_overlay_audio") != "1":
        mudancas.append(Mudanca("audio", "Desligar o áudio do HDMI (disable_uboot_overlay_audio=1)",
                                "O áudio do HDMI usa o McASP0, que disputa P9_28, P9_29 e P9_31 com a PRU."))
    sugerido = overlay_sugerido(dtbos, kernel)
    if sugerido is not None and u.get("uboot_overlay_pru") != f"/lib/firmware/{sugerido}.dtbo":
        atual = u.get("uboot_overlay_pru")
        mudancas.append(Mudanca("pru", f"O overlay da PRU do kernel {kernel} ({sugerido})",
                                "O ler_adc usa o remoteproc da PRU0; hoje o uEnv.txt "
                                + (f"carrega {atual.rsplit('/', 1)[-1]}." if atual else "não carrega overlay da PRU.")))
    if u.get("enable_uboot_cape_universal") != "1":
        mudancas.append(Mudanca("cape", "Ligar o cape universal (enable_uboot_cape_universal=1)",
                                "É ele que deixa o config-pin pôr os pinos no modo da PRU."))
    if not _tem_mem(u):
        mudancas.append(Mudanca("mem", "Reservar a memória dos buffers (mem=496M)",
                                "Os 16 MB do fim da DDR (0x9F000000) ficam fora do Linux, para a PRU escrever as "
                                "amostras; sem isso, ela escreveria por cima do sistema."))
    if u.get("disable_uboot_overlay_video") != "1":
        mudancas.append(Mudanca("video", "Desligar o vídeo do HDMI (disable_uboot_overlay_video=1)",
                                "Opcional: libera P8_27 a P8_46, se um dia a PRU precisar deles (a placa fica sem o "
                                "vídeo do HDMI).", necessaria=False))
    return mudancas


def aplicar(texto: str, nomes, kernel: str | None, dtbos: list[str]) -> str:
    """O ``uEnv.txt`` com as mudanças ``nomes`` (na :data:`ORDEM`), mexendo só nas linhas delas."""
    linhas = ler_o_uenv(texto)
    contexto = {"sugerido": overlay_sugerido(dtbos, kernel)}
    for nome in ORDEM:
        if nome in nomes and not (nome == "pru" and contexto["sugerido"] is None):
            _mudar(linhas, nome, contexto)
    return _texto(linhas)


def diff(antes: str, depois: str) -> str:
    """O diff unificado (para mostrar e para o registro)."""
    return "".join(difflib.unified_diff(antes.splitlines(keepends=True), depois.splitlines(keepends=True),
                                        CAMINHO, CAMINHO + " (novo)", n=1))


def sha256(texto: str) -> str:
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


# ------------------------------------------------------------------ gravar

_GRAVAR_COMO_ROOT = r"""u=$1; sha=$2; copia=$3
[ "$(sha256sum "$u" | cut -c1-64)" = "$sha" ] || { echo "o $u mudou depois de lido" >&2; exit {mudou}; }
cp -p "$u" "$copia" || { echo "não deu para fazer a cópia $copia" >&2; exit {sem_copia}; }
cat > "$u.shan-novo" || { rm -f "$u.shan-novo"; exit {sem_gravar}; }
chmod --reference="$u" "$u.shan-novo" 2>/dev/null || chmod 644 "$u.shan-novo"
mv -f "$u.shan-novo" "$u" || exit {sem_gravar}
sync
sha256sum "$u" | cut -c1-64
"""


def roteiro_de_gravar(sha_lido: str, carimbo: str | None = None) -> str:
    """O que roda na placa para gravar o ``uEnv.txt`` (o "Ver o comando"): o texto novo vai pelo stdin, depois da
    senha. ``carimbo``: a data da cópia, do relógio deste computador (o da placa pode estar errado)."""
    carimbo = carimbo or time.strftime("%Y%m%d-%H%M%S")
    raiz = '"${SHAN_RAIZ:-}"'
    root = _GRAVAR_COMO_ROOT.replace("{mudou}", str(SAIDA_MUDOU)).replace("{sem_copia}", str(SAIDA_SEM_COPIA)) \
        .replace("{sem_gravar}", str(SAIDA_SEM_GRAVAR))
    return com_sudo(f"sh -c {shlex.quote(root)} sh {raiz}{CAMINHO} {shlex.quote(sha_lido)} "
                    f"{raiz}{shlex.quote(CAMINHO.rsplit('/', 1)[0] + '/' + PREFIXO_DAS_COPIAS + carimbo)}")


@dataclass(frozen=True)
class Gravado:
    copia: str                              # o caminho da cópia de segurança na placa
    sha256: str


async def gravar(conexao: ConexaoSSH, novo: str, sha_lido: str, senha_do_sudo: str,
                 carimbo: str | None = None) -> Gravado:
    """Grava ``novo`` no ``/boot/uEnv.txt`` da placa (ver o módulo). ``ErroDaPlaca`` se ele mudou depois de lido,
    se a cópia ou a gravação falharam, ou se o que ficou não é o texto novo."""
    ler_o_uenv(novo)                        # nunca grava o que o próprio assistente não reconheceria
    carimbo = carimbo or time.strftime("%Y%m%d-%H%M%S")
    r = await conexao.executar(roteiro_de_gravar(sha_lido, carimbo), entrada=senha_do_sudo + "\n" + novo,
                               tempo_limite=60, descricao="gravar o /boot/uEnv.txt (sudo, com a cópia de segurança)")
    if r.codigo == SAIDA_SENHA_RECUSADA:
        raise ErroDoSudo("a placa recusou a senha do sudo", senha_recusada=True)
    if r.codigo == SAIDA_SEM_DIRETORIO:
        raise ErroDoSudo("a placa não deixou criar o diretório temporário em /dev/shm (onde a senha fica, na RAM)")
    if r.codigo == SAIDA_MUDOU:
        raise ErroDaPlaca("o /boot/uEnv.txt mudou na placa depois de lido: leia de novo antes de gravar")
    if r.codigo != 0:
        raise ErroDaPlaca(f"o /boot/uEnv.txt não foi gravado (código {r.codigo}): "
                          f"{(r.erro or r.saida).strip()[-300:] or 'sem saída'}")
    gravado = r.saida.strip().splitlines()[-1] if r.saida.strip() else ""
    if gravado != sha256(novo):
        raise ErroDaPlaca("o /boot/uEnv.txt gravado não é o texto novo (o hash não bate): confira-o antes de "
                          "reiniciar a placa")
    return Gravado(f"{CAMINHO.rsplit('/', 1)[0]}/{PREFIXO_DAS_COPIAS}{carimbo}", gravado)


async def ler_copia(conexao: ConexaoSSH, nome: str) -> str:
    """O texto de uma cópia do assistente (``/boot/uEnv.txt.sh-analyzer-…``), para restaurá-la."""
    if not _COPIA.match(nome):
        raise ValueError(f"nome de cópia do uEnv.txt inválido: {nome!r}")
    r = await conexao.executar(f'cat "${{SHAN_RAIZ:-}}"/boot/{shlex.quote(nome)}', descricao=f"ler a cópia {nome}")
    if r.codigo != 0:
        raise ErroDaPlaca(f"não deu para ler a cópia /boot/{nome} (código {r.codigo})")
    return r.saida
