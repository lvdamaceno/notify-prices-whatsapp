# notify-prices-whatsapp

Verifica no Sankhya, a cada 5 minutos, se algum preço de venda mudou e avisa um grupo do WhatsApp. Usa só as APIs oficiais: o gateway OAuth 2.0 do Sankhya e a WhatsApp Cloud API da Meta (Groups API).

## Como funciona

1. Autentica em `POST {SANKHYA_BASE_URL}/authenticate`, mandando o `X-Token` no header e o corpo `client_credentials` em form-urlencoded.
2. Roda `sql/precos_venda.sql` via `DbExplorerSP.executeQuery`, com paginação `OFFSET/FETCH`. A query traz o `VLRVENDA` (TGFEXC) da versão vigente (maior `DTVIGOR` já em vigor) de cada tabela de preço (`CODTAB`), só para produtos ativos.
3. Compara o resultado com a última foto salva no banco (tabela `precos`). A comparação é necessária porque a TGFEXC não tem data de alteração.
4. Se houver diferença, manda a mensagem ao grupo, grava só as linhas que mudaram e registra cada alteração na tabela `historico`.
5. Se o envio ao WhatsApp falhar, a foto **não** é atualizada, e a alteração é detectada e enviada de novo no próximo ciclo.

A primeira execução só cria a foto inicial e não envia nada.

### Banco de dados

| `DATABASE_URL` | Banco usado |
|---|---|
| `postgresql://...` | Postgres (Render) |
| vazia | SQLite local em `dados/precos.db` |

As tabelas são criadas automaticamente:
- `precos`: a foto atual.
- `historico`: todas as alterações detectadas.
- `logs`: os logs de execução.

## Hospedagem no Render

O disco dos serviços do Render é apagado a cada deploy ou reinício, e Cron Jobs não aceitam disco persistente. Por isso os dados ficam num **Render Postgres**. O `render.yaml` cria tudo:

- **Cron Job** `notifica-precos`: roda `python main.py` com o schedule `*/5 * * * *` (UTC, o que não importa para um intervalo fixo). O Render cobra por minuto de execução.
- **Postgres** `notifica-precos-db` (plano `basic-256mb`): o `DATABASE_URL` é ligado ao Cron Job automaticamente, pela rede interna.

Passos:
1. Suba o projeto para um repositório no GitHub ou GitLab.
2. No Render: **New → Blueprint**, escolha o repositório e preencha as variáveis pedidas (credenciais do Sankhya e do WhatsApp, `SANKHYA_CODTABS`).
3. Antes de ligar o agendamento, rode localmente `python main.py --listar-grupos` e `python main.py --testar-whatsapp` para validar as credenciais do WhatsApp.

> Não use o Postgres **Free** do Render: ele expira 30 dias depois de criado e é apagado depois de mais 14 dias, junto com o histórico.

## Instalação local

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env   # preencha as credenciais
```

### Credenciais Sankhya
- `SANKHYA_CLIENT_ID` / `SANKHYA_CLIENT_SECRET`: gerados na Área do Desenvolvedor.
- `SANKHYA_X_TOKEN`: tela **Configurações Gateway** no Sankhya Om.
- Credenciais de sandbox só funcionam com o token de sandbox, e as de produção só com o de produção. Misturar os dois causa erro 401.

### Credenciais WhatsApp (Cloud API)
- O número precisa estar na Cloud API (não no app WhatsApp Business) e a conta precisa ter acesso aos recursos de grupos. Hoje a Meta exige **Official Business Account (OBA)** para isso.
- `WHATSAPP_TOKEN`: token de System User com a permissão `whatsapp_business_messaging`.
- `WHATSAPP_PHONE_NUMBER_ID`: ID do número no WhatsApp Manager.
- Os grupos são criados pela própria API (`POST /{phone-number-id}/groups`), e as pessoas entram pelo link de convite (`GET /{group-id}/invite_link`).
- Para descobrir o `WHATSAPP_GROUP_ID`: `python main.py --listar-grupos`.

## Uso

```bash
.venv/bin/python main.py --testar-whatsapp   # testa o envio ao grupo
.venv/bin/python main.py                     # roda um ciclo (é o que o Cron Job do Render executa)
.venv/bin/python main.py --loop              # fica rodando a cada INTERVALO_MINUTOS (servidor próprio / Background Worker)
```

Código de saída `0` em sucesso e `1` em falha. Uma execução com falha aparece como *failed* no histórico do Cron Job.

## Logs e histórico

- **Console:** aparece em *Logs* no painel do Render, que guarda 7 dias no plano Hobby.
- **Tabela `logs`:** guarda os registros de nível INFO para cima, inclusive os erros com traceback, por `LOG_DIAS_RETENCAO` dias (padrão 90). Cada preço alterado vira uma linha `ALTERACAO ...`.
- **Tabela `historico`:** registro permanente de todas as alterações, com a coluna `notificado`.

Para consultar, use a *External Database URL* do Postgres (aba *Connect* no Render):

```bash
psql "$DATABASE_URL" -c "SELECT detectado_em, codprod, descrprod, vlr_anterior, vlr_novo FROM historico ORDER BY id DESC LIMIT 20"
psql "$DATABASE_URL" -c "SELECT criado_em, nivel, mensagem FROM logs WHERE nivel <> 'INFO' ORDER BY id DESC LIMIT 20"
```

## Ajustes

- `SANKHYA_CODTABS`: quais tabelas de preço monitorar (por exemplo `0` ou `0,5,12`). Vazio monitora todas.
- `MAX_ITENS_MENSAGEM`: quando uma tabela nova entra em vigor e muitos preços mudam juntos, a mensagem lista só os primeiros N itens, e o restante fica no log.
- `TZ`: fuso dos horários na mensagem e nos logs (o servidor do Render roda em UTC).
- Para mudar o que é monitorado, edite `sql/precos_venda.sql`, mantendo o `ORDER BY` determinístico.
