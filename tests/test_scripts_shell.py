"""Testes de ``scripts/BeagleBone_Setup.sh``, a interface entre o computador e a BeagleBone.

Rodam o script de verdade (bash), com programas FALSOS no PATH onde o real não pode ser usado (``ssh``, ``sudo``,
``date -s`` e ``sshfs``): o ssh falso roda o comando "remoto" aqui mesmo, num home falso. Marcados ``e2e``.
(O ``compactar_amostras`` virou Python: ``tests/test_compactacao.py``.)
"""

import glob
import os
import shutil
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
