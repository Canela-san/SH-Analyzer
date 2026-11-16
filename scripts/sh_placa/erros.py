"""Os erros da conexão com a placa, num módulo leve (só a biblioteca padrão): a interface os reconhece pelo tipo (a
chave de host trocada vira um bloqueio; a senha recusada, a pergunta da senha) sem carregar o asyncssh, que custa meio
segundo e só entra quando a Aquisição conecta. ``conexao.py`` os levanta e os exporta também.
"""

from __future__ import annotations

from .agente import ErroDaPlaca
from .destino import Destino


class ErroDeConexao(ErroDaPlaca):
    """A rede: a conexão recusada, sem rota, sem resposta, ou que caiu."""


class ErroDeAutenticacao(ErroDaPlaca):
    """A placa recusou a chave do aplicativo e a senha (ou não havia senha para tentar). ``destino`` diz quem recusou
    (a placa ou o salto, que tem a senha dele), e ``senha_recusada``, se uma senha chegou a ser tentada."""

    def __init__(self, motivo: str, destino: Destino | None = None, senha_recusada: bool = False):
        super().__init__(motivo)
        self.destino, self.senha_recusada = destino, senha_recusada


class HostNaoConfirmado(ErroDaPlaca):
    """A primeira conexão com uma placa, sem o sim para a impressão digital dela: nada foi fixado."""


class ChaveDoHostTrocada(ErroDaPlaca):
    """A placa apresentou outra chave de host: a conexão foi bloqueada."""

    def __init__(self, destino: Destino, conhecida: str, apresentada: str | None):
        self.destino, self.conhecida, self.apresentada = destino, conhecida, apresentada
        super().__init__(
            f"A placa em {destino.conta} apresentou uma chave de host diferente da conhecida (a conhecida é "
            f"{conhecida}; a de agora, {apresentada or 'não deu para ler'}). A conexão foi bloqueada antes de qualquer "
            "senha ou chave sair daqui. Se a placa foi regravada (a imagem reinstalada, outro cartão), a chave nova é "
            "esperada: confira a impressão digital na própria placa (ssh-keygen -lf "
            "/etc/ssh/ssh_host_ed25519_key.pub, pelo console), esqueça a chave antiga e conecte de novo. Se não foi, "
            "alguém pode estar no meio da conexão.")
