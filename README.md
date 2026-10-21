# notify-prices-whatsapp

Verifica no Sankhya, a cada 10 minutos, se algum preço de venda mudou e avisa por **e-mail**, usando o SMTP do Google Workspace da empresa. A consulta usa a API oficial do Sankhya (gateway OAuth 2.0).

> O projeto começou com notificação por WhatsApp, por isso o nome do repositório. A troca para e-mail aconteceu porque nem a Cloud API da Meta (grupos de até 8 participantes, exige OBA) nem a Blip (sem suporte a grupos) atendiam ao caso.

## Como funciona

No Sankhya a tabela de preço (sempre a `CODTAB` 0) é **recriada a cada atualização**: cada vez que alguém muda um preço nasce uma nova versão (`NUTAB` na `TGFTAB`). Essa versão pode trazer **só os produtos alterados** ou **uma cópia de todos**. Então o preço vigente de um produto é o da versão mais recente (maior `DTVIGOR` já em vigor, com desempate pelo `NUTAB`) **que contém aquele produto**. O banco guarda essa foto completa, com cerca de 60 mil preços, e o script trabalha de dois jeitos:

**Primeira carga** (`sql/codigos_produtos.sql` + `sql/precos_produtos.sql`) busca os códigos de todos os produtos ativos e, em lotes de `CARGA_LOTE_PRODUTOS` (padrão 500), pega o preço da versão mais recente que contém cada produto. Assim nenhum produto fica de fora, mesmo que não esteja na última cópia completa. Ela não notifica nada e:
- mostra o andamento no log a cada lote: `lote 12/121 · produtos 5501 a 6000 · 6000/60099 produtos (10.0%) · 1m20s decorridos · ~12m00s restantes`;
- salva cada lote à medida que termina. Se a execução cair no meio (timeout, Sankhya fora), a próxima continua do último produto concluído;
- usa uma trava no Postgres (`pg_try_advisory_lock`), garantindo uma execução por vez também em execuções manuais (o próprio Render já adia a próxima execução do cron enquanto uma está ativa).

**Carga completa** recalcula o preço vigente de todos os produtos, compara com a foto e notifica as diferenças. Para não varrer todo o histórico da `TGFEXC` (milhões de linhas, já que cada atualização recria a tabela), ela parte da **cópia completa mais recente**, que já traz todos os produtos:
1. Conta os itens das versões mais novas, de 20 em 20, pelo índice de `NUTAB` (`sql/copias_completas.sql`). A primeira versão com pelo menos 10% dos produtos ativos (`sql/produtos_ativos.sql`) é a base; ajuste com `COPIA_COMPLETA_MIN_ITENS`.
2. Lê a base (`sql/precos_versao.sql`) e sobrepõe as versões parciais posteriores a ela. Se uma tabela não tiver nenhuma cópia completa, todas as versões dela (todas parciais) são aplicadas.

Ela roda:
- a cada **deploy** no Render (detectado pelo `RENDER_GIT_COMMIT`);
- todo dia às `CARGA_COMPLETA_HORA` (padrão 6h, no fuso de `TZ`), na primeira execução do cron a partir desse horário, para pegar edições feitas direto numa versão que já existia. Se um deploy já fez uma carga completa depois desse horário no mesmo dia, ela não se repete;
- sob demanda, com `python main.py --carga-completa`.

**Incremental**, a cada 10 minutos:
1. Lista as versões já em vigor (`sql/versoes_tabela.sql`) e separa as que ainda não foram processadas. Uma versão com vigor futuro só é processada quando entra em vigor.
2. Lê os preços de cada versão nova (`sql/precos_versao.sql`) e sobrepõe à foto, produto a produto, da versão mais antiga para a mais nova. Uma versão retroativa não desfaz um preço mais recente.
3. Notifica só o que mudou de valor:
   - versão parcial: só os produtos alterados;
   - cópia completa com os mesmos preços: nada;
   - reajuste geral: um e-mail com o CSV de 60 mil linhas (cerca de 3 MB).
4. Grava a foto, as versões processadas e o histórico numa única transação. Se o envio do e-mail falhar, nada é gravado e o ciclo seguinte refaz e reenvia.

A autenticação no Sankhya é feita em `POST {SANKHYA_BASE_URL}/authenticate` (OAuth 2.0 `client_credentials` mais o `X-Token`), e as consultas usam `DbExplorerSP.executeQuery` com paginação `OFFSET/FETCH`.

### O e-mail

- **Assunto:** `Atualização de preços de venda: 2 alterado(s), 1 novo(s) (21/10/2026 10:19)`.
- **Corpo em HTML:** uma tabela com código, modelo, produto, preço anterior, preço novo e variação, com alta em vermelho e queda em verde. Também vai uma versão em texto simples.
- **Anexo CSV** (`;`, UTF-8, abre direto no Excel) com **todas** as alterações, nas mesmas colunas da tabela do corpo. A tabela do corpo mostra no máximo `MAX_ITENS_EMAIL` itens.

### Banco de dados

| `DATABASE_URL` | Banco usado |
|---|---|
| `postgresql://...` | Postgres (Render) |
| vazia | SQLite local em `dados/precos.db` |

As tabelas são criadas automaticamente:
- `precos`: preço vigente de cada produto, com o `NUTAB` e o `DTVIGOR` de origem.
- `versoes_processadas`: versões da tabela já aplicadas.
- `estado`: última carga completa, último commit do deploy e versão do esquema.
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
| `EMAIL_DESTINATARIOS` | **Só no painel do Render** | Separados por vírgula. Basta o usuário (`joao,maria`), e o domínio é completado; e-mail inteiro também vale (`ana@fornecedor.com.br`) |
| `EMAIL_DEPLOY` | **Só no painel do Render** | Quem recebe o aviso de cada deploy (ex.: `gti`) |
| `EMAIL_DOMINIO` | Opcional | Domínio usado para completar os destinatários. Vazio = domínio do `SMTP_USUARIO` |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | Painel do Render | Opcional: avisos de execução no Telegram |
| `DATABASE_URL` | Automático | Ligada ao Postgres pelo `render.yaml` |
| `TZ` | `render.yaml` | `America/Belem` |
| `MAX_ITENS_EMAIL` | `render.yaml` | Padrão `500` |
| `CARGA_LOTE_PRODUTOS` | Opcional | Produtos por consulta na primeira carga. Padrão `500`, máximo `1000` |
| `SANKHYA_TIMEOUT` | Opcional | Segundos de espera por consulta ao Sankhya. Padrão `120` |
| `COPIA_COMPLETA_MIN_ITENS` | Opcional | Itens mínimos para uma versão contar como cópia completa. Padrão `0` = 10% dos produtos ativos |
| `CARGA_COMPLETA_HORA` | `render.yaml` | Hora fixa (0-23) da reconciliação diária. Padrão `6`; vazio desliga (fica só no deploy) |
| `LOG_DIAS_RETENCAO` | `render.yaml` | Padrão `90` |

As variáveis marcadas como `sync: false` no `render.yaml` não têm valor no repositório. Os destinatários e as credenciais existem só no painel do Render, em **notifica-precos → Environment**. Para incluir ou tirar alguém da lista, edite `EMAIL_DESTINATARIOS` ali; não precisa mexer no código. A próxima execução do Cron Job já usa a lista nova.

### Senha de app do Google Workspace

1. Use uma conta dedicada (por exemplo `notificacoes@casacontente.com.br`) com **verificação em duas etapas** ativada.
2. Gere a senha em https://myaccount.google.com/apppasswords e coloque em `SMTP_SENHA`.
3. Se a opção não aparecer, o administrador do Workspace precisa permitir senhas de app (Admin Console → Segurança).

O limite do Gmail é de 2.000 e-mails por dia por conta. O monitor envia no máximo um e-mail a cada 10 minutos (144 por dia), e só quando há alteração.

## Aviso de deploy

Na primeira execução depois de cada deploy no Render (o script compara o `RENDER_GIT_COMMIT` com o último avisado), sai um aviso **uma única vez por commit**:
- **E-mail para `EMAIL_DEPLOY`** com o resultado (sucesso ou falha da primeira execução, com o erro), o serviço, a branch, o commit com link para o GitHub e a configuração ativa: tabelas monitoradas, destinatários de preços, intervalo da reconciliação e Telegram.
- **Mensagem 🚀 no Telegram** com o mesmo resumo e se o e-mail de deploy foi entregue.

Se a primeira execução falhar, os erros seguintes do mesmo tipo não geram aviso novo; quando voltar a funcionar, chega o "voltou a funcionar". Rodando localmente, sem `RENDER_GIT_COMMIT`, não há aviso de deploy.

## Avisos no Telegram

Opcionais: sem `TELEGRAM_BOT_TOKEN` e `TELEGRAM_CHAT_ID`, nada é enviado. Para não avisar a cada 10 minutos, só os eventos relevantes geram mensagem:

| Evento | Aviso |
|---|---|
| Ciclo sem versão nova ou sem alteração | nenhum |
| Preço alterado (e-mail enviado) | ✅ quantidade de alterações, NUTAB e destinatários |
| Deploy | 🚀 resultado da primeira execução (veja *Aviso de deploy*) |
| Reconciliação diária (6h) | 🔄 **só se encontrar alteração**; sem alteração fica em silêncio |
| Carga completa manual (`--carga-completa`) | 🔄 motivo, total de preços e alterações |
| Erro | ❌ só o **primeiro** de cada tipo. Com o Sankhya fora por horas, chega um aviso, não um a cada 10 minutos |
| Volta a funcionar depois de um erro | ✅ "voltou a funcionar" |

Para configurar:
1. No Telegram, fale com o **@BotFather**, use `/newbot` e copie o token para `TELEGRAM_BOT_TOKEN`. Pode reaproveitar o bot do `envio-gfk`.
2. Mande uma mensagem para o bot (ou adicione-o a um grupo) e abra `https://api.telegram.org/bot<TOKEN>/getUpdates`. O `chat.id` que aparece vai em `TELEGRAM_CHAT_ID` (em grupos ele é negativo).
3. Teste com `python main.py --testar-telegram`.

Uma falha no Telegram só é registrada no log e nunca interrompe o monitor nem o envio do e-mail.

## Hospedagem no Render

O disco dos serviços do Render é apagado a cada deploy ou reinício, e Cron Jobs não aceitam disco persistente. Por isso os dados ficam num **Render Postgres**. O `render.yaml` cria:

- **Cron Job** `notifica-precos`: roda `python main.py` com o schedule `*/10 * * * *` (o mínimo do cron é 1 minuto: `* * * * *`). O Render cobra por segundo de execução, com mínimo de US$ 1/mês, e nunca roda duas execuções ao mesmo tempo. O envio de e-mail pelas portas 465 e 587 funciona porque o Cron Job é um serviço pago; os serviços gratuitos bloqueiam SMTP.
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
.venv/bin/python main.py --testar-email   # envia um e-mail de exemplo (produtos e preços fictícios) para EMAIL_DEPLOY
.venv/bin/python main.py                  # roda um ciclo (é o que o Cron Job do Render executa)
.venv/bin/python main.py --testar-telegram # envia um aviso de teste no Telegram
.venv/bin/python main.py --carga-completa # recalcula todos os preços e compara com o banco
.venv/bin/python main.py --loop           # fica rodando a cada INTERVALO_MINUTOS (servidor próprio / Background Worker)
```

Código de saída `0` em sucesso e `1` em falha. Uma execução com falha aparece como *failed* no histórico do Cron Job.

Para testar o e-mail no próprio Render: **notifica-precos → Trigger Run** roda um ciclo normal. Para um teste isolado, mude temporariamente o *Command* para `python main.py --testar-email`.

## Logs e histórico

- **Console:** aparece em *Logs* no painel do Render, que guarda 7 dias no plano Hobby.
- **Tabela `logs`:** guarda os registros de nível INFO para cima, inclusive os erros com traceback, por `LOG_DIAS_RETENCAO` dias. Cada preço alterado vira uma linha `ALTERACAO ...`. Acima de 200 alterações num ciclo, o log registra só o total, e o detalhe fica no `historico` e no CSV.
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
- Para mudar o que é monitorado, edite os arquivos em `sql/`, mantendo o `ORDER BY` determinístico (a paginação depende dele).
- Na primeira versão do projeto a foto guardava só a última versão da tabela. Ao subir esta versão, o banco é migrado sozinho: a foto antiga é descartada e refeita numa carga completa, sem notificar.
