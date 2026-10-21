"""Envio de e-mail pelo SMTP da empresa (Google Workspace, Microsoft 365 etc.)."""

import logging
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formatdate, make_msgid

from .config import Config

log = logging.getLogger(__name__)

TIMEOUT = 30


class EmailErro(RuntimeError):
    pass


def enviar(
    config: Config,
    assunto: str,
    texto: str,
    html: str | None = None,
    anexos: list[tuple[str, bytes, str]] = (),  # (nome do arquivo, conteúdo, tipo MIME)
    destinatarios: list[str] | None = None,  # padrão: EMAIL_DESTINATARIOS
) -> None:
    destinatarios = destinatarios if destinatarios is not None else config.email_destinatarios
    if not config.smtp_host or not destinatarios:
        raise EmailErro("SMTP não configurado ou sem destinatários (SMTP_HOST, EMAIL_DESTINATARIOS/EMAIL_DEPLOY)")

    msg = EmailMessage()
    msg["Subject"] = assunto
    msg["From"] = config.email_remetente
    msg["To"] = ", ".join(destinatarios)
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain=config.email_remetente.rsplit("@", 1)[-1].strip("> "))
    msg.set_content(texto)
    if html:
        msg.add_alternative(html, subtype="html")
    for nome, conteudo, tipo in anexos:
        principal, sub = tipo.split("/", 1)
        # Anexos de texto (CSV) são gerados em UTF-8; sem declarar, leitores podem trocar os acentos.
        params = {"charset": "utf-8"} if principal == "text" else {}
        msg.add_attachment(conteudo, maintype=principal, subtype=sub, filename=nome, params=params)

    contexto = ssl.create_default_context()
    try:
        # Porta 465 usa SSL direto; as demais (587) começam sem criptografia e sobem com STARTTLS.
        if config.smtp_porta == 465:
            smtp = smtplib.SMTP_SSL(config.smtp_host, config.smtp_porta, timeout=TIMEOUT, context=contexto)
        else:
            smtp = smtplib.SMTP(config.smtp_host, config.smtp_porta, timeout=TIMEOUT)
            smtp.starttls(context=contexto)
        with smtp:
            if config.smtp_usuario:
                smtp.login(config.smtp_usuario, config.smtp_senha)
            recusados = smtp.send_message(msg)
    except (smtplib.SMTPException, OSError) as erro:
        raise EmailErro(f"Falha ao enviar e-mail via {config.smtp_host}:{config.smtp_porta}: {erro}") from erro

    if recusados:
        # Pelo menos um destinatário recebeu; os recusados ficam registrados no log.
        log.warning("Destinatários recusados pelo servidor: %s", recusados)
    log.info("E-mail enviado para %d destinatário(s): %s", len(destinatarios), assunto)
