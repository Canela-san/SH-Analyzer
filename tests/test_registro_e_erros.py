"""Logging (formato histórico stdout/stderr) e hierarquia de erros."""

import logging

import pytest
from supraharmonicos.erros import ErroSHAN, ErroUso
from supraharmonicos.registro import configurar_logging_cli

log = logging.getLogger("supraharmonicos.teste")


def test_info_vai_para_stdout_sem_prefixo_e_warning_para_stderr_com_aviso(capsys):
    configurar_logging_cli()
    log.info("progresso normal")
    log.warning("algo suspeito")
    log.error("falha")
    cap = capsys.readouterr()
    assert cap.out == "progresso normal\n"
    assert cap.err == "Aviso: algo suspeito\nErro: falha\n"


def test_configurar_duas_vezes_nao_duplica_mensagens(capsys):
    configurar_logging_cli()
    configurar_logging_cli()
    log.info("uma vez só")
    assert capsys.readouterr().out == "uma vez só\n"


def test_destino_e_resolvido_na_emissao_nao_na_configuracao(capsys):
    """Funciona com redirecionamentos feitos DEPOIS de configurar (capsys, redirect_stdout)."""
    import contextlib
    import io

    configurar_logging_cli()
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        log.info("capturado")
    assert buf.getvalue() == "capturado\n"
    assert capsys.readouterr().out == ""


def test_sem_configuracao_biblioteca_nao_imprime_nada(capsys):
    log.info("silêncio")
    log.warning("silêncio")
    cap = capsys.readouterr()
    assert cap.out == "" and cap.err == ""


def test_erro_uso_e_um_erro_shan():
    assert issubclass(ErroUso, ErroSHAN)
    with pytest.raises(ErroSHAN, match="mensagem sem prefixo"):
        raise ErroUso("mensagem sem prefixo")
