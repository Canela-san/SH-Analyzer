"""Testes de ``scripts/BeagleBone_Setup.sh``, a interface entre o computador e a BeagleBone.

Rodam o script de verdade (bash), com programas FALSOS no PATH onde o real não pode ser usado (``ssh``, ``sudo``,
``date -s`` e ``sshfs``): o ssh falso roda o comando "remoto" aqui mesmo, num home falso. Marcados ``e2e``.
(O ``compactar_amostras`` virou Python: ``tests/test_compactacao.py``.)
"""

import glob
import os
import shutil
import signal
import subprocess
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
SCRIPT = RAIZ / "scripts" / "BeagleBone_Setup.sh"
GIT = ["git", "-c", "user.name=Teste", "-c", "user.email=teste@exemplo", "-c", "commit.gpgsign=false",
       "-c", "tag.gpgsign=false"]

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(sys.platform != "linux" or shutil.which("bash") is None, reason="precisa de Linux com bash"),
]


def _executavel(caminho: Path, conteudo: str) -> Path:
    caminho.write_text(conteudo)
    caminho.chmod(0o755)
    return caminho


def _senhas_na_ram(bancada) -> list[str]:
    """As pastas de senha do sudo que o script deixa na "RAM" da placa durante um comando (têm de sumir no fim).
    Nos testes, a RAM é uma pasta do teste (SH_ANALYZER_RAM), e não /dev/shm, que os testes em paralelo dividem."""
    return sorted(glob.glob(str(bancada.ram / "sh-analyzer.*")))


@pytest.fixture
def bancada(tmp_path):
    """Um repositório de brinquedo com o script e um firmware/ mínimo, e um ssh falso que roda o comando "remoto"
    num home falso (``bancada.home``), lendo o stdin como o ssh de verdade."""
    if shutil.which("git") is None or shutil.which("tar") is None:
        pytest.skip("precisa de git e tar")
    repo = tmp_path / "repo"
    (repo / "scripts").mkdir(parents=True)
    (repo / "firmware").mkdir()
    shutil.copy2(SCRIPT, repo / "scripts" / SCRIPT.name)
    (repo / ".gitignore").write_text("firmware/VERSAO\nfirmware/ler_adc\n")
    (repo / "firmware" / "ler_adc.c").write_text("int main(void) { return 0; }\n")
    (repo / "firmware" / "Makefile").write_text("all:\n")
    _executavel(repo / "firmware" / "setup.sh",
                '#!/bin/bash\necho "setup rodou em $(basename "$PWD")"\n'
                'echo "senha do sudo pelo askpass: $("$SUDO_ASKPASS")"\n'
                'echo "PRU_C_DIR=${PRU_C_DIR:-}"\n')
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run([*GIT, "add", "-A"], cwd=repo, check=True)
    subprocess.run([*GIT, "commit", "-q", "-m", "inicial"], cwd=repo, check=True)
    subprocess.run([*GIT, "tag", "-a", "v9.9", "-m", "v9.9"], cwd=repo, check=True)   # anotada, como as do projeto
    (repo / "firmware" / "ler_adc").write_text("binário compilado no PC: não pode ir\n")   # ignorado pelo git
    home = tmp_path / "home_bbb"
    home.mkdir()
    falsos = tmp_path / "falsos"
    falsos.mkdir()
    _executavel(falsos / "ssh", f'#!/bin/bash\ncd "{home}" && exec bash -c "${{@: -1}}"\n')

    class Bancada:
        pass

    b = Bancada()
    b.repo, b.home, b.falsos, b.tmp, b.ram = repo, home, falsos, tmp_path, tmp_path / "ram"
    b.ram.mkdir()

    def rodar(*args, **env_extra):
        env = {k: v for k, v in os.environ.items() if not k.startswith("BBB_")}
        env.update({"PATH": f"{falsos}:{os.environ['PATH']}", "XDG_CONFIG_HOME": str(tmp_path / "config"),
                    "SH_ANALYZER_RAM": str(b.ram), "NO_COLOR": "1", **env_extra})
        return subprocess.run(["bash", str(repo / "scripts" / SCRIPT.name), *args], cwd=repo, env=env,
                              capture_output=True, text=True, timeout=60)

    def commit(mensagem):
        subprocess.run([*GIT, "commit", "-q", "-am", mensagem], cwd=repo, check=True)

    b.rodar, b.commit = rodar, commit
    return b


# ---------------------------------------------------------------------------
# Acesso: IP, usuário e senha informados uma vez
# ---------------------------------------------------------------------------

def test_askpass_responde_so_a_pedidos_de_senha():
    env = {**os.environ, "_SH_ANALYZER_ASKPASS": "1", "_SH_ANALYZER_SENHA": "s3nh@ com espaço"}
    r = subprocess.run(["bash", str(SCRIPT), "debian@192.168.6.2's password: "], env=env, capture_output=True,
                       text=True, timeout=30)
    assert r.returncode == 0 and r.stdout == "s3nh@ com espaço\n"
    r = subprocess.run(["bash", str(SCRIPT), "Enter passphrase for key '/home/x/.ssh/id_ed25519': "], env=env,
                       capture_output=True, text=True, timeout=30)
    assert r.returncode == 1 and r.stdout == ""                       # a frase de uma chave não é a senha da placa


def test_opcao_vence_variavel_que_vence_o_arquivo_do_configurar(bancada):
    registro = bancada.tmp / "ssh_chamado"
    _executavel(bancada.falsos / "ssh", f'#!/bin/bash\nprintf "%s|%s\\n" "${{@: -2:1}}" "$_SH_ANALYZER_SENHA" >> "{registro}"\n'
                                        'echo "ssh: connect to host x port 22: No route to host" >&2\nexit 255\n')
    config = bancada.tmp / "config" / "sh-analyzer" / "beaglebone.conf"
    config.parent.mkdir(parents=True)
    config.write_text("# comentário\nip=10.1.1.1\nusuario=fulano\nsenha=do arquivo\n")

    r = bancada.rodar("status")
    assert r.returncode == 1 and "não consegui entrar em fulano@10.1.1.1" in r.stderr
    assert "192.168.7.2" in r.stderr                                  # a dica do outro endereço da USB
    assert registro.read_text().splitlines()[-1] == "fulano@10.1.1.1|do arquivo"
    bancada.rodar("status", BBB_IP="10.2.2.2", BBB_SENHA="da variável")
    assert registro.read_text().splitlines()[-1] == "fulano@10.2.2.2|da variável"
    bancada.rodar("--ip", "10.3.3.3", "status", BBB_IP="10.2.2.2")
    assert registro.read_text().splitlines()[-1].startswith("fulano@10.3.3.3|")


def test_padroes_da_imagem_debian(bancada):
    registro = bancada.tmp / "ssh_chamado"
    _executavel(bancada.falsos / "ssh", f'#!/bin/bash\nprintf "%s|%s\\n" "${{@: -2:1}}" "$_SH_ANALYZER_SENHA" >> "{registro}"\n'
                                        'exit 255\n')
    bancada.rodar("hora")
    assert registro.read_text().splitlines()[0] == "debian@192.168.6.2|temppwd"


def test_senha_recusada_e_chave_trocada_tem_dica(bancada):
    _executavel(bancada.falsos / "ssh", '#!/bin/bash\necho "debian@192.168.6.2: Permission denied (password)." >&2\nexit 255\n')
    r = bancada.rodar("setup")
    assert r.returncode == 1 and "configurar" in r.stderr
    _executavel(bancada.falsos / "ssh", '#!/bin/bash\necho "WARNING: REMOTE HOST IDENTIFICATION HAS CHANGED!" >&2\nexit 255\n')
    r = bancada.rodar("ssh")
    assert r.returncode == 1 and "ssh-keygen -R 192.168.6.2" in r.stderr


# ---------------------------------------------------------------------------
# hora (o antigo set_date.sh)
# ---------------------------------------------------------------------------

def test_hora_desconta_o_tempo_do_sudo_e_diz_o_erro(bancada):
    """O sudo falso demora 1 s e o date falso anota a hora que seria gravada, em vez de mudar o relógio."""
    gravada = bancada.tmp / "hora_gravada"
    _executavel(bancada.falsos / "sudo", '#!/bin/bash\nwhile [ "$1" != bash ]; do shift; done\nsleep 1\nexec "$@"\n')
    _executavel(bancada.falsos / "date", f'#!/bin/bash\nif [ "$1 $2" = "-u -s" ]; then echo "${{3#@}}" > "{gravada}"; '
                                         'exit 0; fi\nexec /usr/bin/date "$@"\n')
    antes = float(subprocess.run(["/usr/bin/date", "-u", "+%s.%N"], capture_output=True, text=True).stdout)
    r = bancada.rodar("hora")
    assert r.returncode == 0, r.stdout + r.stderr
    assert 1.0 <= float(gravada.read_text()) - antes < 3.0    # a hora enviada mais o segundo gasto no sudo
    assert "acertado:" in r.stdout and "já estava certo" in r.stdout   # o relógio "de lá" é o daqui
    assert _senhas_na_ram(bancada) == []                       # a senha do sudo não ficou na RAM


# ---------------------------------------------------------------------------
# enviar: só firmware/, com a versão e o plano B (sem copiar capturas)
# ---------------------------------------------------------------------------

def test_envia_so_o_firmware_versionado_com_a_versao(bancada):
    r = bancada.rodar("enviar")
    assert r.returncode == 0, r.stderr
    remoto = bancada.home / "firmware"
    assert sorted(p.name for p in remoto.iterdir()) == ["Makefile", "VERSAO", "ler_adc.c", "setup.sh"]
    assert (remoto / "VERSAO").read_text() == "v9.9\n"
    assert (remoto / "setup.sh").stat().st_mode & 0o111                        # continua executável
    assert not (bancada.home / "firmware-anteriores").exists()
    assert "primeira cópia" in r.stdout and "firmware v9.9 na BeagleBone" in r.stdout
    assert "Próximo passo" in r.stdout and "setup" in r.stdout


def test_segundo_envio_guarda_o_plano_b_sem_as_capturas(bancada):
    assert bancada.rodar("enviar").returncode == 0
    remoto = bancada.home / "firmware"
    (remoto / "ler_adc").write_text("binário compilado na BeagleBone\n")
    (remoto / "T0.bin").write_bytes(b"\x00" * 4096)                             # uma captura na pasta do firmware
    (remoto / "capturas").mkdir()
    (remoto / "capturas" / "x.bin").write_bytes(b"\x00" * 16)
    (bancada.repo / "firmware" / "ler_adc.c").write_text("int main(void) { return 1; }\n")
    bancada.commit("ler_adc novo")
    r = bancada.rodar("enviar")
    assert r.returncode == 0, r.stderr
    (plano_b,) = (bancada.home / "firmware-anteriores").iterdir()
    assert plano_b.name.endswith("_v9.9")
    assert sorted(p.name for p in plano_b.iterdir()) == ["Makefile", "VERSAO", "ler_adc", "ler_adc.c", "setup.sh"]
    assert "return 0" in (plano_b / "ler_adc.c").read_text()                     # o código antigo, inteiro
    assert "return 1" in (remoto / "ler_adc.c").read_text()
    assert (remoto / "VERSAO").read_text().startswith("v9.9-1-g")
    assert (remoto / "T0.bin").stat().st_size == 4096 and (remoto / "capturas" / "x.bin").exists()   # nada apagado


def test_recusa_firmware_com_mudancas_nao_commitadas(bancada):
    (bancada.repo / "firmware" / "ler_adc.c").write_text("int main(void) { return 2; }\n")
    r = bancada.rodar("enviar")
    assert r.returncode == 1 and "mudanças não commitadas" in r.stderr and "ler_adc.c" in r.stderr
    assert not (bancada.home / "firmware").exists()
    r = bancada.rodar("enviar", "--forcar")
    assert r.returncode == 0, r.stderr
    assert (bancada.home / "firmware" / "VERSAO").read_text() == "v9.9-dirty\n"


def test_simular_nao_escreve_nem_envia(bancada):
    r = bancada.rodar("enviar", "--simular")
    assert r.returncode == 0 and "--simular" in r.stdout and "ler_adc.c" in r.stdout
    assert not (bancada.home / "firmware").exists() and not (bancada.repo / "firmware" / "VERSAO").exists()


# ---------------------------------------------------------------------------
# setup e ssh: o sudo de lá sem perguntar, e sem deixar a senha para trás
# ---------------------------------------------------------------------------

def test_pasta_com_til_e_setup_com_a_senha_do_sudo(bancada):
    r = bancada.rodar("enviar", "--setup", BBB_PASTA="~/sh/firmware", BBB_SENHA="abc 123")
    assert r.returncode == 0, r.stderr
    assert (bancada.home / "sh" / "firmware" / "VERSAO").exists()               # o '~/' vira o home, não uma pasta '~'
    assert "setup rodou em firmware" in r.stdout
    assert "senha do sudo pelo askpass: abc 123" in r.stdout                   # o setup.sh não pergunta nada
    assert _senhas_na_ram(bancada) == []


def test_setup_traz_as_variaveis_do_compilador_do_shell_interativo(bancada):
    """A imagem da BeagleBone define o caminho do compilador da PRU só no shell interativo (~/.bashrc, depois do teste
    de interativo): o 'ssh comando' do setup não o via, e o clpru não achava o stdint.h."""
    (bancada.home / ".bashrc").write_text('case $- in *i*) ;; *) return ;; esac\n'
                                          'echo "bem-vindo à BeagleBone"\n'
                                          'export PRU_C_DIR="/usr/share/ti/cgt-pru/include;/usr/share/ti/cgt-pru/lib"\n')
    r = bancada.rodar("enviar", "--setup", HOME=str(bancada.home))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PRU_C_DIR=/usr/share/ti/cgt-pru/include;/usr/share/ti/cgt-pru/lib" in r.stdout
    assert "bem-vindo" not in r.stdout                                          # o que o .bashrc imprime não atrapalha


def test_setup_sem_firmware_la_diz_para_enviar(bancada):
    r = bancada.rodar("setup")
    assert r.returncode == 1 and "envie o firmware antes" in r.stdout + r.stderr


def test_ssh_com_comando_roda_na_pasta_do_firmware(bancada):
    assert bancada.rodar("enviar").returncode == 0
    r = bancada.rodar("ssh", 'echo "em $(basename "$PWD")";', 'echo "sudo: $("$SUDO_ASKPASS")"', BBB_SENHA_SUDO="xyz")
    assert r.returncode == 0, r.stderr
    assert "em firmware" in r.stdout and "sudo: xyz" in r.stdout
    assert _senhas_na_ram(bancada) == []
    r = bancada.rodar("ssh", "exit 7")
    assert r.returncode == 7                                                    # o código de saída de lá


# ---------------------------------------------------------------------------
# status, montar e erros de uso
# ---------------------------------------------------------------------------

def test_status_mostra_o_painel(bancada):
    assert bancada.rodar("enviar").returncode == 0
    (bancada.home / "firmware" / "T7a.bin").write_bytes(b"\x00" * 8192)
    r = bancada.rodar("status")
    assert r.returncode == 0, r.stderr
    assert "Relógio" in r.stdout and "(certo)" in r.stdout
    assert "v9.9" in r.stdout and "o mesmo do repositório" in r.stdout
    assert "ler_adc não compilado" in r.stdout                                  # o envio não leva o binário
    assert "1 arquivo(s) .bin" in r.stdout
    sem_comando = bancada.rodar()                                               # sem comando = status
    assert sem_comando.returncode == 0 and "Relógio" in sem_comando.stdout


def test_montar_recusa_pasta_no_repositorio_e_passa_as_opcoes(bancada):
    registro = bancada.tmp / "sshfs_chamado"
    _executavel(bancada.falsos / "sshfs", f'#!/bin/bash\nprintf "%s\\n" "$@" "askpass=$SSH_ASKPASS" > "{registro}"\n')
    r = bancada.rodar("montar", "./BeagleBone")
    assert r.returncode == 1 and "dentro do repositório" in r.stderr and not registro.exists()
    ponto = bancada.tmp / "montagem"
    r = bancada.rodar("montar", str(ponto))
    assert r.returncode == 0, r.stderr
    alvo, pasta, o, opcoes, askpass = registro.read_text().splitlines()
    assert (alvo, pasta, o) == ("debian@192.168.6.2:", str(ponto), "-o")
    for opcao in ("reconnect", "ServerAliveInterval=15", "ServerAliveCountMax=3", "idmap=user", "ControlMaster=no"):
        assert opcao in opcoes.split(",")
    assert askpass.endswith("BeagleBone_Setup.sh")                             # a senha também na reconexão
    r = bancada.rodar("desmontar", str(ponto))
    assert r.returncode == 0 and "não está montado" in r.stdout


def test_opcao_e_comando_desconhecidos_sao_erro(bancada):
    r = bancada.rodar("--nao-existe")
    assert r.returncode == 1 and "opção desconhecida" in r.stderr
    r = bancada.rodar("voar")
    assert r.returncode == 1 and "comando desconhecido" in r.stderr
    r = bancada.rodar("ajuda")
    assert r.returncode == 0 and "preparar" in r.stdout and "montar" in r.stdout


def test_preparar_acerta_a_hora_envia_e_roda_o_setup(bancada):
    _executavel(bancada.falsos / "sudo", '#!/bin/bash\nwhile [ "$1" != bash ]; do shift; done\nexec "$@"\n')
    _executavel(bancada.falsos / "date", '#!/bin/bash\nif [ "$1 $2" = "-u -s" ]; then exit 0; fi\nexec /usr/bin/date "$@"\n')
    r = bancada.rodar("preparar")
    assert r.returncode == 0, r.stdout + r.stderr
    for trecho in ("Relógio", "acertado:", "firmware v9.9 na BeagleBone", "setup rodou em firmware",
                   "senha do sudo pelo askpass: temppwd", "Pronto."):
        assert trecho in r.stdout, trecho
    assert _senhas_na_ram(bancada) == []


# ---------------------------------------------------------------------------
# firmware/Makefile: o clpru acha o stdint.h mesmo sem a variável do shell interativo
# ---------------------------------------------------------------------------

def _make_pru(tmp_path, clpru_em: Path, **env_extra) -> subprocess.CompletedProcess:
    """'make -n pru' com um clpru falso em ``clpru_em`` (no PATH) e sem as variáveis do shell interativo."""
    usr_bin = tmp_path / "path"
    usr_bin.mkdir(exist_ok=True)
    if not (usr_bin / "clpru").exists():
        (usr_bin / "clpru").symlink_to(clpru_em)
    env = {k: v for k, v in os.environ.items() if k not in ("PRU_CGT", "PRU_C_DIR", "C_DIR")}
    env.update({"PATH": f"{usr_bin}:{env['PATH']}", **env_extra})
    return subprocess.run(["make", "-n", "pru"], cwd=RAIZ / "firmware", env=env, capture_output=True, text=True,
                          timeout=30)


def _instalacao_ti(raiz: Path) -> Path:
    """Uma instalação de brinquedo do compilador da TI: bin/clpru, include/stdint.h e lib/rtspruv3_le.lib."""
    for sub in ("bin", "include", "lib"):
        (raiz / sub).mkdir(parents=True)
    _executavel(raiz / "bin" / "clpru", "#!/bin/sh\n")
    (raiz / "include" / "stdint.h").write_text("/* da PRU */\n")
    (raiz / "lib" / "rtspruv3_le.lib").write_bytes(b"")
    return raiz.resolve()


@pytest.fixture
def com_make():
    if shutil.which("make") is None:
        pytest.skip("precisa do make")


def test_makefile_acha_a_instalacao_ti_pelo_link_do_clpru(tmp_path, com_make):
    """Num 'ssh comando' (o BeagleBone_Setup.sh setup), a PRU_C_DIR do shell interativo não existe."""
    ti = _instalacao_ti(tmp_path / "ti" / "cgt-pru")
    r = _make_pru(tmp_path, ti / "bin" / "clpru")
    assert r.returncode == 0, r.stderr
    assert f"--include_path={ti}/include pru_main.c" in r.stdout
    assert f"-z -i{ti}/lib -i{ti}/include AM335x_PRU.cmd" in r.stdout


def test_makefile_nao_usa_o_usr_include_do_linux(tmp_path, com_make):
    """O clpru da imagem da BeagleBone fica em /usr/bin, e o /usr/include ao lado tem o stdint.h da glibc (o clpru
    parava em "bits/libc-header-start.h"): sem a biblioteca rtspru em lib/, a pasta não é a da TI."""
    usr = tmp_path / "usr"
    (usr / "bin").mkdir(parents=True)
    (usr / "include").mkdir()
    (usr / "include" / "stdint.h").write_text("/* da glibc */\n")
    _executavel(usr / "bin" / "clpru", "#!/bin/sh\n")
    r = _make_pru(tmp_path, usr / "bin" / "clpru")
    if "--include_path=" in r.stdout:                     # uma instalação da TI de verdade nesta máquina
        assert str(usr.resolve()) not in r.stdout
    else:
        assert "não foi achada" in r.stderr and "PRU_CGT" in r.stderr
    ti = _instalacao_ti(tmp_path / "opt" / "ti-cgt-pru")
    r = _make_pru(tmp_path, usr / "bin" / "clpru", PRU_CGT=str(ti))   # a do ambiente vale primeiro
    assert f"--include_path={ti}/include" in r.stdout and f"-i{ti}/lib" in r.stdout
    assert "não foi achada" not in r.stderr


# ---------------------------------------------------------------------------
# firmware/varrer_taxa.sh: o T7e inteiro numa tacada
# ---------------------------------------------------------------------------

LER_ADC_FALSO = r'''#!/bin/bash
# ler_adc falso: a PRU alcança 200 MHz / (595 + 2 (S + H + A)); acima disso, conta amostras atrasadas. A folga da
# grade de tempo (firmware de 22/10/2026) é o que sobra do período nesse quadro.
taxa=$1; canais=$2; shift 2
while [ $# -gt 0 ]; do
    case "$1" in
        -o) saida=$2; shift ;; --atraso-cs) cs=$2; shift ;; --blocos) blocos=$2; shift ;;
        --duracao) duracao=$2; blocos=9; shift ;; --spi) spi=$2; shift ;; -d) descricao=$2; shift ;;
    esac
    shift
done
IFS=, read -r s h a <<< "${cs:-3,1,3}"         # sem --atraso-cs: o padrão do firmware
sleep "${LER_ADC_DEMORA:-0}"
quadro=$((595 + 2 * (s + h + a)))
case "${spi:-}" in rapido*) quadro=467 ;; esac          # o SPI rápido (~428 kS/s no máximo)
maximo=$((200000000 / quadro))
atrasadas=0; real=$taxa
if [ "$taxa" -gt "$maximo" ]; then atrasadas=123; real=$maximo; fi
echo "taxa=$taxa canais=$canais blocos=$blocos cs=$cs${duracao:+ duracao=$duracao}${spi:+ spi=$spi}${descricao:+ d=$descricao}" > "$saida"
if [ "$blocos" -ge 2 ]; then
    printf 'Taxa real medida pelo ARM: %d Hz (pedida %d Hz, %+.2f %%)\n' "$real" "$taxa" \
        "$(awk -v r="$real" -v t="$taxa" 'BEGIN { print 100 * (r / t - 1) }')"
fi
printf 'Integridade: %d amostra(s) atrasada(s), 0 buffer(s) sobrescrito(s), 0 quadro(s) com ruído no SDO\n' "$atrasadas"
if [ "$blocos" -lt 2 ]; then
    echo 'Grade de tempo (PRU): folga ainda não publicada (a PRU a publica logo depois de cada bloco) | rebase: 2 ciclo(s) entre as leituras'
elif [ "$atrasadas" -eq 0 ]; then
    folga=$((200000000 / taxa - quadro))
    printf 'Grade de tempo (PRU): folga mínima %d ciclo(s) = %d ns -- toda amostra no ciclo exato da grade; período constante até ~%d S/s | rebase: 2 ciclo(s) entre as leituras\n' \
        "$folga" $((5 * folga)) $((200000000 / quadro))
else
    echo "Grade de tempo (PRU): 123 amostra(s) fora da grade, a pior 77 ciclo(s) = 385 ns atrasada | rebase: 2 ciclo(s) entre as leituras"
fi
case "${spi:-}" in
    rapido*) echo "SPI rápido (fase B gravada): 0 quadro(s) com a fase A (60 ns) diferente da B (75 ns) e 7 com a C (90 ns), em 2097152 quadro(s) -- o bit seguinte chega antes de 90 ns" ;;
esac
[ -z "${LER_ADC_REGISTRO:-}" ] || pgrep -x dd > /dev/null && echo "dd rodando" >> "${LER_ADC_REGISTRO:-/dev/null}"
'''


@pytest.fixture
def varredura(tmp_path):
    pasta = tmp_path / "firmware"
    pasta.mkdir()
    shutil.copy2(RAIZ / "firmware" / "varrer_taxa.sh", pasta / "varrer_taxa.sh")
    (pasta / "VERSAO").write_text("v9.9\n")
    _executavel(pasta / "ler_adc", LER_ADC_FALSO)
    falsos = tmp_path / "falsos"
    falsos.mkdir()
    _executavel(falsos / "sudo", '#!/bin/bash\nwhile [[ "${1:-}" == -* ]]; do shift; done\n'
                                 '[ $# -gt 0 ] || exit 0\nexec "$@"\n')

    env = {k: v for k, v in os.environ.items() if k != "SUDO_ASKPASS"}
    env.update({"PATH": f"{falsos}:{os.environ['PATH']}", "LC_ALL": "C", "NO_COLOR": "1"})

    def rodar(*args, entrada=""):
        r = subprocess.run(["bash", str(pasta / "varrer_taxa.sh"), *args], cwd=tmp_path, env=env, input=entrada,
                           capture_output=True, text=True, timeout=120)
        resultados = sorted(pasta.glob("T7e_*"))
        return r, (resultados[-1] if resultados else None)

    rodar.pasta, rodar.env = pasta, env
    return rodar


def _resumo(pasta: Path) -> list[dict]:
    import csv
    with open(pasta / "resumo.csv", newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def test_varrer_taxa_captura_o_plano_inteiro_e_resume(varredura):
    r, pasta = varredura(entrada="\np\n")                    # D: feita; C: pulada ("p")
    assert r.returncode == 0, r.stdout + r.stderr
    linhas = _resumo(pasta)
    partes = [linha["parte"] for linha in linhas]
    assert partes.count("A") == 26 and partes.count("B") == 52 and partes.count("D") == 5 and "C" not in partes
    assert len({linha["arquivo"] for linha in linhas}) == len(linhas)          # nenhuma captura repetida no plano
    por_nome = {linha["arquivo"]: linha for linha in linhas}
    assert por_nome["A_cs200-100-100_100000_tom.bin"]["amostras_atrasadas"] == "0"
    lento = por_nome["B_cs200-100-100_500000_tom.bin"]                   # o padrão não chega a 500 kS/s
    assert lento["amostras_atrasadas"] == "123" and int(lento["taxa_arm_hz"]) < 150000
    assert por_nome["B_cs3-1-3_250000_tom.bin"]["amostras_atrasadas"] == "0"
    dois = pasta / "D_cs20-10-10_250000_tom_2canais.bin"
    assert dois.read_text().split() == ["taxa=250000", "canais=0,1", "blocos=3", "cs=20,10,10"]
    log = (pasta / "log.txt").read_text()
    assert "firmware v9.9" in log and "pausa" in log and "Integridade" in log
    assert "Pronto" in r.stdout and "trazer 'T7e_*'" in r.stdout


def test_varrer_taxa_curto_com_1_bloco_e_simular(varredura):
    r, pasta = varredura("--simular")
    assert r.returncode == 0 and "101 capturas" in r.stdout and pasta is None   # nada capturado
    r, pasta = varredura("--partes", "C", entrada="\n")
    assert r.returncode == 0, r.stdout + r.stderr
    linhas = _resumo(pasta)
    assert len(linhas) == 18 and {linha["entrada"] for linha in linhas} == {"curto"}
    assert all(linha["taxa_arm_hz"] == "?" for linha in linhas)          # 1 bloco: o ARM não mede a taxa
    assert "blocos=1" in (pasta / "C_cs3-1-3_100000_curto.bin").read_text()


def test_varrer_taxa_para_sem_terminal_na_pausa_e_continua_de_onde_parou(varredura):
    """Como em 21/10: a conexão caiu na pausa da parte D. Sem terminal, a varredura para ali, com o que
    foi feito salvo; --continuar pula o que tem linha no resumo e refaz a que o ler_adc não terminou."""
    r, pasta = varredura(entrada="")                          # sem terminal: o read da pausa falha
    assert r.returncode == 0, r.stdout + r.stderr
    assert "Parado" in r.stdout and "--continuar" in r.stdout
    linhas = _resumo(pasta)
    assert len(linhas) == 78 and {linha["parte"] for linha in linhas} == {"A", "B"}
    assert "sem terminal" in (pasta / "log.txt").read_text()

    texto = (pasta / "resumo.csv").read_text().splitlines()   # uma captura que o ler_adc não terminou: refeita
    cortada = texto[5].split(",")
    cortada[-11] = "?"                                        # amostras_atrasadas (folga, atraso e o SPI vêm depois)
    texto[5] = ",".join(cortada)
    (pasta / "resumo.csv").write_text("\n".join(texto) + "\n")

    r, continuada = varredura("--continuar", entrada="\n\n")
    assert r.returncode == 0, r.stdout + r.stderr
    assert continuada == pasta                                # a mesma pasta, não uma nova
    assert "77 de 101 já feitas" in r.stdout and "[ 79/101]" in r.stdout and "[  1/101]" not in r.stdout
    linhas = _resumo(pasta)
    nomes = [linha["arquivo"] for linha in linhas]
    assert len(set(nomes)) == 101 and nomes.count(cortada[1]) == 2
    assert "CONTINUAÇÃO" in (pasta / "log.txt").read_text()
    r, _ = varredura("--continuar")
    assert "Nada a fazer" in r.stdout


def test_varrer_taxa_nao_morre_com_a_queda_da_conexao(varredura):
    """SIGHUP (o ssh caiu) no meio das capturas: elas seguem até o fim da parte."""
    env = {**varredura.env, "LER_ADC_DEMORA": "0.05"}
    proc = subprocess.Popen(["bash", str(varredura.pasta / "varrer_taxa.sh"), "--partes", "A"],
                            cwd=varredura.pasta.parent, env=env, stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    import time
    time.sleep(0.6)
    proc.send_signal(signal.SIGHUP)
    proc.communicate(timeout=120)
    assert proc.returncode == 0
    (pasta,) = varredura.pasta.glob("T7e_*")
    assert len(_resumo(pasta)) == 26


def test_varrer_taxa_parte_e_valida_o_firmware_com_capturas_longas(varredura):
    """A parte E (só quando pedida): capturas que cruzam 2^31 ciclos da PRU várias vezes, com --duracao."""
    r, pasta = varredura("--simular")
    assert "E " not in r.stdout.replace("partes", "")                    # fora do padrão (ABDC)
    r, pasta = varredura("--partes", "E")
    assert r.returncode == 0, r.stdout + r.stderr
    nomes = [linha["arquivo"] for linha in _resumo(pasta)]
    assert nomes == ["E_cs200-100-100_100000_tom_35s.bin", "E_cs6-2-6_100000_tom_35s.bin",
                     "E_cs6-2-6_250000_tom_35s.bin", "E_cs6-2-6_250000_tom_600s.bin"]
    assert (pasta / nomes[-1]).read_text().split()[-1] == "duracao=600s"


def test_varrer_taxa_validar_roda_so_a_parte_e_numa_pasta_sem_varredura_anterior(varredura):
    """As capturas antigas foram para o computador: --validar não precisa de nenhuma pasta T7e_* anterior."""
    assert not list(varredura.pasta.glob("T7e_*"))
    r, pasta = varredura("--validar")
    assert r.returncode == 0, r.stdout + r.stderr
    assert [linha["parte"] for linha in _resumo(pasta)] == ["E"] * 4
    r, _ = varredura("--partes", "EX")
    assert r.returncode == 1 and "aceita as letras" in r.stderr


def test_varrer_taxa_validar_recusa_o_firmware_sem_a_correcao(varredura):
    """Validar com o firmware antigo gastaria 12 min à toa: confere o código, a compilação e (na BeagleBone) a PRU."""
    asm = varredura.pasta / "spi_core.asm"
    fw = varredura.pasta / "fw_pru.out"
    asm.write_text("; rebase antigo: SUB r22, r22, r12\n")
    r, pasta = varredura("--validar")
    assert r.returncode == 1 and "não tem a correção" in r.stderr and pasta is None
    asm.write_text("; [CORRIGIDO em 21/10/2026] o rebase zera o contador\n")
    fw.write_bytes(b"\x00")
    os.utime(fw, (1_000_000_000, 1_000_000_000))                       # compilado antes da última mudança
    r, pasta = varredura("--validar")
    assert r.returncode == 1 and "mais antigo" in r.stderr and pasta is None
    os.utime(fw, None)                                                  # compilado agora
    r, pasta = varredura("--validar")
    assert r.returncode == 0, r.stdout + r.stderr
    assert len(_resumo(pasta)) == 4


def test_varrer_taxa_limite_varre_os_ticks_um_a_um_e_usa_o_padrao_do_firmware(varredura):
    """--limite: 303 a 333 kS/s em passos de 1 tick (5 ns) para 3,1,3 e 6,2,6, 60 s perto do limite, 10 min no padrão
    (sem --atraso-cs), 2 canais e o curto."""
    r, pasta = varredura("--limite", "--simular")
    assert "132 capturas" in r.stdout and "L: 122" in r.stdout
    r, pasta = varredura("--limite", entrada="\n\n")
    assert r.returncode == 0, r.stdout + r.stderr
    linhas = _resumo(pasta)
    por_parte = {p: [linha for linha in linhas if linha["parte"] == p] for p in "LMNQR"}
    assert [len(por_parte[p]) for p in "LMNQR"] == [122, 6, 1, 1, 2]
    taxas = [int(linha["taxa_pedida_hz"]) for linha in por_parte["L"][:61]]
    assert [200_000_000 // t for t in taxas] == list(range(660, 599, -1))   # cada taxa é exatamente 1 tick a mais
    acima = [linha for linha in por_parte["L"] if linha["esperas_cs"] == "3,1,3" and linha["amostras_atrasadas"] != "0"]
    assert acima and min(200_000_000 // int(linha["taxa_pedida_hz"]) for linha in acima) == 600
    assert max(200_000_000 // int(linha["taxa_pedida_hz"]) for linha in acima) == 608   # o quadro de 609 do falso
    longa = (pasta / "N_cspadrao_312500_tom_600s.bin").read_text().split()
    assert longa == ["taxa=312500", "canais=1", "blocos=9", "cs=", "duracao=600s"]       # sem --atraso-cs
    assert "blocos=2" in (pasta / por_parte["L"][0]["arquivo"]).read_text()
    assert por_parte["Q"][0]["canais"] == "0,1" and {linha["entrada"] for linha in por_parte["R"]} == {"curto"}


def test_varrer_taxa_grade_roda_a_campanha_t7f_no_padrao(varredura):
    """--grade (firmware de 22/10/2026): capturas longas no padrão, uma com o ARM ocupado, 2 canais e o teto com
    período constante, numa pasta T7f_; a folga e o pior atraso vão para o resumo."""
    r, pasta = varredura("--grade", "--simular")
    assert r.returncode == 0 and "T7f" in r.stdout and "56 capturas" in r.stdout
    registro = varredura.pasta.parent / "registro.txt"
    env = {**varredura.env, "LER_ADC_REGISTRO": str(registro)}
    r = subprocess.run(["bash", str(varredura.pasta / "varrer_taxa.sh"), "--grade"], cwd=varredura.pasta.parent,
                       env=env, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr
    (pasta,) = varredura.pasta.glob("T7f_*")
    linhas = _resumo(pasta)
    assert [linha["parte"] for linha in linhas[:5]] == ["G", "G", "G", "H", "K"]
    assert [linha["arquivo"] for linha in linhas[:3]] == ["G_cspadrao_312500_tom_60s.bin", "G_cspadrao_100000_tom_60s.bin",
                                                         "G_cspadrao_312500_tom_300s.bin"]
    assert (pasta / "K_cspadrao_312500_tom_2canais_60s.bin").read_text().split()[:4] == [
        "taxa=312500", "canais=0,1", "blocos=9", "cs="]
    teto = [linha for linha in linhas if linha["parte"] == "J"]
    assert [200_000_000 // int(linha["taxa_pedida_hz"]) for linha in teto] == list(range(640, 589, -1))
    assert linhas[0]["folga_ciclos"] == "31" and linhas[0]["atraso_max_ciclos"] == ""   # 640 - 609 do falso
    acima = [linha for linha in teto if linha["amostras_atrasadas"] != "0"]
    assert acima and all(linha["atraso_max_ciclos"] == "77" and linha["folga_ciclos"] == "" for linha in acima)
    assert "folga 31 ciclos" in r.stdout and "trazer 'T7f_*'" in r.stdout
    assert registro.read_text().count("dd rodando") == 1                  # a carga só na parte H, e desligada depois


def test_varrer_taxa_continuar_retoma_as_partes_da_varredura_anterior(varredura):
    """Um --continuar sozinho retoma a --grade (as partes vêm do log.txt), não a varredura padrão."""
    r, pasta = varredura("--grade", entrada="")
    assert r.returncode == 0, r.stdout + r.stderr
    (pasta,) = varredura.pasta.glob("T7f_*")
    texto = (pasta / "resumo.csv").read_text().splitlines()
    (pasta / "resumo.csv").write_text("\n".join(texto[:-3]) + "\n")       # as 3 últimas não chegaram a ser gravadas
    r = subprocess.run(["bash", str(varredura.pasta / "varrer_taxa.sh"), "--continuar"], cwd=varredura.pasta.parent,
                       env=varredura.env, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "53 de 56 já feitas" in r.stdout and "T7f" in r.stdout
    assert len(_resumo(pasta)) == 56


def test_varrer_taxa_spi_compara_os_modos_e_mede_o_teto_do_rapido(varredura):
    """--spi (T7g): o padrão e o rápido nas 3 fases a 312,5 kS/s, 60 s a 400 kS/s com 1 e 2 canais, o teto do rápido
    de 520 a 460 ticks e o curto (com uma pausa); o modo do SPI e as divergências vão para o resumo."""
    r, _ = varredura("--spi", "--simular")
    assert r.returncode == 0 and "T7g" in r.stdout and "69 capturas" in r.stdout and "SPI rapido:a" in r.stdout
    r, _ = varredura("--spi", entrada="\n")
    assert r.returncode == 0, r.stdout + r.stderr
    (pasta,) = varredura.pasta.glob("T7g_*")
    linhas = _resumo(pasta)
    assert [linha["parte"] for linha in linhas[:6]] == ["P", "P", "P", "P", "S", "S"]
    assert [linha["spi"] for linha in linhas[:4]] == ["padrao", "rapido:a", "rapido:b", "rapido:c"]
    assert linhas[0]["divergencias_a"] == "" and linhas[1]["divergencias_c"] == "7"
    assert (pasta / "P_cspadrao_312500_tom_spirapido-a.bin").read_text().split()[-1] == "spi=rapido:a"
    assert (pasta / "S_cspadrao_400000_tom_2canais_60s_spirapido.bin").exists()
    teto = [linha for linha in linhas if linha["parte"] == "T"]
    assert [200_000_000 // int(linha["taxa_pedida_hz"]) for linha in teto] == list(range(520, 459, -1))
    acima = [linha for linha in teto if linha["amostras_atrasadas"] != "0"]
    assert acima and max(200_000_000 // int(linha["taxa_pedida_hz"]) for linha in acima) == 466   # o quadro de 467 do falso
    assert [linha["spi"] for linha in linhas if linha["parte"] == "U"] == ["padrao", "rapido"]
    assert "divergências A 0, C 7" in r.stdout


def test_varrer_taxa_fase_pede_cada_quadrada_e_captura_nas_duas_taxas(varredura):
    """--fase (T3f): 7 quadradas (múltiplos ímpares de 256 Hz) e as variantes (1280 Hz em 10 Vpp; 6912 e 20736 Hz em
    16 Vpp com ±2 V), cada uma a 312,5 kS/s (SPI padrão) e a 400 kS/s (rápido), 30 s, com UMA pausa por quadrada para
    trocar o gerador; a f₁ vai na descrição."""
    r, _ = varredura("--fase", "--simular")
    assert r.returncode == 0 and "T3f" in r.stdout and "24 capturas" in r.stdout
    r, _ = varredura("--fase", entrada="\n" * 12)
    assert r.returncode == 0, r.stdout + r.stderr
    (pasta,) = varredura.pasta.glob("T3f_*")
    assert [linha["spi"] for linha in _resumo(pasta)] == ["padrao", "rapido"] * 12
    assert r.stdout.count("ONDA QUADRADA de") == 12 and "ONDA QUADRADA de 20736 Hz, 20 Vpp, High-Z, offset 0 V" in r.stdout
    assert "ONDA QUADRADA de 1280 Hz, 10 Vpp, High-Z, offset 0 V" in r.stdout
    assert "ONDA QUADRADA de 6912 Hz, 16 Vpp, High-Z, offset -2 V" in r.stdout
    assert (pasta / "F_cspadrao_400000_quadrada20736Hz16Vpp+2V_30s_spirapido.bin").exists()
    padrao = (pasta / "F_cspadrao_312500_quadrada1280Hz_30s.bin").read_text()
    rapido = (pasta / "F_cspadrao_400000_quadrada1280Hz_30s_spirapido.bin").read_text()
    meia = (pasta / "F_cspadrao_312500_quadrada1280Hz10Vpp_30s.bin").read_text()
    assert "d=quadrada f=1280Hz" in padrao and "spi=" not in padrao
    assert "spi=rapido" in rapido and "duracao=30s" in rapido and "d=quadrada f=1280Hz10Vpp" in meia
    assert "medir_fase.py" in r.stdout


def test_varrer_taxa_fase_para_na_pausa_sem_terminal(varredura):
    r, _ = varredura("--fase", entrada="")
    assert r.returncode == 0 and "sem terminal na pausa da quadrada de 256 Hz" in r.stdout
    (pasta,) = varredura.pasta.glob("T3f_*")
    assert _resumo(pasta) == []


def test_varrer_taxa_spi_recusa_o_firmware_sem_o_spi_rapido(varredura):
    (varredura.pasta / "spi_core.asm").write_text("; [CORRIGIDO em 21/10/2026]\n; GRADE EXATA\n; QUADRO DE DURAÇÃO FIXA\n")
    r = subprocess.run(["bash", str(varredura.pasta / "varrer_taxa.sh"), "--spi"], cwd=varredura.pasta.parent,
                       env=varredura.env, capture_output=True, text=True, timeout=120)
    assert r.returncode == 1 and "não tem o SPI rápido" in r.stderr
    assert not list(varredura.pasta.glob("T7g_*"))


def test_varrer_taxa_grade_recusa_o_firmware_sem_a_espera_de_precisao(varredura):
    asm = varredura.pasta / "spi_core.asm"
    asm.write_text("; [CORRIGIDO em 21/10/2026] o rebase zera o contador\n")
    r = subprocess.run(["bash", str(varredura.pasta / "varrer_taxa.sh"), "--grade"], cwd=varredura.pasta.parent,
                       env=varredura.env, capture_output=True, text=True, timeout=120)
    assert r.returncode == 1 and "não tem a grade exata" in r.stderr
    # o firmware do T7f (grade exata, mas o quadro ainda dependia do dado): medir de novo seria perder 16 min
    asm.write_text("; [CORRIGIDO em 21/10/2026] ...\n; REVISÃO DE 22/10/2026: GRADE EXATA\n")
    r = subprocess.run(["bash", str(varredura.pasta / "varrer_taxa.sh"), "--grade"], cwd=varredura.pasta.parent,
                       env=varredura.env, capture_output=True, text=True, timeout=120)
    assert r.returncode == 1 and "quadro de duração fixa" in r.stderr
    assert not list(varredura.pasta.glob("T7f_*"))



# ---------------------------------------------------------------------------
# scripts/sessao_lab.sh: o alias 'lab' (fish e bash)
# ---------------------------------------------------------------------------

@pytest.fixture
def sessao(tmp_path):
    """Um repositório de mentira com o sessao_lab.sh, o modelo do caderno e uma ferramenta da placa que só ecoa."""
    raiz = tmp_path / "repo"
    (raiz / "scripts").mkdir(parents=True)
    (raiz / "docs").mkdir()
    shutil.copy2(RAIZ / "scripts" / "sessao_lab.sh", raiz / "scripts" / "sessao_lab.sh")
    (raiz / "docs" / "lab-notes-template.md").write_text("# Anotações da bancada: AAAA-MM-DD\n")
    _executavel(raiz / "scripts" / "BeagleBone_Setup.sh", '#!/bin/bash\necho "placa: $* | DIA=$DIA"\n')
    env = {k: v for k, v in os.environ.items() if k not in ("DIA", "DADOS", "SH_ANALYZER")}
    env.update({"DADOS": str(tmp_path / "dados"), "BBB_IP": "192.0.2.1", "XDG_CONFIG_HOME": str(tmp_path / "cfg"),
                "NO_COLOR": "1"})
    script = raiz / "scripts" / "sessao_lab.sh"
    alias = f"eval \"$({script} --variaveis)\" && {script}"

    def bash(comando: str, **extra):
        return subprocess.run(["bash", "-c", f"shopt -s expand_aliases\nalias lab='{alias}'\n{comando}"],
                              env={**env, **extra}, capture_output=True, text=True, timeout=60)

    bash.raiz, bash.alias, bash.env, bash.dados = raiz, alias, env, tmp_path / "dados"
    return bash


def test_sessao_lab_define_as_variaveis_cria_o_dia_e_mostra_o_estado(sessao):
    import datetime
    hoje = datetime.date.today().isoformat()
    r = sessao('lab; echo "DIA=$DIA"; echo "SH=$SH_ANALYZER"; pwd')
    assert r.returncode == 0, r.stdout + r.stderr
    dia = sessao.dados / "lab" / hoje
    assert f"DIA={dia}" in r.stdout and f"SH={sessao.raiz}" in r.stdout and r.stdout.strip().endswith(str(sessao.raiz))
    assert (dia / "fotos").is_dir()
    assert (dia / "anotacoes.md").read_text() == f"# Anotações da bancada: {hoje}\n"   # o título com a data
    assert "(nova)" in r.stderr and "criado do modelo" in r.stderr
    assert "192.0.2.1 não responde" in r.stdout and "lab preparar" in r.stdout and "não é um repositório git" in r.stdout
    (dia / "anotacoes.md").write_text("o que já foi anotado\n")
    r = sessao("lab")                                                         # de novo: não apaga nada
    assert "já existia" in r.stderr and (dia / "anotacoes.md").read_text() == "o que já foi anotado\n"


def test_sessao_lab_passa_os_argumentos_para_a_placa_sem_expandir_curingas(sessao):
    r = sessao("lab trazer 'T7*'")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "placa: trazer T7* | DIA=" in r.stdout and "Próximo" not in r.stdout


@pytest.mark.skipif(shutil.which("fish") is None, reason="sem o fish")
def test_sessao_lab_no_fish(sessao):
    r = subprocess.run(["fish", "--no-config", "-c", f"alias lab='{sessao.alias}'; lab trazer 'T7*'; echo \"DIA=$DIA\"; pwd"],
                       env=sessao.env, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "placa: trazer T7* | DIA=" in r.stdout and f"DIA={sessao.dados}/lab/" in r.stdout
    assert r.stdout.strip().endswith(str(sessao.raiz))


def test_sessao_lab_continua_a_sessao_que_passou_da_meia_noite(sessao):
    ontem = sessao.dados / "lab" / "2026-10-21"
    (ontem / "T7f_2026-10-21_2330").mkdir(parents=True)
    captura = ontem / "T7f_2026-10-21_2330" / "G.bin"
    captura.write_bytes(b"x")
    r = sessao('lab > /dev/null; echo "DIA=$DIA"', DIA=str(ontem))          # mexida agora: a mesma sessão
    assert f"DIA={ontem}" in r.stdout and "sessão em andamento" in r.stderr
    antigo = 1_000_000_000
    for caminho in (captura, captura.parent, ontem / "anotacoes.md", ontem / "fotos", ontem):
        os.utime(caminho, (antigo, antigo))
    r = sessao('lab > /dev/null; echo "DIA=$DIA"', DIA=str(ontem))          # parada há muito: o dia de hoje
    assert f"DIA={ontem}" not in r.stdout


def test_sessao_lab_para_se_nao_consegue_criar_o_dia(sessao, tmp_path):
    bloqueio = tmp_path / "arquivo"
    bloqueio.write_text("não é pasta")
    r = sessao('lab; echo "depois: $?"', DADOS=str(bloqueio))
    assert "não consegui criar" in r.stderr and "depois: 1" in r.stdout and "Próximo" not in r.stdout
    direto = subprocess.run([str(sessao.raiz / "scripts" / "sessao_lab.sh")], env=sessao.env,
                            capture_output=True, text=True, timeout=30)
    assert direto.returncode == 1 and "rode pelo alias" in direto.stderr
