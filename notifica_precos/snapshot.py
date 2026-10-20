"""Última foto dos preços e histórico de alterações, guardados no banco.

A TGFEXC não tem coluna de data de alteração, então a detecção é feita
comparando a consulta atual com a foto salva no ciclo anterior.
"""

from dataclasses import dataclass
from datetime import datetime

from .banco import Banco

Chave = tuple[int, int, int, str]  # CODTAB, CODPROD, CODLOCAL, CONTROLE


@dataclass(frozen=True)
class Preco:
    codtab: int
    codprod: int
    codlocal: int
    controle: str
    nutab: int
    descrprod: str
    vlrvenda: float

    @property
    def chave(self) -> Chave:
        return (self.codtab, self.codprod, self.codlocal, self.controle)


@dataclass(frozen=True)
class Alteracao:
    atual: Preco
    anterior: Preco | None  # None = produto novo na tabela

    @property
    def variacao_pct(self) -> float | None:
        if not self.anterior or not self.anterior.vlrvenda:
            return None
        return (self.atual.vlrvenda / self.anterior.vlrvenda - 1) * 100


@dataclass
class Diferenca:
    alteracoes: list[Alteracao]  # preço mudou ou produto novo: vão para a notificação
    gravar: list[Preco]  # tudo que difere da foto (inclui troca de NUTAB/descrição sem mudar preço)
    removidos: list[Chave]


def de_registro(r: dict) -> Preco:
    return Preco(
        codtab=int(r["CODTAB"]),
        codprod=int(r["CODPROD"]),
        codlocal=int(r["CODLOCAL"] or 0),
        controle=str(r["CONTROLE"] or " "),
        nutab=int(r["NUTAB"]),
        descrprod=str(r["DESCRPROD"] or "").strip(),
        vlrvenda=round(float(r["VLRVENDA"] or 0), 4),
    )


class Snapshot:
    def __init__(self, banco: Banco):
        self.banco = banco
        self.banco.criar_tabelas()

    def vazio(self) -> bool:
        return self.banco.execute("SELECT COUNT(*) FROM precos").fetchone()[0] == 0

    def _anteriores(self) -> dict[Chave, Preco]:
        linhas = self.banco.execute(
            "SELECT codtab, codprod, codlocal, controle, nutab, descrprod, vlrvenda FROM precos"
        ).fetchall()
        return {p.chave: p for p in (Preco(*l) for l in linhas)}

    def comparar(self, atuais: dict[Chave, Preco]) -> Diferenca:
        anteriores = self._anteriores()
        alteracoes, gravar = [], []
        for k, p in atuais.items():
            anterior = anteriores.get(k)
            if anterior == p:
                continue
            gravar.append(p)
            if anterior is None or anterior.vlrvenda != p.vlrvenda:
                alteracoes.append(Alteracao(atual=p, anterior=anterior))
        return Diferenca(alteracoes, gravar, list(anteriores.keys() - atuais.keys()))

    def salvar(self, dif: Diferenca, notificado: bool) -> None:
        """Grava só o que mudou (upsert/delete), para não reescrever a tabela inteira a cada ciclo."""
        agora = datetime.now().astimezone()
        with self.banco.transacao():
            self.banco.executemany(
                "INSERT INTO precos (codtab, codprod, codlocal, controle, nutab, descrprod, vlrvenda)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)"
                " ON CONFLICT (codtab, codprod, codlocal, controle) DO UPDATE SET"
                " nutab = excluded.nutab, descrprod = excluded.descrprod, vlrvenda = excluded.vlrvenda",
                [(p.codtab, p.codprod, p.codlocal, p.controle, p.nutab, p.descrprod, p.vlrvenda)
                 for p in dif.gravar],
            )
            self.banco.executemany(
                "DELETE FROM precos WHERE codtab = ? AND codprod = ? AND codlocal = ? AND controle = ?",
                dif.removidos,
            )
            self.banco.executemany(
                "INSERT INTO historico (detectado_em, codtab, codprod, codlocal, controle, descrprod,"
                " nutab_anterior, nutab_novo, vlr_anterior, vlr_novo, notificado)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [(agora, a.atual.codtab, a.atual.codprod, a.atual.codlocal, a.atual.controle,
                  a.atual.descrprod, a.anterior.nutab if a.anterior else None, a.atual.nutab,
                  a.anterior.vlrvenda if a.anterior else None, a.atual.vlrvenda, notificado)
                 for a in dif.alteracoes],
            )
