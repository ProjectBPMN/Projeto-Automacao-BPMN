# Workflows V9 no n8n

Esta pasta contém os seis exports executáveis da automação. Cada arquivo
`V9-*.json` pode ser importado, inspecionado e editado visualmente no n8n.

Os arquivos `build_wf*.py` e os helpers são fontes de manutenção: eles evitam
edições divergentes em trechos repetidos, regeneram os JSONs e permitem validar
o grafo de forma determinística. Eles não precisam ser executados por quem vai
apenas importar e operar os workflows. Os exports continuam sendo workflows
nativos do n8n; não se afirma que os 172 nós foram montados manualmente na UI.

## Estado de verificação em 12/08/2026

A revisão corrente passou em 913 verificações estáticas, nove testes de
contrato e um preflight real sem mutação. Isso demonstra integridade estrutural
e coerência dos contratos testados, não correção universal. Ainda faltam o E2E
mutante integral dos JSONs exatos desta revisão e uma calibração isolada e
válida da vazão do WF06. O detalhamento e o roteiro seguro estão em
`TEST_REPORT.md`.

## Artefatos importáveis

| Ordem | Arquivo | Função |
|---:|---|---|
| 1 | `V9-WF02-Triagem.json` | Recupera candidatos e avalia duplicidade. |
| 2 | `V9-WF03-Classificacao.json` | Classifica em DEMO, SOB_DEMANDA, OBRA ou TRIAGEM_MANUAL. |
| 3 | `V9-WF04-Decisao-Fiscal.json` | Exibe e processa a confirmação fiscal de duplicidade. |
| 4 | `V9-WF05-Metricas.json` | Consolida telemetria e mantém a avaliação humana de apoio. |
| 5 | `V9-WF01-Sincronizador.json` | Sincroniza o GLPI e recupera itens pendentes. |
| 6 | `V9-WF06-Fila-IA.json` | Recebe eventos, reserva lotes e controla a vazão. |

A ordem reduz o risco de ativar os gatilhos do WF01/WF06 antes que os
subworkflows e os webhooks de confirmação estejam configurados.

## Antes de importar

1. Copie `n8n/.env.example` para `n8n/.env` e `n8n/.env.local`.
2. Troque todos os valores `CHANGE_ME` e mantenha esses arquivos fora do Git.
3. Inicie PostgreSQL, n8n e Mailpit com o Compose da pasta `n8n`.
4. Inicie a API local e confira se `http://localhost:8090/health` está saudável.
5. Abra `http://localhost:5678` e deixe os workflows inativos até o fim da
   configuração.

Os endereços `localhost` que aparecem no navegador não substituem os endereços
internos usados entre containers. Dentro do n8n, PostgreSQL é
`glpi-dedup-db:5432`, Mailpit é `mailpit:1025` e serviços do host usam
`host.docker.internal` conforme o `.env.example`.

## Credenciais pela interface

Em **Credentials**, crie estas credenciais com os nomes exatos:

### `Postgres Triagem`

- tipo: PostgreSQL;
- host: `glpi-dedup-db`;
- porta: `5432`;
- database: valor de `POSTGRES_DB`;
- user: valor de `POSTGRES_USER`;
- password: valor de `POSTGRES_PASSWORD`;
- SSL: desativado no ambiente Docker local.

### `SMTP Mailpit Local`

- tipo: SMTP;
- host: `mailpit`;
- porta: `1025`;
- SSL/TLS e STARTTLS: desativados;
- usuário e senha: vazios.

Mailpit é somente uma caixa de captura local. Para uso institucional, crie uma
credencial SMTP própria e selecione-a nos nós de e-mail; não publique a senha.

## Importação na UI

Para cada arquivo da tabela, abra **Workflows**, crie um workflow e escolha
**Import from File** no menu do editor. Os exports refletem a implantação e
podem carregar `active=true`; se a sua versão preservar esse estado, desligue o
workflow imediatamente e só volte a ativá-lo na ordem indicada abaixo. Depois
da importação:

1. salve o workflow e confirme o nome `V9 - WFxx ...`;
2. associe `Postgres Triagem` a todos os nós PostgreSQL que exibirem aviso;
3. associe `SMTP Mailpit Local` aos nós de e-mail do WF02, WF03 e WF05;
4. no WF06, abra `Chamar WF02 da Fila` e selecione o WF02 importado;
5. ainda no WF06, abra `Chamar WF03 da Fila` e selecione o WF03 importado;
6. salve novamente.

Os dois últimos passos devem ser feitos mesmo que o nome apareça correto. Uma
instância nova pode atribuir IDs diferentes dos IDs preservados nos exports.

## Conferência dos webhooks

Com os workflows ainda inativos, confira os nós abaixo:

| Workflow | Método | Caminho de produção | Efeito |
|---|---|---|---|
| WF06 | POST | `glpi-ticket-fila-ia-v9` | Ingressa evento autenticado do GLPI. |
| WF04 | GET | `fiscal-confirmacao-v9` | Exibe a confirmação; não altera o ticket. |
| WF04 | POST | `fiscal-decisao-fiscal-ic-2026` | Executa a decisão confirmada. |
| WF05 | GET | `avaliacao-humana-confirmacao-v9` | Exibe a confirmação da avaliação. |
| WF05 | POST | `avaliacao-humana-v9` | Registra a avaliação confirmada. |

Os links colocados no GLPI devem apontar para os endpoints `GET` de
confirmação. A página monta um formulário `POST` para o endpoint de mutação.
Esse desenho evita que scanners de e-mail ou pré-visualizadores alterem um
chamado apenas por abrir o endereço.

## Ativação segura

1. Ative WF02, WF03, WF04 e WF05.
2. Ative WF01.
3. Ative WF06 por último.
4. Volte à lista e confirme que os seis estão ativos e sem aviso de credencial.

Antes de um piloto, use apenas chamados sintéticos e confira:

- o evento chegou ao WF06 e recebeu uma linha de fila;
- WF02 foi executado antes de WF03;
- cada tentativa de modelo ficou registrada antes de qualquer ação no GLPI;
- uma possível duplicidade permaneceu aguardando confirmação;
- abrir o link de confirmação por `GET` não mudou o estado;
- somente o botão do formulário provocou o `POST`;
- baixa confiança e informação insuficiente resultaram em revisão/abstenção;
- o WF05 consolidou métricas sem transformar telemetria em resultado
  científico.

### Testes de contrato e runtime

Os testes locais de contrato não chamam GLPI, PostgreSQL ou webhooks reais:

```powershell
python "n8n\workflows\Versão9\test_v9_hard.py"
```

O preflight chama apenas operações sem mutação: saúde do n8n, rejeição de
uma chave incorreta pelo WF06 e preview inválido do WF04:

```powershell
$env:N8N_BASE_URL = "http://127.0.0.1:5678"
python "n8n\workflows\Versão9\test_v9_runtime.py" --mode preflight
```

O modo `fiscal-preparado` pode alterar um chamado. Por isso ele exige
`TEST_MODE=true`, `V9_E2E_MUTATION_TESTS=true`, credenciais somente no ambiente
e um ticket cujo título comece com um prefixo sintético. O roteiro e as
pendências E2E estão documentados em `TEST_REPORT.md`.

Para a prova integrada principal, prefira o executor que cria e limpa o próprio
contexto sintético, bloqueia calibração concorrente e verifica PostgreSQL:

```powershell
python avaliacao\scripts\validar_webhooks_confirmacao_e2e.py --decision confirmar
python avaliacao\scripts\validar_webhooks_confirmacao_e2e.py --decision nao_duplicado
```

No ramo negativo, o executor segura a reserva WF06 enquanto confere
`REJEITOU_DUP`, campos limpos, evento único e
`PENDENTE_FILA_IA/CLASSIFICACAO`; a trava só é liberada depois do cleanup. Isso
prova o contrato de handoff, não a execução posterior do WF03.

`FILA_IA_RUN_SCOPE` não é uma configuração de produção. Ela permanece vazia no
Compose e é preenchida temporariamente pelo executor de calibração para limitar
as reservas do WF06 a um único `run_id`. Ao terminar, o executor restaura
exatamente o perfil capturado; no perfil normal de produção, o escopo permanece
vazio.

## Manutenção reproduzível

Depois de alterar visualmente um workflow, exporte-o e revise a diferença antes
de substituir o arquivo canônico. Se a alteração for permanente, replique-a no
builder correspondente; caso contrário, a próxima regeneração descartará a
edição feita apenas na UI.

Para mantenedores:

```powershell
python n8n\workflows\Versão9\validate_v9_static.py
python n8n\workflows\Versão9\deploy.py
```

O primeiro comando verifica estrutura, conexões e invariantes de segurança. O
segundo regenera, valida e implanta os seis workflows. O caminho por script é
uma opção de manutenção e reprodução; não impede importação, configuração ou
inspeção integral pela interface.
