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


def milhar(n: int) -> str:
    return f"{n:,}".replace(",", ".")


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


def texto(alteracoes: list[Alteracao], max_itens: int, origem: str = "") -> str:
    """Versão em texto simples, para clientes de e-mail que não exibem HTML."""
    linhas = [f"Atualização de preços de venda - {datetime.now():%d/%m/%Y %H:%M} - {_resumo(alteracoes)}"]
    if origem:
        linhas.append(f"Detectado em: {origem}")
    linhas.append("")
    for a in _ordenar(alteracoes)[:max_itens]:
        anterior = moeda(a.anterior.vlrvenda) if a.anterior else "novo"
        linhas.append(
            f"Tab {a.atual.codtab} | {a.atual.codprod} - {_produto(a)} | "
            f"{anterior} -> {moeda(a.atual.vlrvenda)} {percentual(a)}".rstrip()
        )
    if len(alteracoes) > max_itens:
        linhas += ["", f"...e mais {len(alteracoes) - max_itens} item(ns). Lista completa no CSV anexo."]
    return "\n".join(linhas)


def html(alteracoes: list[Alteracao], max_itens: int, origem: str = "") -> str:
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
<p style="margin:0 0 16px;color:#555">{datetime.now():%d/%m/%Y %H:%M} · {_resumo(alteracoes)}{' · ' + escape(origem) if origem else ''}</p>
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


def deploy(config, precos: int | None, alteracoes: int | None, erro: BaseException | None,
           segundos: float) -> tuple[str, str, str]:
    """Aviso de deploy para a equipe de TI: (assunto, texto, html)."""
    commit = config.render_git_commit[:7]
    status = "falha na primeira execução" if erro else "sucesso"
    link = (f"https://github.com/{config.render_repo_slug}/commit/{config.render_git_commit}"
            if config.render_repo_slug else "")

    if erro:
        resultado = f"A primeira execução falhou: {type(erro).__name__}: {erro}"
    else:
        resultado = (f"Carga completa concluída em {f'{segundos:.1f}'.replace('.', ',')}s: "
                     f"{milhar(precos)} preços vigentes, {milhar(alteracoes)} alteração(ões).")
        if alteracoes:
            resultado += " As alterações foram enviadas aos destinatários de preços."

    dados = [
        ("Data", f"{datetime.now():%d/%m/%Y %H:%M}"),
        ("Serviço", config.render_servico or "-"),
        ("Branch", config.render_git_branch or "-"),
        ("Commit", commit),
        ("Tabelas monitoradas", ", ".join(map(str, config.sankhya_codtabs)) or "todas"),
        ("Destinatários de preços", ", ".join(config.email_destinatarios) or "nenhum (só log)"),
        ("Reconciliação completa", f"a cada {config.carga_completa_horas}h" if config.carga_completa_horas else "só em deploy"),
        ("Telegram", "ativo" if config.telegram_configurado else "não configurado"),
    ]

    assunto = f"Deploy do monitor de preços: {commit} ({status})"
    texto = "\n".join(
        [f"Novo deploy do monitor de preços do Sankhya ({status}).", "", resultado, ""]
        + [f"{k}: {v}" for k, v in dados]
        + ([f"Mudanças: {link}"] if link else [])
    )
    cor = COR_ALTA if erro else COR_QUEDA
    commit_html = f'<a href="{escape(link)}">{commit}</a>' if link else commit
    linhas = "".join(
        f'<tr><td style="padding:4px 12px 4px 0;color:#555">{k}</td>'
        f"<td>{commit_html if k == 'Commit' else escape(str(v))}</td></tr>"
        for k, v in dados
    )
    html = f"""<!doctype html>
<html><body style="font-family:Arial,Helvetica,sans-serif;font-size:14px;color:#222">
<h2 style="margin:0 0 4px">Deploy do monitor de preços</h2>
<p style="margin:0 0 16px"><strong style="color:{cor}">{escape(status.capitalize())}</strong> · {escape(resultado)}</p>
<table style="border-collapse:collapse">{linhas}</table>
<p style="margin-top:24px;color:#888;font-size:12px">Enviado automaticamente pelo monitor de preços do Sankhya.</p>
</body></html>"""
    return assunto, texto, html
