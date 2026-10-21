-- Carga completa: preço vigente de cada produto ativo, por tabela de preço (CODTAB).
-- A tabela é recriada a cada atualização (novo NUTAB), às vezes com todos os produtos e às
-- vezes só com os alterados. Por isso o preço vigente de um produto é o da versão mais
-- recente (maior DTVIGOR já em vigor, desempate por NUTAB) que contém aquele produto.
-- {filtro_tabelas} é substituído pelo script conforme SANKHYA_CODTABS no .env.
-- O ORDER BY precisa ser determinístico (termina na chave) por causa da paginação.
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
    WHERE TAB.DTVIGOR <= CURRENT_TIMESTAMP
      {filtro_tabelas}
) X
JOIN TGFPRO PRO ON PRO.CODPROD = X.CODPROD
WHERE X.ORDEM = 1
  AND PRO.ATIVO = 'S'
ORDER BY X.CODTAB, X.CODPROD, X.CODLOCAL, X.CONTROLE
