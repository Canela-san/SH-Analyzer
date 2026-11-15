"""O estado da BeagleBone (a resposta do comando ``estado`` do agente) e o diagnóstico: o que está errado, por que
importa e como corrigir (docs/gui-plan.md, 11.9). A visão geral e o diagnóstico da interface mostram isto; uma futura
CLI também pode.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

TAXA_DE_REFERENCIA_BYTES_S = 800_000     # 400 kS/s x 2 bytes: quanto disco uma captura gasta por segundo
DISCO_MINIMO_KIB = 1024 * 1024           # menos que 1 GiB livre: avisa
TEMPERATURA_ALTA_C = 75.0
DIFERENCA_DE_RELOGIO_S = 2.0
ESTADOS_NORMAIS_DA_PRU = ("running", "offline")
"""O remoteproc da PRU0 numa placa boa: ``running`` durante a captura e ``offline`` entre uma e outra. O ``ler_adc``
a reinicia no começo de cada captura (ela lê a configuração uma vez por partida) e a para no fim, para ela não
escrever na DDR depois; uma placa parada há horas está ``offline``, e pronta (visto na placa de verdade, 15/11/2026)."""


@dataclass(frozen=True)
class Problema:
    """Um item do diagnóstico. ``nivel``: ``"erro"`` (impede capturar), ``"aviso"`` ou ``"info"``."""

    nivel: str
    codigo: str
    texto: str
    correcao: str | None = None


@dataclass(frozen=True)
class EstadoDaPlaca:
    """O que o agente disse, com acesso fácil aos campos (``bruto`` guarda a resposta inteira)."""

    bruto: dict = field(repr=False)

    @classmethod
    def de_json(cls, resposta: dict) -> EstadoDaPlaca:
        return cls(resposta)

    def _campo(self, *chaves):
        valor = self.bruto
        for chave in chaves:
            if not isinstance(valor, dict):
                return None
            valor = valor.get(chave)
        return valor

    @property
    def serie(self) -> str | None:
        return self._campo("placa", "serie")

    @property
    def nome_da_placa(self) -> str:
        nome = self._campo("placa", "modelo") or self._campo("placa", "nome") or "BeagleBone"
        return nome.replace("TI AM335x ", "")

    @property
    def versao_do_firmware(self) -> str | None:
        return self._campo("firmware", "firmware")

    @property
    def minutos_de_captura_no_disco(self) -> float | None:
        """Quantos minutos de captura a 400 kS/s cabem no disco livre da pasta do firmware."""
        livre = self._campo("disco", "livre_kib")
        return None if livre is None else livre * 1024 / TAXA_DE_REFERENCIA_BYTES_S / 60

    def diagnostico(self, versao_do_aplicativo: str | None = None, agora: float | None = None) -> list[Problema]:
        """Os problemas da placa, do mais grave ao menos grave."""
        p: list[Problema] = []
        estado_pru = self._campo("pru", "estado")
        if estado_pru is None:
            p.append(Problema("erro", "pru_ausente", "A PRU0 não aparece no remoteproc (sem o overlay da PRU?).",
                              "Conferir o overlay da PRU no /boot/uEnv.txt (o assistente de pinos e overlays)."))
        elif estado_pru not in ESTADOS_NORMAIS_DA_PRU:
            p.append(Problema("erro", "pru_com_falha", f"A PRU0 está '{estado_pru}' (o normal é 'running' durante a "
                              "captura e 'offline' entre uma e outra).",
                              "Rodar o setup.sh (recompila e recarrega o firmware na PRU)."))
        pinos = self._campo("pinos") or {}
        errados = sorted(n for n, info in pinos.items() if info.get("certo") is False)
        desconhecidos = sorted(n for n, info in pinos.items() if info.get("certo") is None)
        if errados:
            p.append(Problema("erro", "pinos", f"Pinos fora do modo da PRU: {', '.join(errados)}.",
                              "config-pin (o setup.sh faz; o ler_adc também tenta na hora de capturar)."))
        elif desconhecidos:
            p.append(Problema("aviso", "pinos_desconhecidos",
                              f"Não deu para conferir os pinos {', '.join(desconhecidos)} (sem o pinmux do config-pin).",
                              "Conferir se a imagem tem o cape universal."))
        mem = self._campo("memoria_dos_buffers", "mem_496m")
        if mem is False:
            p.append(Problema("erro", "mem_496m", "Falta 'mem=496M' na linha do kernel: a PRU escreveria por cima "
                              "da memória do Linux.", "Pôr 'mem=496M' na linha cmdline= do /boot/uEnv.txt e reiniciar."))
        elif mem is None:
            p.append(Problema("aviso", "mem_desconhecida", "Não deu para ler a linha do kernel (/proc/cmdline)."))
        if self._campo("firmware", "compilado") is False:
            p.append(Problema("erro", "nao_compilado", "O ler_adc não está compilado na pasta do firmware.",
                              "Rodar o setup.sh."))
        versao = self.versao_do_firmware
        if versao is None:
            p.append(Problema("aviso", "versao_desconhecida", "A pasta do firmware não tem o arquivo VERSAO.",
                              "Enviar o firmware pelo aplicativo (ou pelo BeagleBone_Setup.sh enviar)."))
        elif versao_do_aplicativo and versao != versao_do_aplicativo:
            p.append(Problema("aviso", "firmware_diferente", f"O firmware da placa ({versao}) não é o deste aplicativo "
                              f"({versao_do_aplicativo}).", "Atualizar o firmware (Manutenção)."))
        utc = self._campo("relogio", "utc")
        if utc is not None:
            diferenca = utc - (time.time() if agora is None else agora)
            if abs(diferenca) > DIFERENCA_DE_RELOGIO_S:
                p.append(Problema("aviso", "relogio", f"O relógio da placa está {diferenca:+.0f} s do computador "
                                  "(ela não tem bateria de RTC): a hora gravada nas capturas sai errada.",
                                  "Acertar o relógio pelo do computador."))
        minutos = self.minutos_de_captura_no_disco
        if minutos is not None and self._campo("disco", "livre_kib") < DISCO_MINIMO_KIB:
            p.append(Problema("aviso", "disco", f"Pouco espaço no cartão: ~{minutos:.0f} min de captura a 400 kS/s.",
                              "Transferir as capturas e apagar as já conferidas."))
        temperatura = self._campo("temperatura_c")
        if temperatura is not None and temperatura > TEMPERATURA_ALTA_C:
            p.append(Problema("aviso", "temperatura", f"O processador está a {temperatura:.0f} °C."))
        n_capturas = self._campo("capturas", "quantidade")
        if n_capturas:
            p.append(Problema("info", "capturas", f"{n_capturas} captura(s) na placa."))
        ordem = {"erro": 0, "aviso": 1, "info": 2}
        return sorted(p, key=lambda x: ordem[x.nivel])

    def pronta_para_capturar(self, versao_do_aplicativo: str | None = None, agora: float | None = None) -> bool:
        return not any(x.nivel == "erro" for x in self.diagnostico(versao_do_aplicativo, agora))
