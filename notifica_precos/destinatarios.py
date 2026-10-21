"""Lista de quem recebe o e-mail de preços, guardada no banco e controlada por comandos no Telegram.

Na primeira vez a lista vem de EMAIL_DESTINATARIOS; depois disso vale só a do banco.
Só a conversa direta (privada) com o bot, no TELEGRAM_CHAT_ID, é aceita; grupos e outros chats são ignorados.
"""

import logging
import re
from html import escape

from . import telegram
from .banco import Banco
from .config import Config

log = logging.getLogger(__name__)

LISTAR = "/listar_destinatarios_preco"
ADICIONAR = "/adicionar_destinatario_preco"
REMOVER = "/remover_destinatario_preco"
# Menu do bot (setMyCommands), registrado a cada deploy para ficar igual ao código.
MENU = [
    (LISTAR, "Mostra destinatários da atualização de preços"),
    (ADICIONAR, "Inclui destinatários para atualização de preços"),
    (REMOVER, "Remove destinatários da atualização de preços"),
]

CHAVE_LISTA = "email_destinatarios"
CHAVE_OFFSET = "telegram_offset"
# ADICIONAR ou REMOVER enviado sem e-mail: a próxima mensagem do chat é o e-mail.
CHAVE_PENDENTE = "telegram_comando_pendente"

EMAIL_VALIDO = re.compile(r"^[^@\s,;<>]+@[^@\s,;<>]+\.[^@\s,;<>]+$")

AJUDA = "\n".join([
    "<b>Destinatários do e-mail de preços</b>",
    f"{LISTAR} — mostra a lista",
    f"{ADICIONAR} joao maria@empresa.com — inclui (só o usuário usa o domínio padrão)",
    f"{REMOVER} joao — tira da lista",
    "Sem o e-mail, o bot pergunta e a próxima mensagem é a resposta.",
    "As mudanças valem a partir do próximo ciclo (até 1 min).",
])


def lista(banco: Banco, config: Config) -> list[str]:
    salva = banco.obter_estado(CHAVE_LISTA)
    if salva is None:
        # Primeira execução: grava a lista de EMAIL_DESTINATARIOS, que daí em diante pode ser removida.
        _gravar(banco, list(config.email_destinatarios))
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
    # Em grupos o comando chega como /comando@NomeDoBot.
    comando = partes[0].split("@")[0].lower() if partes else ""
    argumentos = partes[1:]
    emails = lista(banco, config)

    if comando == LISTAR:
        return _mostrar(emails)
    if comando not in (ADICIONAR, REMOVER):
        return AJUDA
    validos = [(a, _normalizar(a, config.email_dominio)) for a in argumentos]
    invalidos = [a for a, e in validos if e is None]
    alvos = [e for _, e in validos if e]
    if comando == ADICIONAR:
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
        chat = msg.get("chat", {})
        if chat.get("type") != "private" or str(chat.get("id")) != config.telegram_chat_id:
            log.warning("Comando do Telegram ignorado: chat %s (%s) não autorizado", chat.get("id"), chat.get("type"))
            continue
        partes = texto.split()
        comando = partes[0].split("@")[0].lower() if partes else ""
        if comando in (ADICIONAR, REMOVER) and len(partes) == 1:
            banco.definir_estado(CHAVE_PENDENTE, comando)
            pergunta = "adicionar" if comando == ADICIONAR else "remover"
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


def registrar_menu(config: Config) -> None:
    if config.telegram_configurado:
        telegram.definir_comandos(config, [(c.lstrip("/"), d) for c, d in MENU])
