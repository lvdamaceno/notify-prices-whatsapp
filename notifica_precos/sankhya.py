"""Autenticação OAuth 2.0 e consultas SQL pela API oficial do Sankhya (gateway)."""

import logging
import time

import requests

from .config import RAIZ, Config

log = logging.getLogger(__name__)

TAMANHO_PAGINA = 4000
TIMEOUT = 60


class SankhyaErro(RuntimeError):
    pass


class Sankhya:
    def __init__(self, config: Config):
        self.config = config
        self._token = ""
        self._expira_em = 0.0

    def _autenticar(self) -> str:
        # O token dura ~5 minutos; renova com 30s de folga.
        if self._token and time.time() < self._expira_em - 30:
            return self._token

        resp = requests.post(
            f"{self.config.sankhya_base_url}/authenticate",
            headers={"X-Token": self.config.sankhya_x_token},
            data={
                "client_id": self.config.sankhya_client_id,
                "client_secret": self.config.sankhya_client_secret,
                "grant_type": "client_credentials",
            },
            timeout=TIMEOUT,
        )
        if resp.status_code != 200:
            raise SankhyaErro(f"Falha na autenticação ({resp.status_code}): {resp.text[:500]}")

        dados = resp.json()
        self._token = dados["access_token"]
        self._expira_em = time.time() + int(dados.get("expires_in", 300))
        log.info("Token Sankhya gerado (expira em %ss)", dados.get("expires_in"))
        return self._token

    def _executar_sql(self, sql: str) -> tuple[list[str], list[list]]:
        resp = requests.post(
            f"{self.config.sankhya_base_url}/gateway/v1/mge/service.sbr",
            params={"serviceName": "DbExplorerSP.executeQuery", "outputType": "json"},
            headers={"Authorization": f"Bearer {self._autenticar()}"},
            json={"serviceName": "DbExplorerSP.executeQuery", "requestBody": {"sql": sql}},
            timeout=TIMEOUT,
        )
        if resp.status_code == 401:
            # Token invalidado antes do previsto: força nova autenticação na próxima chamada.
            self._token = ""
        resp.raise_for_status()

        dados = resp.json()
        if str(dados.get("status")) != "1":
            raise SankhyaErro(f"Erro na consulta: {dados.get('statusMessage') or dados}")

        corpo = dados.get("responseBody", {})
        if corpo.get("burstLimit"):
            raise SankhyaErro("Resposta truncada pelo Sankhya (burstLimit); reduza TAMANHO_PAGINA")

        colunas = [c["name"] for c in corpo.get("fieldsMetadata", [])]
        return colunas, corpo.get("rows", [])

    def consultar(self, sql: str) -> list[dict]:
        """Executa o SQL paginando com OFFSET/FETCH até a última página."""
        registros: list[dict] = []
        offset = 0
        while True:
            pagina = f"{sql}\nOFFSET {offset} ROWS FETCH NEXT {TAMANHO_PAGINA} ROWS ONLY"
            colunas, linhas = self._executar_sql(pagina)
            registros.extend(dict(zip(colunas, linha)) for linha in linhas)
            if len(linhas) < TAMANHO_PAGINA:
                return registros
            offset += TAMANHO_PAGINA

    def _sql(self, arquivo: str, **valores: int) -> str:
        sql = (RAIZ / "sql" / arquivo).read_text(encoding="utf-8")
        # Remove os comentários de linha para não atrapalhar a cláusula de paginação.
        sql = "\n".join(l for l in sql.splitlines() if not l.strip().startswith("--"))
        filtro = ""
        if self.config.sankhya_codtabs:
            filtro = f"AND TAB.CODTAB IN ({', '.join(map(str, self.config.sankhya_codtabs))})"
        sql = sql.replace("{filtro_tabelas}", filtro)
        for nome, valor in valores.items():
            sql = sql.replace("{" + nome + "}", str(int(valor)))
        return sql.strip()

    def precos_vigentes(self) -> list[dict]:
        """Preço vigente de todos os produtos (carga completa)."""
        return self.consultar(self._sql("precos_vigentes.sql"))

    def versoes_tabela(self) -> list[dict]:
        """Versões (NUTAB) já em vigor das tabelas monitoradas."""
        return self.consultar(self._sql("versoes_tabela.sql"))

    def precos_versao(self, nutab: int) -> list[dict]:
        """Preços contidos em uma versão específica da tabela."""
        return self.consultar(self._sql("precos_versao.sql", nutab=nutab))
