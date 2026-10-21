"""Conexão com o banco: Postgres quando DATABASE_URL está definida (Render), senão SQLite local.

As queries são escritas com placeholder `?` e traduzidas para `%s` no Postgres.
"""

import sqlite3
from contextlib import contextmanager
from datetime import datetime

from .config import RAIZ

ARQUIVO_SQLITE = RAIZ / "dados" / "precos.db"

# Versão 2: a foto passou a guardar o preço vigente por produto (com DTVIGOR) em vez de só a
# última versão da tabela. A foto antiga não serve para comparar e é refeita numa carga completa.
VERSAO_ESQUEMA = "2"

DDL_ESTADO = "CREATE TABLE IF NOT EXISTS estado (chave TEXT PRIMARY KEY, valor TEXT)"

DDL_POSTGRES = """
CREATE TABLE IF NOT EXISTS precos (
    codtab INTEGER, codprod BIGINT, codlocal BIGINT, controle TEXT,
    nutab BIGINT, dtvigor TEXT, descrprod TEXT, vlrvenda DOUBLE PRECISION,
    PRIMARY KEY (codtab, codprod, codlocal, controle)
);
CREATE TABLE IF NOT EXISTS versoes_processadas (
    nutab BIGINT PRIMARY KEY, codtab INTEGER, dtvigor TEXT, processada_em TIMESTAMPTZ
);
CREATE TABLE IF NOT EXISTS historico (
    id BIGSERIAL PRIMARY KEY,
    detectado_em TIMESTAMPTZ, codtab INTEGER, codprod BIGINT, codlocal BIGINT,
    controle TEXT, descrprod TEXT, nutab_anterior BIGINT, nutab_novo BIGINT,
    vlr_anterior DOUBLE PRECISION, vlr_novo DOUBLE PRECISION, notificado BOOLEAN
);
CREATE TABLE IF NOT EXISTS logs (
    id BIGSERIAL PRIMARY KEY,
    criado_em TIMESTAMPTZ, nivel TEXT, origem TEXT, mensagem TEXT
);
CREATE INDEX IF NOT EXISTS logs_criado_em ON logs (criado_em);
"""

DDL_SQLITE = """
CREATE TABLE IF NOT EXISTS precos (
    codtab INTEGER, codprod INTEGER, codlocal INTEGER, controle TEXT,
    nutab INTEGER, dtvigor TEXT, descrprod TEXT, vlrvenda REAL,
    PRIMARY KEY (codtab, codprod, codlocal, controle)
);
CREATE TABLE IF NOT EXISTS versoes_processadas (
    nutab INTEGER PRIMARY KEY, codtab INTEGER, dtvigor TEXT, processada_em TEXT
);
CREATE TABLE IF NOT EXISTS historico (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    detectado_em TEXT, codtab INTEGER, codprod INTEGER, codlocal INTEGER,
    controle TEXT, descrprod TEXT, nutab_anterior INTEGER, nutab_novo INTEGER,
    vlr_anterior REAL, vlr_novo REAL, notificado INTEGER
);
CREATE TABLE IF NOT EXISTS logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    criado_em TEXT, nivel TEXT, origem TEXT, mensagem TEXT
);
CREATE INDEX IF NOT EXISTS logs_criado_em ON logs (criado_em);
"""


class Banco:
    def __init__(self, url: str):
        self.url = url
        self.postgres = url.startswith(("postgres://", "postgresql://"))
        self.conn = None
        self._conectar()

    def _conectar(self) -> None:
        if self.postgres:
            import psycopg

            self.conn = psycopg.connect(self.url, autocommit=True, connect_timeout=15)
        else:
            ARQUIVO_SQLITE.parent.mkdir(exist_ok=True)
            self.conn = sqlite3.connect(ARQUIVO_SQLITE, isolation_level=None)

    def _garantir_conexao(self) -> None:
        # No modo --loop a conexão com o Postgres pode cair (manutenção, ociosidade); reconecta.
        if self.postgres and (self.conn.closed or self.conn.broken):
            self._conectar()

    def _sql(self, sql: str) -> str:
        return sql.replace("?", "%s") if self.postgres else sql

    def _params(self, params: tuple) -> tuple:
        if self.postgres:
            return params
        return tuple(p.isoformat(timespec="seconds") if isinstance(p, datetime) else p for p in params)

    def criar_tabelas(self) -> None:
        self._garantir_conexao()
        self.conn.execute(DDL_ESTADO)
        if self.obter_estado("esquema") != VERSAO_ESQUEMA:
            self.conn.execute("DROP TABLE IF EXISTS precos")
            self.conn.execute("DROP TABLE IF EXISTS versoes_processadas")
        if self.postgres:
            self.conn.execute(DDL_POSTGRES)
        else:
            self.conn.executescript(DDL_SQLITE)
        self.definir_estado("esquema", VERSAO_ESQUEMA)

    def obter_estado(self, chave: str) -> str | None:
        linha = self.execute("SELECT valor FROM estado WHERE chave = ?", (chave,)).fetchone()
        return linha[0] if linha else None

    def definir_estado(self, chave: str, valor: str) -> None:
        self.execute(
            "INSERT INTO estado (chave, valor) VALUES (?, ?)"
            " ON CONFLICT (chave) DO UPDATE SET valor = excluded.valor",
            (chave, valor),
        )

    def execute(self, sql: str, params: tuple = ()):
        self._garantir_conexao()
        return self.conn.execute(self._sql(sql), self._params(params))

    def executemany(self, sql: str, linhas: list[tuple]) -> None:
        if not linhas:
            return
        self._garantir_conexao()
        self.conn.cursor().executemany(self._sql(sql), [self._params(l) for l in linhas])

    @contextmanager
    def transacao(self):
        self._garantir_conexao()
        if self.postgres:
            with self.conn.transaction():
                yield
            return
        self.conn.execute("BEGIN")
        try:
            yield
        except BaseException:
            self.conn.execute("ROLLBACK")
            raise
        self.conn.execute("COMMIT")
