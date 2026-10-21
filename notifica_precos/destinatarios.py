"""Lista de quem recebe o e-mail de preços, guardada no banco e controlada por comandos no Telegram.

Na primeira vez a lista vem de EMAIL_DESTINATARIOS; depois disso vale só a do banco.
Só mensagens do TELEGRAM_CHAT_ID são aceitas; qualquer outro chat é ignorado.
"""

import logging
import re
from html import escape

from . import telegram
from .banco import Banco
from .config import Config

log = logging.getLogger(__name__)

CHAVE_LISTA = "email_destinatarios"
CHAVE_OFFSET = "telegram_offset"
# /adicionar ou /remover enviado sem e-mail: a próxima mensagem do chat é o e-mail.
CHAVE_PENDENTE = "telegram_comando_pendente"

EMAIL_VALIDO = re.compile(r"^[^@\s,;<>]+@[^@\s,;<>]+\.[^@\s,;<>]+$")

AJUDA = "\n".join([
    "<b>Destinatários do e-mail de preços</b>",
    "/emails — mostra a lista",
    "/adicionar joao maria@empresa.com — inclui (só o usuário usa o domínio padrão)",
    "Sem o e-mail, o bot pergunta e a próxima mensagem é a resposta.",
    "/remover joao — tira da lista",
    "As mudanças valem a partir do próximo ciclo (até 10 min).",
])


def lista(banco: Banco, config: Config) -> list[str]:
    salva = banco.obter_estado(CHAVE_LISTA)
    if salva is None:
        return list(config.email_destinatarios)
    return [e for e in salva.split(",") if e]


def _gravar(banco: Banco, emails: list[str]) -> None:
    banco.definir_estado(CHAVE_LISTA, ",".join(emails))


def _normalizar(item: str, dominio: str) -> str | None:
    item = item.strip().lower()
    if "@" not in item and dominio:
        item = f"{item}@{dominio}"
    return item if EMAIL_VALIDO.match(item) else None


def _mostrar(emails: list[str]) -> str:
    if not emails:
        return "Nenhum destinatário: o e-mail de preços não está sendo enviado."
    return f"<b>{len(emails)} destinatário(s):</b>\n" + "\n".join(f"• {escape(e)}" for e in emails)


def _executar(banco: Banco, config: Config, texto: str) -> str:
    partes = texto.replace(",", " ").replace(";", " ").split()
    # Em grupos o comando chega como /emails@NomeDoBot.
    comando = partes[0].split("@")[0].lower() if partes else ""
    argumentos = partes[1:]
    emails = lista(banco, config)

    if comando in ("/emails", "/lista"):
        return _mostrar(emails)
    if comando not in ("/adicionar", "/remover"):
        return AJUDA
    validos = [(a, _normalizar(a, config.email_dominio)) for a in argumentos]
    invalidos = [a for a, e in validos if e is None]
    alvos = [e for _, e in validos if e]
    if comando == "/adicionar":
        mudou = [e for e in dict.fromkeys(alvos) if e not in emails]
        emails += mudou
        acao = "Incluído(s)"
    else:
        mudou = [e for e in dict.fromkeys(alvos) if e in emails]
        emails = [e for e in emails if e not in mudou]
        acao = "Removido(s)"
    if mudou:
        _gravar(banco, emails)
        log.info("Destinatários via Telegram: %s %s", acao.lower(), ", ".join(mudou))

    linhas = [f"{acao}: {escape(', '.join(mudou))}" if mudou else "Nada mudou."]
    if invalidos:
        linhas.append(f"E-mail inválido: {escape(', '.join(invalidos))}")
    return "\n".join(linhas + ["", _mostrar(emails)])


def processar_comandos(banco: Banco, config: Config) -> None:
    """Lê os comandos recebidos pelo bot desde o último ciclo e responde no próprio chat."""
    if not config.telegram_configurado:
        return
    offset = int(banco.obter_estado(CHAVE_OFFSET) or 0)
    for update in telegram.mensagens_recebidas(config, offset):
        # Grava antes de responder: um comando com erro não fica sendo reprocessado a cada ciclo.
        banco.definir_estado(CHAVE_OFFSET, str(update["update_id"] + 1))
        msg = update.get("message") or {}
        texto = msg.get("text", "")
        if str(msg.get("chat", {}).get("id")) != config.telegram_chat_id:
            log.warning("Comando do Telegram ignorado: chat %s não autorizado", msg.get("chat", {}).get("id"))
            continue
        partes = texto.split()
        comando = partes[0].split("@")[0].lower() if partes else ""
        if comando in ("/adicionar", "/remover") and len(partes) == 1:
            banco.definir_estado(CHAVE_PENDENTE, comando)
            pergunta = "adicionar" if comando == "/adicionar" else "remover"
            telegram.enviar(config, f"Qual e-mail {pergunta}? (pode mandar vários)", pedir_resposta=True)
            continue
        pendente = banco.obter_estado(CHAVE_PENDENTE)
        if pendente:
            banco.definir_estado(CHAVE_PENDENTE, "")
        if not texto.startswith("/"):
            if not pendente:
                continue
            texto = f"{pendente} {texto}"
        telegram.enviar(config, _executar(banco, config, texto))
