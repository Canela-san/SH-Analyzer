"""Os cenários do simulador da placa (docs/gui-plan.md, 11.11): o nome, o título e a descrição que a interface mostra.
À parte do ``simulador.py`` (que traz o asyncssh) para a interface listá-los sem carregar a rede."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Cenario:
    nome: str
    titulo: str
    descricao: str
    grupo: str                            # "uso": como a placa se comporta; "configuracao": um problema dela


CENARIOS = {c.nome: c for c in (
    Cenario("normal", "Rede de 60 Hz com supraharmônicos",
            "A placa pronta para capturar, com capturas da tomada: 60 Hz, os harmônicos e os supraharmônicos de um "
            "inversor, de drivers de LED e de uma comunicação pela rede.", "uso"),
    Cenario("adc_mudo", "ADC mudo",
            "A placa de aquisição sem alimentação (a BeagleBone pelo USB): a conferência mais recente ficou em 0.",
            "uso"),
    Cenario("disco_cheio", "Cartão cheio",
            "Quase sem espaço no cartão: transfira as capturas e apague as conferidas.", "uso"),
    Cenario("conexao_instavel", "Conexão que cai",
            "O cabo com mau contato: a conexão cai no meio de cada transferência e de tempos em tempos, e volta "
            "sozinha.", "uso"),
    Cenario("firmware_antigo", "Firmware de outra versão",
            "A placa com o firmware v0.7.0, de outra versão do aplicativo.", "uso"),
    Cenario("relogio_errado", "Relógio errado",
            "A placa ligada sem internet depois de dias desligada: o relógio atrasado, sem NTP.", "uso"),
    Cenario("pru_com_falha", "PRU com falha", "O remoteproc da PRU0 parou com falha.", "configuracao"),
    Cenario("pinos_errados", "Pinos fora do modo da PRU",
            "Depois de um reinício, sem o config-pin: P9_28 e P9_31 em default.", "configuracao"),
    Cenario("sem_mem_496m", "Sem o mem=496M",
            "O kernel sem o mem=496M: a memória dos buffers da PRU fica com o sistema.", "configuracao"),
    Cenario("sem_compilar", "Firmware sem compilar", "A pasta do firmware sem o ler_adc e o fw_pru.out.",
            "configuracao"),
    Cenario("pru_desatualizada", "PRU desatualizada",
            "O firmware instalado na PRU não é o compilado na pasta.", "configuracao"),
    Cenario("audio_hdmi", "Áudio do HDMI ligado",
            "O overlay do HDMI com áudio disputa os pinos da PRU.", "configuracao"),
    Cenario("sem_overlay_da_pru", "Sem o overlay da PRU",
            "O uEnv.txt sem o overlay do remoteproc: a PRU0 não existe.", "configuracao"),
)}
"""Os cenários, na ordem em que a interface os mostra."""
