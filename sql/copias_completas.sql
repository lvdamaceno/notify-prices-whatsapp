-- Entre as versões informadas, as que são cópias completas da tabela (com pelo menos
-- {limite} itens). Usa só o índice da chave da TGFEXC (NUTAB primeiro), sem varrer o histórico.
SELECT
    EXC.NUTAB,
    COUNT(*) AS QTD
FROM TGFEXC EXC
WHERE EXC.NUTAB IN ({nutabs})
GROUP BY EXC.NUTAB
HAVING COUNT(*) >= {limite}
ORDER BY EXC.NUTAB
