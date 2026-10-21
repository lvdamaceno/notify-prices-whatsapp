-- Versões (NUTAB) das tabelas de preço monitoradas que já entraram em vigor.
-- O script compara com as versões já processadas para achar as novas.
SELECT
    TAB.NUTAB,
    TAB.CODTAB,
    TAB.DTVIGOR
FROM TGFTAB TAB
WHERE TAB.DTVIGOR <= CURRENT_TIMESTAMP
  {filtro_tabelas}
ORDER BY TAB.NUTAB
