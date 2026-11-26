"""Os avisos de um traço (docs/gui-plan.md, 1, "a verdade fica à vista"): o que o chip dele mostra além do nome,
para quem olha o gráfico não precisar abrir o painel de avisos.

* **Do canal** (os do motor ao abrir a captura): a sonda registrada que não pôde ser usada; a faixa do ADC suposta
  (a captura não a registra, e a amplitude depende dela).
* **Da captura:** as amostras que não conferem com o CRC gravado.
* **Da cadeia, neste canal:** uma etapa que não serve (um corte acima da Nyquist, um perfil que não abre) ou que não
  faz nada (a correção automática sem sonda).
* **Da conta:** o erro da materialização ou do espectro, que quem desenha passa.

Sem Qt: os mesmos avisos em qualquer vista.

**Na tela** (:func:`para_a_tela`), os avisos que o motor escreve para a CLI ganham as palavras da interface: no lugar
das opções da linha de comando (``--sonda-perfil 0:ARQUIVO``), o que fazer na janela; e os números com o separador
decimal das configurações.
"""

from __future__ import annotations

import re

import supraharmonicos.api as api

from .cadeia import Cadeia, ContextoDaCadeia

NIVEIS = ("info", "aviso", "erro")


def avisos_do_canal(canal: api.CanalDaCaptura) -> tuple[api.Aviso, ...]:
    avisos = []
    if canal.problema_sonda:
        avisos.append(api.Aviso("aviso", f"a sonda registrada não pôde ser usada: {canal.problema_sonda}"))
    if not canal.faixa_confiavel:
        avisos.append(api.Aviso("aviso", f"a captura não registra a faixa do ADC: os valores supõem a faixa de "
                                         f"±{canal.faixa_v:g} V, e a amplitude depende dela"))
    return tuple(avisos)


def avisos_da_cadeia(cadeia: Cadeia, contexto: ContextoDaCadeia) -> tuple[api.Aviso, ...]:
    avisos = []
    for etapa in cadeia.ligadas:
        try:
            etapa.validar(contexto)
        except api.ErroSHAN as e:
            avisos.append(api.Aviso("erro", f"{etapa.resumo()}: {e}"))
            continue
        texto = etapa.aviso(contexto)
        if texto:
            avisos.append(api.Aviso("aviso", texto))
    return tuple(avisos)


def avisos_do_traco(canal: api.CanalDaCaptura, cadeia: Cadeia, contexto: ContextoDaCadeia, *,
                    integridade: str = "", erro: str = "") -> tuple[api.Aviso, ...]:
    """Os avisos do traço, do mais grave para o menos (na mesma gravidade, na ordem acima). ``integridade`` é a da
    fonte no projeto (``FonteDoProjeto.integridade``); ``erro``, o da conta de quem desenha."""
    avisos = [*avisos_do_canal(canal)]
    if integridade == "nao_confere":
        avisos.append(api.Aviso("erro", "as amostras não conferem com o CRC gravado na captura: o arquivo foi "
                                        "alterado ou corrompido depois dela"))
    avisos += avisos_da_cadeia(cadeia, contexto)
    # O erro da conta, se ainda não foi dito: a materialização de uma cadeia com uma etapa que não serve falha com o
    # mesmo motivo.
    if erro and not any(erro in a.texto for a in avisos):
        avisos.append(api.Aviso("erro", erro))
    return tuple(sorted(dict.fromkeys(avisos), key=lambda a: -NIVEIS.index(a.nivel)))


def pior_nivel(avisos) -> str | None:
    """O nível mais grave (``"erro"``, ``"aviso"``, ``"info"``), ou None sem avisos."""
    return max((a.nivel for a in avisos), key=NIVEIS.index, default=None)


# ------------------------------------------------------------------ na tela

_SEM_PERFIL = re.compile(r"canal (\d+) é de corrente mas não tem sonda/perfil resolvido -- usando só --ganho escalar "
                         r"\(sem correção por frequência\)\. Registre a sonda na captura \(--sonda em ler_adc\) ou use "
                         r"--sonda-perfil \d+:ARQUIVO\.")
_GANHO = re.compile(r"Ganho por canal: o declarado na captura \(ler_adc --ganho\) -- (.*)")
_NUMERO = re.compile(r"(?<![\w.])(\d+)\.(\d+)(?![\w.])")
"""Um número com uma casa decimal só (``19.357``): nem uma versão (``v0.8``), nem um IP, nem parte de um nome."""


def com_o_separador(texto: str, separador: str) -> str:
    """Os números decimais de ``texto`` com ``separador`` (``","``): só os soltos, não os de nomes, versões e IPs."""
    if separador == ".":
        return texto
    return _NUMERO.sub(lambda m: f"{m[1]}{separador}{m[2]}", texto)


def para_a_tela(aviso: api.Aviso, separador: str = ",") -> api.Aviso:
    """O aviso nas palavras da interface (ver o começo do módulo): o mesmo nível, o texto reescrito."""
    texto = aviso.texto
    if m := _SEM_PERFIL.fullmatch(texto):
        texto = (f"o canal {m[1]} é de corrente e não tem um perfil de sonda: os valores usam só o ganho da captura, "
                 f"sem a correção em frequência. Para corrigir, no inspetor do traço, \"Adicionar etapa\" → "
                 f"\"Correção de sonda\" e escolha o perfil (ou registre a sonda na captura)")
    elif m := _GANHO.fullmatch(texto):
        texto = "o ganho de cada canal é o declarado na captura: " + m[1].replace(", canal", "; canal")
    return api.Aviso(aviso.nivel, com_o_separador(texto, separador))
