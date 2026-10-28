-- Códigos de todos os produtos ativos de revenda (USOPROD = 'R'); a primeira carga percorre essa lista em lotes.
SELECT PRO.CODPROD
FROM TGFPRO PRO
WHERE PRO.ATIVO = 'S'
  AND PRO.USOPROD = 'R'
ORDER BY PRO.CODPROD
