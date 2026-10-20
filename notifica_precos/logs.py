"""Logs no console (capturado pelo Render) e na tabela `logs` do banco.

O Render guarda os logs do painel por poucos dias (7 no plano Hobby) e o disco
dos serviços é apagado a cada deploy, por isso o histórico fica no banco.
"""

import logging
import sys
from datetime import datetime, timedelta

from .banco import Banco


class BancoHandler(logging.Handler):
    def __init__(self, banco: Banco):
        super().__init__(level=logging.INFO)
        self.banco = banco

    def emit(self, record: logging.LogRecord) -> None:
        try:
            mensagem = record.getMessage()
            if record.exc_info:
                mensagem += "\n" + logging.Formatter().formatException(record.exc_info)
            self.banco.execute(
                "INSERT INTO logs (criado_em, nivel, origem, mensagem) VALUES (?, ?, ?, ?)",
                (datetime.fromtimestamp(record.created).astimezone(), record.levelname, record.name, mensagem),
            )
        except Exception as erro:
            # Banco indisponível não pode derrubar o script; o log segue no console.
            print(f"[logs] falha ao gravar log no banco: {erro}", file=sys.stderr)


def configurar(banco: Banco | None = None) -> None:
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))

    raiz = logging.getLogger()
    raiz.setLevel(logging.INFO)
    raiz.handlers[:] = [console]
    if banco:
        raiz.addHandler(BancoHandler(banco))
    for ruidoso in ("urllib3", "psycopg"):
        logging.getLogger(ruidoso).setLevel(logging.WARNING)


def limpar_antigos(banco: Banco, dias_retencao: int) -> int:
    limite = datetime.now().astimezone() - timedelta(days=dias_retencao)
    return banco.execute("DELETE FROM logs WHERE criado_em < ?", (limite,)).rowcount
