"""A conexão SSH com a placa (F3.2; ``sh_placa/conexao.py``, ``chaves.py``, ``registro.py`` e o ``TransporteSSH``),
contra o servidor SSH do próprio teste (``tests/servidor_ssh.py``), com o agente de verdade sobre a placa simulada:
a primeira conexão com a senha e depois com a chave instalada, a chave de host confirmada e fixada, a trocada que
bloqueia, a senha fora do registro e do log, cada comando no registro, a queda e o tempo esgotado como erros claros,
e o salto. Sem placa e sem o cofre de verdade do sistema."""

import asyncio
import logging

import pytest

asyncssh = pytest.importorskip("asyncssh")
pytest.importorskip("keyring")

import keyring  # noqa: E402
import keyring.backend  # noqa: E402
import keyring.backends.fail  # noqa: E402
import keyring.errors  # noqa: E402
from servidor_ssh import SENHA_PADRAO, ServidorSSH  # noqa: E402
from sh_placa.agente import ClienteDoAgente, ErroDaPlaca, TransporteSSH  # noqa: E402
from sh_placa.chaves import ChaveDoAplicativo, CofreDeSenhas, HostsConhecidos  # noqa: E402
from sh_placa.conexao import (  # noqa: E402
    ChaveDoHostTrocada,
    ConexaoSSH,
    Destino,
    ErroDeAutenticacao,
    ErroDeConexao,
    HostNaoConfirmado,
)
from sh_placa.registro import RegistroDeAtividade  # noqa: E402
from sh_placa.simulador import VERSAO_SIMULADA  # noqa: E402


class Aplicativo:
    """O que o aplicativo guarda entre as conexões: a chave dele, as chaves de host e o registro; e o diálogo da
    primeira conexão, que diz sim e anota o que perguntou."""

    def __init__(self, pasta):
        self.chave = ChaveDoAplicativo(pasta / "chaves")
        self.hosts = HostsConhecidos(pasta / "chaves" / "known_hosts")
        self.registro = RegistroDeAtividade()
        self.perguntas: list[tuple[str, str]] = []

    async def confirmar(self, destino, impressao):
        self.perguntas.append((destino.conta, impressao))
        return True

    def conexao(self, placa: ServidorSSH, **opcoes) -> ConexaoSSH:
        opcoes.setdefault("confirmar_host", self.confirmar)
        return ConexaoSSH(Destino("127.0.0.1", placa.porta), chave=self.chave, hosts=self.hosts,
                          registro=self.registro, **opcoes)


@pytest.fixture
def app(tmp_path):
    return Aplicativo(tmp_path / "aplicativo")


def rodar(corrotina):
    return asyncio.run(corrotina)


def test_a_primeira_conexao_com_a_senha_e_depois_so_com_a_chave(app, tmp_path):
    async def cenario():
        async with ServidorSSH(tmp_path / "placa") as placa:
            async with app.conexao(placa, senha=SENHA_PADRAO) as c:
                assert c.autenticada_com == "senha"
                assert app.perguntas == [(f"debian@127.0.0.1:{placa.porta}", placa.impressao)]
                assert await c.instalar_chave() is True
                assert await c.instalar_chave() is False                  # já estava: uma linha só
            assert placa.authorized_keys.read_text().splitlines() == [app.chave.linha_publica]
            async with app.conexao(placa) as c:                            # sem senha, e sem perguntar de novo
                assert c.autenticada_com == "chave"
                estado = await ClienteDoAgente(TransporteSSH(c)).saude()
            assert len(app.perguntas) == 1
            assert placa.autenticacoes.count(("senha", True)) == 1
            return estado

    estado = rodar(cenario())
    assert estado.versao_do_firmware == VERSAO_SIMULADA                   # o agente, pelo stdin, leu a placa simulada
    assert [p.codigo for p in estado.diagnostico(VERSAO_SIMULADA) if p.nivel != "info"] == []
    assert app.chave.caminho.stat().st_mode & 0o777 == 0o600              # a chave privada, só do dono
    assert app.chave.pasta.stat().st_mode & 0o777 == 0o700


def test_a_impressao_conferida_e_a_da_chave_ed25519(app, tmp_path):
    """Com as chaves RSA e ED25519 (a placa tem as duas), a fixada é a ED25519, a que o ``ssh`` do usuário e o
    ``ssh-keygen`` da placa mostram: o asyncssh, sozinho, negociava a RSA, e a impressão que o usuário conferia não
    era nenhuma das que ele conhecia (visto na placa de verdade, 15/11/2026)."""
    async def cenario():
        async with ServidorSSH(tmp_path / "placa", tambem_rsa=True) as placa:
            async with app.conexao(placa, senha=SENHA_PADRAO):
                pass
            async with app.conexao(placa, senha=SENHA_PADRAO):            # e a fixada é a que vale depois
                pass
            return placa

    placa = rodar(cenario())
    assert [impressao for _conta, impressao in app.perguntas] == [placa.impressao]
    assert app.hosts.chave_de("127.0.0.1", placa.porta).algorithm == b"ssh-ed25519"


def test_a_chave_entra_numa_linha_propria(app, tmp_path):
    """Um ``authorized_keys`` que não termina numa linha nova (editado à mão) não emenda a chave na de outro."""
    outra = asyncssh.generate_private_key("ssh-ed25519", comment="alguem@outro").export_public_key("openssh")
    outra = outra.decode("ascii").strip()

    async def cenario():
        async with ServidorSSH(tmp_path / "placa") as placa:
            placa.authorized_keys.parent.mkdir(mode=0o700)
            placa.authorized_keys.write_text(outra)                       # sem a linha nova no fim
            async with app.conexao(placa, senha=SENHA_PADRAO) as c:
                await c.instalar_chave()
            return placa.authorized_keys.read_text().splitlines()

    assert rodar(cenario()) == [outra, app.chave.linha_publica]


def test_sem_o_sim_para_a_impressao_nada_e_fixado_nem_enviado(app, tmp_path):
    async def nao(destino, impressao):
        return False

    async def cenario():
        async with ServidorSSH(tmp_path / "placa") as placa:
            with pytest.raises(HostNaoConfirmado, match="não foi confirmada"):
                await app.conexao(placa, senha=SENHA_PADRAO, confirmar_host=nao).conectar()
            return placa

    placa = rodar(cenario())
    assert app.hosts.chave_de("127.0.0.1", placa.porta) is None
    assert placa.autenticacoes == []                                      # nem a chave nem a senha saíram daqui


def test_a_chave_de_host_trocada_bloqueia_antes_de_autenticar(app, tmp_path):
    async def cenario():
        async with ServidorSSH(tmp_path / "placa") as placa:
            async with app.conexao(placa, senha=SENHA_PADRAO):
                pass
            antiga = placa.impressao
            await placa.trocar_chave_do_host()                            # a placa regravada (ou alguém no meio)
            placa.autenticacoes.clear()
            with pytest.raises(ChaveDoHostTrocada) as erro:
                await app.conexao(placa, senha=SENHA_PADRAO).conectar()
            assert (erro.value.conhecida, erro.value.apresentada) == (antiga, placa.impressao)
            assert antiga in str(erro.value) and placa.impressao in str(erro.value) and "bloqueada" in str(erro.value)
            assert placa.autenticacoes == []                              # nada saiu daqui
            assert app.hosts.chave_de("127.0.0.1", placa.porta).get_fingerprint() == antiga   # continua a antiga
            assert len(app.perguntas) == 1                                 # e ninguém perguntou de novo

            assert app.hosts.esquecer("127.0.0.1", placa.porta)            # o usuário esquece a antiga
            async with app.conexao(placa, senha=SENHA_PADRAO):
                pass
            assert app.perguntas[-1] == (f"debian@127.0.0.1:{placa.porta}", placa.impressao)

    rodar(cenario())


def test_a_senha_errada_e_a_falta_dela(app, tmp_path):
    async def cenario():
        async with ServidorSSH(tmp_path / "placa") as placa:
            with pytest.raises(ErroDeAutenticacao, match="recusou a senha"):
                await app.conexao(placa, senha="errada").conectar()
            assert placa.autenticacoes.count(("senha", False)) == 1         # uma tentativa só
            with pytest.raises(ErroDeAutenticacao, match="não há senha para tentar"):
                await app.conexao(placa).conectar()

    rodar(cenario())


def test_cada_comando_vai_para_o_registro_e_a_senha_para_lugar_nenhum(app, tmp_path, caplog):
    caplog.set_level(logging.DEBUG)

    async def cenario():
        async with ServidorSSH(tmp_path / "placa") as placa:
            async with app.conexao(placa, senha=SENHA_PADRAO) as c:
                assert (await ClienteDoAgente(TransporteSSH(c)).versao())["firmware"] == VERSAO_SIMULADA
                r = await c.executar("echo saída; echo erro >&2; exit 3", descricao="falha de propósito")
                assert (r.codigo, r.saida, r.erro) == (3, "saída\n", "erro\n")
                await c.instalar_chave()
            return placa

    placa = rodar(cenario())
    comandos = [e for e in app.registro.entradas if e.tipo == "comando"]
    assert [e.descricao.split(" (")[0] for e in comandos] == ["agente: versao", "falha de propósito",
                                                             "instalar a chave do aplicativo"]
    assert [e.codigo for e in comandos] == [0, 3, 0]
    assert all(e.duracao_s > 0 and e.inicio > 0 and e.destino == f"debian@127.0.0.1:{placa.porta}" for e in comandos)
    assert [e.comando for e in comandos] == placa.comandos                # o registro mostra exatamente o que rodou
    assert comandos[0].comando == 'SHAN_PASTA="$HOME"/firmware python3 - versao'
    fatos = [e.descricao for e in app.registro.entradas if e.tipo == "conexao"]
    assert fatos[0].startswith("a chave do host confirmada e fixada: SHA256:")
    assert fatos[1:] == ["conectado, com a senha", "desconectado"]
    arquivos = [p.read_bytes().decode("utf-8", "replace") for p in app.chave.pasta.iterdir()]
    for texto in (app.registro.em_texto(), caplog.text, *placa.comandos, *arquivos):
        assert SENHA_PADRAO not in texto


def test_a_queda_no_meio_de_um_comando_e_um_erro_claro(app, tmp_path):
    quedas = []

    async def cenario():
        async with ServidorSSH(tmp_path / "placa") as placa:
            c = app.conexao(placa, senha=SENHA_PADRAO, ao_cair=quedas.append)
            await c.conectar()
            comando = asyncio.create_task(c.executar("sleep 30", descricao="uma captura longa"))
            await asyncio.sleep(0.3)
            placa.derrubar()                                              # o cabo USB que solta
            with pytest.raises(ErroDeConexao, match="caiu durante uma captura longa"):
                await comando
            assert not c.conectada
            with pytest.raises(ErroDeConexao, match="conecte antes"):
                await c.executar("true")
            await c.conectar()                                            # e conecta de novo
            assert (await c.executar("echo de volta")).saida == "de volta\n"
            await c.fechar()

    rodar(cenario())
    assert len(quedas) == 1 and "caiu" in quedas[0]
    (longa,) = [e for e in app.registro.entradas if e.descricao == "uma captura longa"]
    assert longa.codigo is None and longa.falha == "a conexão caiu"


def test_o_tempo_esgotado_nao_derruba_a_conexao(app, tmp_path):
    async def cenario():
        async with ServidorSSH(tmp_path / "placa") as placa:
            async with app.conexao(placa, senha=SENHA_PADRAO) as c:
                with pytest.raises(ErroDeConexao, match="não respondeu em 0.3 s"):
                    await c.executar("sleep 30", tempo_limite=0.3, descricao="o agente travado")
                assert c.conectada and (await c.executar("echo ainda aqui")).saida == "ainda aqui\n"

    rodar(cenario())
    (travado,) = [e for e in app.registro.entradas if e.descricao == "o agente travado"]
    assert travado.codigo is None and travado.falha == "sem resposta em 0.3 s"


def test_sem_placa_no_endereco(app, tmp_path):
    async def cenario():
        async with ServidorSSH(tmp_path / "placa") as placa:
            porta = placa.porta
        conexao = ConexaoSSH(Destino("127.0.0.1", porta), chave=app.chave, hosts=app.hosts, registro=app.registro,
                             confirmar_host=app.confirmar)
        with pytest.raises(ErroDeConexao, match="recusou a conexão"):
            await conexao.conectar()

    rodar(cenario())


def test_pelo_salto(app, tmp_path):
    """O ProxyJump: a conexão com a placa por dentro da do salto, cada uma com a chave de host dela."""
    async def cenario():
        async with ServidorSSH(tmp_path / "salto", permitir_tunel=True) as salto, \
                ServidorSSH(tmp_path / "placa") as placa:
            destino = Destino("127.0.0.1", placa.porta, salto=Destino("127.0.0.1", salto.porta))
            conexao = ConexaoSSH(destino, chave=app.chave, hosts=app.hosts, registro=app.registro,
                                 senha=SENHA_PADRAO, senha_do_salto=SENHA_PADRAO, confirmar_host=app.confirmar)
            async with conexao as c:
                assert (await c.executar("echo $HOME")).saida.strip() == str(placa.home)
            assert placa.comandos == ["echo $HOME"] and salto.comandos == []
            return salto, placa

    salto, placa = rodar(cenario())
    assert app.perguntas == [(f"debian@127.0.0.1:{salto.porta}", salto.impressao),
                             (f"debian@127.0.0.1:{placa.porta}", placa.impressao)]


def test_a_chave_do_aplicativo_e_os_hosts_conhecidos(tmp_path):
    chave = ChaveDoAplicativo(tmp_path / "chaves")
    primeira = chave.impressao
    assert ChaveDoAplicativo(tmp_path / "chaves").impressao == primeira          # gerada uma vez, lida depois
    assert chave.linha_publica.startswith("ssh-ed25519 ") and "sh-analyzer@" in chave.linha_publica
    hosts = HostsConhecidos(tmp_path / "chaves" / "known_hosts")
    host_a, host_b = (asyncssh.generate_private_key("ssh-ed25519") for _ in range(2))
    hosts.fixar("192.168.6.2", 22, host_a)
    hosts.fixar("192.168.6.2", 2222, host_b)
    linhas = hosts.arquivo.read_text().splitlines()
    assert [linha.split()[0] for linha in linhas] == ["192.168.6.2", "[192.168.6.2]:2222"]   # o formato do OpenSSH
    assert hosts.chave_de("192.168.6.2").get_fingerprint() == host_a.get_fingerprint()
    assert hosts.chave_de("192.168.6.2", 2222).get_fingerprint() == host_b.get_fingerprint()
    assert hosts.chave_de("192.168.7.2") is None
    assert hosts.esquecer("192.168.6.2") and not hosts.esquecer("192.168.6.2")
    assert hosts.chave_de("192.168.6.2") is None and hosts.chave_de("192.168.6.2", 2222) is not None


def test_o_comando_do_agente_pelo_stdin():
    class Nada:
        async def executar(self, *a, **k):
            raise AssertionError

    assert TransporteSSH(Nada()).comando(["estado"]) == 'SHAN_PASTA="$HOME"/firmware python3 - estado'
    assert TransporteSSH(Nada(), "~/meu firmware").comando(["x y"]) == \
        "SHAN_PASTA=\"$HOME\"/'meu firmware' python3 - 'x y'"
    assert TransporteSSH(Nada(), "/opt/fw").comando(["versao"]) == "SHAN_PASTA=/opt/fw python3 - versao"


class CofreNaMemoria(keyring.backend.KeyringBackend):
    priority = 1

    def __init__(self):
        super().__init__()
        self.senhas = {}

    def get_password(self, servico, conta):
        return self.senhas.get((servico, conta))

    def set_password(self, servico, conta, senha):
        self.senhas[(servico, conta)] = senha

    def delete_password(self, servico, conta):
        if (servico, conta) not in self.senhas:
            raise keyring.errors.PasswordDeleteError("não havia")
        del self.senhas[(servico, conta)]


@pytest.fixture
def cofre_do_sistema():
    """Troca o cofre do sistema (o Secret Service de verdade, no Linux) por outro, e o devolve no fim."""
    anterior = keyring.get_keyring()

    def trocar(backend):
        keyring.set_keyring(backend)
        return backend
    yield trocar
    keyring.set_keyring(anterior)


def test_o_cofre_de_senhas(cofre_do_sistema):
    memoria = cofre_do_sistema(CofreNaMemoria())
    cofre = CofreDeSenhas()
    assert cofre.senha("debian@192.168.6.2") is None
    cofre.guardar("debian@192.168.6.2", "segredo")
    assert cofre.senha("debian@192.168.6.2") == "segredo"
    assert memoria.senhas == {(CofreDeSenhas.SERVICO, "debian@192.168.6.2"): "segredo"}
    cofre.esquecer("debian@192.168.6.2")
    cofre.esquecer("debian@192.168.6.2")                                   # já esquecida: nada
    assert cofre.senha("debian@192.168.6.2") is None


def test_sem_cofre_no_sistema(cofre_do_sistema):
    cofre_do_sistema(keyring.backends.fail.Keyring())
    cofre = CofreDeSenhas()
    assert cofre.senha("debian@192.168.6.2") is None
    with pytest.raises(ErroDaPlaca, match="não guardou a senha") as erro:
        cofre.guardar("debian@192.168.6.2", "segredo")
    assert "segredo" not in str(erro.value)
