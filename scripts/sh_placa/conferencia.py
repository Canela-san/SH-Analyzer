"""O "Conferir antes" da captura (docs/gui-plan.md, 11.5; a F4.3): a bancada está pronta para a captura pedida?

Uma captura curta com o pedido do formulário (um bloco, pela saída contínua da F4.2, num arquivo temporário deste
computador), medida no motor com as regras do ``coletar.sh conferir`` (``supraharmonicos.conferencia``): a
integridade, o ADC respondendo, e em cada canal o nível, a frequência, a saturação e a faixa sugerida. Com o pedido
do formulário, a conferência mede exatamente a captura que vai ser feita (as faixas de cada canal, o SPI, as esperas
de CS), o que a rotina do ``coletar.sh`` não faz (uma faixa para todos os canais, só o SPI rápido ou o lento). O
arquivo some depois da medida.

A senha do sudo é a da captura (``captura.py``): a primeira linha do stdin, validada na placa e nunca escrita.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from supraharmonicos.conferencia import Conferencia, conferir_captura

from .agente import PASTA_DO_FIRMWARE
from .captura import CapturaContinua, CapturaRecebida, Progresso, caminho_parcial
from .pedido import AMOSTRAS_POR_BLOCO, PedidoDeCaptura

if TYPE_CHECKING:
    from .conexao import ConexaoSSH

TITULO = "conferência"
SAIDA_ADC_MUDO = 4


def pedido_da_conferencia(pedido: PedidoDeCaptura) -> PedidoDeCaptura:
    """O pedido de ``pedido`` para a conferência: os mesmos canais, a taxa e o avançado, com um bloco só, direto no
    computador, e o título ``conferência`` (uma captura que alguém ache depois diz o que ela foi)."""
    return pedido.com(duracao_s=None, blocos=1, titulo=TITULO, descricao="", destino="computador",
                      arquivo_no_cartao="")


def segundos_da_conferencia(pedido: PedidoDeCaptura) -> float:
    """Quanto a conferência leva na placa: um bloco à taxa pedida (2,6 s a 400 kS/s; 21 s a 50 kS/s)."""
    return AMOSTRAS_POR_BLOCO / pedido.taxa_real_hz


@dataclass(frozen=True)
class ConferenciaFeita:
    """O resultado: o pedido conferido (o do formulário com um bloco), a medida do motor e a captura recebida (o código
    do ``ler_adc``, o texto dele)."""

    pedido: PedidoDeCaptura
    conferencia: Conferencia
    recebida: CapturaRecebida
    feita_em: float

    @property
    def adc_mudo(self) -> bool:
        return self.recebida.codigo == SAIDA_ADC_MUDO

    @property
    def problemas(self) -> int:
        return self.conferencia.problemas

    @property
    def pronta(self) -> bool:
        return self.conferencia.pronta and not self.adc_mudo

    @property
    def faixas_sugeridas(self) -> dict[int, float]:
        """A faixa que cada canal pede (só a dos canais em que ela muda)."""
        return {n.canal: n.faixa_sugerida_v for n in self.conferencia.canais if n.faixa_sugerida_v is not None}


async def conferir(conexao: ConexaoSSH, pedido: PedidoDeCaptura, pasta: Path, *, senha_do_sudo: str,
                   pasta_firmware: str = PASTA_DO_FIRMWARE,
                   ao_progresso: Callable[[Progresso], object] | None = None) -> ConferenciaFeita:
    """Confere ``pedido`` na placa de ``conexao``: a captura curta em ``pasta`` (um nome que não existe), a medida e o
    arquivo apagado. Os erros são os da captura (``ErroDaCaptura``, ``ErroDoSudo``, ``ErroDeConexao``)."""
    conferido = pedido_da_conferencia(pedido)
    Path(pasta).mkdir(parents=True, exist_ok=True)
    arquivo = Path(pasta) / f"conferencia_{uuid.uuid4().hex[:12]}.bin"
    captura = CapturaContinua(conexao, conferido.argumentos(), arquivo, senha_do_sudo=senha_do_sudo,
                              pasta_firmware=pasta_firmware, ao_progresso=ao_progresso)
    try:
        recebida = await captura.rodar()
        conferencia = await asyncio.to_thread(conferir_captura, recebida.arquivo)
    finally:
        arquivo.unlink(missing_ok=True)
        caminho_parcial(arquivo).unlink(missing_ok=True)
    return ConferenciaFeita(conferido, conferencia, recebida, time.time())
