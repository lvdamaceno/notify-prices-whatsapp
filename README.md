# notify-prices-whatsapp

Verifica no Sankhya, a cada 5 minutos, se algum preço de venda mudou e avisa por **e-mail**, usando o SMTP do Google Workspace da empresa. A consulta usa a API oficial do Sankhya (gateway OAuth 2.0).

> O projeto começou com notificação por WhatsApp, por isso o nome do repositório. A troca para e-mail aconteceu porque nem a Cloud API da Meta (grupos de até 8 participantes, exige OBA) nem a Blip (sem suporte a grupos) atendiam ao caso.

## Como funciona

1. Autentica em `POST {SANKHYA_BASE_URL}/authenticate`, mandando o `X-Token` no header e o corpo `client_credentials` em form-urlencoded.
2. Roda `sql/precos_venda.sql` via `DbExplorerSP.executeQuery`, com paginação `OFFSET/FETCH`. A query traz o `VLRVENDA` (TGFEXC) da versão vigente (maior `DTVIGOR` já em vigor) de cada tabela de preço (`CODTAB`), só para produtos ativos.
3. Compara o resultado com a última foto salva no banco (tabela `precos`). A comparação é necessária porque a TGFEXC não tem data de alteração.
4. Se houver diferença, envia o e-mail, grava só as linhas que mudaram e registra cada alteração na tabela `historico`.
5. Se o envio falhar, a foto **não** é atualizada, e a alteração é detectada e enviada de novo no próximo ciclo.

A primeira execução só cria a foto inicial e não envia nada.

### O e-mail

- **Assunto:** `Atualização de preços de venda: 2 alterado(s), 1 novo(s) (21/10/2026 10:19)`.
- **Corpo em HTML:** uma tabela com tabela de preço, código, produto, preço anterior, preço novo e variação, com alta em vermelho e queda em verde. Também vai uma versão em texto simples.
- **Anexo CSV** (`;`, UTF-8, abre direto no Excel) com **todas** as alterações. A tabela do corpo mostra no máximo `MAX_ITENS_EMAIL` itens.

### Banco de dados

| `DATABASE_URL` | Banco usado |
|---|---|
| `postgresql://...` | Postgres (Render) |
| vazia | SQLite local em `dados/precos.db` |

As tabelas são criadas automaticamente:
- `precos`: a foto atual.
- `historico`: todas as alterações detectadas.
- `logs`: os logs de execução.

## Variáveis de ambiente

| Variável | Onde definir | Descrição |
|---|---|---|
| `SANKHYA_CLIENT_ID`, `SANKHYA_CLIENT_SECRET` | Painel do Render | Área do Desenvolvedor do Sankhya |
| `SANKHYA_X_TOKEN` | Painel do Render | Tela **Configurações Gateway** do Sankhya Om |
| `SANKHYA_CODTABS` | Painel do Render | Tabelas de preço monitoradas (ex.: `0,5`). Vazio monitora todas |
| `SMTP_HOST` | Painel do Render | `smtp.gmail.com` |
| `SMTP_PORTA` | `render.yaml` | `587` (STARTTLS) ou `465` (SSL) |
| `SMTP_USUARIO` | Painel do Render | Conta que envia, ex.: `notificacoes@casacontente.com.br` |
| `SMTP_SENHA` | Painel do Render | Senha de app da conta (veja abaixo) |
| `EMAIL_REMETENTE` | Painel do Render | Opcional, ex.: `Monitor de Preços <notificacoes@casacontente.com.br>` |
| `EMAIL_DESTINATARIOS` | **Só no painel do Render** | E-mails separados por vírgula |
| `DATABASE_URL` | Automático | Ligada ao Postgres pelo `render.yaml` |
| `TZ` | `render.yaml` | `America/Belem` |
| `MAX_ITENS_EMAIL` | `render.yaml` | Padrão `500` |
| `LOG_DIAS_RETENCAO` | `render.yaml` | Padrão `90` |

As variáveis marcadas como `sync: false` no `render.yaml` não têm valor no repositório. Os destinatários e as credenciais existem só no painel do Render, em **notifica-precos → Environment**. Para incluir ou tirar alguém da lista, edite `EMAIL_DESTINATARIOS` ali; não precisa mexer no código. A próxima execução do Cron Job já usa a lista nova.

### Senha de app do Google Workspace

1. Use uma conta dedicada (por exemplo `notificacoes@casacontente.com.br`) com **verificação em duas etapas** ativada.
2. Gere a senha em https://myaccount.google.com/apppasswords e coloque em `SMTP_SENHA`.
3. Se a opção não aparecer, o administrador do Workspace precisa permitir senhas de app (Admin Console → Segurança).

O limite do Gmail é de 2.000 e-mails por dia por conta. O monitor envia no máximo um e-mail a cada 5 minutos (288 por dia), e só quando há alteração.

## Hospedagem no Render

O disco dos serviços do Render é apagado a cada deploy ou reinício, e Cron Jobs não aceitam disco persistente. Por isso os dados ficam num **Render Postgres**. O `render.yaml` cria:

- **Cron Job** `notifica-precos`: roda `python main.py` com o schedule `*/5 * * * *`. O Render cobra por minuto de execução. O envio de e-mail pelas portas 465 e 587 funciona porque o Cron Job é um serviço pago; os serviços gratuitos bloqueiam SMTP.
- **Postgres** `notifica-precos-db` (plano `basic-256mb`): o `DATABASE_URL` é ligado ao Cron Job pela rede interna.

> Não use o Postgres **Free** do Render: ele expira 30 dias depois de criado e é apagado depois de mais 14 dias, junto com o histórico.

**Serviço já criado antes da troca para e-mail:** o Render só pede as variáveis `sync: false` na criação do Blueprint. Adicione `SMTP_HOST`, `SMTP_USUARIO`, `SMTP_SENHA`, `EMAIL_REMETENTE` e `EMAIL_DESTINATARIOS` manualmente em **Environment** e apague as `WHATSAPP_*`.

## Instalação local

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env   # preencha as credenciais
```

Credenciais de sandbox do Sankhya só funcionam com o token de sandbox, e as de produção só com o de produção. Misturar os dois causa erro 401.

## Uso

```bash
.venv/bin/python main.py --testar-email   # envia um e-mail de teste aos destinatários
.venv/bin/python main.py                  # roda um ciclo (é o que o Cron Job do Render executa)
.venv/bin/python main.py --loop           # fica rodando a cada INTERVALO_MINUTOS (servidor próprio / Background Worker)
```

Código de saída `0` em sucesso e `1` em falha. Uma execução com falha aparece como *failed* no histórico do Cron Job.

Para testar o e-mail no próprio Render: **notifica-precos → Trigger Run** roda um ciclo normal. Para um teste isolado, mude temporariamente o *Command* para `python main.py --testar-email`.

## Logs e histórico

- **Console:** aparece em *Logs* no painel do Render, que guarda 7 dias no plano Hobby.
- **Tabela `logs`:** guarda os registros de nível INFO para cima, inclusive os erros com traceback, por `LOG_DIAS_RETENCAO` dias. Cada preço alterado vira uma linha `ALTERACAO ...`.
- **Tabela `historico`:** registro permanente de todas as alterações, com a coluna `notificado`.

Para consultar, use a *External Database URL* do Postgres (aba *Connect* no Render):

```bash
psql "$DATABASE_URL" -c "SELECT detectado_em, codprod, descrprod, vlr_anterior, vlr_novo FROM historico ORDER BY id DESC LIMIT 20"
psql "$DATABASE_URL" -c "SELECT criado_em, nivel, mensagem FROM logs WHERE nivel <> 'INFO' ORDER BY id DESC LIMIT 20"
```

## Ajustes

- `SANKHYA_CODTABS`: quais tabelas de preço monitorar.
- `MAX_ITENS_EMAIL`: quantos itens aparecem na tabela do corpo. O CSV anexo sempre tem todos.
- `TZ`: fuso dos horários no e-mail e nos logs (o servidor do Render roda em UTC).
- Para mudar o que é monitorado, edite `sql/precos_venda.sql`, mantendo o `ORDER BY` determinístico.
