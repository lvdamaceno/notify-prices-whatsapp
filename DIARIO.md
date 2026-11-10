# Diário do notifica-precos

O que foi feito em cada dia de trabalho no monitor de preços, do mais recente para o mais antigo, com quem fez cada
coisa entre parênteses.

## 10/11/2026 (terça-feira)

- Verificação de preços a cada 2 minutos, em vez de a cada minuto (pedido do usuário): eram 3 consultas por minuto ao
  Sankhya o dia todo, 12% de tudo o que passava pela conexão central. O cron no Render já está com `*/2 * * * *`; os
  comandos do Telegram passam a valer em até 2 minutos (Vinícius Damaceno, com o Claude).
