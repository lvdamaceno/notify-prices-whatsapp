"""Envio de mensagens para grupo pela WhatsApp Cloud API oficial (Meta).

Requer número na Cloud API com acesso à Groups API (Official Business Account).
"""

import logging

import requests

from .config import Config

log = logging.getLogger(__name__)

LIMITE_TEXTO = 4096
TIMEOUT = 30


class WhatsAppErro(RuntimeError):
    pass


def _url(config: Config, caminho: str) -> str:
    return f"https://graph.facebook.com/{config.whatsapp_api_version}/{caminho}"


def _headers(config: Config) -> dict:
    return {"Authorization": f"Bearer {config.whatsapp_token}"}


def dividir(texto: str, limite: int = LIMITE_TEXTO) -> list[str]:
    """Quebra o texto em partes de até `limite` caracteres, sem cortar linhas."""
    partes, atual = [], ""
    for linha in texto.splitlines(keepends=True):
        if len(atual) + len(linha) > limite and atual:
            partes.append(atual)
            atual = ""
        atual += linha[:limite]
    if atual:
        partes.append(atual)
    return partes


def enviar_grupo(config: Config, texto: str) -> None:
    if not config.whatsapp_group_id:
        raise WhatsAppErro("WHATSAPP_GROUP_ID não definido (use --listar-grupos para descobrir)")

    for parte in dividir(texto):
        resp = requests.post(
            _url(config, f"{config.whatsapp_phone_number_id}/messages"),
            headers=_headers(config),
            json={
                "messaging_product": "whatsapp",
                "recipient_type": "group",
                "to": config.whatsapp_group_id,
                "type": "text",
                "text": {"body": parte},
            },
            timeout=TIMEOUT,
        )
        if resp.status_code != 200:
            raise WhatsAppErro(f"Falha ao enviar mensagem ({resp.status_code}): {resp.text[:500]}")
        log.info("Mensagem enviada ao grupo (id %s)", resp.json().get("messages", [{}])[0].get("id"))


def listar_grupos(config: Config) -> list[dict]:
    grupos, params = [], {"limit": 1024}
    while True:
        resp = requests.get(
            _url(config, f"{config.whatsapp_phone_number_id}/groups"),
            headers=_headers(config),
            params=params,
            timeout=TIMEOUT,
        )
        if resp.status_code != 200:
            raise WhatsAppErro(f"Falha ao listar grupos ({resp.status_code}): {resp.text[:500]}")
        dados = resp.json()
        grupos.extend(dados.get("data", {}).get("groups", []))
        depois = dados.get("paging", {}).get("cursors", {}).get("after")
        if not depois or not dados.get("paging", {}).get("next"):
            return grupos
        params["after"] = depois
