"""O console serial da placa (docs/gui-plan.md, 11.10; a F6.8): o resgate quando a rede pelo USB não sobe (um
``uEnv.txt`` que impediu o boot, o ``dnsmasq`` desligado, a senha esquecida). A BeagleBone, pelo USB, também é uma
porta serial (o gadget ACM: ``/dev/ttyACM0`` no Linux, ``/dev/cu.usbmodem…`` no macOS, ``COMn`` no Windows), com o
``serial-getty@ttyGS0`` da imagem: o login de sempre, sem a rede. (O console do u-boot e do kernel é outro, o de
três pinos do J1, com um cabo FTDI de 3,3 V: ele aparece aqui como uma porta ``ttyUSB``.)

**As portas** (:func:`portas`): as do gadget primeiro (pelo VID:PID, como a descoberta), depois as outras USB; cada
uma diz se este usuário pode abri-la. **Sem permissão** (o Linux dá a porta ao grupo ``dialout``, ou ``uucp``):
:func:`como_liberar` diz o que fazer, uma vez, num terminal do computador; o aplicativo não mexe nos grupos do
sistema sozinho.

**O console** (:class:`ConsoleSerial`): 115200 8N1, sem controle de fluxo (o do getty da imagem); ler com um tempo
curto (uma thread lê, a interface escreve) e fechar.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass

VELOCIDADE = 115200
IDS_DO_GADGET = {(0x1D6B, 0x0104), (0x0451, 0x6141)}
"""O VID:PID do gadget USB das imagens da BeagleBoard (o da Linux Foundation; o da TI nas imagens antigas)."""


def _nome_do_produto(produto: str | None) -> str | None:
    """``BeagleBoneBlack`` (o produto do gadget) vira ``BeagleBone Black``."""
    if not produto:
        return None
    if produto.startswith("BeagleBone") and len(produto) > len("BeagleBone"):
        resto = produto[len("BeagleBone"):]
        return "BeagleBone " + "".join(f" {c}" if c.isupper() and i else c for i, c in enumerate(resto))
    return produto


def _listar_portas_seriais() -> list:
    from serial.tools import list_ports
    return list_ports.comports()


@dataclass(frozen=True)
class PortaSerial:
    caminho: str
    descricao: str
    da_placa: bool                  # o gadget da BeagleBone (o console do getty)
    serie: str | None
    acessivel: bool
    grupo: str | None               # o grupo dono da porta (o que dá a permissão), no Linux e no macOS

    @property
    def titulo(self) -> str:
        return f"{self.descricao} ({self.caminho})"


def _grupo_e_acesso(caminho: str) -> tuple[str | None, bool]:
    if sys.platform.startswith("win"):
        return None, True
    try:
        import grp

        grupo = grp.getgrgid(os.stat(caminho).st_gid).gr_name
    except (OSError, KeyError, ImportError):
        grupo = None
    return grupo, os.access(caminho, os.R_OK | os.W_OK)


def portas(listar=_listar_portas_seriais) -> list[PortaSerial]:
    """As portas seriais USB deste computador: as da placa (o gadget) primeiro. As ``ttyS`` sem dono USB (as da
    placa-mãe) ficam de fora."""
    achadas = []
    for p in listar():
        if p.vid is None and not str(p.device).lower().startswith(("com", "/dev/cu.", "/dev/ttyusb", "/dev/ttyacm")):
            continue
        da_placa = (p.vid, p.pid) in IDS_DO_GADGET
        descricao = (_nome_do_produto(p.product) or "BeagleBone") if da_placa else (p.description or p.device)
        grupo, acessivel = _grupo_e_acesso(p.device)
        achadas.append(PortaSerial(p.device, descricao, da_placa, p.serial_number or None, acessivel, grupo))
    return sorted(achadas, key=lambda x: (not x.da_placa, x.caminho))


def como_liberar(porta: PortaSerial, usuario: str | None = None) -> tuple[str, list[str]]:
    """O porquê de não abrir ``porta`` e os comandos que liberam (para o usuário rodar, uma vez)."""
    usuario = usuario or os.environ.get("USER") or os.environ.get("USERNAME") or "$USER"
    grupo = porta.grupo or "dialout"
    if sys.platform == "darwin":
        return (f"O macOS não deixou abrir {porta.caminho}.", [])
    return (f"A porta {porta.caminho} é do grupo {grupo}, e o usuário {usuario} não está nele. Rode uma vez, num "
            "terminal deste computador, e saia da sessão e entre de novo (o grupo novo só vale numa sessão nova):",
            [f"sudo usermod -aG {grupo} {usuario}"])


class ConsoleSerial:
    """A porta aberta: :meth:`ler` (o que chegou, até ``tempo_s``), :meth:`escrever` e :meth:`fechar`."""

    def __init__(self, caminho: str, velocidade: int = VELOCIDADE):
        import serial

        self.caminho = caminho
        self._porta = serial.Serial(caminho, velocidade, bytesize=8, parity="N", stopbits=1, timeout=0.1,
                                    write_timeout=2, xonxoff=False, rtscts=False)

    def ler(self) -> bytes:
        porta = self._porta
        dados = porta.read(1)
        if dados and porta.in_waiting:
            dados += porta.read(porta.in_waiting)
        return dados

    def escrever(self, dados: bytes) -> None:
        self._porta.write(dados)

    def fechar(self) -> None:
        self._porta.close()
