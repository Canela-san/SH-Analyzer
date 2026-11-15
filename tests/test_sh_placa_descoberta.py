"""A descoberta das placas (F3.3; ``sh_placa/descoberta.py`` e ``conhecidas.py``), com portas seriais, respostas de
mDNS e portas TCP falsas (o servidor SSH do teste nos endereços do loopback): a mesma placa achada pelo USB, pelos
dois IPs dele e pelo mDNS aparece uma vez; a chave de host é lida uma vez e guardada; as conhecidas dão o nome, ligam
a chave ao nº de série e aparecem como ausentes; uma fonte que falha não derruba a varredura. Sem placa e sem rede."""

import asyncio
from types import SimpleNamespace

import pytest

pytest.importorskip("asyncssh")

from servidor_ssh import ServidorSSH, porta_livre  # noqa: E402
from sh_placa import conhecidas  # noqa: E402
from sh_placa.conhecidas import PlacaConhecida  # noqa: E402
from sh_placa.descoberta import (  # noqa: E402
    Achado,
    Caminho,
    Descoberta,
    FonteConhecidas,
    FonteMDNS,
    FonteSimulador,
    FonteUSB,
    SondaSSH,
    _nome_do_produto,
    agrupar,
)
from sh_placa.destino import Destino  # noqa: E402
from sh_placa.simulador import SERIE_SIMULADA  # noqa: E402

SERIE = "2017BBBK382A"
IPS = {"127.0.0.1": "ECM", "127.0.0.2": "RNDIS"}         # os dois IPs do gadget, no loopback


def gadget(device="/dev/ttyACM0", serie=SERIE):
    """A porta serial do gadget, como o pyserial a mostrou na placa de verdade (15/11/2026)."""
    return SimpleNamespace(device=device, vid=0x1D6B, pid=0x0104, serial_number=serie,
                           manufacturer="BeagleBoard.org", product="BeagleBoneBlack")


OUTRA_SERIAL = SimpleNamespace(device="/dev/ttyUSB0", vid=0x0403, pid=0x6001, serial_number="A50285BI",
                               manufacturer="FTDI", product="FT232R USB UART")
SEM_USB = SimpleNamespace(device="/dev/ttyS0", vid=None, pid=None, serial_number=None, manufacturer=None, product=None)


def descoberta(porta, portas=(), mdns=None, sonda=None):
    sonda = sonda if sonda is not None else SondaSSH(tempo_s=1.0)

    async def consultar(_nomes):
        return mdns or {}

    return Descoberta([FonteUSB(sonda, lambda: list(portas), ips=IPS, porta=porta),
                       FonteMDNS(sonda, consultar, ips_do_usb=IPS, porta=porta),
                       FonteConhecidas(sonda, ips_do_usb=IPS), FonteSimulador()], sonda=sonda)


def rodar(corrotina):
    return asyncio.run(corrotina)


def test_a_placa_pelo_usb_pelos_dois_ips_e_pelo_mdns_aparece_uma_vez(tmp_path):
    async def cenario():
        async with ServidorSSH(tmp_path / "placa", enderecos=tuple(IPS)) as placa:
            d = descoberta(placa.porta, [SEM_USB, OUTRA_SERIAL, gadget()],
                           mdns={"beaglebone.local.": ["127.0.0.1", "127.0.0.2"]})
            primeira = await d.varrer()
            trocas = d.sonda.trocas_de_chaves
            segunda = await d.varrer()                    # a chave de host guardada: a placa não é cansada de novo
            return placa, d, primeira, segunda, trocas

    placa, d, placas, segunda, trocas = rodar(cenario())
    bbb, simulador = placas
    assert (bbb.estado, bbb.serie, bbb.impressao, bbb.nome, bbb.porta_serial) == (
        "disponivel", SERIE, placa.impressao, "BeagleBone Black", "/dev/ttyACM0")
    assert {c.destino.host if c.destino else None: c.detalhe for c in bbb.caminhos} == {
        "127.0.0.1": "USB (ECM) · beaglebone.local (mDNS)", "127.0.0.2": "USB (RNDIS) · beaglebone.local (mDNS)",
        None: "porta serial /dev/ttyACM0"}
    assert bbb.caminhos[-1].destino is None and bbb.melhor.destino.porta == placa.porta and bbb.latencia_ms > 0
    assert bbb.chave == f"serie:{SERIE}" and bbb.vista_em is not None and bbb.conhecida is None
    assert (simulador.estado, simulador.serie) == ("simulador", SERIE_SIMULADA)
    assert trocas == 2 and d.sonda.trocas_de_chaves == 2   # uma por endereço (o mDNS usou a sonda do USB)
    assert [p.chave for p in segunda] == [p.chave for p in placas] and d.falhas == []
    assert placa.autenticacoes == []                       # a sonda nunca autentica


def test_duas_placas_diferentes_ficam_separadas(tmp_path):
    async def cenario():
        async with ServidorSSH(tmp_path / "usb", enderecos=("127.0.0.1",)) as usb:
            outra = ServidorSSH(tmp_path / "lan", enderecos=("127.0.0.3",))
            outra.porta = usb.porta                          # a 22 das duas, em endereços diferentes
            async with outra:
                d = descoberta(usb.porta, [gadget()],
                               mdns={"beaglebone.local.": ["127.0.0.1"], "lab-bbb.local.": ["127.0.0.3"]})
                return usb, outra, await d.varrer()

    usb, outra, placas = rodar(cenario())
    estados = {p.nome: (p.estado, p.serie, p.impressao) for p in placas}
    assert estados == {"BeagleBone Black": ("disponivel", SERIE, usb.impressao),
                       "lab-bbb": ("disponivel", None, outra.impressao),
                       "Simulador (BeagleBone Black)": ("simulador", SERIE_SIMULADA, None)}
    lab = next(p for p in placas if p.nome == "lab-bbb")
    assert lab.chave == f"impressao:{outra.impressao}" and lab.melhor.tipo == "lan"
    assert lab.melhor.detalhe == "lab-bbb.local (mDNS)"


def test_o_gadget_sem_a_rede_ainda():
    """O gadget está no USB, e o SSH dele não responde (a placa ainda ligando)."""
    bbb, _simulador = rodar(descoberta(porta_livre(), [gadget()]).varrer())
    assert (bbb.estado, bbb.serie, bbb.porta_serial, bbb.melhor) == ("so_serial", SERIE, "/dev/ttyACM0", None)


def test_as_conhecidas_dao_o_nome_e_as_ausentes_aparecem(tmp_path):
    async def cenario():
        async with ServidorSSH(tmp_path / "lab", enderecos=("127.0.0.3",)) as lab:
            porta = lab.porta
            endereco = Destino("127.0.0.3", porta)
            salto = Destino("10.0.0.9", 2222, "debian", Destino("gateway.lab", 22, "canela"))
            lista = (
                PlacaConhecida("3714BBBK0001", "Placa do laboratório", lab.impressao, (endereco,), 1_000.0),
                PlacaConhecida("3714BBBK0002", "A de casa", "SHA256:outra", (Destino("127.0.0.9", porta),), 2_000.0),
                # o IP de uma rede com DHCP, hoje de outra placa: a chave não é a dela
                PlacaConhecida("3714BBBK0003", "A do DHCP", "SHA256:dela", (endereco,), 3_000.0),
                PlacaConhecida("3714BBBK0004", "A do campus", None, (salto,), 4_000.0),
            )
            return lab, await descoberta(porta).varrer(lista, agora=9_000.0)

    lab, placas = rodar(cenario())
    por_nome = {p.nome: p for p in placas}
    assert set(por_nome) == {"Placa do laboratório", "A de casa", "A do DHCP", "A do campus",
                             "Simulador (BeagleBone Black)"}
    laboratorio = por_nome["Placa do laboratório"]
    assert (laboratorio.estado, laboratorio.serie, laboratorio.vista_em) == ("disponivel", "3714BBBK0001", 9_000.0)
    assert laboratorio.conhecida is not None and laboratorio.melhor.detalhe == "conhecida"
    assert (por_nome["A de casa"].estado, por_nome["A de casa"].vista_em) == ("ausente", 2_000.0)
    assert por_nome["A do DHCP"].estado == "ausente"         # o endereço é da do laboratório agora
    campus = por_nome["A do campus"]
    assert (campus.estado, campus.serie, campus.melhor.detalhe) == ("pelo_salto", "3714BBBK0004",
                                                                    "pelo salto canela@gateway.lab")
    assert [p.estado for p in placas] == ["disponivel", "pelo_salto", "ausente", "ausente", "simulador"]


def test_a_chave_de_uma_conhecida_liga_o_mdns_ao_numero_de_serie():
    """A placa achada só pelo mDNS mostra a chave de host; a conhecida diz de que placa ela é."""
    achados = [Achado(Caminho("lan", Destino("192.168.0.40"), "bbb.local (mDNS)", 3.0), impressao="SHA256:a",
                      nome="bbb")]
    conhecida = PlacaConhecida("3714BBBK0001", "Placa do laboratório", "SHA256:a", (), 1.0)
    (placa,) = agrupar(achados, [conhecida], agora=5.0)
    assert (placa.serie, placa.nome, placa.chave, placa.estado) == ("3714BBBK0001", "Placa do laboratório",
                                                                    "serie:3714BBBK0001", "disponivel")


def test_o_ip_do_usb_de_outra_placa_nao_e_ligado_ao_gadget():
    """Com um gadget só, os IPs do USB são dele, a não ser que uma conhecida diga que a chave neles é de outra placa
    (um gadget que acabou de trocar, a rede da anterior ainda de pé)."""
    achados = [Achado(Caminho("usb", None, "porta serial /dev/ttyACM0"), serie=SERIE, porta_serial="/dev/ttyACM0"),
               Achado(Caminho("usb", Destino("192.168.6.2"), "USB (ECM)", 1.0), impressao="SHA256:da-outra")]
    outra = PlacaConhecida("3714BBBK9999", "A outra", "SHA256:da-outra", (), 1.0)
    assert len(agrupar(achados, [outra], agora=2.0)) == 2
    assert len(agrupar(achados, [], agora=2.0)) == 1


def test_uma_fonte_que_falha_nao_derruba_a_varredura():
    class MulticastBloqueado:
        nome = "mDNS"

        async def __call__(self, _conhecidas):
            raise OSError("o multicast está bloqueado nesta rede")

    d = Descoberta([MulticastBloqueado(), FonteSimulador()])
    (simulador,) = rodar(d.varrer())
    assert simulador.estado == "simulador" and d.falhas == ["mDNS: o multicast está bloqueado nesta rede"]


def test_a_sonda_so_aceita_um_ssh(tmp_path):
    async def http(_leitor, escritor):
        escritor.write(b"HTTP/1.1 400 Bad Request\r\n\r\n")
        await escritor.drain()
        escritor.close()

    async def cenario():
        sonda = SondaSSH(tempo_s=1.0)
        servidor_http = await asyncio.start_server(http, "127.0.0.1", 0)
        porta_http = servidor_http.sockets[0].getsockname()[1]
        async with servidor_http, ServidorSSH(tmp_path / "placa") as placa:
            resultados = (await sonda.sondar("127.0.0.1", porta_http), await sonda.sondar("127.0.0.1", placa.porta))
        sonda.nova_varredura()                                   # senão, a resposta desta varredura valeria
        return placa, resultados, await sonda.sondar("127.0.0.1", placa.porta)

    placa, (http_, ssh), fechada = rodar(cenario())
    assert http_ is None and fechada is None
    latencia, impressao = ssh
    assert latencia > 0 and impressao == placa.impressao


def test_as_placas_conhecidas_lembradas_e_gravadas():
    usb, casa = Destino("192.168.6.2"), Destino("192.168.0.40", 2222, "lab", Destino("gw", 22, "eu"))
    lista = conhecidas.lembrar((), SERIE, "BeagleBone Black", "SHA256:a", usb, quando=1.0)
    lista = conhecidas.lembrar(lista, SERIE, "Placa do laboratório", None, casa, quando=2.0)
    lista = conhecidas.lembrar(lista, "3714BBBK0002", "Outra", "SHA256:b", usb, quando=3.0)
    (outra, placa) = lista
    assert (placa.nome, placa.impressao, placa.destinos, placa.vista_em) == (
        "Placa do laboratório", "SHA256:a", (casa, usb), 2.0)          # a chave fica; o endereço novo na frente
    assert outra.serie == "3714BBBK0002"
    gravada = conhecidas.de_lista(conhecidas.para_lista(lista))
    assert gravada == lista
    estragada = [*conhecidas.para_lista(lista), {"nome": "sem série"}, {"serie": "X", "destinos": [{"porta": 22}]}, 7]
    assert conhecidas.de_lista(estragada) == lista and conhecidas.de_lista("não é lista") == ()
    assert conhecidas.esquecer(lista, SERIE) == (outra,)
    muitos = ()
    for i in range(8):
        muitos = conhecidas.lembrar(muitos, SERIE, "x", None, Destino(f"10.0.0.{i}"), quando=float(i))
    assert [d.host for d in muitos[0].destinos] == [f"10.0.0.{i}" for i in (7, 6, 5, 4, 3)]


def test_o_nome_do_produto_do_gadget():
    assert _nome_do_produto("BeagleBoneBlack") == "BeagleBone Black"
    assert _nome_do_produto("BeagleBoneGreenWireless") == "BeagleBone Green Wireless"
    assert _nome_do_produto("PocketBeagle") == "PocketBeagle" and _nome_do_produto(None) is None
