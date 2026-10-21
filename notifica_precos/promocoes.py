"""Promoções da TGFDES: preço de venda com desconto, por produto, e o que mudou desde o último ciclo.

O preço com desconto é calculado sobre o preço de tabela da foto (tabela `precos`):
VLRVENDA da promoção é o próprio preço; PERCENTUAL desconta a porcentagem; VLRDESC desconta o valor.
Avisa quando um produto entra em promoção, quando o desconto muda e quando a promoção acaba.
Uma troca só de preço de tabela durante a promoção não gera aviso aqui (já vai no e-mail de preços).
"""

from dataclasses import dataclass
from datetime import datetime

from .banco import Banco
from .snapshot import Chave, Preco, data_iso

# Preço da tabela (CODTAB, CODPROD, CODLOCAL, CONTROLE) + local da promoção (0 = todos).
ChavePromo = tuple[int, int, int, str, int]

INICIO = "inicio"
ALTERADA = "alterada"
FIM = "fim"


@dataclass(frozen=True)
class Promocao:
    codtab: int
    codprod: int
    codlocal: int
    controle: str
    local_promo: int
    nupromocao: int
    descricao: str
    percentual: float
    vlrdesc: float
    vlrfixo: float
    dtinicial: str
    dtfinal: str  # "" = sem data final
    preco_base: float
    preco_promo: float
    descrprod: str
    modelo: str

    @property
    def chave(self) -> ChavePromo:
        return (self.codtab, self.codprod, self.codlocal, self.controle, self.local_promo)

    @property
    def desconto(self) -> tuple[float, float, float]:
        """O que define o desconto; mudou = aviso de promoção alterada."""
        return (self.percentual, self.vlrdesc, self.vlrfixo)


@dataclass(frozen=True)
class Evento:
    tipo: str  # INICIO, ALTERADA ou FIM
    promo: Promocao  # a atual; no FIM, a que acabou
    anterior: Promocao | None = None  # só em ALTERADA
    preco_atual: float = 0.0  # preço de tabela agora (sem desconto)


def _numero(valor) -> float:
    return round(float(valor or 0), 4)


def _aplica(r: dict, p: Preco) -> bool:
    codtab = r["CODTAB"]
    if codtab not in (None, "") and int(codtab) != p.codtab:
        return False
    local = int(r["CODLOCAL"] or 0)
    if local and p.codlocal not in (0, local):
        return False
    controle = str(r["CONTROLE"] or "").strip()
    return not controle or controle == p.controle.strip()


def preco_com_desconto(base: float, percentual: float, vlrdesc: float, vlrfixo: float) -> float | None:
    if vlrfixo > 0:
        valor = vlrfixo
    elif percentual > 0:
        valor = base * (1 - percentual / 100)
    elif vlrdesc > 0:
        valor = base - vlrdesc
    else:
        return None  # promoção sem desconto informado
    return round(max(valor, 0.0), 2)


def calcular(registros: list[dict], precos: dict[Chave, Preco]) -> dict[ChavePromo, Promocao]:
    """Cruza as promoções vigentes com os preços da foto. Se mais de uma valer para o mesmo
    preço e local, fica a de menor preço final."""
    por_produto: dict[int, list[Preco]] = {}
    for p in precos.values():
        por_produto.setdefault(p.codprod, []).append(p)

    atuais: dict[ChavePromo, Promocao] = {}
    for r in registros:
        percentual, vlrdesc, vlrfixo = _numero(r["PERCENTUAL"]), _numero(r["VLRDESC"]), _numero(r["VLRVENDA"])
        for p in por_produto.get(int(r["CODPROD"]), []):
            if not _aplica(r, p):
                continue
            final = preco_com_desconto(p.vlrvenda, percentual, vlrdesc, vlrfixo)
            if final is None:
                continue
            promo = Promocao(
                p.codtab, p.codprod, p.codlocal, p.controle, int(r["CODLOCAL"] or 0),
                int(r["NUPROMOCAO"]), str(r["DESCRPROMOCAO"] or "").strip(), percentual, vlrdesc, vlrfixo,
                data_iso(r["DTINICIAL"]), data_iso(r["DTFINAL"]) if r["DTFINAL"] else "",
                p.vlrvenda, final, p.descrprod, p.modelo,
            )
            atual = atuais.get(promo.chave)
            if atual is None or (promo.preco_promo, -promo.nupromocao) < (atual.preco_promo, -atual.nupromocao):
                atuais[promo.chave] = promo
    return atuais


def comparar(
    anteriores: dict[ChavePromo, Promocao], atuais: dict[ChavePromo, Promocao], precos: dict[Chave, Preco],
) -> list[Evento]:
    eventos = []
    for k, promo in atuais.items():
        anterior = anteriores.get(k)
        if anterior is None:
            eventos.append(Evento(INICIO, promo, preco_atual=promo.preco_base))
        elif anterior.desconto != promo.desconto:
            eventos.append(Evento(ALTERADA, promo, anterior, preco_atual=promo.preco_base))
    for k, promo in anteriores.items():
        if k not in atuais:
            preco = precos.get(k[:4])
            eventos.append(Evento(FIM, promo, preco_atual=preco.vlrvenda if preco else promo.preco_base))
    return eventos


COLUNAS = ("codtab, codprod, codlocal, controle, local_promo, nupromocao, descricao, percentual, vlrdesc,"
           " vlrfixo, dtinicial, dtfinal, preco_base, preco_promo, descrprod, modelo")


def carregar(banco: Banco) -> dict[ChavePromo, Promocao]:
    linhas = banco.execute(f"SELECT {COLUNAS} FROM promocoes").fetchall()
    return {p.chave: p for p in (Promocao(*l) for l in linhas)}


def salvar(banco: Banco, atuais: dict[ChavePromo, Promocao], eventos: list[Evento],
           notificado: bool, estado: dict[str, str]) -> None:
    """Regrava a foto das promoções e o histórico numa transação; se o e-mail falhar antes,
    nada é gravado e os mesmos avisos saem no próximo ciclo."""
    agora = datetime.now().astimezone()
    with banco.transacao():
        banco.execute("DELETE FROM promocoes")
        banco.executemany(
            f"INSERT INTO promocoes ({COLUNAS}) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [(p.codtab, p.codprod, p.codlocal, p.controle, p.local_promo, p.nupromocao, p.descricao,
              p.percentual, p.vlrdesc, p.vlrfixo, p.dtinicial, p.dtfinal, p.preco_base, p.preco_promo,
              p.descrprod, p.modelo) for p in atuais.values()],
        )
        banco.executemany(
            "INSERT INTO historico_promocoes (detectado_em, tipo, codprod, codlocal, controle, local_promo,"
            " nupromocao, descricao, preco_base, preco_promo, notificado) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [(agora, e.tipo, e.promo.codprod, e.promo.codlocal, e.promo.controle, e.promo.local_promo,
              e.promo.nupromocao, e.promo.descricao, e.preco_atual, e.promo.preco_promo, notificado) for e in eventos],
        )
        for chave, valor in estado.items():
            banco.definir_estado(chave, valor)
