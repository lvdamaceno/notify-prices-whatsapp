-- Quantidade de produtos ativos; base para saber se uma versão da tabela é uma cópia completa.
SELECT COUNT(*) AS QTD
FROM TGFPRO PRO
WHERE PRO.ATIVO = 'S'
