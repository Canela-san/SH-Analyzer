"""A captura que chega pela saída contínua (``ler_adc -o -``), fechada no computador: ``supraharmonicos.saida_continua``.

Primeiro com fluxos montados aqui (o cabeçalho provisório, os blocos, o final), depois com o ``ler_adc`` de verdade
contra a PRU falsa (``tests/pru_falsa.py``): o fluxo que cai no meio de um bloco, fechado pelo computador, tem de dar
o que o ``ler_adc`` gravaria no cartão com os mesmos blocos (o CRC das amostras, o sinal de cada canal, os contadores).
"""

import json
import logging
import subprocess
import zlib
from dataclasses import asdict

import numpy as np
import pytest
from capturas_sinteticas import escrever_bin, montar_cabecalho
from supraharmonicos import cabecalho as cab
from supraharmonicos.erros import ErroSHAN
from supraharmonicos.saida_continua import Acompanhamento, CapturaVazia, fechar

T = cab.CABECALHO_TAMANHO_V9
POR_BLOCO = 1000            # amostras por bloco: com 3 canais, cada bloco começa num canal diferente
CANAIS = (0, 1, 2)
ID = "00112233445566778899aabbccddeeff"     # o EXTENSAO_PADRAO das capturas sintéticas


def amostras(blocos: int, semente: int = 0) -> np.ndarray:
    """Códigos ao acaso, com o fundo de escala em alguns (as saturadas) e um canal com média longe do meio."""
    rng = np.random.default_rng(semente)
    codigos = rng.integers(1, 65535, size=blocos * POR_BLOCO, dtype=np.int64)
    codigos[::7] = 0
    codigos[3::11] = 65535
    codigos[1::3] = 40000 + codigos[1::3] % 300
    return codigos.astype("<u2")


def cabecalhos(codigos: np.ndarray, blocos: int, **kw) -> tuple[bytes, bytes]:
    """(o provisório, o final) de uma captura dos :data:`CANAIS` com estas amostras, como o ``ler_adc -o -`` os
    manda: o provisório com o fim zerado, o final com o que o ``ler_adc`` mede em todas as amostras."""
    k = len(CANAIS)
    extensao = kw.pop("extensao", {})
    comuns = dict(versao=9, amostras_por_buffer=POR_BLOCO, **kw)
    provisorio = montar_cabecalho(POR_BLOCO, CANAIS, (0,) * k, ("",) * k, 400_000, blocos=0, total_amostras=0,
                                  extensao={"fim": (0, 0), "pior_bloco_ms": 0, "duracao": 0.0, **extensao}, **comuns)
    por_canal = [codigos[i::k].astype(np.float64) for i in range(k)]
    final = montar_cabecalho(POR_BLOCO, CANAIS, (0,) * k, ("",) * k, 400_000, blocos=blocos,
                             total_amostras=len(codigos), crc_amostras=zlib.crc32(codigos.tobytes()),
                             taxa_medida_hz=399_990.0, integridade=(5 * blocos, 0, blocos),
                             extensao={"minimos": [int(c.min()) for c in por_canal],
                                       "maximos": [int(c.max()) for c in por_canal],
                                       "saturadas": [int(np.count_nonzero((c == 0) | (c == 65535))) for c in por_canal],
                                       "medias": [float(c.mean()) for c in por_canal],
                                       "desvios": [float(c.std()) for c in por_canal], **extensao}, **comuns)
    return provisorio, final


def progresso(blocos: int, ate: int | None = None) -> Acompanhamento:
    """As linhas do ``--progresso-json`` de uma captura de ``blocos`` blocos, com as dos blocos até ``ate`` (as que
    chegaram), no meio do texto para humanos."""
    a = Acompanhamento()
    a.receber(json.dumps({"evento": "inicio", "formato": 1, "id_captura": ID, "blocos": blocos,
                          "versao_protocolo_pru": 5, "amostras_por_bloco": POR_BLOCO}))
    a.receber("ler_adc v1.0: 400000 S/s, canais 0, 1 e 2")
    for n in range(1, (blocos if ate is None else ate) + 1):
        a.receber(json.dumps({"evento": "bloco", "formato": 1, "bloco": n, "blocos": blocos,
                              "amostras": n * POR_BLOCO, "t_s": 0.0026 * n + 0.001, "gravacao_ms": 100.0 + 10 * n,
                              "amostras_atrasadas": 5 * n, "buffers_sobrescritos": 0, "quadros_preambulo_ruim": n,
                              "folga_minima_ciclos": 18, "atraso_maximo_ciclos": 3 * n, "divergencias_fase_a": 0,
                              "divergencias_fase_c": 0, "ciclos_rebase": 2, "saturadas": [0, 0, 0]}))
    return a


def esperado(codigos: np.ndarray) -> dict:
    """O sinal de cada canal destas amostras, contado à parte (o canal é a posição no arquivo)."""
    k = len(CANAIS)
    por_canal = [codigos[i::k].astype(np.float64) for i in range(k)]
    return {"codigo_minimo_por_canal": tuple(int(c.min()) for c in por_canal),
            "codigo_maximo_por_canal": tuple(int(c.max()) for c in por_canal),
            "amostras_saturadas_por_canal": tuple(int(np.count_nonzero((c == 0) | (c == 65535))) for c in por_canal),
            "media_codigos_por_canal": tuple(float(c.mean()) for c in por_canal),
            "desvio_codigos_por_canal": tuple(float(c.std()) for c in por_canal)}


def conferir_sinal(c: cab.CabecalhoArquivo, codigos: np.ndarray) -> None:
    for nome, valor in esperado(codigos).items():
        assert getattr(c, nome) == pytest.approx(valor, rel=1e-12, abs=1e-9), nome


# --- O fluxo inteiro -------------------------------------------------------------------------------------------------

def test_o_fluxo_inteiro_vira_o_arquivo_do_cartao(tmp_path):
    """O cabeçalho final (depois do último bloco) vai para o lugar do provisório, e os 4096 bytes do fim saem: o
    arquivo é o do cartão, byte a byte, e o CRC das amostras confere."""
    codigos = amostras(3)
    provisorio, final = cabecalhos(codigos, 3)
    p = tmp_path / "captura.bin"
    p.write_bytes(provisorio + codigos.tobytes() + final)
    f = fechar(p, progresso(3))
    assert p.read_bytes() == final + codigos.tobytes()
    assert (f.pelo_computador, f.bytes_descartados, f.crc_confere, f.blocos) == (False, 0, True, 3)
    assert f.cabecalho.fim_pelo_computador is False and f.cabecalho.crc32_valido


def test_o_crc_calculado_por_quem_recebeu_dispensa_a_releitura_e_acusa_a_diferenca(tmp_path):
    codigos = amostras(2)
    provisorio, final = cabecalhos(codigos, 2)
    for crc, confere in ((zlib.crc32(codigos.tobytes()), True), (zlib.crc32(b"outra coisa"), False)):
        p = tmp_path / f"captura_{confere}.bin"
        p.write_bytes(provisorio + codigos.tobytes() + final)
        assert fechar(p, crc_das_amostras=crc).crc_confere is confere


def test_amostra_corrompida_no_caminho_nao_confere(tmp_path):
    codigos = amostras(2)
    provisorio, final = cabecalhos(codigos, 2)
    corpo = bytearray(codigos.tobytes())
    corpo[777] ^= 0x10
    p = tmp_path / "captura.bin"
    p.write_bytes(provisorio + bytes(corpo) + final)
    assert fechar(p).crc_confere is False


def test_fechar_de_novo_nao_muda_nada(tmp_path):
    """Uma captura já fechada (o cabeçalho do começo já é o final) volta como está, pelo ler_adc ou pelo computador."""
    codigos = amostras(2)
    provisorio, final = cabecalhos(codigos, 2)
    p, q = tmp_path / "inteira.bin", tmp_path / "caiu.bin"
    p.write_bytes(provisorio + codigos.tobytes() + final)
    q.write_bytes(provisorio + codigos.tobytes() + b"\x01" * 300)
    fechar(p)
    fechar(q, progresso(3, ate=2))
    antes = p.read_bytes(), q.read_bytes()
    assert fechar(p).crc_confere is True and fechar(q).pelo_computador is True
    assert (p.read_bytes(), q.read_bytes()) == antes


# --- A queda -----------------------------------------------------------------------------------------------------------

def test_a_queda_no_meio_de_um_bloco_fecha_com_os_blocos_inteiros(tmp_path):
    """A conexão caiu no 3º bloco: ficam os 2 inteiros, e o fim é calculado aqui. O CRC e o sinal de cada canal, das
    amostras (o canal pela posição no arquivo: com 3 canais, cada bloco começa num); os contadores, o tempo e a taxa,
    das linhas de progresso que chegaram; e a marca do fim escrito pelo computador. O resto do cabeçalho é o do
    provisório (a identificação, a configuração, o sistema)."""
    codigos = amostras(3)
    provisorio, _ = cabecalhos(codigos, 3)
    p = tmp_path / "captura.bin"
    p.write_bytes(provisorio + codigos.tobytes()[:2 * 2 * POR_BLOCO + 1234])
    f = fechar(p, progresso(3, ate=2))
    dois = codigos[:2 * POR_BLOCO]
    assert p.stat().st_size == T + dois.nbytes
    assert (f.pelo_computador, f.bytes_descartados, f.crc_confere, f.blocos) == (True, 1234, None, 2)
    c = cab.ler_cabecalho(p)
    assert c == f.cabecalho and c.crc32_valido and c.fim_pelo_computador is True
    assert (c.blocos_gravados, c.total_amostras_gravadas) == (2, 2 * POR_BLOCO)
    assert c.crc32_amostras == zlib.crc32(dois.tobytes()) and cab.conferir_crc_das_amostras(p, c) is True
    conferir_sinal(c, dois)
    assert (c.amostras_atrasadas, c.quadros_preambulo_ruim, c.atraso_maximo_ciclos, c.folga_minima_ciclos) == (10, 2, 6, 18)
    assert (c.versao_protocolo_pru, c.ciclos_rebase) == (5, 2)
    assert c.taxa_medida_hz == pytest.approx(POR_BLOCO / 0.0026)
    assert c.duracao_monotonica_s == pytest.approx(0.0062) and c.pior_bloco_ms == 120
    inicio = c.timestamp_unix + c.timestamp_ns * 1e-9
    assert c.timestamp_fim_unix + c.timestamp_fim_ns * 1e-9 == pytest.approx(inicio + 0.0062, abs=1e-6)
    intocados = set(asdict(c)) - {"blocos_gravados", "total_amostras_gravadas", "crc32_amostras", "header_crc32",
                                  "amostras_atrasadas", "quadros_preambulo_ruim", "atraso_maximo_ciclos",
                                  "taxa_medida_hz", "duracao_monotonica_s", "pior_bloco_ms", "timestamp_fim_unix",
                                  "timestamp_fim_ns", "fim_pelo_computador", "versao_protocolo_pru", "ciclos_rebase",
                                  "folga_minima_ciclos", *esperado(dois)}
    antes = asdict(cab.interpretar_cabecalho(provisorio, "provisorio"))
    assert {k: v for k, v in asdict(c).items() if k in intocados} == {k: antes[k] for k in intocados}
    assert c.id_captura == ID


def test_sem_a_linha_do_ultimo_bloco_o_tempo_dele_e_estimado_pela_taxa(tmp_path):
    """Os 3 blocos chegaram, mas a linha de progresso do 3º não (o stderr e o stdout são canais diferentes): os
    contadores são os do 2º, e o fim é o do 2º mais um bloco na taxa medida entre o 1º e o 2º."""
    codigos = amostras(3)
    provisorio, _ = cabecalhos(codigos, 3)
    p = tmp_path / "captura.bin"
    p.write_bytes(provisorio + codigos.tobytes())
    f = fechar(p, progresso(3, ate=2))
    c = f.cabecalho
    assert (f.blocos, f.bytes_descartados, c.amostras_atrasadas) == (3, 0, 10)
    conferir_sinal(c, codigos)
    assert c.taxa_medida_hz == pytest.approx(POR_BLOCO / 0.0026)
    assert c.duracao_monotonica_s == pytest.approx(0.0062 + 0.0026)


def test_sem_nenhuma_linha_de_progresso_o_tempo_e_o_nominal(tmp_path):
    """Sem as linhas (quem recebe não as leu): o sinal e o CRC continuam medidos; o tempo é o nominal dos blocos, a
    taxa fica não medida, e os contadores, os do provisório."""
    codigos = amostras(2)
    provisorio, _ = cabecalhos(codigos, 2)
    p = tmp_path / "captura.bin"
    p.write_bytes(provisorio + codigos.tobytes() + b"\x00" * 10)
    c = fechar(p).cabecalho
    conferir_sinal(c, codigos)
    assert c.duracao_monotonica_s == pytest.approx(2 * POR_BLOCO / 400_000) and c.pior_bloco_ms == 0
    assert c.taxa_medida_hz is None and c.amostras_atrasadas == 0


def test_a_queda_antes_do_primeiro_bloco_deixa_so_o_cabecalho(tmp_path):
    codigos = amostras(1)
    provisorio, _ = cabecalhos(codigos, 1)
    p = tmp_path / "captura.bin"
    p.write_bytes(provisorio + codigos.tobytes()[:999])
    f = fechar(p, progresso(1, ate=0))
    assert p.stat().st_size == T and (f.blocos, f.bytes_descartados, f.pelo_computador) == (0, 999, True)
    c = cab.ler_cabecalho(p)
    assert c.crc32_valido and c.fim_pelo_computador is True and c.crc32_amostras is None
    assert c.codigo_minimo_por_canal == () and c.timestamp_fim_unix is None


def test_nada_que_de_uma_captura(tmp_path):
    p = tmp_path / "captura.bin"
    for conteudo in (b"", b"SHAN" + b"\x00" * 100):
        p.write_bytes(conteudo)
        with pytest.raises(CapturaVazia):
            fechar(p)


def test_o_que_nao_e_uma_saida_continua_e_recusado_sem_mexer_no_arquivo(tmp_path):
    """Um .bin de antes da v9, um cabeçalho com o CRC errado, o cabeçalho do fim de outra captura ou de outros blocos:
    nada é reescrito nem cortado."""
    v8 = escrever_bin(tmp_path / "v8.bin", [np.zeros(5000)] * 2, versao=8)
    codigos = amostras(2)
    provisorio, final = cabecalhos(codigos, 2)
    corrompido = bytearray(provisorio)
    corrompido[300] ^= 1
    _, de_outra = cabecalhos(codigos, 2, extensao={"id": "ff" * 16})
    _, de_outros_blocos = cabecalhos(codigos[:POR_BLOCO], 1)
    casos = {v8: "não começa", tmp_path / "crc.bin": "não começa", tmp_path / "outra.bin": "de outra captura",
             tmp_path / "blocos.bin": "diz 1 bloco"}
    (tmp_path / "crc.bin").write_bytes(bytes(corrompido) + codigos.tobytes() + final)
    (tmp_path / "outra.bin").write_bytes(provisorio + codigos.tobytes() + de_outra)
    (tmp_path / "blocos.bin").write_bytes(provisorio + codigos.tobytes() + de_outros_blocos)
    for p, mensagem in casos.items():
        antes = p.read_bytes()
        with pytest.raises(ErroSHAN, match=mensagem):
            fechar(p)
        assert p.read_bytes() == antes, p.name


# --- As linhas de progresso --------------------------------------------------------------------------------------------

def test_o_acompanhamento_le_as_linhas_json_e_deixa_o_texto(caplog):
    a = Acompanhamento()
    assert a.receber("Captura concluída\n") is None and a.receber("") is None
    assert a.receber('{"evento": "inicio", "formato": 1, "blocos": 0}\n')["evento"] == "inicio"
    a.receber('{"evento": "bloco", "formato": 1, "bloco": 1, "t_s": 2.6}')
    a.receber('{"evento": "bloco", "formato": 1, "bloco": 3, "t_s": 7.9}')
    with caplog.at_level(logging.WARNING):
        assert a.receber('{"evento": "bloco", "formato": 2, "bloco": 4}') is None
        assert a.receber('{"evento": "bloco", "formato": 1, "bloco"') is None
    assert len(caplog.records) == 2
    a.receber('{"evento": "fim", "formato": 1, "codigo": 6, "motivo": "saida_fechada"}')
    assert sorted(a.blocos) == [1, 3] and a.fim["codigo"] == 6 and a.inicio["blocos"] == 0
    assert a.ate(2)["bloco"] == 1 and a.ate(3)["bloco"] == 3 and a.ate(0) is None


# --- Com o ler_adc de verdade --------------------------------------------------------------------------------------------

pru_falsa = pytest.importorskip("pru_falsa")


@pytest.fixture(scope="module")
def ler_adc(tmp_path_factory):
    if not pru_falsa.tem_gcc():
        pytest.skip("sem gcc no computador")
    return pru_falsa.compilar_ler_adc(tmp_path_factory.mktemp("ler_adc_saida_continua"))


def rodar(ler_adc, pasta, *args, saida="-", **opcoes_da_pru):
    pasta.mkdir(exist_ok=True)
    placa = pru_falsa.PlacaFalsa(pasta)
    pru = placa.pru(**opcoes_da_pru)
    try:
        r = subprocess.run([str(ler_adc), *map(str, args), "--progresso-json", "-o", str(saida)], env=placa.ambiente,
                           capture_output=True, timeout=60)
    finally:
        pru.parar()
    assert r.returncode == 0, r.stderr.decode()
    return r.stdout, r.stderr.decode()


@pytest.mark.parametrize("canais", ["1", "0,1,2", "0,1,2,3,4,5,6"])
def test_a_queda_fechada_aqui_da_o_que_o_ler_adc_gravaria_no_cartao(ler_adc, tmp_path, canais):
    """O fluxo do ler_adc de verdade, cortado no meio do 3º bloco (com as linhas de progresso até o 2º), fechado
    aqui; e a mesma captura de 2 blocos no cartão. As amostras, o CRC delas, o sinal de cada canal (com 3 e 7 canais,
    cada bloco começa num canal), os contadores e a configuração são os mesmos; muda o que muda de uma captura para
    outra, o disco (que o fluxo não tem) e a marca do fim."""
    pru = dict(atrasadas_por_bloco=5, preambulo_por_bloco=1)
    fluxo, stderr = rodar(ler_adc, tmp_path / "a", 400_000, canais, "--blocos", 3, **pru)
    tamanho_do_bloco = 2 * pru_falsa.AMOSTRAS_POR_BLOCO
    p = tmp_path / "caiu.bin"
    p.write_bytes(fluxo[:T + 2 * tamanho_do_bloco + 4321])
    acompanhamento = Acompanhamento()
    for linha in stderr.splitlines():
        evento = acompanhamento.receber(linha)
        if evento and evento["evento"] == "bloco" and evento["bloco"] == 2:
            break
    f = fechar(p, acompanhamento)
    assert (f.blocos, f.bytes_descartados, f.pelo_computador) == (2, 4321, True)

    cartao = tmp_path / "b" / "cartao.bin"
    rodar(ler_adc, tmp_path / "b", 400_000, canais, "--blocos", 2, saida=cartao, **pru)
    assert p.read_bytes()[T:] == cartao.read_bytes()[T:]
    aqui, la = asdict(cab.ler_cabecalho(p)), asdict(cab.ler_cabecalho(cartao))
    assert aqui["crc32_valido"] and aqui["fim_pelo_computador"] and not la["fim_pelo_computador"]
    muda = {"timestamp_unix", "timestamp_ns", "timestamp_fim_unix", "timestamp_fim_ns", "duracao_monotonica_s",
            "pior_bloco_ms", "taxa_medida_hz", "id_captura", "header_crc32", "uptime_s", "carga_1min",
            "memoria_disponivel_kib", "disco_programa_livre_kib", "linha_de_comando", "disco_saida_total_kib",
            "disco_saida_livre_kib", "disco_saida_livre_fim_kib", "duracao_pedida_segundos", "fim_pelo_computador",
            "media_codigos_por_canal", "desvio_codigos_por_canal"}
    assert {k: v for k, v in aqui.items() if k not in muda} == {k: v for k, v in la.items() if k not in muda}
    for nome in ("media_codigos_por_canal", "desvio_codigos_por_canal"):      # a soma em outra ordem
        assert aqui[nome] == pytest.approx(la[nome], rel=1e-12)
    assert aqui["amostras_atrasadas"] == 10 and aqui["quadros_preambulo_ruim"] == 2
    # o tempo e a taxa: os das linhas de progresso que chegaram, como o ler_adc os mede (a PRU falsa não tem o tempo
    # da de verdade, e duas capturas dela não dão a mesma taxa)
    um, dois = acompanhamento.blocos[1], acompanhamento.blocos[2]
    assert aqui["taxa_medida_hz"] == pytest.approx(pru_falsa.AMOSTRAS_POR_BLOCO / (dois["t_s"] - um["t_s"]))
    assert aqui["duracao_monotonica_s"] == dois["t_s"]
    # o fluxo inteiro, fechado aqui: o cabeçalho final do ler_adc, e o CRC confere
    q = tmp_path / "inteiro.bin"
    q.write_bytes(fluxo)
    inteiro = fechar(q)
    assert (inteiro.blocos, inteiro.pelo_computador, inteiro.crc_confere) == (3, False, True)
    assert q.read_bytes() == fluxo[-T:] + fluxo[T:-T]


def test_o_ao_vivo_abre_pela_api_so_os_blocos_inteiros_do_parcial(tmp_path):
    """``api.abrir_ao_vivo``: o ``.parcial`` que ainda chega (o cabeçalho provisório, dois blocos e meio), aberto com
    os canais do cabeçalho e só os blocos contados; o sinal de cada canal é o da captura inteira, depois de fechada."""
    from supraharmonicos import api
    codigos = amostras(3)
    provisorio, final = cabecalhos(codigos, 3)
    parcial = tmp_path / "ao_vivo.bin.parcial"
    parcial.write_bytes(provisorio + codigos[:2 * POR_BLOCO + 400].tobytes())
    ao_vivo = api.abrir_ao_vivo(parcial, 2)
    completo = tmp_path / "ao_vivo.bin"
    completo.write_bytes(final + codigos.tobytes())
    captura = api.abrir_captura(completo)
    assert [c.numero for c in ao_vivo.canais] == list(CANAIS) and len(ao_vivo.amostras) == 2 * POR_BLOCO
    for numero in CANAIS:
        n = len(ao_vivo.canal(numero).amostras)
        assert n == 2 * POR_BLOCO // len(CANAIS) and ao_vivo.canal(numero).taxa_hz == captura.canal(numero).taxa_hz
        np.testing.assert_array_equal(api.sinal_do_canal(ao_vivo, numero), api.sinal_do_canal(captura, numero, 0, n))
    for blocos in (0, 3):
        with pytest.raises(ErroSHAN):
            api.abrir_ao_vivo(parcial, blocos)
    (tmp_path / "outro.parcial").write_bytes(b"nada de captura")
    with pytest.raises(ErroSHAN):
        api.abrir_ao_vivo(tmp_path / "outro.parcial", 1)
