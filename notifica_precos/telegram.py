"""Avisos de execução no Telegram (sucesso relevante, erro e recuperação).

Falhas no Telegram só são logadas: o aviso é secundário e não pode interromper o monitor.
"""

import logging
from html import escape

import requests

from .config import Config

log = logging.getLogger(__name__)

TIMEOUT = 15
LIMITE_TEXTO = 4096


def enviar(config: Config, texto: str, pedir_resposta: bool = False) -> bool:
    """`pedir_resposta` abre o campo de resposta no Telegram (ForceReply), para quando o bot faz uma pergunta."""
    if not config.telegram_configurado:
        return False
    corpo = {
        "chat_id": config.telegram_chat_id,
        "text": texto[:LIMITE_TEXTO],
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    if pedir_resposta:
        corpo["reply_markup"] = {"force_reply": True, "input_field_placeholder": "joao ou ana@fornecedor.com.br"}
    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{config.telegram_bot_token}/sendMessage",
            json=corpo,
            timeout=TIMEOUT,
        )
        if resp.status_code != 200:
            log.error("Falha ao avisar no Telegram (%s): %s", resp.status_code, resp.text[:300])
            return False
        return True
    except requests.RequestException as erro:
        log.error("Falha ao avisar no Telegram: %s", erro)
        return False


def mensagens_recebidas(config: Config, offset: int) -> list[dict]:
    """Mensagens novas enviadas ao bot (getUpdates). Sem webhook: o próprio cron busca a cada ciclo."""
    resp = requests.get(
        f"https://api.telegram.org/bot{config.telegram_bot_token}/getUpdates",
        params={"offset": offset, "timeout": 0, "allowed_updates": '["message"]'},
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json().get("result", [])


def titulo(icone: str, texto: str) -> str:
    return f"{icone} <b>Monitor de preços</b> · {escape(texto)}"


def bloco_erro(erro: BaseException) -> str:
    return f"<code>{escape(type(erro).__name__)}: {escape(str(erro))[:1500]}</code>"
