"""Monta o e-mail de alteração de preços: assunto, texto simples, HTML e CSV completo."""

import csv
import io
from datetime import datetime
from html import escape

from .snapshot import Alteracao

COR_ALTA = "#c62828"
COR_QUEDA = "#2e7d32"


def moeda(valor: float) -> str:
    return "R$ " + f"{valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def percentual(a: Alteracao) -> str:
    pct = a.variacao_pct
    return f"{pct:+.2f}%".replace(".", ",") if pct is not None else ""


def _produto(a: Alteracao) -> str:
    p = a.atual
    descr = p.descrprod
    if p.codlocal or p.controle.strip():
        descr += f" (local {p.codlocal}{', ' + p.controle.strip() if p.controle.strip() else ''})"
    return descr


def _ordenar(alteracoes: list[Alteracao]) -> list[Alteracao]:
    return sorted(alteracoes, key=lambda a: (a.atual.codtab, a.atual.descrprod))


def _resumo(alteracoes: list[Alteracao]) -> str:
    alterados = sum(1 for a in alteracoes if a.anterior)
    novos = len(alteracoes) - alterados
    partes = []
    if alterados:
        partes.append(f"{alterados} alterado(s)")
    if novos:
        partes.append(f"{novos} novo(s)")
    return ", ".join(partes)


def assunto(alteracoes: list[Alteracao]) -> str:
    return f"Atualização de preços de venda: {_resumo(alteracoes)} ({datetime.now():%d/%m/%Y %H:%M})"


def texto(alteracoes: list[Alteracao], max_itens: int) -> str:
    """Versão em texto simples, para clientes de e-mail que não exibem HTML."""
    linhas = [f"Atualização de preços de venda - {datetime.now():%d/%m/%Y %H:%M} - {_resumo(alteracoes)}", ""]
    for a in _ordenar(alteracoes)[:max_itens]:
        anterior = moeda(a.anterior.vlrvenda) if a.anterior else "novo"
        linhas.append(
            f"Tab {a.atual.codtab} | {a.atual.codprod} - {_produto(a)} | "
            f"{anterior} -> {moeda(a.atual.vlrvenda)} {percentual(a)}".rstrip()
        )
    if len(alteracoes) > max_itens:
        linhas += ["", f"...e mais {len(alteracoes) - max_itens} item(ns). Lista completa no CSV anexo."]
    return "\n".join(linhas)


def html(alteracoes: list[Alteracao], max_itens: int) -> str:
    celula = 'style="padding:6px 10px;border-bottom:1px solid #e0e0e0"'
    numero = 'style="padding:6px 10px;border-bottom:1px solid #e0e0e0;text-align:right;white-space:nowrap"'

    linhas = []
    for a in _ordenar(alteracoes)[:max_itens]:
        if a.anterior is None:
            cor, anterior = "#555", "<em>novo</em>"
        else:
            cor = COR_ALTA if a.atual.vlrvenda > a.anterior.vlrvenda else COR_QUEDA
            anterior = moeda(a.anterior.vlrvenda)
        linhas.append(
            f"<tr><td {numero}>{a.atual.codtab}</td><td {numero}>{a.atual.codprod}</td>"
            f"<td {celula}>{escape(_produto(a))}</td><td {numero}>{anterior}</td>"
            f"<td {numero}><strong>{moeda(a.atual.vlrvenda)}</strong></td>"
            f'<td {numero}><span style="color:{cor}">{percentual(a)}</span></td></tr>'
        )

    restante = ""
    if len(alteracoes) > max_itens:
        restante = (
            f'<p style="color:#555">…e mais {len(alteracoes) - max_itens} item(ns). '
            "A lista completa está no CSV anexo.</p>"
        )

    cabecalho = "".join(
        f'<th style="padding:6px 10px;text-align:{alinhamento};border-bottom:2px solid #333">{titulo}</th>'
        for titulo, alinhamento in [
            ("Tabela", "right"), ("Código", "right"), ("Produto", "left"),
            ("Preço anterior", "right"), ("Preço novo", "right"), ("Variação", "right"),
        ]
    )
    return f"""<!doctype html>
<html><body style="font-family:Arial,Helvetica,sans-serif;font-size:14px;color:#222">
<h2 style="margin:0 0 4px">Atualização de preços de venda</h2>
<p style="margin:0 0 16px;color:#555">{datetime.now():%d/%m/%Y %H:%M} · {_resumo(alteracoes)}</p>
<table style="border-collapse:collapse">
<thead><tr>{cabecalho}</tr></thead>
<tbody>{''.join(linhas)}</tbody>
</table>
{restante}
<p style="margin-top:24px;color:#888;font-size:12px">Enviado automaticamente pelo monitor de preços do Sankhya.</p>
</body></html>"""


def csv_completo(alteracoes: list[Alteracao]) -> bytes:
    """Todas as alterações, separadas por ';' e com BOM para abrir direto no Excel em português."""
    saida = io.StringIO()
    escritor = csv.writer(saida, delimiter=";")
    escritor.writerow(["CODTAB", "CODPROD", "PRODUTO", "CODLOCAL", "CONTROLE", "NUTAB",
                       "PRECO_ANTERIOR", "PRECO_NOVO", "VARIACAO_PCT"])
    for a in _ordenar(alteracoes):
        anterior = f"{a.anterior.vlrvenda:.2f}".replace(".", ",") if a.anterior else ""
        pct = a.variacao_pct
        escritor.writerow([
            a.atual.codtab, a.atual.codprod, a.atual.descrprod, a.atual.codlocal, a.atual.controle.strip(),
            a.atual.nutab, anterior, f"{a.atual.vlrvenda:.2f}".replace(".", ","),
            f"{pct:.2f}".replace(".", ",") if pct is not None else "",
        ])
    return saida.getvalue().encode("utf-8-sig")
