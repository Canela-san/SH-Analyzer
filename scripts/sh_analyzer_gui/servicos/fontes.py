"""O que cada captura aberta precisa, em segundo plano: a pirâmide de cada canal (do cache em disco, ou construída)
e, depois, a conferência do CRC das amostras (``api.conferir_integridade``). Uma por vez por captura: a pirâmide
lê o arquivo inteiro uma vez, e a conferência vem depois, sem disputar o disco com ela.

O serviço segue o projeto: uma captura que entra é preparada; um projeto que sai tem as tarefas canceladas.

**O cache das pirâmides** segue as configurações (:meth:`ServicoDeFontes.definir_cache`): outra pasta é um cache
novo (o que já está rodando termina no antigo, que a tarefa guardou); o limite vale na hora. O "limpar" nunca apaga
as pirâmides das capturas abertas.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject
from supraharmonicos.api import conferir_integridade

from ..dados.cache import CacheDePiramides
from ..modelo.objetos import FonteDoProjeto, Projeto
from .tarefas import GerenciadorDeTarefas, Tarefa


class ServicoDeFontes(QObject):
    def __init__(self, tarefas: GerenciadorDeTarefas, cache: CacheDePiramides | None = None,
                 parent: QObject | None = None):
        super().__init__(parent)
        self.tarefas = tarefas
        self.cache = cache or CacheDePiramides()
        self.projeto: Projeto | None = None
        self._fonte_da_tarefa: dict[Tarefa, FonteDoProjeto] = {}

    def acompanhar(self, projeto: Projeto) -> None:
        """Passa a preparar as capturas de ``projeto`` (as que já estão nele e as que entrarem)."""
        if self.projeto is not None:
            self.projeto.fonteEntrou.disconnect(self._fonte_entrou)
            for fonte in self.projeto.fontes:
                self.tarefas.cancelar_grupo(fonte.id)
        self.projeto = projeto
        projeto.fonteEntrou.connect(self._fonte_entrou)
        for fonte in projeto.fontes:
            self.preparar(fonte)

    def _fonte_entrou(self, fonte: FonteDoProjeto, _indice: int) -> None:
        self.preparar(fonte)

    # ------------------------------------------------------------------ o cache

    def piramides_abertas(self) -> set[Path]:
        """Os arquivos das pirâmides das capturas abertas no projeto (no cache de agora)."""
        if self.projeto is None:
            return set()
        return {self.cache.caminho(f.fonte.chave, c) for f in self.projeto.fontes if not f.esta_ausente
                for c in range(len(f.canais))}

    def definir_cache(self, pasta: Path, limite_bytes: int) -> None:
        """A pasta e o limite do cache das pirâmides. Passar do limite apaga as menos usadas na hora (nunca as
        abertas)."""
        if Path(pasta) != self.cache.pasta:
            self.cache = CacheDePiramides(pasta, limite_bytes)
        else:
            self.cache.limite_bytes = limite_bytes
        self.cache.aparar(manter=self.piramides_abertas())

    def limpar_cache(self) -> int:
        """Apaga as pirâmides do cache, menos as das capturas abertas; devolve os bytes liberados."""
        return self.cache.limpar(manter=self.piramides_abertas())

    def preparar(self, fonte: FonteDoProjeto) -> None:
        """Constrói (ou abre do cache) a pirâmide; depois, confere o CRC. Nada para uma ausente, nem de novo para
        uma já pronta (desfazer e refazer a abertura não refaz o trabalho)."""
        if fonte.esta_ausente or fonte.progresso_da_piramide is not None:
            return
        if fonte.piramides is None:
            origem, cache = fonte.fonte, self.cache

            def construir(progresso, cancelado):
                return cache.obter(origem.chave, origem.captura.amostras, len(origem.canais), progresso=progresso,
                                   cancelado=cancelado)

            fonte.definir_progresso_da_piramide(0.0)
            self._iniciar(fonte, self.tr("Pirâmide de {}").format(fonte.nome), construir, self._piramide_terminou,
                          self._progresso)
        elif fonte.integridade == "pendente":
            self._conferir(fonte)

    def _progresso(self, tarefa: Tarefa, fracao: float) -> None:
        fonte = self._fonte_da_tarefa.get(tarefa)
        if fonte is not None and tarefa.ativa:
            fonte.definir_progresso_da_piramide(fracao)

    def _piramide_terminou(self, tarefa: Tarefa) -> None:
        fonte = self._fonte_da_tarefa.pop(tarefa, None)
        if fonte is None:
            return
        if tarefa.estado == "concluida":
            fonte.definir_piramides(tarefa.resultado)
            if fonte.integridade == "pendente":
                self._conferir(fonte)
        else:
            fonte.definir_progresso_da_piramide(None)

    def _conferir(self, fonte: FonteDoProjeto) -> None:
        captura = fonte.fonte.captura

        def conferir(progresso, cancelado):
            return conferir_integridade(captura, progresso=progresso, cancelado=cancelado)

        fonte.definir_integridade("conferindo")
        self._iniciar(fonte, self.tr("Conferir o CRC de {}").format(fonte.nome), conferir, self._conferencia_terminou)

    def _iniciar(self, fonte: FonteDoProjeto, nome: str, funcao, ao_terminar, ao_progredir=None) -> None:
        """A tarefa de ``fonte``, com os ouvintes ligados antes de ela começar. O fim chega pela fila de eventos (a
        tarefa termina noutra thread): o par tarefa -> fonte, guardado logo depois do ``iniciar``, já está lá."""
        tarefa = self.tarefas.iniciar(nome, funcao, fonte.id, ao_terminar=ao_terminar, ao_progredir=ao_progredir)
        self._fonte_da_tarefa[tarefa] = fonte

    def _conferencia_terminou(self, tarefa: Tarefa) -> None:
        fonte = self._fonte_da_tarefa.pop(tarefa, None)
        if fonte is None:
            return
        if tarefa.estado == "concluida":
            fonte.definir_integridade({True: "confere", False: "nao_confere", None: "sem_crc"}[tarefa.resultado])
        elif tarefa.estado == "falhou":
            fonte.definir_integridade("erro")
        else:
            fonte.definir_integridade("pendente")
