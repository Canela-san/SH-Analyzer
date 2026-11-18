"""O ``ler_adc`` da placa simulada (docs/gui-plan.md, 11.11; a F4.2): a linha de comando do ``firmware/ler_adc.c``
(a frequência, os canais e as opções dele) e as capturas que ele faz, com as amostras da rede de 60 Hz com
supraharmônicos (``capturas_simuladas``), contínuas de um bloco para o outro:

* **a linha de comando**, lida como o C a lê (``sh_placa/pedido.py``, conferido contra o ``ler_adc.c``): os mesmos
  erros de uso e o mesmo teto da PRU; a faixa, a sonda, o SPI e as esperas de CS de cada captura vão para o
  cabeçalho, e o sinal satura numa faixa pequena demais para ele;
* **a saída contínua** (``-o -``): o cabeçalho provisório, os blocos no ritmo da taxa (um bloco de 1 048 576 amostras
  a cada 2,6 s, a 400 kS/s) e o cabeçalho final depois do último; o texto, todo no stderr;
* **o cartão** (``-o ARQUIVO``): o arquivo na pasta do firmware, com o cabeçalho final no lugar do provisório;
* **o ``--progresso-json``**: as linhas ``inicio``, ``bloco`` e ``fim`` do ``ler_adc`` (os mesmos campos);
* **o Ctrl+C** (o ``SIGINT``, o ``SIGTERM`` e o ``SIGHUP``): o bloco em curso é descartado, e a captura fecha no
  último inteiro (o código 0 até o Ctrl+C, ``--blocos 0``; 5 com os blocos contados); quem recebe que fecha a saída dá
  o código 6;
* **os cenários** (``SHAN_CENARIO``): o ADC mudo (um bloco em 0, o código 4), o firmware de outra versão (sem o
  ``-o -``: a ajuda e a recusa de antes da F4.1) e os problemas de configuração que impedem a captura (a PRU com
  falha, sem o ``mem=496M``, sem o overlay, a PRU desatualizada, o áudio do HDMI), com o erro que o de verdade dá.

O tamanho do bloco vem de ``SHAN_AMOSTRAS_POR_BLOCO`` (o das capturas simuladas: os testes o diminuem), e o relógio
da placa, o deste computador mais o desvio da placa simulada (``SHAN_RAIZ``). Roda pelo ``ler_adc`` da pasta do
firmware dela (:func:`roteiro`), com o Python deste aplicativo.
"""

from __future__ import annotations

import hashlib
import json
import os
import shlex
import signal
import sys
import time
from dataclasses import dataclass, replace
from pathlib import Path

import numpy as np

from . import capturas_simuladas as cs
from .pedido import CODIGOS_DO_SPI, ErroDeUso, LinhaDeComando, blocos_para_duracao, ler_argumentos

OK, ERRO, USO, SOBRESCRITO, ADC_MUDO, INTERROMPIDA, SAIDA_FECHADA = range(7)
MOTIVOS = ("ok", "erro", "uso", "sobrescrito", "adc_mudo", "interrompida", "saida_fechada")
PROTOCOLO_DA_PRU = cs.PROTOCOLO_DA_PRU
GRANDEZAS = {"tensao": cs.GRANDEZA_TENSAO, "corrente": cs.GRANDEZA_CORRENTE, "temperatura": 2}
ANTIGAS = {"-o -", "--progresso-json"}
"""O que o ``ler_adc`` de antes da F4.1 (o cenário ``firmware_antigo``) não tem."""

FALHAS = {
    "pru_com_falha": "a PRU não ficou pronta em 500 ms (versao_protocolo_pru = 0x00000000). O fw_pru.out carregado é "
                     "anterior a 23/10/2026 ou a PRU não iniciou: recompile e recarregue os dois com sudo ./setup.sh.",
    "pru_desatualizada": f"o firmware da PRU não é o deste ler_adc (protocolo {PROTOCOLO_DA_PRU - 1}; este espera "
                         f"{PROTOCOLO_DA_PRU}): recompile e recarregue os dois com sudo ./setup.sh.",
    "sem_mem_496m": "a memória dos buffers da PRU (0x9F000000-0x9F3FFFFF) é RAM do Linux (/proc/iomem: 80000000-"
                    "9FDFFFFF : System RAM): a PRU escreveria por cima do sistema. Ponha 'mem=496M' na linha cmdline= "
                    "do /boot/uEnv.txt e reinicie a placa.",
    "sem_overlay_da_pru": "a PRU0 não existe (/sys/class/remoteproc/remoteproc1): o /boot/uEnv.txt sem o overlay do "
                          "remoteproc da PRU.",
    "audio_hdmi": "os pinos da PRU (P9_28, P9_29, P9_30, P9_31) estão com o áudio do HDMI (o overlay do HDMI com "
                  "áudio): desligue-o no /boot/uEnv.txt (disable_uboot_overlay_audio=1) e reinicie a placa.",
}
"""Os cenários em que o ``ler_adc`` de verdade não captura: o erro dele (o código 1, antes de qualquer amostra)."""


@dataclass(frozen=True)
class Pedido:
    """A captura pedida, como a placa simulada a usa: a linha de comando lida (``pedido.ler_argumentos``), os blocos
    de uma duração contados no bloco dela (os testes o diminuem) e o nome do arquivo no cartão."""

    linha: LinhaDeComando
    blocos: int
    arquivo: str

    @property
    def frequencia(self) -> int:
        return self.linha.pedido.taxa_hz

    @property
    def canais(self) -> tuple[int, ...]:
        return self.linha.pedido.numeros

    @property
    def continua(self) -> bool:
        return self.linha.continua

    @property
    def progresso_json(self) -> bool:
        return self.linha.progresso_json


AJUDA = """Uso: ler_adc [FREQUENCIA] [CANAIS] [opções]   (a placa simulada do SH-Analyzer)

  FREQUENCIA            a taxa total, em Hz (padrão 400000; até 500000)
  CANAIS                os canais, de 0 a 7, separados por vírgula (padrão 1)
  --blocos N            blocos de 1 048 576 amostras (padrão 1; 0 = até Ctrl+C)
  --duracao T           a duração (30, 30s, 5m, 1h), em vez de --blocos
  -o, --saida ARQUIVO   o arquivo da captura; -o - a manda pelo stdout (o cabeçalho final depois do último bloco)
  -t, --titulo TEXTO    -d, --descricao TEXTO
  --grandeza C:tensao|corrente|temperatura   --ganho C:G   --sonda C:ID   --faixa-adc C:F
  --spi MODO   --atraso-cs S,H,A   --forcar-taxa
  --progresso-json      uma linha JSON por bloco no stderr (inicio, bloco, fim)

Códigos de saída: 0 ok, 1 erro, 2 uso, 3 buffer sobrescrito, 4 ADC mudo, 5 interrompida, 6 a saída fechou.
"""
AJUDA_ANTIGA = AJUDA.replace("; -o - a manda pelo stdout (o cabeçalho final depois do último bloco)", "").replace(
    "  --progresso-json      uma linha JSON por bloco no stderr (inicio, bloco, fim)\n", "").replace(
    ", 6 a saída fechou", "")


class _Saida:
    """Para onde vai a captura: o stdout (o fluxo) ou um arquivo (o cabeçalho final no lugar do provisório)."""

    def __init__(self, pedido: Pedido, pasta: Path):
        self.continua = pedido.continua
        if self.continua:
            self._f = os.fdopen(os.dup(1), "wb", buffering=0)
            os.dup2(2, 1)                   # o texto vai todo para o stderr, como no ler_adc de verdade
        else:
            self._f = open(pasta / pedido.arquivo, "wb")

    def escrever(self, dados: bytes) -> None:
        self._f.write(dados)

    def fechar(self, final: bytes) -> None:
        if self.continua:
            self._f.write(final)
        else:
            self._f.seek(0)
            self._f.write(final)
        self._f.close()


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    cenario = os.environ.get("SHAN_CENARIO", "normal")
    por_bloco = int(os.environ.get("SHAN_AMOSTRAS_POR_BLOCO") or cs.AMOSTRAS_POR_BLOCO_DO_FIRMWARE)
    antigo = cenario == "firmware_antigo"
    if any(a in ("-h", "--help") for a in argv):
        _linha(sys.stdout, AJUDA_ANTIGA if antigo else AJUDA)
        return OK
    try:
        if antigo and ("--progresso-json" in argv or _tem_o_traco(argv)):
            raise ErroDeUso("opção desconhecida '--progresso-json' (veja ler_adc --help)." if "--progresso-json" in argv
                            else "nome de arquivo inválido '-' em -o.")
        linha = ler_argumentos(argv)
        if linha.continua and os.isatty(1):
            raise ErroDeUso("-o - escreve a captura (binária) no stdout, e ele é um terminal: mande-a para um pipe ou "
                            "um arquivo (ler_adc -o - | ...), ou use -o ARQUIVO.")
    except ErroDeUso as e:
        _erro(str(e))
        return USO
    if cenario in FALHAS:
        _erro(FALHAS[cenario])
        return ERRO
    p = linha.pedido
    blocos = blocos_para_duracao(p.duracao_s, p.taxa_hz, por_bloco) if p.duracao_s is not None else p.blocos
    arquivo = linha.arquivo or time.strftime("captura_%Y%m%d_%H%M%S.bin", time.localtime(_agora()))
    return Captura(Pedido(linha, blocos, arquivo), por_bloco, cenario, " ".join(shlex.quote(a) for a in argv)).rodar()


def _tem_o_traco(argv: list[str]) -> bool:
    return any(a in ("-o", "--saida") and b == "-" for a, b in zip(argv, argv[1:]))


def _linha(arquivo, texto: str) -> None:
    """Uma linha para quem lê (o programa é o ler_adc: o texto é a saída dele)."""
    arquivo.write(texto.rstrip("\n") + "\n")
    arquivo.flush()


def _erro(texto: str) -> None:
    _linha(sys.stderr, f"Erro: {texto}")


def _disco_do_cartao() -> tuple[int, int]:
    """O total e o livre do cartão da placa simulada, como o agente os vê (o tamanho dele, menos o sistema e os
    arquivos da pasta do firmware, que é esta); desconhecidos fora dela."""
    raiz = os.environ.get("SHAN_RAIZ")
    try:
        total, reservado = (int(x) for x in (Path(raiz) / "run/simulador/disco").read_text().split()[:2])
    except (TypeError, OSError, ValueError):
        return cs.VALOR_DESCONHECIDO, cs.VALOR_DESCONHECIDO
    usado = sum(f.lstat().st_size for f in Path.cwd().rglob("*") if f.is_file() and not f.is_symlink())
    return total, max(0, total - reservado - usado // 1024)


def _agora() -> float:
    """O relógio da placa simulada: o deste computador mais o desvio dela (o que o agente lê)."""
    raiz = os.environ.get("SHAN_RAIZ")
    if raiz:
        try:
            return time.time() + float((Path(raiz) / "run/simulador/relogio").read_text().strip() or 0)
        except (OSError, ValueError):
            pass
    return time.time()


class Captura:
    def __init__(self, pedido: Pedido, por_bloco: int, cenario: str, comando: str):
        self.pedido, self.por_bloco, self.cenario = pedido, por_bloco, cenario
        self.parar = False
        self.inicio = _agora()
        self.identidade = f"{self.inicio!r}:{os.getpid()}"
        p = pedido.linha.pedido
        self.faixas = tuple(c.faixa_v for c in p.canais)
        self.configuracao = cs.Configuracao(
            p.numeros, p.taxa_hz, por_bloco, p.duracao_s or 0.0, p.titulo, p.descricao, comando,
            grandezas=tuple(GRANDEZAS[c.grandeza] for c in p.canais), ganhos=tuple(c.ganho or 0.0 for c in p.canais),
            faixas=self.faixas, sondas=tuple(c.sonda for c in p.canais), modo_spi=CODIGOS_DO_SPI[p.spi],
            atrasos_cs=p.atrasos_cs)
        total, livre = _disco_do_cartao()
        self.sistema = cs.Sistema(os.environ.get("SHAN_KERNEL", ""), os.environ.get("SHAN_SISTEMA", ""),
                                  os.environ.get("SHAN_PLACA", ""), versao_firmware=os.environ.get("SHAN_VERSAO", ""),
                                  disco_total_kib=total, disco_livre_kib=livre, saida_no_disco=not pedido.continua)
        ticks = 200_000_000 // pedido.frequencia
        self.taxa_real = 200_000_000 / ticks
        self.segundos_por_bloco = por_bloco / self.taxa_real

    def _progresso(self, evento: str, **campos) -> None:
        if self.pedido.progresso_json:
            _linha(sys.stderr, json.dumps({"evento": evento, "formato": 1, **campos}, ensure_ascii=False))

    def _cabecalho(self, fim: cs.Fim | None) -> bytes:
        sistema = self.sistema
        if fim is not None and sistema.saida_no_disco:
            sistema = replace(sistema, disco_livre_fim_kib=_disco_do_cartao()[1])
        return cs.montar_cabecalho(self.configuracao, inicio=self.inicio, sistema=sistema,
                                   identidade=self.identidade, fim=fim)

    def rodar(self) -> int:
        for sinal in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            signal.signal(sinal, self._ao_sinal)
        p = self.pedido
        try:
            saida = _Saida(p, Path.cwd())          # com -o -, daqui em diante o stdout é o stderr
        except OSError as e:
            _erro(f"não deu para criar '{p.arquivo}': {e.strerror}")
            return ERRO
        _linha(sys.stdout, f"ler_adc (placa simulada): {p.frequencia} S/s, canais {','.join(map(str, p.canais))}, "
               + (f"{p.blocos} bloco(s)" if p.blocos else "até Ctrl+C")
               + f", saída {'contínua, no stdout' if p.continua else p.arquivo}")
        self._progresso("inicio", id_captura=self._id(), continua=p.continua, frequencia_hz=p.frequencia,
                        taxa_real_hz=self.taxa_real, canais=list(p.canais), blocos=p.blocos,
                        amostras_por_bloco=self.por_bloco, bytes_por_bloco=2 * self.por_bloco,
                        bytes_do_cabecalho=cs.CABECALHO_V9, segundos_por_bloco=self.segundos_por_bloco,
                        versao_protocolo_pru=PROTOCOLO_DA_PRU)
        medida = cs.Medida(len(p.canais))
        t0 = time.monotonic()
        codigo, blocos, pior_s, vistos = OK, 0, 0.0, []
        try:
            saida.escrever(self._cabecalho(None))
            while not self.parar and (p.blocos == 0 or blocos < p.blocos):
                pronto_em = t0 + (blocos + 1) * self.segundos_por_bloco
                while not self.parar and time.monotonic() < pronto_em:
                    time.sleep(min(0.05, max(pronto_em - time.monotonic(), 0.0)))
                if self.parar:
                    break
                visto = time.monotonic()
                mudo = self.cenario == "adc_mudo"
                codigos = (np.zeros(self.por_bloco, dtype="<u2") if mudo else
                           cs.codigos_do_bloco(p.canais, self.taxa_real, self.por_bloco, blocos, faixas=self.faixas))
                saida.escrever(codigos.tobytes())
                medida.somar(codigos)
                blocos += 1
                vistos.append(visto - t0)
                gasto = time.monotonic() - visto
                pior_s = max(pior_s, gasto)
                self._progresso("bloco", bloco=blocos, blocos=p.blocos, amostras=medida.amostras, t_s=visto - t0,
                                gravacao_ms=round(1e3 * gasto, 1), amostras_atrasadas=0, buffers_sobrescritos=0,
                                quadros_preambulo_ruim=0, folga_minima_ciclos=18, atraso_maximo_ciclos=0,
                                divergencias_fase_a=0, divergencias_fase_c=0, ciclos_rebase=2,
                                saturadas=list(medida.saturadas))
                if mudo:
                    _erro(f"o ADC não está respondendo: as 64 primeiras amostras do bloco {blocos} valem todas "
                          "0x0000. Causas prováveis: a placa de aquisição sem alimentação (a BeagleBone tem de estar "
                          "na fonte de 5 V do conector: pelo USB, a placa fica desligada) ou os pinos da PRU sem "
                          "configuração (sudo ./setup.sh). A captura foi interrompida.")
                    codigo = ADC_MUDO
                    break
            if codigo == OK and self.parar and p.blocos and blocos < p.blocos:
                codigo = INTERROMPIDA
            taxa = (blocos - 1) * self.por_bloco / (vistos[-1] - vistos[0]) if blocos >= 2 else 0.0
            duracao = vistos[-1] if vistos else 0.0
            fim = medida.fim(self.inicio + duracao, duracao, pior_bloco_ms=int(1e3 * pior_s + 0.5),
                             taxa_medida_hz=taxa, blocos=blocos) if blocos else None
            saida.fechar(self._cabecalho(fim))
        except BrokenPipeError:
            _erro(f"a saída fechou no bloco {blocos + 1} (quem recebia a captura parou de ler: a conexão caiu?). A "
                  "captura foi encerrada; do outro lado, ela vai até o último bloco que chegou inteiro.")
            codigo, fim = SAIDA_FECHADA, None
            taxa = 0.0
        if codigo in (OK, INTERROMPIDA):
            _linha(sys.stdout, f"Captura concluída: {blocos} bloco(s), {medida.amostras} amostras"
                   + ("" if codigo == OK else " (interrompida)"))
        self._progresso("fim", codigo=codigo, motivo=MOTIVOS[codigo], blocos=blocos, amostras=medida.amostras,
                        crc32_amostras=medida.crc, taxa_medida_hz=round(taxa, 3), amostras_atrasadas=0,
                        buffers_sobrescritos=0, quadros_preambulo_ruim=0)
        return codigo

    def _id(self) -> str:
        return hashlib.sha256(self.identidade.encode()).digest()[:16].hex()     # o do cabeçalho

    def _ao_sinal(self, _sinal, _quadro) -> None:
        self.parar = True


def roteiro(cenario: str, amostras_por_bloco: int, sistema: cs.Sistema) -> str:
    """O ``ler_adc`` da pasta do firmware da placa simulada: este módulo, pelo Python deste aplicativo (o caminho dele:
    o ``python3`` da placa simulada é o mesmo programa fora do ambiente virtual, sem o numpy), com o cenário, o bloco
    e o sistema dela no ambiente."""
    scripts = Path(__file__).resolve().parents[1]
    codigo = (f"import sys; sys.path.insert(0, {str(scripts)!r}); from sh_placa.ler_adc_simulado import main; "
              "sys.exit(main())")
    ambiente = {"SHAN_CENARIO": cenario, "SHAN_AMOSTRAS_POR_BLOCO": str(int(amostras_por_bloco)),
                "SHAN_KERNEL": sistema.kernel, "SHAN_SISTEMA": sistema.sistema, "SHAN_PLACA": sistema.placa,
                "SHAN_VERSAO": sistema.versao_firmware}
    variaveis = " ".join(f"{nome}={shlex.quote(valor)}" for nome, valor in ambiente.items())
    return ("#!/bin/sh\n# O ler_adc da placa simulada (sh_placa/ler_adc_simulado.py).\n"
            f"{variaveis} exec {shlex.quote(sys.executable)} -c {shlex.quote(codigo)} \"$@\"\n")


if __name__ == "__main__":
    sys.exit(main())
