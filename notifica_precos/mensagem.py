"""Monta os e-mails de alteração de preços e de promoções: assunto, texto simples, HTML e CSV completo."""

import csv
import io
from datetime import datetime
from html import escape

from . import promocoes as promo
from .promocoes import Evento, Promocao
from .snapshot import Alteracao, Preco

COR_ALTA = "#c62828"
COR_QUEDA = "#2e7d32"
EMAIL_CANCELAMENTO = "gti@casacontente.com.br"
AVISO_CANCELAMENTO = f"Caso você não queira receber esses e-mails, solicite o cancelamento para {EMAIL_CANCELAMENTO}."


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


def _rodape_html() -> str:
    link = f'<a href="mailto:{EMAIL_CANCELAMENTO}" style="color:#888">{EMAIL_CANCELAMENTO}</a>'
    return (
        '<p style="margin-top:24px;color:#888;font-size:12px">Enviado automaticamente pelo monitor de preços do Sankhya.</p>\n'
        f'<p style="margin-top:4px;color:#888;font-size:12px">{escape(AVISO_CANCELAMENTO).replace(EMAIL_CANCELAMENTO, link)}</p>'
    )


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
            f"{a.atual.codprod}{' | ' + a.atual.modelo if a.atual.modelo else ''} | {_produto(a)} | "
            f"{anterior} -> {moeda(a.atual.vlrvenda)} {percentual(a)}".rstrip()
        )
    if len(alteracoes) > max_itens:
        linhas += ["", f"...e mais {len(alteracoes) - max_itens} item(ns). Lista completa no CSV anexo."]
    linhas += ["", AVISO_CANCELAMENTO]
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
            f"<tr><td {numero}>{a.atual.codprod}</td><td {celula}>{escape(a.atual.modelo)}</td>"
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
            ("Código", "right"), ("Modelo", "left"), ("Produto", "left"),
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
{_rodape_html()}
</body></html>"""


def exemplo() -> list[Alteracao]:
    """Alterações fictícias para o --testar-email: alta, queda, produto novo e item com local."""
    def preco(codprod, modelo, descr, valor, nutab=1001, codlocal=0, controle=" "):
        return Preco(0, codprod, codlocal, controle, nutab, "2026-01-01T00:00:00", descr, modelo, valor)

    return [
        Alteracao(preco(90001, "SF-3L-TESTE", "SOFÁ 3 LUGARES (EXEMPLO)", 2699.0, 1002),
                  preco(90001, "SF-3L-TESTE", "SOFÁ 3 LUGARES (EXEMPLO)", 2499.0)),
        Alteracao(preco(90002, "MC-120-TESTE", "MESA DE CENTRO (EXEMPLO)", 849.9, 1002),
                  preco(90002, "MC-120-TESTE", "MESA DE CENTRO (EXEMPLO)", 899.9)),
        Alteracao(preco(90003, "PT-AZ-TESTE", "POLTRONA AZUL (EXEMPLO)", 1299.0, 1002, 2, "LOTE A"),
                  preco(90003, "PT-AZ-TESTE", "POLTRONA AZUL (EXEMPLO)", 1199.0, 1001, 2, "LOTE A")),
        Alteracao(preco(90004, "CD-01-TESTE", "CADEIRA DE JANTAR (EXEMPLO)", 459.0, 1002), None),
    ]


def csv_completo(alteracoes: list[Alteracao]) -> bytes:
    """Todas as alterações, com as mesmas colunas da tabela do corpo do e-mail.

    Separado por ';' e com BOM para abrir direto no Excel em português.
    """
    def numero(valor: float) -> str:
        return f"{valor:.2f}".replace(".", ",")

    saida = io.StringIO()
    escritor = csv.writer(saida, delimiter=";")
    escritor.writerow(["Código", "Modelo", "Produto", "Preço anterior", "Preço novo", "Variação (%)"])
    for a in _ordenar(alteracoes):
        pct = a.variacao_pct
        escritor.writerow([
            a.atual.codprod, a.atual.modelo, _produto(a),
            numero(a.anterior.vlrvenda) if a.anterior else "novo",
            numero(a.atual.vlrvenda),
            numero(pct) if pct is not None else "",
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
        ("Reconciliação completa", f"todo dia às {config.carga_completa_hora}h"
         if config.carga_completa_hora is not None else "só em deploy"),
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


# --- Promoções ---------------------------------------------------------------------------------

SITUACAO = {promo.INICIO: "Entrou em promoção", promo.ALTERADA: "Desconto alterado", promo.FIM: "Promoção encerrada"}
ORDEM_SITUACAO = {promo.INICIO: 0, promo.ALTERADA: 1, promo.FIM: 2}


def _data(iso: str) -> str:
    return f"{iso[8:10]}/{iso[5:7]}/{iso[:4]}" if iso else ""


def _desconto(p: Promocao) -> str:
    if p.vlrfixo > 0:
        return "preço fixo"
    if p.percentual > 0:
        return f"{p.percentual:g}%".replace(".", ",")
    return moeda(p.vlrdesc)


def _produto_promo(p: Promocao) -> str:
    descr = p.descrprod
    if p.codlocal or p.controle.strip():
        descr += f" (local {p.codlocal}{', ' + p.controle.strip() if p.controle.strip() else ''})"
    return descr


def _periodo(e: Evento) -> str:
    p = e.promo
    if e.tipo == promo.FIM:
        # Antes do último dia, a promoção foi apagada, desativada ou o produto saiu do grupo no Sankhya.
        if p.dtfinal and p.dtfinal[:10] < datetime.now().date().isoformat():
            return f"venceu em {_data(p.dtfinal)}"
        return "encerrada no Sankhya"
    fim = f"até {_data(p.dtfinal)}" if p.dtfinal else "sem data final"
    return f"{fim}{f' · só no local {p.local_promo}' if p.local_promo else ''}"


def _ordenar_eventos(eventos: list[Evento]) -> list[Evento]:
    return sorted(eventos, key=lambda e: (ORDEM_SITUACAO[e.tipo], e.promo.descrprod, e.promo.codprod))


def _resumo_promocoes(eventos: list[Evento]) -> str:
    nomes = {promo.INICIO: "iniciada(s)", promo.ALTERADA: "alterada(s)", promo.FIM: "encerrada(s)"}
    return ", ".join(f"{n} {nomes[t]}" for t in nomes if (n := sum(1 for e in eventos if e.tipo == t)))


def assunto_promocoes(eventos: list[Evento]) -> str:
    return f"Promoções de preço: {_resumo_promocoes(eventos)} ({datetime.now():%d/%m/%Y %H:%M})"


def texto_promocoes(eventos: list[Evento], max_itens: int) -> str:
    linhas = [f"Promoções de preço - {datetime.now():%d/%m/%Y %H:%M} - {_resumo_promocoes(eventos)}", ""]
    for e in _ordenar_eventos(eventos)[:max_itens]:
        p = e.promo
        if e.tipo == promo.FIM:
            valores = f"preço de venda volta a {moeda(e.preco_atual)} (com desconto era {moeda(p.preco_promo)})"
        else:
            valores = f"{moeda(e.preco_atual)} -> {moeda(p.preco_promo)} ({_desconto(p)} de desconto)"
        linhas.append(
            f"{SITUACAO[e.tipo]} | {p.codprod}{' | ' + p.modelo if p.modelo else ''} | {_produto_promo(p)} | "
            f"{valores} | {_periodo(e)}"
        )
    if len(eventos) > max_itens:
        linhas += ["", f"...e mais {len(eventos) - max_itens} item(ns). Lista completa no CSV anexo."]
    linhas += ["", AVISO_CANCELAMENTO]
    return "\n".join(linhas)


def html_promocoes(eventos: list[Evento], max_itens: int) -> str:
    celula = 'style="padding:6px 10px;border-bottom:1px solid #e0e0e0"'
    numero = 'style="padding:6px 10px;border-bottom:1px solid #e0e0e0;text-align:right;white-space:nowrap"'
    cores = {promo.INICIO: COR_QUEDA, promo.ALTERADA: "#ef6c00", promo.FIM: "#555"}

    linhas = []
    for e in _ordenar_eventos(eventos)[:max_itens]:
        p = e.promo
        if e.tipo == promo.FIM:
            sem = f"<strong>{moeda(e.preco_atual)}</strong>"
            com = f"<s>{moeda(p.preco_promo)}</s>"
        else:
            sem = moeda(e.preco_atual)
            com = f"<strong>{moeda(p.preco_promo)}</strong>"
            if e.anterior:
                com += f'<br><span style="color:#888;font-size:12px">antes {moeda(e.anterior.preco_promo)}</span>'
        linhas.append(
            f'<tr><td {celula}><span style="color:{cores[e.tipo]}">{SITUACAO[e.tipo]}</span></td>'
            f"<td {numero}>{p.codprod}</td><td {celula}>{escape(p.modelo)}</td>"
            f"<td {celula}>{escape(_produto_promo(p))}</td><td {numero}>{sem}</td><td {numero}>{com}</td>"
            f"<td {numero}>{_desconto(p)}</td><td {celula}>{escape(_periodo(e))}</td></tr>"
        )

    restante = ""
    if len(eventos) > max_itens:
        restante = (
            f'<p style="color:#555">…e mais {len(eventos) - max_itens} item(ns). '
            "A lista completa está no CSV anexo.</p>"
        )
    cabecalho = "".join(
        f'<th style="padding:6px 10px;text-align:{alinhamento};border-bottom:2px solid #333">{titulo}</th>'
        for titulo, alinhamento in [
            ("Situação", "left"), ("Código", "right"), ("Modelo", "left"), ("Produto", "left"),
            ("Preço sem desconto", "right"), ("Preço com desconto", "right"), ("Desconto", "right"),
            ("Período", "left"),
        ]
    )
    return f"""<!doctype html>
<html><body style="font-family:Arial,Helvetica,sans-serif;font-size:14px;color:#222">
<h2 style="margin:0 0 4px">Promoções de preço</h2>
<p style="margin:0 0 16px;color:#555">{datetime.now():%d/%m/%Y %H:%M} · {_resumo_promocoes(eventos)}</p>
<table style="border-collapse:collapse">
<thead><tr>{cabecalho}</tr></thead>
<tbody>{''.join(linhas)}</tbody>
</table>
{restante}
{_rodape_html()}
</body></html>"""


def csv_promocoes(eventos: list[Evento]) -> bytes:
    """Todos os avisos de promoção, com as mesmas colunas da tabela do e-mail."""
    def numero(valor: float) -> str:
        return f"{valor:.2f}".replace(".", ",")

    saida = io.StringIO()
    escritor = csv.writer(saida, delimiter=";")
    escritor.writerow(["Situação", "Código", "Modelo", "Produto", "Preço sem desconto", "Preço com desconto",
                       "Desconto", "Período", "Promoção (NUPROMOCAO)", "Descrição da promoção"])
    for e in _ordenar_eventos(eventos):
        p = e.promo
        escritor.writerow([
            SITUACAO[e.tipo], p.codprod, p.modelo, _produto_promo(p), numero(e.preco_atual),
            numero(p.preco_promo), _desconto(p), _periodo(e), p.nupromocao, p.descricao,
        ])
    return saida.getvalue().encode("utf-8-sig")


def exemplo_promocoes() -> list[Evento]:
    """Avisos fictícios para o --testar-email: início, desconto alterado e fim."""
    def p(codprod, modelo, descr, base, final, pct=0.0, vlrdesc=0.0, fim="2026-12-31T00:00:00", local=0):
        return Promocao(0, codprod, 0, " ", local, 9000 + codprod % 100, "PROMOÇÃO DE TESTE", pct, vlrdesc, 0.0,
                        "2026-10-01T00:00:00", fim, base, final, descr, modelo)

    return [
        Evento(promo.INICIO, p(90001, "SF-3L-TESTE", "SOFÁ 3 LUGARES (EXEMPLO)", 2699.0, 2159.2, pct=20), preco_atual=2699.0),
        Evento(promo.INICIO, p(90005, "RK-TESTE", "RACK (EXEMPLO)", 1299.0, 1199.0, vlrdesc=100, local=102), preco_atual=1299.0),
        Evento(promo.ALTERADA, p(90002, "MC-120-TESTE", "MESA DE CENTRO (EXEMPLO)", 899.9, 629.93, pct=30),
               p(90002, "MC-120-TESTE", "MESA DE CENTRO (EXEMPLO)", 899.9, 809.91, pct=10), preco_atual=899.9),
        Evento(promo.FIM, p(90004, "CD-01-TESTE", "CADEIRA DE JANTAR (EXEMPLO)", 459.0, 413.1, pct=10,
                            fim="2026-10-20T00:00:00"), preco_atual=459.0),
    ]
