"""Monta o texto da notificação de alteração de preços."""

from datetime import datetime

from .snapshot import Alteracao


def moeda(valor: float) -> str:
    return "R$ " + f"{valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _linha(a: Alteracao) -> str:
    p = a.atual
    produto = f"*{p.codprod}* - {p.descrprod}"
    if p.codlocal or p.controle.strip():
        produto += f" (local {p.codlocal}{', ' + p.controle.strip() if p.controle.strip() else ''})"

    if a.anterior is None:
        return f"🆕 {produto}\n    Tab {p.codtab}: {moeda(p.vlrvenda)}"

    seta = "🔺" if p.vlrvenda > a.anterior.vlrvenda else "🔻"
    pct = a.variacao_pct
    variacao = f" ({pct:+.2f}%)".replace(".", ",") if pct is not None else ""
    return (
        f"{seta} {produto}\n"
        f"    Tab {p.codtab}: {moeda(a.anterior.vlrvenda)} → {moeda(p.vlrvenda)}{variacao}"
    )


def montar(alteracoes: list[Alteracao], max_itens: int) -> str:
    ordenadas = sorted(alteracoes, key=lambda a: (a.atual.codtab, a.atual.descrprod))
    alterados = sum(1 for a in alteracoes if a.anterior)
    novos = len(alteracoes) - alterados

    resumo = []
    if alterados:
        resumo.append(f"{alterados} alterado(s)")
    if novos:
        resumo.append(f"{novos} novo(s)")

    linhas = [
        "*📢 Atualização de preços de venda*",
        f"{datetime.now():%d/%m/%Y %H:%M} · {', '.join(resumo)}",
        "",
    ]
    linhas += [_linha(a) for a in ordenadas[:max_itens]]
    if len(ordenadas) > max_itens:
        linhas += ["", f"…e mais {len(ordenadas) - max_itens} item(ns). Detalhes no log."]
    return "\n".join(linhas)
