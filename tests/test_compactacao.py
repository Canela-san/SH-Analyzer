"""Testes de ``supraharmonicos.compactacao`` e da CLI ``compactar_amostras``: o pacote ``.zpaq.tar`` devolve cada
arquivo IDÊNTICO (bytes, data, permissões), detecta corrupção e não deixa nada pela metade.

Os testes rápidos usam o método ``rapido`` (xz, da biblioteca padrão). Os que precisam do ``zpaq`` são pulados
sem ele (``sudo apt install zpaq``) e ficam marcados ``e2e``.
"""

import hashlib
import io
import json
import os
import shutil
import signal
import subprocess
import sys
import tarfile
import textwrap
import time
from pathlib import Path

import numpy as np
import pytest
from capturas_sinteticas import escrever_bin
from supraharmonicos import compactacao as cp
from supraharmonicos.cli_compactar import main
from supraharmonicos.erros import ErroSHAN, ErroUso

RAIZ = Path(__file__).resolve().parents[1]
XZ = cp.METODOS["rapido"]
ZPAQ = cp.METODOS["max"]
precisa_zpaq = pytest.mark.skipif(shutil.which("zpaq") is None, reason="zpaq não instalado")


@pytest.fixture(autouse=True)
def _console_largo(monkeypatch):
    monkeypatch.setenv("COLUMNS", "250")     # tabelas do rich sem quebra de linha nos caminhos longos do tmp_path


def _sha(caminho: Path) -> str:
    return hashlib.sha256(caminho.read_bytes()).hexdigest()


def _captura(caminho: Path, canais=(0, 1, 2), n=3001, cauda=b"", seed=0, **kw) -> Path:
    rng = np.random.default_rng(seed)
    t = np.arange(n) / 10_000
    sinais = [np.sin(2 * np.pi * (60 + 100 * i) * t) + 0.01 * rng.standard_normal(n) for i in range(len(canais))]
    escrever_bin(caminho, sinais, canais=canais, grandezas=(0,) * len(canais), sondas=("",) * len(canais),
                 fs_total=100_000, versao=3, **kw)
    if cauda:
        with open(caminho, "ab") as f:
            f.write(cauda)
    return caminho


@pytest.fixture
def pasta(tmp_path) -> Path:
    """Pasta com o que aparece de verdade: capturas de 1 e 3 canais (uma com cauda de byte ímpar), um arquivo
    sem cabeçalho, texto, um arquivo vazio, subpasta e permissões/datas diferentes."""
    raiz = tmp_path / "ensaio"
    (raiz / "sub").mkdir(parents=True)
    _captura(raiz / "tres_canais.bin", cauda=b"\x01\x02\x03")
    _captura(raiz / "sub" / "um_canal.bin", canais=(1,), n=5000)
    (raiz / "sub" / "legado.bin").write_bytes(os.urandom(4097))
    (raiz / "notas.txt").write_text("ensaio de bancada\n", encoding="utf-8")
    (raiz / "vazio.dat").write_bytes(b"")
    os.chmod(raiz / "notas.txt", 0o600)
    os.utime(raiz / "tres_canais.bin", ns=(1_700_000_000_123_456_789, 1_700_000_000_123_456_789))
    return raiz


def _arquivos(raiz: Path) -> dict[str, tuple[str, int, int]]:
    return {str(p.relative_to(raiz)): (_sha(p), p.stat().st_mtime_ns, p.stat().st_mode & 0o7777)
            for p in sorted(raiz.rglob("*")) if p.is_file()}


def _compactar(pasta: Path, saida: Path, metodo=XZ, **kw) -> cp.Resultado:
    entradas, _ = cp.descobrir_entradas([pasta])
    return cp.compactar(entradas, saida, metodo=metodo, processos=2, **kw)


# ---------------------------------------------------------------------------
# Transformação
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("cortes", [[0, 7000, 20_011], [0, 1, 1025, 1026, 9999, 20_011], [0, 20_011]])
def test_desentrelacar_e_voltar_e_exato_com_cortes_em_qualquer_byte(tmp_path, cortes):
    arq = _captura(tmp_path / "c.bin", n=3164, cauda=b"\xff\xee\xdd")      # 1024 + 3*3164*2 + 3 = 20011 bytes
    tamanho = arq.stat().st_size
    assert tamanho == cortes[-1]
    transf, resumo = cp.escolher_transformacao(arq, tamanho)
    assert transf == cp.Desentrelacamento(1024, 3, 3164) and resumo["canais"] == [0, 1, 2]
    fluxo = b"".join(cp.ler_fluxo(arq, transf, a, b) for a, b in zip(cortes, cortes[1:]))
    original = arq.read_bytes()
    amostras = np.frombuffer(original[1024:1024 + 6 * 3164], "<u2").reshape(-1, 3)
    assert fluxo[:1024] == original[:1024] and fluxo[-3:] == b"\xff\xee\xdd"
    assert fluxo[1024:1024 + 2 * 3164] == amostras[:, 0].tobytes()            # o canal 0 inteiro, depois o 1...
    (tmp_path / "fluxo").write_bytes(fluxo)
    cp.desfazer_transformacao(tmp_path / "fluxo", transf, tmp_path / "volta.bin", tamanho)
    assert (tmp_path / "volta.bin").read_bytes() == original


def test_receita_do_leiame_reconstroi_o_original_sem_o_programa(tmp_path):
    """O trecho de numpy do LEIA-ME (quem tiver só o tar e o zpaq) precisa funcionar de verdade."""
    arq = _captura(tmp_path / "c.bin", canais=(0, 1, 2, 3, 4, 5, 6, 7), n=513, cauda=b"\x07")
    transf, _ = cp.escolher_transformacao(arq, arq.stat().st_size)
    (tmp_path / "fluxo").write_bytes(cp.ler_fluxo(arq, transf, 0, arq.stat().st_size))
    trecho = cp.gerar_leiame({"criado_em": "x", "totais": {"arquivos": 1, "bytes": 1},
                              "metodo": {"programa": "p", "nome": "max", "codec": "zpaq", "nivel": "5"}})
    ini = trecho.rindex("\n", 0, trecho.index("import numpy")) + 1
    codigo = textwrap.dedent(trecho[ini:trecho.index("4. Confira")])
    cwd = os.getcwd()
    os.chdir(tmp_path)
    try:
        exec(compile(codigo, "LEIA-ME.txt", "exec"), {"P": transf.prefixo, "C": transf.canais, "N": transf.quadros})
    finally:
        os.chdir(cwd)
    assert (tmp_path / "original.bin").read_bytes() == arq.read_bytes()


def test_so_captura_multicanal_e_desentrelacada(tmp_path):
    um = _captura(tmp_path / "um.bin", canais=(3,))
    assert cp.escolher_transformacao(um, um.stat().st_size)[0] is None              # 1 canal: já é contínuo
    assert cp.escolher_transformacao(um, um.stat().st_size)[1]["canais"] == [3]     # ...mas o resumo vai para o 'listar'
    lixo = tmp_path / "lixo.bin"
    lixo.write_bytes(os.urandom(5000))
    assert cp.escolher_transformacao(lixo, 5000) == (None, None)
    pequeno = tmp_path / "p.bin"
    pequeno.write_bytes(b"SHAN")
    assert cp.escolher_transformacao(pequeno, 4) == (None, None)


def test_cabecalho_com_crc_errado_ainda_e_desentrelacado(tmp_path):
    arq = _captura(tmp_path / "c.bin", crc_valido=False)
    transf, resumo = cp.escolher_transformacao(arq, arq.stat().st_size)
    assert transf is not None and resumo["crc_ok"] is False


def test_partes_cobrem_o_fluxo_em_pedacos_pares_e_do_tamanho_maximo():
    e = cp.Entrada(None, "x.bin", 10_000_001, 0, 0o644)
    partes = cp.cortar_em_partes(e, 7, XZ, tamanho_max=3_000_000)
    assert [p.membro for p in partes] == [f"pecas/{n:06d}.xz" for n in (7, 8, 9, 10)]
    assert partes[0].ini == 0 and partes[-1].fim == e.tamanho
    assert all(a.fim == b.ini for a, b in zip(partes, partes[1:]))
    assert all(p.ini % 2 == 0 and p.tamanho <= 3_000_000 for p in partes)
    assert partes[1].nome_interno == "x.bin.parte-002-de-004"
    assert cp.cortar_em_partes(cp.Entrada(None, "v", 0, 0, 0), 1, XZ) == []
    assert cp.cortar_em_partes(cp.Entrada(None, "a.bin", 10, 0, 0), 1, ZPAQ)[0].nome_interno == "a.bin"


def test_nome_para_o_zpaq_nao_vira_opcao_nem_curinga():
    assert cp._nome_seguro("-x.bin") == "_-x.bin"
    assert cp._nome_seguro("a*b?/c\\d") == "a_b_/c_d"
    assert cp._nome_seguro("60 khz puro/60hz-102_4khz.bin") == "60 khz puro/60hz-102_4khz.bin"


# ---------------------------------------------------------------------------
# Descoberta e recursos
# ---------------------------------------------------------------------------
def test_descobrir_usa_nomes_relativos_a_pasta_mae_e_exclui(pasta, tmp_path):
    entradas, avisos = cp.descobrir_entradas([pasta], excluir=["*.txt"])
    assert [e.nome for e in entradas] == ["ensaio/tres_canais.bin", "ensaio/vazio.dat", "ensaio/sub/legado.bin",
                                          "ensaio/sub/um_canal.bin"]
    assert avisos == []
    (pasta / "link.bin").symlink_to(pasta / "tres_canais.bin")
    _, avisos = cp.descobrir_entradas([pasta])
    assert any("link simbólico" in a for a in avisos)
    entradas, _ = cp.descobrir_entradas([pasta / "notas.txt"])
    assert [e.nome for e in entradas] == ["notas.txt"]


def test_dois_arquivos_com_o_mesmo_nome_no_pacote_sao_recusados(tmp_path):
    for lado in ("a", "b"):
        (tmp_path / lado / "dados").mkdir(parents=True)
        (tmp_path / lado / "dados" / "x.bin").write_bytes(b"1")
    with pytest.raises(ErroUso, match="mesmo nome"):
        cp.descobrir_entradas([tmp_path / "a" / "dados", tmp_path / "b" / "dados"])


def test_processos_cabem_na_memoria():
    assert cp.planejar_processos(ZPAQ, 64 * 2**20, 50, nucleos=8, memoria=2_000_000_000) == (2, 800_000_000)
    assert cp.planejar_processos(ZPAQ, 2 * 10**6, 50, nucleos=8, memoria=10**12)[0] == 8
    assert cp.planejar_processos(ZPAQ, 2 * 10**6, 3, nucleos=8, memoria=10**12)[0] == 3      # não mais que as peças
    assert cp.planejar_processos(ZPAQ, 64 * 2**20, 50, nucleos=8, memoria=1)[0] == 1           # nunca zero
    assert cp.planejar_processos(ZPAQ, 1, 1, pedidos=5)[0] == 5


# ---------------------------------------------------------------------------
# Ida e volta (xz)
# ---------------------------------------------------------------------------
def test_ida_e_volta_devolve_bytes_datas_e_permissoes(pasta, tmp_path):
    saida = tmp_path / "p.xz.tar"
    res = _compactar(pasta, saida, tamanho_peca=4000)            # força várias peças por arquivo
    assert res.segundos_verificacao is not None
    assert len(next(e for e in res.entradas if e.nome == "ensaio/tres_canais.bin").partes) > 1
    assert not list(tmp_path.glob(f"{cp.PREFIXO_TEMPORARIO}*")) and not list(tmp_path.glob("*.parcial"))
    destino = tmp_path / "volta"
    rel = cp.Pacote(saida).restaurar(None, destino, 2)
    assert rel.falhas == [] and len(rel.restaurados) == 5
    assert _arquivos(destino / "ensaio") == _arquivos(pasta)
    assert not list(destino.glob(f"{cp.PREFIXO_TEMPORARIO}*"))


@pytest.mark.skipif(os.name != "posix" or os.geteuid() == 0, reason="precisa de permissões POSIX e de não ser root")
def test_verificar_pacote_numa_pasta_sem_escrita_usa_o_temporario_do_sistema(pasta, tmp_path):
    protegida = tmp_path / "protegida"
    protegida.mkdir()
    _compactar(pasta, protegida / "p.xz.tar")
    os.chmod(protegida, 0o555)
    try:
        assert cp.Pacote(protegida / "p.xz.tar").restaurar(None, None, 2).falhas == []
    finally:
        os.chmod(protegida, 0o755)


def test_pacote_e_um_tar_comum_com_leiame_e_manifesto_primeiro(pasta, tmp_path):
    _compactar(pasta, tmp_path / "p.xz.tar")
    with tarfile.open(tmp_path / "p.xz.tar") as tar:
        nomes = tar.getnames()
        manifesto = json.load(tar.extractfile("manifesto.json"))
    assert nomes[:2] == ["LEIA-ME.txt", "manifesto.json"] and all(n.startswith("pecas/") for n in nomes[2:])
    assert manifesto["formato"] == cp.FORMATO and manifesto["versao"] == cp.VERSAO_FORMATO
    tres = next(a for a in manifesto["arquivos"] if a["caminho"] == "ensaio/tres_canais.bin")
    assert tres["transformacao"]["tipo"] == "desentrelacar-uint16" and tres["captura"]["frequencia_hz"] == 100_000
    assert tres["sha256"] == _sha(pasta / "tres_canais.bin")


def test_pecas_xz_se_abrem_com_o_xz_comum(pasta, tmp_path):
    import lzma
    _compactar(pasta, tmp_path / "p.xz.tar")
    pacote = cp.Pacote(tmp_path / "p.xz.tar")
    e = next(e for e in pacote.entradas if e.nome == "ensaio/notas.txt")
    assert lzma.decompress(pacote.ler_membro(e.partes[0].membro)) == (pasta / "notas.txt").read_bytes()


def test_extrair_so_o_pedido_e_pular_o_que_ja_existe(pasta, tmp_path):
    _compactar(pasta, tmp_path / "p.xz.tar")
    pacote = cp.Pacote(tmp_path / "p.xz.tar")
    assert [pacote.entradas[i].nome for i in pacote.selecionar(["um_canal.bin"])] == ["ensaio/sub/um_canal.bin"]
    assert len(pacote.selecionar(["ensaio/sub"])) == 2 and len(pacote.selecionar(["*.bin"])) == 3
    assert pacote.selecionar(["nao_existe"]) == []
    destino = tmp_path / "volta"
    pacote.restaurar(pacote.selecionar(["*_cana*"]), destino, 2)
    assert sorted(p.name for p in destino.rglob("*") if p.is_file()) == ["tres_canais.bin", "um_canal.bin"]
    rel = pacote.restaurar(pacote.selecionar(["*_cana*"]), destino, 2)
    assert rel.restaurados == [] and {m for _, m in rel.pulados} == {"já existe, idêntico"}
    (destino / "ensaio" / "sub" / "um_canal.bin").write_bytes(b"outro")
    rel = pacote.restaurar(pacote.selecionar(["um_canal.bin"]), destino, 2)
    assert "DIFERENTE" in rel.pulados[0][1]
    rel = pacote.restaurar(pacote.selecionar(["um_canal.bin"]), destino, 2, sobrescrever=True)
    assert rel.restaurados == ["ensaio/sub/um_canal.bin"]
    assert _sha(destino / "ensaio" / "sub" / "um_canal.bin") == _sha(pasta / "sub" / "um_canal.bin")


# ---------------------------------------------------------------------------
# Corrupção, falhas e segurança
# ---------------------------------------------------------------------------
def _corromper_membro(pacote: Path, membro: str) -> None:
    with tarfile.open(pacote) as tar:
        info = tar.getmember(membro)
    with open(pacote, "r+b") as f:
        f.seek(info.offset_data + info.size // 2)
        b = f.read(1)
        f.seek(-1, 1)
        f.write(bytes([b[0] ^ 0x10]))


def test_corrupcao_e_detectada_e_o_arquivo_estragado_nao_e_gravado(pasta, tmp_path):
    saida = tmp_path / "p.xz.tar"
    _compactar(pasta, saida)
    pacote = cp.Pacote(saida)
    alvo = next(e for e in pacote.entradas if e.nome == "ensaio/tres_canais.bin")
    _corromper_membro(saida, alvo.partes[0].membro)
    assert [n for n, _ in cp.Pacote(saida).verificar_rapido()] == ["ensaio/tres_canais.bin"]
    rel = cp.Pacote(saida).restaurar(None, tmp_path / "volta", 2)
    assert [n for n, _ in rel.falhas] == ["ensaio/tres_canais.bin"] and len(rel.restaurados) == 4
    assert not (tmp_path / "volta" / "ensaio" / "tres_canais.bin").exists()


def test_falha_no_meio_nao_deixa_pacote_nem_temporarios(pasta, tmp_path, monkeypatch):
    chamadas = []

    def quebrar(*a, **k):
        chamadas.append(1)
        if len(chamadas) == 3:
            raise ErroSHAN("disco cheio (simulado)")
        return original(*a, **k)
    original = cp._comprimir_peca
    monkeypatch.setattr(cp, "_comprimir_peca", quebrar)
    with pytest.raises(ErroSHAN, match="simulado"):
        _compactar(pasta, tmp_path / "p.xz.tar")
    assert sorted(p.name for p in tmp_path.iterdir()) == ["ensaio"]


def test_verificacao_que_falha_impede_o_pacote(pasta, tmp_path, monkeypatch):
    monkeypatch.setattr(cp, "desfazer_transformacao", lambda fluxo, t, destino, n: destino.write_bytes(b"\0" * n))
    with pytest.raises(ErroSHAN, match="verificação do pacote FALHOU"):
        _compactar(pasta, tmp_path / "p.xz.tar")
    assert not (tmp_path / "p.xz.tar").exists() and not (tmp_path / "p.xz.tar.parcial").exists()


def test_original_modificado_durante_a_compactacao_e_recusado(pasta, tmp_path, monkeypatch):
    original = cp._comprimir_peca

    def mexer(*a, **k):
        os.utime(pasta / "notas.txt", ns=(1, 1))
        return original(*a, **k)
    monkeypatch.setattr(cp, "_comprimir_peca", mexer)
    with pytest.raises(ErroSHAN, match="modificado durante"):
        _compactar(pasta, tmp_path / "p.xz.tar")


def _pacote_com_manifesto(caminho: Path, manifesto: dict) -> Path:
    with tarfile.open(caminho, "w", format=tarfile.PAX_FORMAT) as tar:
        dados = json.dumps(manifesto).encode()
        info = tarfile.TarInfo("manifesto.json")
        info.size = len(dados)
        tar.addfile(info, io.BytesIO(dados))
    return caminho


def test_caminho_malicioso_no_manifesto_e_recusado(tmp_path):
    base = {"formato": cp.FORMATO, "versao": 1, "metodo": {"codec": "xz"}}
    for ruim in ("../fora.bin", "/etc/passwd", "a/../../b"):
        arq = {"caminho": ruim, "tamanho": 0, "sha256": "", "mtime_ns": 0, "modo": 420, "partes": []}
        with pytest.raises(ErroSHAN, match="inseguro"):
            cp.Pacote(_pacote_com_manifesto(tmp_path / "m.tar", {**base, "arquivos": [arq]}))


def test_formato_mais_novo_ou_outro_arquivo_dao_mensagem_clara(tmp_path):
    with pytest.raises(ErroSHAN, match="versão 2 do formato"):
        cp.Pacote(_pacote_com_manifesto(tmp_path / "m.tar", {"formato": cp.FORMATO, "versao": 2, "metodo": {}}))
    (tmp_path / "x.tar").write_bytes(b"isto nao e um tar" * 100)
    with pytest.raises(ErroSHAN, match="não é um pacote"):
        cp.Pacote(tmp_path / "x.tar")


def test_remover_originais_so_apaga_o_que_continua_identico(pasta, tmp_path):
    res = _compactar(pasta, tmp_path / "p.xz.tar")
    (pasta / "notas.txt").write_text("mudou depois\n", encoding="utf-8")
    apagados, liberados, avisos = cp.remover_originais(res.entradas, [pasta])
    assert apagados == 4 and len(avisos) == 1 and "notas.txt" in avisos[0]
    assert sorted(p.name for p in pasta.rglob("*")) == ["notas.txt"]          # 'sub' ficou vazia e saiu; a raiz fica
    assert liberados == sum(e.tamanho for e in res.entradas if e.nome != "ensaio/notas.txt")


# ---------------------------------------------------------------------------
# CLI (no mesmo processo)
# ---------------------------------------------------------------------------
def test_cli_compactar_listar_verificar_extrair(cli, pasta, tmp_path):
    saida = tmp_path / "p.xz.tar"
    rc, out, err = cli(main, pasta, "--rapido", "-o", saida, "--sim")
    assert rc == 0, err
    assert "Pacote pronto" in out and "SHA-256 conferido" in out and saida.exists()
    rc, out, _ = cli(main, "listar", saida)
    assert rc == 0 and "ensaio/sub/um_canal.bin" in out and "100 kS/s" in out and "canais 0,1,2" in out
    rc, out, _ = cli(main, "verificar", saida, "--rapido")
    assert rc == 0 and "íntegras" in out
    rc, out, _ = cli(main, "extrair", saida, "-d", tmp_path / "volta", "um_canal.bin")   # padrão DEPOIS da opção
    assert rc == 0 and "1 arquivo(s) restaurado(s)" in out
    assert [p.name for p in (tmp_path / "volta").rglob("*") if p.is_file()] == ["um_canal.bin"]
    rc, _, err = cli(main, "extrair", saida, "nada_casa")
    assert rc == 1 and "nenhum arquivo" in err


def test_cli_recusa_combinacoes_e_saida_existente(cli, pasta, tmp_path):
    (tmp_path / "ja.tar").write_bytes(b"x")
    assert cli(main, pasta, "--rapido", "-o", tmp_path / "ja.tar")[0] == 2
    assert cli(main, pasta, "--rapido", "--sem-verificar", "--remover-originais")[0] == 2
    assert cli(main, tmp_path / "nao_existe", "--rapido")[0] == 2
    rc, out, _ = cli(main)
    assert rc == 0 and "compactar PASTA" in out


def test_cli_remover_originais_sem_terminal_exige_sim(cli, pasta, tmp_path):
    rc, _, err = cli(main, pasta, "--rapido", "-o", tmp_path / "p.xz.tar", "--remover-originais")
    assert rc == 2 and "--sim" in err and (pasta / "notas.txt").exists()       # o pacote fica; nada é apagado
    rc, out, _ = cli(main, pasta, "--rapido", "-o", tmp_path / "q.xz.tar", "--remover-originais", "--sim")
    assert rc == 0 and "5 arquivo(s) apagado(s)" in out and not any(p.is_file() for p in pasta.rglob("*"))
    rc, _, _ = cli(main, "extrair", tmp_path / "q.xz.tar", "-d", tmp_path)
    assert rc == 0 and (pasta / "tres_canais.bin").exists()


def test_formatacao_em_portugues():
    from supraharmonicos.cli_compactar import fmt_bytes, fmt_duracao, fmt_taxa
    assert fmt_bytes(391_234_567) == "391 MB" and fmt_bytes(41_300_000) == "41,3 MB" and fmt_bytes(12) == "12 B"
    assert fmt_duracao(5) == "5 s" and fmt_duracao(845) == "14 min 05 s" and fmt_duracao(7380) == "2 h 03 min"
    assert fmt_taxa(1000, 106) == "10,6 %  (9,4× menor)"


# ---------------------------------------------------------------------------
# zpaq (e2e: precisa do programa)
# ---------------------------------------------------------------------------
@pytest.mark.e2e
@precisa_zpaq
def test_zpaq_ida_e_volta_e_peca_inteira_abre_com_o_zpaq_comum(pasta, tmp_path):
    saida = tmp_path / "p.zpaq.tar"
    _compactar(pasta, saida, metodo=ZPAQ)
    pacote = cp.Pacote(saida)
    assert pacote.manifesto["metodo"]["programa"].startswith("zpaq")
    rel = pacote.restaurar(None, tmp_path / "volta", 3)
    assert rel.falhas == [] and _arquivos(tmp_path / "volta" / "ensaio") == _arquivos(pasta)
    # Arquivo sem transformação e numa peça só: o zpaq x comum já devolve o original, com o nome certo.
    e = next(e for e in pacote.entradas if e.nome == "ensaio/sub/um_canal.bin")
    (tmp_path / "peca.zpaq").write_bytes(pacote.ler_membro(e.partes[0].membro))
    subprocess.run(["zpaq", "x", "peca.zpaq", "-to", "zx"], cwd=tmp_path, check=True, capture_output=True)
    assert _sha(tmp_path / "zx" / "ensaio" / "sub" / "um_canal.bin") == e.sha256


@pytest.mark.e2e
@precisa_zpaq
def test_ctrl_c_no_meio_nao_deixa_nada_nem_zpaq_orfao(tmp_path):
    pasta = tmp_path / "grande"
    pasta.mkdir()
    for i in range(3):
        _captura(pasta / f"c{i}.bin", canais=(0, 1), n=400_000, seed=i)    # ~1,6 MB cada: segundos de zpaq -m5
    proc = subprocess.Popen([sys.executable, str(RAIZ / "scripts" / "compactar_amostras.py"), str(pasta),
                             "-o", str(tmp_path / "p.zpaq.tar"), "--sim"], cwd=tmp_path,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    limite = time.monotonic() + 60
    while not list(tmp_path.glob(f"{cp.PREFIXO_TEMPORARIO}*/*.d")) and time.monotonic() < limite:
        time.sleep(0.05)                                                     # espera um zpaq começar
    proc.send_signal(signal.SIGINT)
    saida, _ = proc.communicate(timeout=60)
    assert proc.returncode == 130, saida
    assert "Interrompido" in saida
    assert sorted(p.name for p in tmp_path.iterdir()) == ["grande"]
    vivos = subprocess.run(["pgrep", "-f", f"zpaq add {tmp_path}"], capture_output=True, text=True).stdout
    assert vivos == ""
