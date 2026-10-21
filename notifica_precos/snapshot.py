"""Foto dos preços vigentes, versões já processadas e histórico de alterações, guardados no banco.

No Sankhya a tabela de preço é recriada a cada atualização (novo NUTAB). A nova versão pode
trazer só os produtos alterados ou uma cópia de todos, e a TGFEXC não tem data de alteração.
Por isso a foto guarda, para cada produto, o preço da versão mais recente que o contém:

- carga completa: recalcula a foto inteira no Sankhya e compara com a anterior;
- incremental: aplica sobre a foto só as versões novas, produto a produto.
"""

from dataclasses import dataclass, field
from datetime import datetime

from .banco import Banco

Chave = tuple[int, int, int, str]  # CODTAB, CODPROD, CODLOCAL, CONTROLE

# Formatos brasileiros que o Sankhya usa nas respostas; ISO é tratado à parte.
FORMATOS_DATA = ("%d%m%Y %H:%M:%S", "%d/%m/%Y %H:%M:%S", "%d%m%Y", "%d/%m/%Y")


def data_iso(valor) -> str:
    """Normaliza a data do Sankhya para ISO (AAAA-MM-DDTHH:MM:SS), que ordena como texto."""
    if isinstance(valor, (int, float)):  # epoch em milissegundos
        return datetime.fromtimestamp(valor / 1000).isoformat(timespec="seconds")
    texto = str(valor).strip()
    for formato in FORMATOS_DATA:
        try:
            return datetime.strptime(texto, formato).isoformat(timespec="seconds")
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(texto).replace(tzinfo=None, microsecond=0).isoformat()
    except ValueError:
        raise ValueError(f"Formato de data do Sankhya não reconhecido: {valor!r}") from None


@dataclass(frozen=True)
class Preco:
    codtab: int
    codprod: int
    codlocal: int
    controle: str
    nutab: int
    dtvigor: str
    descrprod: str
    modelo: str
    vlrvenda: float

    @property
    def chave(self) -> Chave:
        return (self.codtab, self.codprod, self.codlocal, self.controle)

    @property
    def versao(self) -> tuple[str, int]:
        return (self.dtvigor, self.nutab)


@dataclass(frozen=True)
class Versao:
    nutab: int
    codtab: int
    dtvigor: str


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
    alteracoes: list[Alteracao] = field(default_factory=list)  # preço mudou ou produto novo: notificar
    gravar: list[Preco] = field(default_factory=list)  # tudo que difere da foto (inclui troca de NUTAB)
    removidos: list[Chave] = field(default_factory=list)  # só na carga completa


def de_registro(r: dict) -> Preco:
    return Preco(
        codtab=int(r["CODTAB"]),
        codprod=int(r["CODPROD"]),
        codlocal=int(r["CODLOCAL"] or 0),
        controle=str(r["CONTROLE"] or " "),
        nutab=int(r["NUTAB"]),
        dtvigor=data_iso(r["DTVIGOR"]),
        descrprod=str(r["DESCRPROD"] or "").strip(),
        modelo=str(r["AD_MODELOREF"] or "").strip(),
        vlrvenda=round(float(r["VLRVENDA"] or 0), 4),
    )


def versao_de_registro(r: dict) -> Versao:
    return Versao(nutab=int(r["NUTAB"]), codtab=int(r["CODTAB"]), dtvigor=data_iso(r["DTVIGOR"]))


def _diferenca(anteriores: dict[Chave, Preco], novos: dict[Chave, Preco]) -> Diferenca:
    dif = Diferenca()
    for k, p in novos.items():
        anterior = anteriores.get(k)
        if anterior == p:
            continue
        dif.gravar.append(p)
        if anterior is None or anterior.vlrvenda != p.vlrvenda:
            dif.alteracoes.append(Alteracao(atual=p, anterior=anterior))
    return dif


def comparar_completo(anteriores: dict[Chave, Preco], atuais: dict[Chave, Preco]) -> Diferenca:
    """Carga completa: compara a foto nova com a anterior. O que não veio fica em `removidos`
    só para informação; a carga completa mantém esses itens no banco (ver main.carga_completa)."""
    dif = _diferenca(anteriores, atuais)
    dif.removidos = list(anteriores.keys() - atuais.keys())
    return dif


def aplicar_versoes(anteriores: dict[Chave, Preco], versoes: list[tuple[Versao, list[Preco]]]) -> Diferenca:
    """Incremental: sobrepõe as versões novas, da mais antiga para a mais nova.

    Um produto só é sobrescrito por uma versão igual ou mais recente que a que está na foto,
    então uma versão retroativa não desfaz um preço mais novo. Se o mesmo produto mudar em
    várias versões do mesmo ciclo, a notificação mostra o preço da foto contra o final.
    """
    mudados: dict[Chave, Preco] = {}
    for versao, precos in sorted(versoes, key=lambda v: (v[0].dtvigor, v[0].nutab)):
        for p in precos:
            atual = mudados.get(p.chave) or anteriores.get(p.chave)
            if atual is None or p.versao >= atual.versao:
                mudados[p.chave] = p
    return _diferenca(anteriores, mudados)


class Snapshot:
    def __init__(self, banco: Banco):
        self.banco = banco
        self.banco.criar_tabelas()

    def vazio(self) -> bool:
        return self.banco.execute("SELECT COUNT(*) FROM precos").fetchone()[0] == 0

    def precos(self) -> dict[Chave, Preco]:
        linhas = self.banco.execute(
            "SELECT codtab, codprod, codlocal, controle, nutab, dtvigor, descrprod, modelo, vlrvenda FROM precos"
        ).fetchall()
        return {p.chave: p for p in (Preco(*l) for l in linhas)}

    def versoes_processadas(self) -> set[int]:
        return {l[0] for l in self.banco.execute("SELECT nutab FROM versoes_processadas").fetchall()}

    def estado(self, chave: str) -> str | None:
        return self.banco.obter_estado(chave)

    def salvar(
        self,
        dif: Diferenca,
        notificado: bool,
        versoes: list[Versao] = (),
        estado: dict[str, str] | None = None,
    ) -> None:
        """Grava tudo numa transação: se algo falhar, o ciclo inteiro é refeito na próxima execução."""
        agora = datetime.now().astimezone()
        with self.banco.transacao():
            self.banco.executemany(
                "INSERT INTO precos (codtab, codprod, codlocal, controle, nutab, dtvigor, descrprod, modelo, vlrvenda)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"
                " ON CONFLICT (codtab, codprod, codlocal, controle) DO UPDATE SET"
                " nutab = excluded.nutab, dtvigor = excluded.dtvigor,"
                " descrprod = excluded.descrprod, modelo = excluded.modelo, vlrvenda = excluded.vlrvenda",
                [(p.codtab, p.codprod, p.codlocal, p.controle, p.nutab, p.dtvigor, p.descrprod, p.modelo, p.vlrvenda)
                 for p in dif.gravar],
            )
            self.banco.executemany(
                "DELETE FROM precos WHERE codtab = ? AND codprod = ? AND codlocal = ? AND controle = ?",
                dif.removidos,
            )
            self.banco.executemany(
                "INSERT INTO versoes_processadas (nutab, codtab, dtvigor, processada_em) VALUES (?, ?, ?, ?)"
                " ON CONFLICT (nutab) DO NOTHING",
                [(v.nutab, v.codtab, v.dtvigor, agora) for v in versoes],
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
            for chave, valor in (estado or {}).items():
                self.banco.definir_estado(chave, valor)
