"""SH-Analyzer -- pós-processamento das capturas do ADS8688 (BeagleBone Black + PRU).

Este pacote contém TODA a lógica de análise; ``scripts/adc_tool.py``,
``scripts/gerar_perfil_sonda.py``, ``scripts/medir_captura.py`` e
``scripts/compactar_amostras.py`` são só entradas de linha de comando finas.
Ver ``docs/arquitetura_software.md`` para o mapa dos módulos e as regras de
dependência entre eles.
"""

import logging

# Boa prática para bibliotecas: sem handler configurado, não imprimir nada
# (nem o aviso "No handlers could be found"). A CLI liga o console em
# supraharmonicos.registro.configurar_logging_cli().
logging.getLogger(__name__).addHandler(logging.NullHandler())
