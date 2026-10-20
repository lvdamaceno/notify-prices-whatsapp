-- Preço de venda vigente de cada produto ativo, por tabela de preço (CODTAB).
-- Para cada CODTAB usa a versão (NUTAB) com a maior DTVIGOR que já entrou em vigor.
-- {filtro_tabelas} é substituído pelo script conforme SANKHYA_CODTABS no .env.
-- O ORDER BY precisa ser determinístico (termina na chave da TGFEXC) por causa da paginação.
SELECT
    TAB.CODTAB,
    EXC.NUTAB,
    EXC.CODPROD,
    PRO.DESCRPROD,
    EXC.CODLOCAL,
    EXC.CONTROLE,
    EXC.VLRVENDA
FROM TGFEXC EXC
JOIN TGFTAB TAB ON TAB.NUTAB = EXC.NUTAB
JOIN TGFPRO PRO ON PRO.CODPROD = EXC.CODPROD
WHERE PRO.ATIVO = 'S'
  AND TAB.DTVIGOR = (
        SELECT MAX(T2.DTVIGOR)
        FROM TGFTAB T2
        WHERE T2.CODTAB = TAB.CODTAB
          AND T2.DTVIGOR <= CURRENT_TIMESTAMP
      )
  {filtro_tabelas}
ORDER BY TAB.CODTAB, EXC.NUTAB, EXC.CODPROD, EXC.CODLOCAL, EXC.CONTROLE
