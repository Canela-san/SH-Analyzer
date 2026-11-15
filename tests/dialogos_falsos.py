"""Respostas prontas para os diálogos da interface (``controle_do_projeto.Dialogos``): um teste diz o que o usuário
responderia, e o teste falha se aparecer uma pergunta que ele não previu."""

from pathlib import Path


class DialogosFalsos:
    """``respostas``: uma fila de respostas, na ordem em que as perguntas aparecem (a chave da opção, um caminho
    ou ``None`` para cancelar). ``perguntas`` guarda os títulos, na ordem."""

    def __init__(self, *respostas):
        self.respostas = list(respostas)
        self.perguntas: list[str] = []
        self.pedidos: list = []                      # (pedido, sugestão) de cada captura sem o cabeçalho

    def _proxima(self, titulo: str):
        self.perguntas.append(titulo)
        if not self.respostas:
            raise AssertionError(f"pergunta não prevista no teste: {titulo!r}")
        return self.respostas.pop(0)

    def abrir_arquivos(self, titulo, filtro, pasta=""):
        r = self._proxima(titulo)
        return [Path(c) for c in r] if r is not None else []

    def abrir_arquivo(self, titulo, filtro, pasta=""):
        r = self._proxima(titulo)
        return Path(r) if r is not None else None

    def salvar_arquivo(self, titulo, filtro, sugestao=""):
        r = self._proxima(titulo)
        return Path(r) if r is not None else None

    def escolher_pasta(self, titulo, pasta=""):
        r = self._proxima(titulo)
        return Path(r) if r is not None else None

    def parametros_da_captura(self, caminho, pedido, sugestao):
        """A resposta é um ``ParametrosSemCabecalho`` (ou ``None`` para cancelar)."""
        self.pedidos.append((pedido, sugestao))
        return self._proxima(f"a taxa e os canais de {Path(caminho).name}")

    def perguntar(self, titulo, texto, opcoes, padrao):
        r = self._proxima(titulo)
        assert r is None or r in opcoes, f"{r!r} não é uma das opções de {titulo!r}: {list(opcoes)}"
        return r
