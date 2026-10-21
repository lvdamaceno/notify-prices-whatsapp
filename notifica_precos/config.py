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


def _destinatarios(valor: str, dominio: str) -> list[str]:
    """Aceita só o usuário (`joao`, completado com o domínio padrão) ou o e-mail inteiro (`ana@fornecedor.com`)."""
    emails = []
    for item in _lista(valor):
        if "@" not in item:
            if not dominio:
                raise RuntimeError(
                    f"Destinatário '{item}' sem domínio: defina EMAIL_DOMINIO ou um SMTP_USUARIO com @"
                )
            item = f"{item}@{dominio}"
        emails.append(item)
    return emails


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
    sankhya_timeout: int

    smtp_host: str
    smtp_porta: int
    smtp_usuario: str
    smtp_senha: str
    email_remetente: str
    email_destinatarios: list[str]
    email_deploy: list[str]

    telegram_bot_token: str
    telegram_chat_id: str

    database_url: str
    render_git_commit: str
    render_git_branch: str
    render_repo_slug: str
    render_servico: str

    intervalo_minutos: int
    max_itens_email: int
    carga_completa_horas: int
    copia_completa_min_itens: int
    carga_lote_produtos: int
    log_dias_retencao: int

    @property
    def email_configurado(self) -> bool:
        return bool(self.smtp_host and self.email_destinatarios)

    @property
    def telegram_configurado(self) -> bool:
        return bool(self.telegram_bot_token and self.telegram_chat_id)


def carregar() -> Config:
    smtp_usuario = os.getenv("SMTP_USUARIO", "").strip()
    # Domínio dos destinatários informados sem @; por padrão, o mesmo da conta que envia.
    dominio = os.getenv("EMAIL_DOMINIO", "").strip().lstrip("@") or smtp_usuario.rpartition("@")[2]
    return Config(
        sankhya_base_url=os.getenv("SANKHYA_BASE_URL", "https://api.sankhya.com.br").rstrip("/"),
        sankhya_client_id=_obrigatoria("SANKHYA_CLIENT_ID"),
        sankhya_client_secret=_obrigatoria("SANKHYA_CLIENT_SECRET"),
        sankhya_x_token=_obrigatoria("SANKHYA_X_TOKEN"),
        sankhya_codtabs=_codtabs(os.getenv("SANKHYA_CODTABS", "")),
        # Segundos de espera por resposta de cada consulta ao Sankhya.
        sankhya_timeout=int(os.getenv("SANKHYA_TIMEOUT", "120")),
        smtp_host=os.getenv("SMTP_HOST", "").strip(),
        smtp_porta=int(os.getenv("SMTP_PORTA", "587")),
        smtp_usuario=smtp_usuario,
        smtp_senha=os.getenv("SMTP_SENHA", "").strip(),
        # Sem EMAIL_REMETENTE, envia em nome da própria conta SMTP.
        email_remetente=os.getenv("EMAIL_REMETENTE", "").strip() or smtp_usuario,
        email_destinatarios=_destinatarios(os.getenv("EMAIL_DESTINATARIOS", ""), dominio),
        # Quem recebe o aviso de cada deploy (ex.: gti).
        email_deploy=_destinatarios(os.getenv("EMAIL_DEPLOY", ""), dominio),
        telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN", "").strip(),
        telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID", "").strip(),
        database_url=os.getenv("DATABASE_URL", "").strip(),
        # Definida pelo Render em cada deploy; quando muda, o script faz uma carga completa.
        render_git_commit=os.getenv("RENDER_GIT_COMMIT", "").strip(),
        render_git_branch=os.getenv("RENDER_GIT_BRANCH", "").strip(),
        render_repo_slug=os.getenv("RENDER_GIT_REPO_SLUG", "").strip(),
        render_servico=os.getenv("RENDER_SERVICE_NAME", "").strip(),
        intervalo_minutos=int(os.getenv("INTERVALO_MINUTOS", "10")),
        max_itens_email=int(os.getenv("MAX_ITENS_EMAIL", "500")),
        carga_completa_horas=int(os.getenv("CARGA_COMPLETA_HORAS", "24")),
        # Itens mínimos para uma versão contar como cópia completa; 0 = 10% dos produtos ativos.
        copia_completa_min_itens=int(os.getenv("COPIA_COMPLETA_MIN_ITENS", "0")),
        # Produtos por consulta na primeira carga (máximo 1000, limite do IN no Oracle).
        carga_lote_produtos=min(1000, int(os.getenv("CARGA_LOTE_PRODUTOS", "500"))),
        log_dias_retencao=int(os.getenv("LOG_DIAS_RETENCAO", "90")),
    )
