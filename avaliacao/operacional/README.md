# Validação operacional e governança de risco

Esta pasta implementa controles de desenvolvimento para carga e concorrência,
falhas de dependências, restauração isolada, menor privilégio, monitoramento,
SLO e drift. Ela **não certifica produção**, não torna o projeto “100% correto”
e não substitui aceite institucional.

A referência de governança é o [NIST AI Risk Management Framework 1.0
(NIST AI 100-1)](https://doi.org/10.6028/NIST.AI.100-1). O AI RMF é voluntário,
agnóstico a setor e caso de uso. A matriz abaixo é um perfil local parcial, não
uma declaração de conformidade do NIST.

## Estado honesto

A atualização de 09/09 está em
[`docs/auditoria_critica_completa_2026-09-09.md`](../../docs/auditoria_critica_completa_2026-09-09.md).
As contagens de janelas legadas não aprovam suas métricas de decisões: a
reanálise corrigida registra cobertura insuficiente. O proxy do editor foi
corrigido para preservar a porta externa sem desativar validação de origem.

- `politica_operacional_v1.json` é uma proposta ainda não aprovada; seus
  limiares só se tornam compromisso institucional após aceite e congelamento
  formais.
- os SLOs são limiares propostos e não aprovados. A interpretação de 03/09 que
  tratava quatro/seis blocos como janelas temporais válidas foi invalidada: o
  coletor anterior à versão 1.1 repetia contexto de 30 dias e snapshots
  históricos em janelas de quatro horas. Seus p95, taxas de erro e `FAIL`/`STOP`
  não são medições temporais válidas;
- as três partições aceleradas e disjuntas por grupo são outra evidência,
  destinada a testar o mecanismo sobre rótulos-proxy; nenhuma delas é janela de
  produção;
- os testes de falha padrão usam servidores efêmeros no loopback e nunca
  desligam GLPI, IA ou PostgreSQL vivos;
- o restore com `--apply` usa containers aleatórios, `--network none`, nenhuma
  porta publicada e remoção em `finally`;
- `database/init_v9.sql` comprova apenas restauração de esquema PostgreSQL. Para
  comprovar backup de dados é necessário fornecer um dump real, íntegro e
  aprovado;
- o DDL foi retirado do JSON runtime do WF05. O ambiente vivo agora usa
  `triagem_migration_admin` para migração e `triagem_app` para runtime; a prova
  de menor privilégio inclui negação de DDL com SQLSTATE 42501.
- o coletor está instalado como daemon oculto via `pythonw.exe`, iniciado pela
  chave de usuário `ProjetoICMonitoramento` em `HKCU\...\Run`; a tarefa
  agendada antiga foi removida e subprocessos usam `CREATE_NO_WINDOW`.
- a homologação sintética separada está instanciada com nove serviços, redes,
  volumes, portas e segredos próprios, sem copiar chamados reais.

## Matriz NIST AI RMF 1.0

| Função | Risco/objetivo local | Controle e evidência nesta pasta | Estado |
|---|---|---|---|
| GOVERN | Responsabilidade, tolerância e rastreabilidade | política versionada; rótulos de evidência; SLO explicitamente não aprovado; ações fail-closed; plano de rollback | Parcial; responsáveis e aceite institucional pendentes |
| MAP | Contexto GLPI–n8n–IA–PostgreSQL e impacto de decisões erradas | dependências mapeadas; mutação GLPI bloqueada quando falta uma dependência; limites de interpretação em todo relatório | Parcial; impacto e subgrupos precisam validação institucional |
| MEASURE | Disponibilidade, latência, fila, DLQ, erros, backup e drift | carga limitada; coletor intervalar corrigido; três partições proxy aceleradas; Jensen–Shannon e PSI; restore do volume n8n; auditoria de privilégios | Parcial; janelas temporais válidas ainda precisam ser acumuladas e não há validade longitudinal/semântica |
| MANAGE | Resposta a falha, abstinência e rollback | simulação isolada; E2E sintético com cleanup; decisão automática proibida em falha; diagnóstico de drift; SQL de menor privilégio | Parcial; `STOP` ainda não possui atuação no runtime e a aprovação operacional está pendente |

O framework também trata sistemas de IA como sociotécnicos e recomenda separar
atores que desenvolvem daqueles que verificam e validam. O projeto decidiu não
realizar verificação humana ou em pares; isso deve ser registrado como lacuna
de governança, e não compensado por uma alegação automática de aprovação.

## Execução segura

Todos os comandos abaixo são dry-run ou somente leitura por padrão.

```powershell
python avaliacao/operacional/validar_operacao.py
python avaliacao/operacional/least_privilege.py --live-read-only
python avaliacao/operacional/backup_restore_drill.py
```

Uma coleta viva pontual é opt-in e não mede disponibilidade mensal:

```powershell
python avaliacao/operacional/validar_operacao.py --live-read-only
```

O cenário de carga exige `--apply`, aceita apenas loopback e endpoints da lista
segura, e limita requisições, concorrência e duração pela política. O token vem
de variável de ambiente e nunca da linha de comando:

```powershell
python avaliacao/operacional/validar_operacao.py `
  --load-url http://127.0.0.1:8090/health `
  --load-requests 100 --load-concurrency 8 --apply `
  --output avaliacao/resultados/operacional/carga.json
```

Em 03/09, a carga híbrida local teve 40/40 respostas 200 com concorrência 1
(19,73 req/s; p95 35,30 ms). Com concorrência 4, houve 17/40 respostas 200 e
23/40 respostas 429 (saturação 57,5%; p95 1.736,30 ms), sem 5xx. Isso evidencia
o limite atual do semáforo de inferência e recomenda pacing conservador; não é
evidência de capacidade E2E ou de eficácia científica.

O restore real também exige autorização explícita. Ele não usa nem remove os
containers vivos:

```powershell
python avaliacao/operacional/backup_restore_drill.py `
  --postgres-artifact C:/caminho/backup_postgres.sql `
  --mariadb-artifact C:/caminho/backup_glpi.sql `
  --apply --output avaliacao/resultados/operacional/restore.json
```

## Menor privilégio

`least_privilege.py` primeiro audita. Remediação só é possível com `--apply`,
`--output` e uma credencial administrativa em
`OPERACIONAL_PG_ADMIN_DSN`; não existe parâmetro CLI para a senha. O executor:

1. registra atributos e proprietários anteriores;
2. cria os grupos NOLOGIN `triagem_migration_owner` e `triagem_runtime`;
3. transfere propriedade/DDL ao migration owner e concede somente DML ao
   runtime;
4. remove `SUPERUSER`, `CREATEDB`, `CREATEROLE`, `REPLICATION` e `BYPASSRLS` do
   login runtime;
5. exige erro PostgreSQL `42501` ao tentar `CREATE TABLE` sob o login runtime;
6. reverte a transação se a negação não ocorrer;
7. gera, antes da mudança, um `.rollback.sql` ao lado do relatório.

O DDL já foi removido do JSON runtime do WF05. A remediação foi aplicada no
ambiente vivo e registrada em
`avaliacao/resultados/operacional/postgres-menor-privilegio-20260902.json`.
Novas migrações continuam exigindo credencial administrativa e janela de
mudança; o login runtime não pode executá-las.

## Monitoramento e SLO propostos

O coletor local executa a cada minuto em segundo plano. `daemon-status.json`
informa o estado do processo; `latest.json` contém a coleta atual; e
`windows.json` acumula janelas. A política longitudinal de 30 dias foi retirada
do escopo.

### Errata de integridade das janelas de 03/09

O coletor anterior ao schema 1.1 atribuía a cada janela de quatro horas métricas
rolantes de 30 dias e snapshots dos 400 registros mais recentes. Assim, a
quantidade de probes e a duração transcorrida eram reais, mas a cobertura de
decisões, o p95, a taxa de erro e o drift não pertenciam necessariamente à
janela. As quatro/seis janelas e seus `FAIL`/`STOP` permanecem como trilha
histórica, porém não podem ser citados como avaliação temporal válida de SLO.

O schema 1.1 registra intervalo `[start, end)`, decisões únicas e cobertura. Uma
janela só pode produzir p95/taxa de erro quando houver decisões novas e
cobertura temporal suficiente; espera p95 de fila permanece
`INSUFFICIENT_DATA`, pois a fonte disponível guarda apenas percentis por ciclo.
Contexto rolante legado é preservado e explicitamente separado da evidência da
janela. Ainda não há, nesta documentação, uma nova série temporal válida que
autorize aprovar ou reprovar o SLO.

Separadamente, `validate_accelerated_proxy_windows.py` criou três partições por
contagem, com 372/371/371 registros e grupos sem sobreposição. Elas exercitam o
mecanismo técnico sobre rótulos-proxy; não são janelas temporais. Os estados
`production_slo_estimated=false` e `semantic_correctness_confirmed=false`
permanecem obrigatórios.

Diagnósticos definidos na política:

- imediato: qualquer erro automático crítico ou DLQ aberta;
- `STOP`: drift acima do limite, sem retreinamento automático;
- degradação: p95, fila ou disponibilidade fora do SLO por janela definida;
- continuidade: restore aprovado com mais de 168 horas;
- segurança: mudança de role, digest de imagem, workflow ou política.

## Drift

O detector exige ao menos 200 observações na referência e na janela corrente.
Usa Jensen–Shannon para variáveis categóricas e PSI para histogramas numéricos.
Snapshots sem variáveis comparáveis retornam `INCOMPATIBLE_SNAPSHOTS`, nunca
`PASS`. Drift indica mudança de distribuição, não queda comprovada de acurácia.
No runtime atual, `automatic_stop_enforced=false` e o escopo é
`READ_ONLY_DIAGNOSTIC_NO_RUNTIME_ACTUATION`: `STOP` é um diagnóstico/pedido de
bloqueio, não um atuador. Não há revisão humana, retreinamento ou promoção
automática.

## Critérios ainda pendentes

- aceitar formalmente responsáveis, tolerância de risco e SLO;
- aprovar formalmente os limiares, responsáveis e RTO/RPO;
- promover workflows e credenciais sintéticas para a homologação sem copiar
  tickets reais, caso se deseje E2E também nessa stack;
- implementar e ensaiar a atuação operacional do `STOP`, caso esse gate deva
  bloquear o runtime, ou manter sua natureza apenas diagnóstica explicitamente;
- rotacionar credenciais históricas e decidir separadamente sobre reescrita do
  histórico Git;
- revisão independente de segurança, privacidade e proteção de dados.
