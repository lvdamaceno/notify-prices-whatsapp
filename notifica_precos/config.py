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


def _lista(valor: str) -> list[str]:
    return [v.strip() for v in valor.replace(";", ",").split(",") if v.strip()]


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

    smtp_host: str
    smtp_porta: int
    smtp_usuario: str
    smtp_senha: str
    email_remetente: str
    email_destinatarios: list[str]

    database_url: str

    intervalo_minutos: int
    max_itens_email: int
    log_dias_retencao: int

    @property
    def email_configurado(self) -> bool:
        return bool(self.smtp_host and self.email_destinatarios)


def carregar() -> Config:
    return Config(
        sankhya_base_url=os.getenv("SANKHYA_BASE_URL", "https://api.sankhya.com.br").rstrip("/"),
        sankhya_client_id=_obrigatoria("SANKHYA_CLIENT_ID"),
        sankhya_client_secret=_obrigatoria("SANKHYA_CLIENT_SECRET"),
        sankhya_x_token=_obrigatoria("SANKHYA_X_TOKEN"),
        sankhya_codtabs=_codtabs(os.getenv("SANKHYA_CODTABS", "")),
        smtp_host=os.getenv("SMTP_HOST", "").strip(),
        smtp_porta=int(os.getenv("SMTP_PORTA", "587")),
        smtp_usuario=os.getenv("SMTP_USUARIO", "").strip(),
        smtp_senha=os.getenv("SMTP_SENHA", "").strip(),
        # Sem EMAIL_REMETENTE, envia em nome da própria conta SMTP.
        email_remetente=(os.getenv("EMAIL_REMETENTE", "").strip() or os.getenv("SMTP_USUARIO", "").strip()),
        email_destinatarios=_lista(os.getenv("EMAIL_DESTINATARIOS", "")),
        database_url=os.getenv("DATABASE_URL", "").strip(),
        intervalo_minutos=int(os.getenv("INTERVALO_MINUTOS", "5")),
        max_itens_email=int(os.getenv("MAX_ITENS_EMAIL", "500")),
        log_dias_retencao=int(os.getenv("LOG_DIAS_RETENCAO", "90")),
    )
