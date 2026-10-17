"""Testes de ``firmware/calibrar_sonda.sh`` (coleta dos pontos de calibração de uma sonda).

Não precisam de BeagleBone: o script é executado de verdade (bash), mas no lugar do ``ler_adc``
entra um FALSO (``ler_adc_falso.py``) que grava ``.bin`` v2 sintéticos e sabe simular defeitos
(saturação, disco cheio, CRC ruim, travamento...). O que se confere:

* o contrato com o resto do projeto: offsets do cabeçalho, códigos de grandeza e limite de
  saturação que o script usa batem com o firmware (C) e com o Python;
* o fluxo do operador: coleta nova, refazer um ponto ruim, opção inválida no menu, pular e
  retomar, refazer um ponto já aceito, adensar e refinar;
* os dois jeitos de capturar: 2 canais (sonda + referência no shunt; Nyquist efetiva = taxa/4) e
  1 canal (só a sonda, com a leitura do osciloscópio digitada a cada ponto; Nyquist = taxa/2);
* que o que o script produz é exatamente o que ``gerar_perfil_sonda.py`` consome.

Marcados ``e2e`` (rodam bash e processos Python; ~1 min no total). Só funcionam em Linux com
bash >= 4.4 (o mesmo ambiente da BeagleBone e do CI); no resto são pulados.
"""

import csv
import json
import os
import re
import shutil
import struct
import subprocess
import sys
from pathlib import Path

import pytest
from capturas_sinteticas import planta_h
from supraharmonicos import cabecalho as cab
from supraharmonicos import calibracao_sonda
from supraharmonicos.cli_gerar_perfil import main as gerar_perfil

RAIZ = Path(__file__).resolve().parents[1]
SCRIPT = RAIZ / "firmware" / "calibrar_sonda.sh"
LER_ADC_C = RAIZ / "firmware" / "ler_adc.c"
MEMORIA_PRU_H = RAIZ / "firmware" / "memoria_pru.h"
FALSO = Path(__file__).with_name("ler_adc_falso.py")

SPB_TESTE = 400_000  # amostras brutas por bloco nos testes (o real é 1048576): capturas menores, testes mais rápidos
SONDA = "sonda_ci"
TAXA = 102_400


def _bash_ok() -> bool:
    if sys.platform != "linux" or shutil.which("bash") is None:
        return False
    versao = subprocess.run(
        ["bash", "-c", 'echo "${BASH_VERSINFO[0]} ${BASH_VERSINFO[1]}"'], capture_output=True, text=True
    ).stdout.split()
    return len(versao) == 2 and (int(versao[0]), int(versao[1])) >= (4, 4)


pytestmark = pytest.mark.skipif(not SCRIPT.exists(), reason="firmware/calibrar_sonda.sh não encontrado")
e2e = [pytest.mark.e2e, pytest.mark.skipif(not _bash_ok(), reason="precisa de Linux com bash >= 4.4")]


def com_e2e(funcao):
    for marca in reversed(e2e):
        funcao = marca(funcao)
    return funcao


# --------------------------------------------------------------------------------------
# Bancada de teste
# --------------------------------------------------------------------------------------
class Bancada:
    """Uma 'bancada' isolada: pasta de capturas + ler_adc falso + roteiro de defeitos."""

    def __init__(self, base: Path):
        self.base = base
        self.sim = base / "sim"
        self.sim.mkdir(parents=True, exist_ok=True)
        self.capturas = base / "capturas"
        self.wrapper = base / "ler_adc_falso"
        self.wrapper.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{FALSO}" "$@"\n')
        self.wrapper.chmod(0o755)

    def cenario(self, *diretivas: str) -> None:
        """Define o que cada chamada do ler_adc falso faz (a partir da 1ª). Reinicia o contador."""
        (self.sim / "cenario").write_text("\n".join(diretivas) + "\n")
        (self.sim / "contador").unlink(missing_ok=True)
        (self.sim / "chamadas.log").unlink(missing_ok=True)

    def rodar(self, *args, entradas: str = "", extra_env: dict | None = None, canais: bool = True,
              eof: bool = False) -> tuple[int, str]:
        """Roda o script. ``entradas`` = respostas do operador (linhas); depois vêm só ENTERs
        (ou, com ``eof=True``, a entrada acaba logo após ``entradas``).

        ``canais=True`` acrescenta ``--canal-sonda 1 --canal-referencia 0`` (captura de 2 canais) quando
        os argumentos não trazem ``--canal-sonda``; ``canais=False`` não acrescenta nada."""
        args = [str(a) for a in args]
        if canais and not {"--canal-sonda", "-c"} & set(args):
            args = ["--canal-sonda", "1", "--canal-referencia", "0", *args]
        env = {
            **os.environ,
            "SIM_DIR": str(self.sim),
            "SIM_SPB": str(SPB_TESTE),
            "SH_LER_ADC": str(self.wrapper),
            "SH_PULAR_VERIFICACAO_ROOT": "1",
            **(extra_env or {}),
        }
        proc = subprocess.run(
            ["bash", str(SCRIPT), "--pasta", str(self.capturas), *args],
            input=entradas if eof else entradas + "\n" * 400, capture_output=True, text=True, env=env, timeout=600,
        )
        return proc.returncode, proc.stderr + proc.stdout

    def chamadas(self) -> list[str]:
        arquivo = self.sim / "chamadas.log"
        return arquivo.read_text().splitlines() if arquivo.exists() else []

    def pasta(self, sonda: str = SONDA) -> Path:
        return self.capturas / sonda

    def bins(self, sonda: str = SONDA) -> list[str]:
        return sorted(p.name for p in self.pasta(sonda).glob("calibracao_*.bin"))

    def manifesto(self, sonda: str = SONDA) -> list[dict]:
        with open(self.pasta(sonda) / "pontos_coletados.csv", newline="", encoding="utf-8") as f:
            return list(csv.DictReader(f))


@pytest.fixture
def bancada(tmp_path):
    return Bancada(tmp_path)


@pytest.fixture(scope="module")
def coleta_base(tmp_path_factory):
    """Uma coleta nova de 3 pontos, feita UMA vez; cada teste que precisa dela trabalha numa cópia."""
    b = Bancada(tmp_path_factory.mktemp("coleta_base"))
    rc, saida = b.rodar("--taxa", "102.4k", "--pontos", 3, "--sonda", SONDA, "-y")
    assert rc == 0, saida
    return b


@pytest.fixture(scope="module")
def coleta_1canal(tmp_path_factory):
    """Coleta de 1 canal (só a sonda, no canal 3) com 3 pontos e a leitura do osciloscópio de cada um."""
    b = Bancada(tmp_path_factory.mktemp("coleta_1canal"))
    por_ponto = "\n0.7071\n\n"   # ENTER (medir), leitura do osciloscópio, ENTER (aceitar)
    rc, saida = b.rodar("--taxa", TAXA, "--pontos", 3, "--sonda", SONDA, "--canal-sonda", 3, "--ref-externa", "-y",
                        entradas=por_ponto * 3)
    assert rc == 0, saida
    return b


@pytest.fixture
def com_coleta(coleta_base, tmp_path):
    """Bancada nova com uma CÓPIA da coleta base (a original nunca é alterada)."""
    b = Bancada(tmp_path)
    shutil.copytree(coleta_base.capturas, b.capturas)
    return b


# --------------------------------------------------------------------------------------
# Contrato com o firmware e com o Python (rápido, não executa o script)
# --------------------------------------------------------------------------------------
def constantes_do_script() -> dict[str, str]:
    texto = SCRIPT.read_text(encoding="utf-8")
    return dict(re.findall(r'^readonly (\w+)=["\']?([^"\'\s#]+)', texto, re.M))


def test_offsets_do_cabecalho_no_script_batem_com_o_formato_do_python():
    """O script lê o cabeçalho por offsets fixos: se o formato mudar, este teste acusa."""
    tokens = re.findall(r"\d*[a-zA-Z]", cab._FORMATO_CABECALHO_V2.lstrip("<"))
    pos, deslocamento = [], 0
    for t in tokens:
        pos.append(deslocamento)
        deslocamento += struct.calcsize("<" + t)
    # índices dos campos na ordem do formato (ver _FORMATO_CABECALHO_V2 em cabecalho.py)
    esperado = {
        "CAB_OFF_VERSAO": pos[1], "CAB_OFF_FREQUENCIA": pos[4], "CAB_OFF_NUM_CANAIS": pos[6],
        "CAB_OFF_LISTA_CANAIS": pos[7], "CAB_OFF_SPB": pos[8], "CAB_OFF_BYTES_AMOSTRA": pos[9],
        "CAB_OFF_BLOCOS": pos[14], "CAB_OFF_TOTAL_AMOSTRAS": pos[15], "CAB_OFF_GRANDEZA": pos[18],
        "CAB_OFF_SONDA_ID": pos[19], "CAB_OFF_CRC_V2": pos[-1],
        "CAB_TAMANHO": cab.CABECALHO_TAMANHO_TOTAL, "CAB_TAM_SONDA_ID": cab.CABECALHO_SONDA_ID_TAMANHO,
    }
    do_script = constantes_do_script()
    for nome, valor in esperado.items():
        assert int(do_script[nome]) == valor, f"{nome}: script={do_script[nome]} esperado={valor}"
    assert cab._OFFSET_HEADER_CRC32_V2 == esperado["CAB_OFF_CRC_V2"]


@pytest.mark.skipif(not LER_ADC_C.exists(), reason="firmware/ler_adc.c não encontrado")
def test_codigos_e_limites_do_script_batem_com_firmware_e_python():
    do_script = constantes_do_script()
    fonte_c = LER_ADC_C.read_text(encoding="utf-8")
    for nome_c, nome_sh in (("GRANDEZA_TENSAO", "GRANDEZA_TENSAO"), ("GRANDEZA_CORRENTE", "GRANDEZA_CORRENTE")):
        valor_c = int(re.search(rf"#define\s+{nome_c}\s+(\d+)", fonte_c).group(1))
        assert int(do_script[nome_sh]) == valor_c
    if MEMORIA_PRU_H.exists():
        spb = int(re.search(r"#define\s+SAMPLES_PER_BUFFER\s+(\d+)", MEMORIA_PRU_H.read_text()).group(1))
        assert int(do_script["SPB_PADRAO"]) == spb
    # a checagem rápida de saturação do script tem que ser a MESMA que o gerar_perfil_sonda aplica
    assert float(do_script["SATURACAO_MAXIMA"]) == calibracao_sonda.FRACAO_SATURACAO_MAXIMA
    # e a tolerância de frequência: o script só avisa como ERRO acima do que o Python ainda aceita
    assert float(do_script["FREQ_DESVIO_ERRO_PCT"]) == calibracao_sonda.TOLERANCIA_FREQ_PCT_PADRAO


# --------------------------------------------------------------------------------------
# Validação de argumentos (não captura nada)
# --------------------------------------------------------------------------------------
@com_e2e
@pytest.mark.parametrize(
    ("args", "trecho"),
    [
        (["--taxa", "abc", "--sonda", "x"], "Valor inválido para --taxa"),
        (["--taxa", "600000", "--sonda", "x"], "entre 1 e 500000"),
        (["--taxa", "102400", "--sonda", "x", "--pontos", "1"], "entre 2 e 500"),
        (["--taxa", "102400", "--sonda", "x", "--freq-max", "30k"], "Nyquist efetiva"),
        (["--taxa", "102400", "--sonda", "x", "--canal-sonda", "1", "--freq-max", "51k"], "abaixo de 98%"),
        (["--taxa", "102400", "--sonda", "x", "--canal-sonda", "1", "--canal-referencia", "0", "--freq-max", "25.2k"], "abaixo de 98%"),
        (["--taxa", "102400", "--sonda", "x", "--canal-referencia", "1", "--canal-sonda", "1"], "não podem ser o mesmo"),
        (["--taxa", "102400", "--sonda", "x", "--canal-sonda", "8"], "entre 0 e 7"),
        (["--taxa", "102400", "--sonda", "x", "--canal-sonda", "1", "--canal-referencia", "0", "--ref-externa"], "captura de 1 canal"),
        (["--taxa", "102400", "--sonda", "s" * 40], "no máximo 31"),
        (["--taxa", "102400", "--sonda", "///"], "nenhum caractere válido"),
        (["--taxa", "102400", "--sonda", "x", "--modo", "xyz"], "Modo desconhecido"),
    ],
)
def test_argumentos_invalidos_sao_recusados_antes_de_medir(bancada, args, trecho):
    rc, saida = bancada.rodar(*args, "-y")
    assert rc != 0
    assert trecho in saida
    assert bancada.chamadas() == []  # o ler_adc nem chegou a ser chamado


@com_e2e
def test_opcao_desconhecida_e_ajuda(bancada):
    rc, saida = bancada.rodar("--bogus")
    assert rc == 2 and "Opção desconhecida" in saida
    rc, saida = bancada.rodar("--help")
    assert rc == 0 and "--modo MODO" in saida


# --------------------------------------------------------------------------------------
# Coleta nova + o que o gerar_perfil_sonda.py faz com ela
# --------------------------------------------------------------------------------------
@com_e2e
def test_coleta_nova_grava_bins_validos_e_manifesto(coleta_base):
    b = coleta_base
    bins = b.bins()
    assert len(bins) == 3 and all(re.fullmatch(r"calibracao_\d+Hz_rep1\.bin", n) for n in bins)
    assert not list(b.pasta().glob(".em_andamento*"))  # nenhum temporário esquecido
    assert [m["status"] for m in b.manifesto()] == ["ok"] * 3
    assert (b.pasta() / "plano_coleta.txt").exists() and (b.pasta() / "ler_adc.log").exists()
    for nome in bins:
        h = cab.ler_cabecalho(b.pasta() / nome)
        assert h.versao_cabecalho == 2 and h.crc32_valido
        assert h.frequencia_hz == TAXA and list(h.lista_canais) == [0, 1]
        assert h.grandeza_por_canal == (0, 1) and h.sonda_id_por_canal == ("", SONDA)
        assert h.blocos_gravados == 1 and h.total_amostras_gravadas == SPB_TESTE
        assert nome.split("_")[1].removesuffix("Hz") in h.titulo  # a frequência pedida vai no título


@com_e2e
def test_coleta_serve_de_entrada_para_gerar_perfil_sonda(coleta_base, tmp_path, cli):
    saida_json = tmp_path / "perfil.json"
    rc, _, _ = cli(gerar_perfil, coleta_base.pasta(), "--resistencia-shunt", 1, "-o", saida_json)
    assert rc == 0
    pontos = json.loads(saida_json.read_text())["pontos"]
    assert len(pontos) == 3
    for p in pontos:  # o ganho recuperado é o da "sonda" simulada (passa-baixa 30 kHz)
        assert p["ganho"] == pytest.approx(float(planta_h(p["freq_hz"])), rel=0.02)


@com_e2e
def test_plano_sugerido_esta_dentro_da_banda_efetiva(bancada):
    """Com 2 canais a Nyquist efetiva é taxa/4: nenhuma frequência do plano pode passar disso."""
    rc, saida = bancada.rodar("--taxa", TAXA, "--pontos", 20, "--sonda", SONDA, entradas="n\n")  # cancela ao ser perguntado
    assert rc == 0 and "Cancelado antes de iniciar" in saida
    freqs = [int(f) for f in re.search(r"Frequências \(Hz\):\s+([\d ]+)", saida).group(1).split()]
    assert len(freqs) == 20 and freqs == sorted(freqs) and freqs[0] == 50
    assert freqs[-1] < TAXA / 4
    assert not bancada.capturas.exists()  # cancelou: nada foi criado


# --------------------------------------------------------------------------------------
# Erros do ponto: o script recusa o ruim e deixa o operador refazer
# --------------------------------------------------------------------------------------
@com_e2e
def test_captura_saturada_e_refeita_ate_ficar_boa(bancada):
    bancada.cenario("sat_sonda", "ok", "ok")
    rc, saida = bancada.rodar("--taxa", TAXA, "--pontos", 2, "--sonda", SONDA, "-y")
    assert rc == 0
    assert "saturou o ADC" in saida
    assert len(bancada.chamadas()) == 3  # a ruim foi medida de novo (sugestão padrão = [R])
    assert len(bancada.bins()) == 2 and [m["status"] for m in bancada.manifesto()] == ["ok", "ok"]


@com_e2e
@pytest.mark.parametrize(
    ("diretiva", "mensagem"),
    [
        ("crc_ruim", "CRC-32 do cabeçalho não confere"),
        ("sonda_errada", "id da sonda no cabeçalho"),
        ("grandeza_tensao", "não está marcado como 'corrente'"),
        ("cab_v1", "versão 1"),
        ("sem_cabecalho", "não começa com o cabeçalho"),
        ("truncar", "captura incompleta"),
        ("falha", "terminou com código 255"),
        ("sem_sinal_sonda", "sem sinal no canal da sonda"),
        ("sem_sinal_ref", "sem sinal no canal de referência"),
        ("sat_ref", "canal de referência (0) saturou"),
        ("freq_errada", "fora da planejada"),
    ],
)
def test_cada_defeito_e_detectado_e_a_captura_ruim_nao_vira_ponto(bancada, diretiva, mensagem):
    bancada.cenario(diretiva, "ok", "ok")
    rc, saida = bancada.rodar("--taxa", TAXA, "--pontos", 2, "--sonda", SONDA, "-y")
    assert rc == 0
    assert mensagem in saida
    assert len(bancada.chamadas()) == 3
    assert len(bancada.bins()) == 2 and all(m["status"] == "ok" for m in bancada.manifesto())


@com_e2e
def test_avisos_nao_impedem_aceitar_e_ficam_no_manifesto(bancada):
    bancada.cenario("fraco", "cab_zero", "ok")
    rc, saida = bancada.rodar("--taxa", TAXA, "--pontos", 2, "--sonda", SONDA, "-y")
    assert rc == 0 and "sinal fraco" in saida
    status = [m["status"] for m in bancada.manifesto()]
    assert status[0] == "ok_com_aviso_fraco_ref_fraco_sonda" and status[1].startswith("ok_com_aviso_cabecalho_final")


@com_e2e
def test_ler_adc_travado_estoura_o_timeout_e_a_captura_e_refeita(bancada):
    bancada.cenario("travar", "ok", "ok")
    rc, saida = bancada.rodar("--taxa", TAXA, "--pontos", 2, "--sonda", SONDA, "-y", extra_env={"SH_LER_ADC_TIMEOUT": "2"})
    assert rc == 0 and "estourou o tempo limite" in saida
    assert len(bancada.bins()) == 2


@com_e2e
def test_opcao_invalida_no_menu_nao_dispara_nova_medicao(bancada):
    # respostas: ENTER (mede), 'x' (inválida), 'c' (aceita) -- e o ponto 2 com ENTERs
    rc, saida = bancada.rodar("--taxa", TAXA, "--pontos", 2, "--sonda", SONDA, "-y", entradas="\nx\nc\n")
    assert rc == 0 and "Opção inválida" in saida
    assert len(bancada.chamadas()) == 2  # uma por ponto: o 'x' não mediu de novo


@com_e2e
def test_pular_e_retomar(bancada):
    # ponto 1: mede e aceita; ponto 2: 'p' (pula antes de medir)
    rc, _ = bancada.rodar("--taxa", TAXA, "--pontos", 2, "--sonda", SONDA, "-y", entradas="\nc\np\n")
    assert rc == 0 and len(bancada.bins()) == 1
    assert [m["status"] for m in bancada.manifesto()] == ["ok", "pulado"]
    rc, saida = bancada.rodar("--modo", "retomar", "--sonda", SONDA, "-y")  # taxa e plano vêm do plano salvo
    assert rc == 0 and "Faltam 1 captura" in saida
    assert len(bancada.bins()) == 2
    assert len(bancada.chamadas()) == 2


@com_e2e
def test_abortar_descarta_a_captura_em_andamento_e_mantem_as_aceitas(bancada):
    rc, saida = bancada.rodar("--taxa", TAXA, "--pontos", 2, "--sonda", SONDA, "-y", entradas="\nc\n\na\n")
    assert rc == 0 and "--modo retomar" in saida
    assert len(bancada.bins()) == 1 and not list(bancada.pasta().glob(".em_andamento*"))


@com_e2e
def test_retomar_com_taxa_diferente_da_do_plano_e_recusado(com_coleta):
    rc, saida = com_coleta.rodar("--modo", "retomar", "--sonda", SONDA, "--taxa", 51200, "-y")
    assert rc != 0 and "Taxa diferente da do plano" in saida
    assert com_coleta.chamadas() == []


# --------------------------------------------------------------------------------------
# Outros modos, sobre uma cópia da coleta base
# --------------------------------------------------------------------------------------
@com_e2e
def test_refazer_substitui_a_captura_antiga_e_a_arquiva(com_coleta):
    freq = com_coleta.bins()[0].split("_")[1].removesuffix("Hz")
    antes = (com_coleta.pasta() / f"calibracao_{freq}Hz_rep1.bin").read_bytes()
    com_coleta.cenario("sat_sonda", "ok")  # a 1ª tentativa sai ruim: a antiga NÃO pode ser arquivada por ela
    rc, saida = com_coleta.rodar("--modo", "refazer", "--freqs", freq, "--sonda", SONDA, "-y")
    assert rc == 0, saida
    assert len(com_coleta.bins()) == 3  # continua 1 captura por frequência
    arquivadas = list((com_coleta.pasta() / "descartadas").glob("*.bin"))
    assert len(arquivadas) == 1 and arquivadas[0].read_bytes() == antes
    assert (com_coleta.pasta() / f"calibracao_{freq}Hz_rep1.bin").read_bytes() != antes
    assert "substituido" in [m["status"] for m in com_coleta.manifesto()]


@com_e2e
def test_refazer_pula_frequencia_inexistente(com_coleta):
    rc, saida = com_coleta.rodar("--modo", "refazer", "--freqs", "999", "--sonda", SONDA, "-y")
    assert rc == 0 and "Não há captura de 999 Hz" in saida
    assert com_coleta.chamadas() == []


@com_e2e
def test_adensar_coloca_um_ponto_entre_cada_par_de_vizinhas(com_coleta):
    antes = sorted(int(n.split("_")[1].removesuffix("Hz")) for n in com_coleta.bins())
    rc, saida = com_coleta.rodar("--modo", "adensar", "--sonda", SONDA, "-y")
    assert rc == 0, saida
    depois = sorted(int(n.split("_")[1].removesuffix("Hz")) for n in com_coleta.bins())
    assert len(depois) == 2 * len(antes) - 1
    assert set(antes) <= set(depois)
    novos = sorted(set(depois) - set(antes))
    for baixo, alto, novo in zip(antes, antes[1:], novos):
        assert baixo < novo < alto
        assert novo == pytest.approx((baixo * alto) ** 0.5, rel=0.01)  # média geométrica (escala log)


@com_e2e
def test_refinar_mede_onde_o_ganho_muda_mais(com_coleta):
    rc, saida = com_coleta.rodar("--modo", "refinar", "--pontos", 1, "--sonda", SONDA, "-y")
    assert rc == 0, saida
    assert "Pontos extras sugeridos" in saida
    assert len(com_coleta.bins()) == 4
    # a sonda simulada só "cai" perto da frequência de corte: o ponto extra tem que vir da parte ALTA
    freqs = sorted(int(n.split("_")[1].removesuffix("Hz")) for n in com_coleta.bins())
    assert freqs[-2] > freqs[1]


@com_e2e
def test_resumo_nao_mede_nada(com_coleta):
    rc, saida = com_coleta.rodar("--modo", "resumo", "--sonda", SONDA)
    assert rc == 0 and "Resumo da coleta" in saida and "Próximos passos" in saida
    assert com_coleta.chamadas() == []


@com_e2e
def test_novo_sobre_pasta_existente_pede_decisao(com_coleta):
    rc, saida = com_coleta.rodar("--taxa", TAXA, "--pontos", 3, "--sonda", SONDA, "-y")
    assert rc != 0 and "--modo retomar" in saida  # com -y não decide por você
    # modo interativo, opção 2: arquiva a coleta anterior e recomeça do zero
    # respostas: 2 (arquivar), ENTER (iniciar), 4 x ENTER (2 pontos: medir + aceitar), 0 (nenhum ponto extra)
    rc, saida = com_coleta.rodar("--taxa", TAXA, "--pontos", 2, "--sonda", SONDA, entradas="2\n" + "\n" * 5 + "0\n")
    assert rc == 0, saida
    arquivadas = list((com_coleta.capturas / "_arquivadas").glob(f"{SONDA}_*"))
    assert len(arquivadas) == 1 and len(list(arquivadas[0].glob("calibracao_*.bin"))) == 3
    assert len(com_coleta.bins()) == 2


# --------------------------------------------------------------------------------------
# Captura de 1 canal (padrão): só a sonda, Nyquist efetiva = taxa/2
# --------------------------------------------------------------------------------------
@com_e2e
def test_um_canal_vai_ate_perto_da_nyquist_inteira_e_o_cabecalho_tem_so_a_sonda(bancada):
    rc, saida = bancada.rodar("--taxa", TAXA, "--canal-sonda", 3, "--pontos", 3, "--freq-min", 1000, "--freq-max", 50000,
                              "--sonda", SONDA, "-y")
    assert rc == 0, saida
    assert "passa de 90% da Nyquist efetiva (51200.0 Hz)" in saida  # 50 kHz = 97,7%: permitido, mas avisa
    assert [m["status"] for m in bancada.manifesto()] == ["ok"] * 3  # inclusive o ponto de 50 kHz (2,05 amostras por ciclo)
    assert sorted(int(n.split("_")[1].removesuffix("Hz")) for n in bancada.bins())[-1] == 50000
    for nome in bancada.bins():
        h = cab.ler_cabecalho(bancada.pasta() / nome)
        assert h.crc32_valido and h.frequencia_hz == TAXA
        assert h.num_canais == 1 and list(h.lista_canais[:1]) == [3]
        assert h.grandeza_por_canal[0] == 1 and h.sonda_id_por_canal[0] == SONDA
    # o ler_adc recebeu UM canal só
    assert all(f":: {TAXA} 3 --blocos" in linha for linha in bancada.chamadas())
    assert "referência" not in "\n".join(re.findall(r"Canais:.*", saida)) and "Corrente real:       CONSTANTE" in saida


@com_e2e
def test_plano_de_um_canal_passa_do_limite_dos_dois_canais(bancada):
    rc, saida = bancada.rodar("--taxa", TAXA, "--canal-sonda", 1, "--pontos", 20, "--sonda", SONDA, entradas="n\n")
    assert rc == 0 and "Cancelado antes de iniciar" in saida
    freqs = [int(f) for f in re.search(r"Frequências \(Hz\):\s+([\d ]+)", saida).group(1).split()]
    assert TAXA / 4 < freqs[-1] < 0.9 * TAXA / 2  # 40,9 kHz: 80% de taxa/2 (com 2 canais seriam 20,4 kHz)
    assert "Nyquist efetiva 51200.0 Hz" in saida


@com_e2e
@pytest.mark.parametrize(
    ("diretiva", "mensagem"),
    [
        ("crc_ruim", "CRC-32 do cabeçalho não confere"),
        ("sonda_errada", "id da sonda no cabeçalho"),
        ("grandeza_tensao", "não está marcado como 'corrente'"),
        ("truncar", "captura incompleta"),
        ("sat_sonda", "canal da sonda (1) saturou"),
        ("sem_sinal_sonda", "sem sinal no canal da sonda"),
        ("freq_errada", "fora da planejada"),
    ],
)
def test_um_canal_detecta_os_mesmos_defeitos(bancada, diretiva, mensagem):
    bancada.cenario(diretiva, "ok", "ok")
    rc, saida = bancada.rodar("--taxa", TAXA, "--canal-sonda", 1, "--pontos", 2, "--sonda", SONDA, "-y")
    assert rc == 0
    assert mensagem in saida
    assert len(bancada.chamadas()) == 3
    assert len(bancada.bins()) == 2 and all(m["status"] == "ok" for m in bancada.manifesto())


@com_e2e
def test_ref_externa_pede_a_leitura_valida_a_entrada_e_grava_o_csv(bancada):
    # ponto 1: ENTER (medir), 'abc' (inválida), 707.1m (milivolts), ENTER (aceita); ponto 2: leitura em volts
    rc, saida = bancada.rodar("--taxa", TAXA, "--canal-sonda", 3, "--pontos", 2, "--sonda", SONDA, "--ref-externa", "-y",
                              entradas="\nabc\n707.1m\n\n\n0,7071\n\n")
    assert rc == 0, saida
    assert "Valor inválido: 'abc'" in saida and "Leitura do osciloscópio: 0.7071 V RMS no shunt" in saida
    linhas = (bancada.pasta() / "referencia_externa.csv").read_text().splitlines()
    assert linhas[0] == "arquivo,v_shunt_rms_V" and len(linhas) == 3
    assert [ln.split(",")[1] for ln in linhas[1:]] == ["0.7071", "0.7071"]
    assert [m["ref_externa_v_rms"] for m in bancada.manifesto()] == ["0.7071", "0.7071"]
    assert "--referencia-externa --resistencia-shunt" in saida  # o comando sugerido para gerar o perfil


@com_e2e
def test_ref_externa_sem_leitura_avisa_e_deixa_o_ponto_de_fora_do_perfil(bancada, cli, tmp_path):
    rc, saida = bancada.rodar("--taxa", TAXA, "--canal-sonda", 3, "--pontos", 2, "--sonda", SONDA, "--ref-externa", "-y",
                              entradas="\n0.7071\n\n\n\n\n")  # ponto 2 sem leitura (ENTER)
    assert rc == 0, saida
    assert "Sem leitura para este ponto" in saida and "1 captura(s) sem leitura do osciloscópio" in saida
    rc, _, err = cli(gerar_perfil, bancada.pasta(), "--referencia-externa", "--resistencia-shunt", 1, "-o", tmp_path / "p.json")
    assert rc == 1 and "sem leitura do instrumento externo" in err  # sobrou 1 ponto: precisa de 2


@com_e2e
def test_um_canal_e_ref_externa_servem_de_entrada_para_gerar_perfil_sonda(coleta_1canal, tmp_path, cli):
    b = coleta_1canal
    assert [m["status"] for m in b.manifesto()] == ["ok"] * 3
    saida_json = tmp_path / "perfil.json"
    # shunt de 1 ohm: a leitura digitada (0,7071 V RMS) = 1 A de pico; o ler_adc falso gera H(f) V na sonda
    rc, _, err = cli(gerar_perfil, b.pasta(), "--referencia-externa", "--resistencia-shunt", 1, "-o", saida_json)
    assert rc == 0, err
    pontos = json.loads(saida_json.read_text())["pontos"]
    assert len(pontos) == 3
    for p in pontos:
        assert p["ganho"] == pytest.approx(float(planta_h(p["freq_hz"])), rel=0.02)
    # e a corrente constante informada à mão dá o mesmo perfil
    rc, _, err = cli(gerar_perfil, b.pasta(), "--amplitude-referencia", 1, "-o", tmp_path / "p2.json")
    assert rc == 0, err
    for p in json.loads((tmp_path / "p2.json").read_text())["pontos"]:
        assert p["ganho"] == pytest.approx(float(planta_h(p["freq_hz"])), rel=0.02)


@com_e2e
def test_refazer_com_ref_externa_nao_herda_a_leitura_antiga(com_coleta_1canal):
    b = com_coleta_1canal
    nome = b.bins()[0]
    antes = (b.pasta() / "referencia_externa.csv").read_text()
    # refaz o 1º ponto SEM digitar leitura (ENTER): a leitura antiga daquele arquivo tem que ser anulada
    freq = nome.split("_")[1].removesuffix("Hz")
    rc, saida = b.rodar("--modo", "refazer", "--freqs", freq, "--sonda", SONDA, "-y", canais=False, entradas="\n\n\n")
    assert rc == 0, saida
    depois = (b.pasta() / "referencia_externa.csv").read_text()
    assert depois.startswith(antes) and depois.splitlines()[-1] == f"{nome},"
    assert "1 captura(s) sem leitura do osciloscópio" in saida


@pytest.fixture
def com_coleta_1canal(coleta_1canal, tmp_path):
    b = Bancada(tmp_path)
    shutil.copytree(coleta_1canal.capturas, b.capturas)
    return b


@com_e2e
def test_sem_canal_da_sonda_o_script_pergunta(bancada):
    # respostas: canal 2; referência: opção 2 (corrente constante, 1 canal); depois só ENTERs
    rc, saida = bancada.rodar("--taxa", TAXA, "--pontos", 2, "--sonda", SONDA, "-y", canais=False, entradas="2\n2\n")
    assert rc == 0, saida
    assert "Como o script vai saber a corrente real" in saida  # (o prompt do read não aparece com stdin em pipe)
    h = cab.ler_cabecalho(bancada.pasta() / bancada.bins()[0])
    assert h.num_canais == 1 and list(h.lista_canais[:1]) == [2]


@com_e2e
def test_sem_canal_da_sonda_e_sem_resposta_da_erro_claro(bancada):
    rc, saida = bancada.rodar("--taxa", TAXA, "--pontos", 2, "--sonda", SONDA, "-y", canais=False, eof=True)
    assert rc != 0 and "--canal-sonda" in saida
    assert bancada.chamadas() == []


@com_e2e
def test_retomar_herda_os_canais_do_plano(coleta_1canal, tmp_path):
    b = Bancada(tmp_path)
    shutil.copytree(coleta_1canal.capturas, b.capturas)
    (b.pasta() / b.bins()[0]).unlink()   # falta 1 ponto
    rc, saida = b.rodar("--modo", "retomar", "--sonda", SONDA, "-y", canais=False, entradas="\n0.7071\n\n")
    assert rc == 0, saida
    assert len(b.bins()) == 3 and f":: {TAXA} 3 --blocos" in b.chamadas()[0]   # canal 3, sem referência, vindo do plano
    assert "Faltam 1 captura" in saida


@com_e2e
def test_retomar_com_canais_diferentes_do_plano_e_recusado(coleta_1canal):
    antes = coleta_1canal.chamadas()
    rc, saida = coleta_1canal.rodar("--modo", "retomar", "--sonda", SONDA, "--canal-sonda", 1, "--canal-referencia", 0, "-y",
                                    canais=False)
    assert rc != 0 and "Canais diferentes dos do plano" in saida
    assert coleta_1canal.chamadas() == antes  # nada novo foi medido
