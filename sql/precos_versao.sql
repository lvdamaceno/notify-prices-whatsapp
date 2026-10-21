-- Preços de uma versão (NUTAB) da tabela. Pode trazer só os produtos alterados
-- ou uma cópia completa da versão anterior; o script sobrepõe à foto atual.
SELECT
    TAB.CODTAB,
    EXC.NUTAB,
    TAB.DTVIGOR,
    EXC.CODPROD,
    PRO.DESCRPROD,
    PRO.AD_MODELOREF,
    EXC.CODLOCAL,
    EXC.CONTROLE,
    EXC.VLRVENDA
FROM TGFEXC EXC
JOIN TGFTAB TAB ON TAB.NUTAB = EXC.NUTAB
JOIN TGFPRO PRO ON PRO.CODPROD = EXC.CODPROD
WHERE EXC.NUTAB = {nutab}
  AND PRO.ATIVO = 'S'
ORDER BY EXC.CODPROD, EXC.CODLOCAL, EXC.CONTROLE
