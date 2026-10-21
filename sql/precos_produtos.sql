-- Primeira carga: preço vigente de um lote de produtos ({codprods}, até 1000 por causa do
-- limite do IN no Oracle). Para cada produto vale a versão mais recente da tabela (maior
-- DTVIGOR já em vigor, desempate por NUTAB) que contém aquele produto.
-- {filtro_tabelas} é substituído pelo script conforme SANKHYA_CODTABS no .env.
SELECT
    X.CODTAB,
    X.NUTAB,
    X.DTVIGOR,
    X.CODPROD,
    PRO.DESCRPROD,
    X.CODLOCAL,
    X.CONTROLE,
    X.VLRVENDA
FROM (
    SELECT
        TAB.CODTAB,
        EXC.NUTAB,
        TAB.DTVIGOR,
        EXC.CODPROD,
        EXC.CODLOCAL,
        EXC.CONTROLE,
        EXC.VLRVENDA,
        ROW_NUMBER() OVER (
            PARTITION BY TAB.CODTAB, EXC.CODPROD, EXC.CODLOCAL, EXC.CONTROLE
            ORDER BY TAB.DTVIGOR DESC, EXC.NUTAB DESC
        ) AS ORDEM
    FROM TGFEXC EXC
    JOIN TGFTAB TAB ON TAB.NUTAB = EXC.NUTAB
    WHERE EXC.CODPROD IN ({codprods})
      AND TAB.DTVIGOR <= CURRENT_TIMESTAMP
      {filtro_tabelas}
) X
JOIN TGFPRO PRO ON PRO.CODPROD = X.CODPROD
WHERE X.ORDEM = 1
ORDER BY X.CODTAB, X.CODPROD, X.CODLOCAL, X.CONTROLE
