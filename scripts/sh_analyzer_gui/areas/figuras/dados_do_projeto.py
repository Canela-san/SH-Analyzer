"""Os dados do desenho da figura com o projeto aberto (o ``DadosDaFigura`` de ``dados/desenho_da_figura.py``): as
capturas, as materializações e o que cada vista aberta mostra. Roda na thread da interface (a área colhe tudo antes
de desenhar numa de trabalho).

* **Um traço de tempo** vem como a vista o desenha: o canal pela pirâmide e as amostras, com a conversão para a
  unidade do traço (a grandeza e a unidade de ``unidades.do_traco``); com transformações (a cadeia), da
  materialização pronta, que o serviço da janela calcula uma vez e guarda (a figura só a acompanha). Enquanto ela não
  fica pronta, o traço não entra, e :attr:`esperando` diz que vale desenhar de novo quando ela chegar.
* **Os espectros** vêm do resultado que a vista de espectro já calculou (os traços da vista de tempo ligada a ela, o
  desenho, a escala, o log): a figura não refaz a FFT. O painel congelado de espectro ainda não desenha (a cópia da
  vista não guarda o espectro; recalculá-lo fica para depois).
* **As cores** são as do tema claro: a página é branca.
"""

from __future__ import annotations

from pathlib import Path

import supraharmonicos.api as api

from ...dados import unidades
from ...dados.cadeia import Cadeia
from ...dados.desenho_da_figura import SerieDoEspectro, SerieDoTempo
from ...dados.projeto import VistaSalva
from ...dados.proveniencia import FonteDaProveniencia
from ...dados.receita import ReceitaDoTraco
from ...modelo.objetos import Projeto, Vista
from ...modelo.persistencia import descrever_fonte, descrever_vista
from ...tema.tokens import CLARO, cor_do_traco


class DadosDoProjeto:
    def __init__(self, projeto: Projeto, analise, materializacoes):
        self.projeto, self.analise, self.materializacoes = projeto, analise, materializacoes
        self.esperando = False                  # um traço ficou de fora à espera da materialização
        self._acompanhadas: set = set()         # as materializações que as figuras usam (o serviço as segura)
        self._usadas: set = set()

    def comecar(self) -> None:
        """Antes de colher uma figura: zera a espera e a conta das materializações usadas."""
        self.esperando = False
        self._usadas = set()

    def terminar(self) -> None:
        """Depois de colher: as materializações que nenhuma figura usa mais são largadas."""
        for usuario in self._acompanhadas - self._usadas:
            self.materializacoes.largar(usuario)
        self._acompanhadas = self._usadas

    # ------------------------------------------------------------------ o DadosDaFigura

    def tempo(self, vista: VistaSalva, receita: ReceitaDoTraco) -> SerieDoTempo | None:
        fonte = next((f for f in self.projeto.fontes if f.id == receita.fonte), None)
        if fonte is None or fonte.esta_ausente or fonte.piramides is None:
            return None
        try:
            canal = fonte.canal(receita.canal)
        except KeyError:
            return None
        grandeza, unidade = unidades.do_traco(receita.unidade, canal.unidade, canal.nome_grandeza)
        cor, tracejado = cor_do_traco(receita.cor, CLARO)
        comum = {"nome": receita.nome, "cor": cor, "unidade": unidade, "t0": receita.deslocamento_s,
                 "tracejado": tracejado, "grandeza": grandeza}
        if Cadeia(receita.cadeia.ligadas).vazia:
            escala, deslocamento = receita.afim(canal.escala, canal.deslocamento)
            return SerieDoTempo(fonte.piramides[fonte.posicao_do_canal(receita.canal)], canal.amostras,
                                canal.taxa_hz, escala=escala, deslocamento=deslocamento, **comum)
        usuario = ("figura", fonte.id, receita.canal, Cadeia(receita.cadeia.ligadas))
        estado = self.materializacoes.acompanhar(usuario, fonte, receita.canal, receita.cadeia)
        self._usadas.add(usuario)
        self._acompanhadas.add(usuario)
        if estado is None or estado.pronta is None:
            self.esperando = True
            return None
        escala, deslocamento = receita.afim(1.0, 0.0)
        return SerieDoTempo(estado.pronta.piramide, estado.pronta.amostras, canal.taxa_hz, escala=escala,
                            deslocamento=deslocamento, **comum)

    def espectros(self, vista: VistaSalva) -> list[SerieDoEspectro]:
        """Os espectros que a vista calculou (os dos traços da vista de tempo ligada a ela), na ordem dela."""
        viva = self._viva(vista)
        widget = self.analise.widget_da_vista(viva) if viva is not None else None
        if widget is None:
            return []
        opcoes, series = viva.opcoes, []
        for r in getattr(widget, "resultados", ()):
            if r.desenho is None:
                continue
            rotulo = {"rms": r.unidade, "dbc": "dBc"}.get(opcoes.escala) or r.espectro.rotulo(r.unidade)
            cor, tracejado = cor_do_traco(r.traco.receita.cor, CLARO)
            series.append(SerieDoEspectro(r.desenho, r.traco.receita.nome, cor, rotulo,
                                          frequencia_log=opcoes.frequencia_log, tracejado=tracejado))
        return series

    def janela(self, vista: VistaSalva) -> tuple[float, float] | None:
        viva = self._viva(vista)
        return self.analise.janela_da_vista(viva) if viva is not None else None

    def _viva(self, vista: VistaSalva) -> Vista | None:
        """A vista do projeto que ``vista`` descreve agora (a de mesmo id, se ela ainda é igual à cópia)."""
        viva = next((v for v in self.projeto.vistas if v.id == vista.id), None)
        return viva if viva is not None and descrever_vista(viva) == vista else None

    def fontes_da_proveniencia(self) -> dict[str, FonteDaProveniencia]:
        """As capturas do projeto como a proveniência as diz: o caminho, o tamanho, o CRC e o cabeçalho (o de uma
        ausente, o que o projeto lembra dela)."""
        saida = {}
        for f in self.projeto.fontes:
            if f.esta_ausente:
                salva, cabecalho = f.origem, {}
            else:
                cabecalho = api.cabecalho_em_dict(f.fonte.captura)
                try:
                    salva = descrever_fonte(f, f.caminho.parent)
                except OSError:                   # o arquivo sumiu depois de aberto
                    salva = None
            saida[f.id] = FonteDaProveniencia(
                f.id, f.nome, salva.caminho_absoluto if salva is not None else str(Path(f.caminho).resolve()),
                salva.tamanho if salva is not None else None, salva.crc32_amostras if salva is not None else None,
                cabecalho)
        return saida
