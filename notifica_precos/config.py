"""Configuração lida do .env."""

import os
import time
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

RAIZ = Path(__file__).resolve().parent.parent

load_dotenv(RAIZ / ".env")

# Aplica o fuso de TZ (ex.: America/Belem). No Render o servidor roda em UTC.
if os.getenv("TZ"):
    time.tzset()


def _obrigatoria(nome: str) -> str:
    valor = os.getenv(nome, "").strip()
    if not valor:
        raise RuntimeError(f"Variável {nome} não definida no .env")
    return valor


def _codtabs(valor: str) -> list[int]:
    # Só aceita números, para o valor poder ir direto no SQL sem risco de injeção.
    return [int(v) for v in valor.replace(" ", "").split(",") if v]


@dataclass(frozen=True)
class Config:
    sankhya_base_url: str
    sankhya_client_id: str
    sankhya_client_secret: str
    sankhya_x_token: str
    sankhya_codtabs: list[int]

    whatsapp_token: str
    whatsapp_phone_number_id: str
    whatsapp_group_id: str
    whatsapp_api_version: str

    database_url: str

    intervalo_minutos: int
    max_itens_mensagem: int
    log_dias_retencao: int

    @property
    def whatsapp_configurado(self) -> bool:
        return bool(self.whatsapp_token and self.whatsapp_phone_number_id)


def carregar() -> Config:
    return Config(
        sankhya_base_url=os.getenv("SANKHYA_BASE_URL", "https://api.sankhya.com.br").rstrip("/"),
        sankhya_client_id=_obrigatoria("SANKHYA_CLIENT_ID"),
        sankhya_client_secret=_obrigatoria("SANKHYA_CLIENT_SECRET"),
        sankhya_x_token=_obrigatoria("SANKHYA_X_TOKEN"),
        sankhya_codtabs=_codtabs(os.getenv("SANKHYA_CODTABS", "")),
        whatsapp_token=os.getenv("WHATSAPP_TOKEN", "").strip(),
        whatsapp_phone_number_id=os.getenv("WHATSAPP_PHONE_NUMBER_ID", "").strip(),
        whatsapp_group_id=os.getenv("WHATSAPP_GROUP_ID", "").strip(),
        whatsapp_api_version=os.getenv("WHATSAPP_API_VERSION", "v26.0").strip(),
        database_url=os.getenv("DATABASE_URL", "").strip(),
        intervalo_minutos=int(os.getenv("INTERVALO_MINUTOS", "5")),
        max_itens_mensagem=int(os.getenv("MAX_ITENS_MENSAGEM", "50")),
        log_dias_retencao=int(os.getenv("LOG_DIAS_RETENCAO", "90")),
    )
