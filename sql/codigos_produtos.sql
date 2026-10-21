-- Códigos de todos os produtos ativos; a primeira carga percorre essa lista em lotes.
SELECT PRO.CODPROD
FROM TGFPRO PRO
WHERE PRO.ATIVO = 'S'
ORDER BY PRO.CODPROD
