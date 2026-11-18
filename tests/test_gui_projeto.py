"""O arquivo de projeto ``.shproj`` (``sh_analyzer_gui.dados.projeto``, F1.3), sem Qt: a ida e a volta, as recusas
com a mensagem, a gravação atômica, o salvamento automático e a busca de uma captura movida pelo CRC."""

import json
import os
import time

import pytest
from sh_analyzer_gui.dados import projeto as arq
from sh_analyzer_gui.dados.cadeia import Cadeia, CorrecaoSonda, Filtro, RemoverDC
from sh_analyzer_gui.dados.captura import ParametrosSemCabecalho
from sh_analyzer_gui.dados.projeto import (
    FonteSalva,
    ModeloDeCaptura,
    ProjetoInvalido,
    ProjetoSalvo,
    TracoSalvo,
    VistaSalva,
    caminho_relativo,
    localizar_fonte,
)
from sh_analyzer_gui.dados.receita import ReceitaDoTraco
from sh_placa.pedido import Canal, PedidoDeCaptura

CADEIA = Cadeia((CorrecaoSonda(), Filtro("passa_altas", (2000.0,), 4), RemoverDC(ligada=False)))


def exemplo() -> ProjetoSalvo:
    fontes = (FonteSalva("f1", "dados/a.bin", "/lab/dados/a.bin", 1024, 0xDEADBEEF),
              FonteSalva("f2", "b.bin", "/lab/b.bin", 2048, None, "int16", ParametrosSemCabecalho(4e5, (3, 1))))
    r1 = ReceitaDoTraco("f1", 0, "V_A · 09h30", 0, ganho=-1.5, offset=0.25, deslocamento_s=0.004, cadeia=CADEIA)
    r2 = ReceitaDoTraco("f2", 3, "I_A", 1, visivel=False, faixa=1)
    vistas = (VistaSalva("v1", "Afundamento", "tempo", (TracoSalvo("t1", r1), TracoSalvo("t2", r2)),
                         {"sobrepor": True}),
              VistaSalva("v2", "Vazia", "tempo", opcoes={"sobrepor": False}))
    modelos = (ModeloDeCaptura("Rede V + I", PedidoDeCaptura((Canal(0, "corrente", "sct013_100a_sn001", 5.12, 19.65),
                                                              Canal(1, ganho=19.357)), duracao_s=3600.0,
                                                             titulo="Rede de casa")),
               ModeloDeCaptura("Calibração da tensão", PedidoDeCaptura(blocos=4, destino="cartao")))
    return ProjetoSalvo(fontes, vistas, {"janela": "AAEC"}, "0.8.0", modelos)


def test_ida_e_volta_pelo_json():
    p = exemplo()
    dados = json.loads(json.dumps(arq.para_dict(p)))
    assert dados["formato"] == arq.FORMATO and dados["versao"] == arq.VERSAO == 4
    assert arq.de_dict(dados) == p
    assert [m["nome"] for m in dados["modelos_de_captura"]] == ["Rede V + I", "Calibração da tensão"]
    assert dados["modelos_de_captura"][0]["pedido"]["canais"][0]["sonda"] == "sct013_100a_sn001"
    assert "sem_cabecalho" not in dados["fontes"][0]                     # só nas sem o cabeçalho
    assert dados["fontes"][1]["sem_cabecalho"] == {"taxa_total_hz": 400_000.0, "canais": [3, 1]}
    t1, t2 = dados["vistas"][0]["tracos"]
    assert t1["etapas"] == [{"tipo": "correcao_sonda", "ligada": True, "perfil": None},
                            {"tipo": "filtro", "ligada": True, "filtro": "passa_altas", "cortes": [2000.0], "ordem": 4},
                            {"tipo": "remover_dc", "ligada": False}]
    assert t2["etapas"] == [] and "cadeia" not in t1


def test_o_projeto_da_versao_1_abre_sem_nenhuma_etapa():
    """O formato 1 (a Fase 1) não tinha a cadeia: cada traço abre com a cadeia vazia. E nele, ``etapas`` é um campo
    desconhecido (um arquivo 1 com etapas foi mexido à mão ou é de outra coisa)."""
    dados = arq.para_dict(exemplo())
    dados["versao"] = 1
    for vista in dados["vistas"]:
        for traco in vista["tracos"]:
            traco.pop("etapas")
    aberto = arq.de_dict(json.loads(json.dumps(dados)))
    assert all(t.receita.cadeia == Cadeia() for v in aberto.vistas for t in v.tracos)
    assert aberto.vistas[0].tracos[0].receita.nome == "V_A · 09h30"
    dados["vistas"][0]["tracos"][0]["etapas"] = []
    with pytest.raises(ProjetoInvalido, match="desconhecidos: etapas"):
        arq.de_dict(dados)


def test_o_projeto_da_versao_3_abre_sem_modelos_de_captura():
    dados = arq.para_dict(exemplo())
    dados["versao"] = 3
    dados.pop("modelos_de_captura")
    assert arq.de_dict(json.loads(json.dumps(dados))).modelos_de_captura == ()


def test_um_modelo_com_um_valor_fora_das_regras_abre_e_o_formulario_o_mostra():
    dados = arq.para_dict(exemplo())
    dados["modelos_de_captura"][1]["pedido"]["taxa_hz"] = 900_000
    assert arq.de_dict(dados).modelos_de_captura[1].pedido.taxa_hz == 900_000


def test_a_vista_de_tempo_de_antes_das_opcoes_abre_com_as_padrao():
    """Até a F2.10 a vista de tempo não tinha opções (``{}``, ou nem o campo): abre com as padrão, sem sobrepor."""
    dados = arq.para_dict(exemplo())
    dados["vistas"][0]["opcoes"] = {}
    dados["vistas"][1].pop("opcoes")
    aberto = arq.de_dict(json.loads(json.dumps(dados)))
    assert [v.opcoes for v in aberto.vistas] == [{"sobrepor": False}, {"sobrepor": False}]


def test_salvar_e_abrir_o_arquivo(tmp_path):
    caminho = tmp_path / "rede.shproj"
    arq.salvar_automatico(exemplo(), caminho)
    assert arq.automatico(caminho).is_file()
    arq.salvar(exemplo(), caminho)
    assert arq.abrir(caminho) == exemplo()
    assert not arq.automatico(caminho).exists()                  # salvar apaga o automático, que ficou velho
    assert sorted(p.name for p in tmp_path.iterdir()) == ["rede.shproj"]   # nenhum temporário sobrando
    assert "V_A · 09h30" in caminho.read_text(encoding="utf-8")   # legível, sem escapar os acentos


@pytest.mark.parametrize("mexer, trecho", [
    (lambda d: d.update(formato="outro"), "não é um projeto"),
    (lambda d: d.update(versao=arq.VERSAO + 1), "versão mais nova"),
    (lambda d: d.update(versao="1"), "versao"),
    (lambda d: d.pop("fontes"), "fontes"),
    (lambda d: d["fontes"][0].pop("tamanho"), "tamanho"),
    (lambda d: d["fontes"][0].update(crc32_amostras="abc"), "CRC"),
    (lambda d: d["fontes"][1].update(id="f1"), "mesmo id"),
    (lambda d: d["vistas"][0]["tracos"][0].update(ganho=0), "ganho"),
    (lambda d: d["vistas"][0]["tracos"][0].update(fonte="f9"), "fonte que não está"),
    (lambda d: d["vistas"][0]["tracos"][0].update(brilho=3), "desconhecidos: brilho"),
    (lambda d: d["vistas"][0]["tracos"][0].pop("nome"), "incompleto"),
    (lambda d: d["vistas"][0]["tracos"][0].update(etapas={"tipo": "remover_dc"}), "etapas são uma lista"),
    (lambda d: d["vistas"][0]["tracos"][0]["etapas"].append({"tipo": "derivada"}), "etapa desconhecida"),
    (lambda d: d["vistas"][0]["tracos"][0]["etapas"][1].update(ordem=40), "ordem do filtro"),
    (lambda d: d["vistas"][0].update(tipo="xy"), "tipo que esta versão não abre"),
    (lambda d: d["vistas"][0].update(nome=" "), "sem nome"),
    (lambda d: d["vistas"][0]["opcoes"].update(sobrepor="sim"), "sobrepor"),
    (lambda d: d["fontes"][1]["sem_cabecalho"].pop("canais"), "a taxa e os canais de a fonte 2 estão incompletos"),
    (lambda d: d["fontes"][1]["sem_cabecalho"].update(canais=["3"]), "incompletos"),
    (lambda d: d["fontes"][1]["sem_cabecalho"].update(taxa_total_hz=-1), "taxa total"),
    (lambda d: d["fontes"][1]["sem_cabecalho"].update(canais=[3, 3]), "repetido"),
    (lambda d: d["vistas"][0]["opcoes"].update(cor=1), "desconhecidas: cor"),
    (lambda d: d.update(modelos_de_captura={}), "não são uma lista"),
    (lambda d: d["modelos_de_captura"][1].update(nome="Rede V + I"), "dois modelos de captura com o nome"),
    (lambda d: d["modelos_de_captura"][0].update(nome="  "), "sem nome"),
    (lambda d: d["modelos_de_captura"][0].pop("pedido"), "pedido"),
    (lambda d: d["modelos_de_captura"][0]["pedido"].update(taxa_hz="400k"), "'Rede V \\+ I': o campo 'taxa_hz'"),
])
def test_um_projeto_invalido_e_recusado_com_a_mensagem(mexer, trecho):
    dados = arq.para_dict(exemplo())
    mexer(dados)
    with pytest.raises(ProjetoInvalido, match=trecho):
        arq.de_dict(dados)


def test_arquivos_que_nao_sao_projeto(tmp_path):
    estragado = tmp_path / "estragado.shproj"
    estragado.write_text('{"formato": "sh-analyzer-projeto", ', encoding="utf-8")
    with pytest.raises(ProjetoInvalido, match="JSON inválido na linha 1"):
        arq.abrir(estragado)
    binario = tmp_path / "captura.bin"
    binario.write_bytes(bytes(range(256)) * 4)
    with pytest.raises(ProjetoInvalido, match="não é"):
        arq.abrir(binario)


def test_um_layout_invalido_e_ignorado():
    dados = arq.para_dict(exemplo())
    dados["layout"] = {"janela": 3}
    assert arq.de_dict(dados).layout == {}


def test_recuperacao_pendente(tmp_path):
    caminho = tmp_path / "p.shproj"
    assert arq.recuperacao_pendente(caminho) is None
    arq.salvar(exemplo(), caminho)
    auto = arq.salvar_automatico(exemplo(), caminho)
    agora = time.time()
    os.utime(caminho, (agora - 10, agora - 10))
    assert arq.recuperacao_pendente(caminho) == auto              # o automático é mais novo: houve uma queda
    os.utime(auto, (agora - 20, agora - 20))
    assert arq.recuperacao_pendente(caminho) is None              # o principal foi salvo depois
    caminho.unlink()
    assert arq.recuperacao_pendente(caminho) == auto              # sem o principal, só resta o automático


def test_caminho_relativo(tmp_path):
    (tmp_path / "dados").mkdir()
    assert caminho_relativo(tmp_path / "dados" / "a.bin", tmp_path / "projetos") == "../dados/a.bin"
    assert caminho_relativo(tmp_path / "a.bin", tmp_path) == "a.bin"


def _fonte(caminho, pasta, conteudo, crc):
    return FonteSalva("f1", caminho_relativo(caminho, pasta), caminho.resolve().as_posix(), len(conteudo), crc)


def test_localizar_pelo_caminho_relativo_e_pelo_absoluto(tmp_path):
    conteudo = b"amostras" * 100
    dados = tmp_path / "lab" / "a.bin"
    dados.parent.mkdir()
    dados.write_bytes(conteudo)
    fonte = _fonte(dados, tmp_path / "lab", conteudo, 7)
    crc = {dados: 7}.get
    assert localizar_fonte(fonte, tmp_path / "lab", crc) == tmp_path / "lab" / "a.bin"
    # O projeto mudou de pasta, os dados não: vale o absoluto.
    assert localizar_fonte(fonte, tmp_path / "outro", crc) == dados


def test_localizar_pelo_crc_quando_a_captura_mudou_de_lugar(tmp_path):
    conteudo = b"amostras" * 100
    antigo = tmp_path / "antigo" / "a.bin"
    fonte = FonteSalva("f1", "../antigo/a.bin", antigo.as_posix(), len(conteudo), 7)
    projeto = tmp_path / "projeto"
    (projeto / "dados" / "sub").mkdir(parents=True)
    impostor = projeto / "dados" / "a.bin"                         # mesmo nome e tamanho, outro CRC
    impostor.write_bytes(conteudo)
    movido = projeto / "dados" / "sub" / "renomeado.bin"
    movido.write_bytes(conteudo)
    (projeto / "dados" / "outro.bin").write_bytes(b"x" * 10)
    crcs = {impostor: 9, movido: 7}
    lidos = []

    def crc_de(p):
        lidos.append(p.name)
        if p not in crcs:
            raise ValueError("sem cabeçalho")
        return crcs[p]

    assert localizar_fonte(fonte, projeto, crc_de) == movido
    assert "outro.bin" not in lidos                                 # o tamanho filtra antes de ler o cabeçalho
    sem_crc = FonteSalva("f1", "../antigo/a.bin", antigo.as_posix(), len(conteudo), None)
    assert localizar_fonte(sem_crc, projeto, crc_de) is None        # sem CRC, o tamanho sozinho não basta
    assert localizar_fonte(fonte, tmp_path / "vazio", crc_de) is None
