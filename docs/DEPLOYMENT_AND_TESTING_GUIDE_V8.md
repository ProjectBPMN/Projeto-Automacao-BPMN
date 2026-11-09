# 📋 GUIA COMPLETO DE DEPLOYMENT E TESTES
**Versão 8 - n8n + GLPI Automation**

> **Snapshot histórico substituído pela V9.** As alegações de completude e
> produção deste guia não foram revalidadas e não representam o estado atual.
> Use `../../tutorial_reproducao_e_implantacao.md`.

---

## 1. PRÉ-REQUISITOS

- Docker Desktop instalado
- PowerShell (Windows) ou Bash (Linux/Mac)
- Git (opcional)
- Acesso à pasta raiz do projeto: `./`

---

## 2. INICIALIZAÇÃO RÁPIDA (5 minutos)

### 2.1 Iniciar Docker Compose

```powershell
# Terminal 1: Iniciar n8n + PostgreSQL + Mailpit
cd 'n8n'
docker compose up -d

# Terminal 2: Iniciar GLPI
cd 'glpi'
docker compose up -d

# Aguarde 30 segundos para inicialização completa
Start-Sleep -Seconds 30
```

### 2.2 Ativar Plugin GLPI (primeira vez apenas)

```powershell
# Plugin: Instalar
docker exec glpi-app php /var/www/html/glpi/bin/console --allow-superuser plugin:install n8nwebhook

# Plugin: Ativar
docker exec glpi-app php /var/www/html/glpi/bin/console --allow-superuser plugin:activate n8nwebhook

# Verificar status
docker exec glpi-app php /var/www/html/glpi/bin/console --allow-superuser plugin:list | Select-String "n8nwebhook"
# Output: n8nwebhook | Habilitado
```

### 2.3 Publicar Workflows n8n

```powershell
cd 'n8n\workflows\Versão8'

# Publicar todos os 3 workflows
python deploy.py --all

# Ou individualmente
python deploy.py --wf01
python deploy.py --wf02
python deploy.py --wf03
```

### 2.4 Verificação Rápida

```powershell
# Verificar n8n
curl http://localhost:5678/healthz

# Verificar GLPI
curl http://localhost:8080

# Verificar Mailpit
curl http://localhost:1025
```

---

## 3. TESTES DE WEBHOOK (PASSO A PASSO)

### 3.1 Setup para Teste de Webhook

**Passo 1: Abra o n8n**
```
URL: http://localhost:5678
Workflows → V8 - WF01 Orquestrador
```

**Passo 2: Ative o trigger de webhook**
```
Clique em "T2. Webhook GLPI"
Selecione "Listening" para ativar
```

**Passo 3: Obtenha a URL de webhook**
```
Copie a URL exibida (algo como):
http://localhost:5678/webhook/glpi-ticket-novo-<sua_chave>
```

**Passo 4: Abra GLPI em nova aba**
```
URL: http://localhost:8080
Login: glpi
Senha: admin
```

**Passo 5: Crie um novo ticket**

Caminho:
```
Menu: Assistência → Meus chamados → Adicionar
```

Preenchimento:
```
- Título: "Teste webhook - Lâmpada queimada"
- Tipo: "Requisição" (⚠️ NÃO "Incidente")
- Categoria: "Elétrica"
- Descrição: "Lâmpada queimada no bloco A, sala 101. Precisa ser trocada."
- Data de abertura: [Manual - hoje]
- Solicitante: [admin]
```

**Passo 6: Submeta o ticket**
```
Clique em "Enviar"
```

**Passo 7: Observe a execução**
```
Volte ao n8n (aba anterior)
A execução deve aparecer em ~100ms
Verifique os dados capturados
```

### 3.2 Validação de Webhook

Após criar o ticket, verifique:

**Em n8n (WF01):**
- [ ] Webhook dispara
- [ ] `tid` capturado (ID do ticket GLPI)
- [ ] `titulo`, `status`, `tipo`, `categoria` presentes
- [ ] `data_abertura` no formato correto
- [ ] Modo = `INCREMENTAL`
- [ ] Origem = `WEBHOOK`

**Em GLPI:**
- [ ] Ticket visível em "Meus chamados"
- [ ] Status = "Novo"

**Em PostgreSQL:**
```powershell
docker exec projeto-ic-postgres-1 psql -U glpi -d glpi -c "SELECT ticket_id, titulo, status FROM tickets_processados ORDER BY created_at DESC LIMIT 1;"
# Deve mostrar o ticket recém criado
```

**Em n8n WF02:**
- [ ] Execução automática dispara após WF01 terminar
- [ ] Classificação IA executada
- [ ] Status de triagem atualizado

---

## 4. TESTES DOS 3 TRIGGERS

### 4.1 Trigger 1: Manual (Bootstrap)

**Quando usar:** Primeira execução ou sincronização forçada

**Como testar:**
```powershell
# n8n UI
Workflows → WF01 Orquestrador
Nó: T1. Bootstrap Manual
Clique em "Test"
Selecione: modo=SCHEDULE, origem=MANUAL
```

**Validação:**
- [ ] Busca TODOS os tickets (Novo + Pendente + histórico 90 dias)
- [ ] PostgreSQL populado com histórico
- [ ] WF02 dispara para cada ticket

### 4.2 Trigger 2: Webhook (24/7)

**Quando usar:** Novo ticket chega em tempo real

**Como testar:**
```powershell
# Siga os passos 3.1 - 3.2 acima
```

**Validação:**
- [ ] Dispara ~100ms após ticket criado
- [ ] Processa apenas novo ticket (não histórico)
- [ ] Modo = INCREMENTAL

### 4.3 Trigger 3: Schedule (06h/12h)

**Quando usar:** Sincronização periódica programada

**Como testar (simular):**
```powershell
# n8n UI
Workflows → WF01 Orquestrador
Nó: T3. Schedule Periodico
Clique em "Execute node"
# Simula execução do schedule
```

**Validação:**
- [ ] Busca Pendente + Planejado + Solucionado + Fechado
- [ ] Respeita janela de 90 dias
- [ ] Executa às 06h00 e 12h00 (use `date` para verificar)
- [ ] Não bloqueia webhook

### 4.4 Teste de Concorrência (Webhook + Schedule)

**Objetivo:** Provar que ambos executam em paralelo

**Como testar:**
```powershell
# 1. Configure schedule para daqui 2 minutos
docker exec projeto-ic-postgres-1 psql -U glpi -d glpi -c "UPDATE n8n_schedule SET next_trigger = NOW() + INTERVAL '2 minutes'"

# 2. Crie um ticket no GLPI (ativa webhook)

# 3. Observe n8n:
# - Webhook executa imediatamente
# - Schedule também dispara (não bloqueado)
# - Ambos na lista de execuções simultâneas
```

---

## 5. TESTES DE CLASSIFICAÇÃO IA

### 5.1 Teste Classificação: OBRA

**Criar ticket:**
```
Título: "Construir novo galpão no campus"
Descrição: "Necessário construir novo galpão anexo ao bloco D. 
Projeto aprovado. Envolve novas fundações e estrutura de concreto."
```

**Validação:**
- [ ] IA classifica como OBRA
- [ ] Email enviado para DDI/DG (Mailpit)
- [ ] GLPI ticket fechado
- [ ] PostgreSQL marca: `tipo_servico=OBRA`, `triagem_status=CLASSIFICADO`

**Ver email em Mailpit:**
```
http://localhost:1025
Deve haver email com assunto: "NOVO CHAMADO - OBRA SOLICITADA"
```

### 5.2 Teste Classificação: DEMO

**Criar ticket:**
```
Título: "Lâmpada queimada no bloco A"
Descrição: "Luminária com 3 lâmpadas queimadas na sala 101. 
Precisa de simples substituição. Equipe tem em estoque."
```

**Validação:**
- [ ] IA classifica como MANUTENÇÃO (DEMO)
- [ ] GLPI status → "Em atendimento (atribuído)"
- [ ] PostgreSQL: `tipo_servico=DEMO`, `executor=DEMO`
- [ ] Sem email (não é OBRA)

### 5.3 Teste Classificação: SOB_DEMANDA

**Criar ticket:**
```
Título: "Ar condicionado com problema"
Descrição: "Ar condicionado da sala de aula 203 não está refrigerando. 
Dreno entupido. Precisa limpeza profissional do sistema."
```

**Validação:**
- [ ] IA classifica como MANUTENÇÃO (SOB_DEMANDA)
- [ ] GLPI status → "Em atendimento (planejado)"
- [ ] PostgreSQL: `tipo_servico=SOB_DEMANDA`

---

## 6. TESTES DE DEDUPLICAÇÃO

### 6.1 Criar Dois Tickets Duplicados

**Ticket 1:**
```
Título: "Problema com torneira da sala 105"
Descrição: "A torneira do banheiro da sala 105 está pingando constantemente. 
Causa vazamento e dano ao piso. Necessário reparo urgente."
```

**Ticket 2 (alguns minutos depois):**
```
Título: "Vazamento no banheiro da sala 105"
Descrição: "Banheiro da sala 105 com vazamento. A torneira está danificada 
e precisa de conserto para parar o vazamento."
```

### 6.2 Validar Detecção

**Após ambos processados:**
- [ ] WF02 detecta duplicação
- [ ] Ticket 2 marcado como `[Duplicado]`
- [ ] Ticket 2 status → `DUPLICADO_PENDENTE`
- [ ] PostgreSQL armazena: ID do ticket duplicado, motivo

**Links de decisão fiscal criados:**
- [ ] Link "Confirmar duplicado" → WF03
- [ ] Link "Não duplicado" → Reclassificação

### 6.3 Teste Decisão: Confirmar

**Simular clique do fiscal:**
```powershell
# Enviar webhook de decisão
curl -X GET "http://localhost:5678/webhook/fiscal-decisao-<FISCAL_KEY>?decisao=confirmar&chamado_id=XX&ref_id=YY"
```

**Validação:**
- [ ] WF03 processa decisão
- [ ] Ticket Ticket 2 fechado em GLPI
- [ ] PostgreSQL: `triagem_status=DUPLICADO_FECHADO`
- [ ] Ticket 1 segue para classificação normal

### 6.4 Teste Decisão: Rejeitar

**Simular clique do fiscal:**
```powershell
# Enviar webhook de decisão
curl -X GET "http://localhost:5678/webhook/fiscal-decisao-<FISCAL_KEY>?decisao=nao_duplicado&chamado_id=XX&ref_id=YY"
```

**Validação:**
- [ ] WF03 remove marca `[Duplicado]`
- [ ] PostgreSQL: `triagem_status=ERRO_IA` (para reprocessamento)
- [ ] WF02 executa novamente com reclassificação
- [ ] Ticket agora segue fluxo de classificação normal

---

## 7. TESTES AUTOMATIZADOS

### 7.1 Smoke Test Completo

```powershell
cd 'n8n\workflows\Versão8'
powershell -ExecutionPolicy Bypass -File .\test_smoke.ps1
```

**O que testa:**
- ✓ Workflows publicados
- ✓ GLPI respondendo
- ✓ Plugin ativo
- ✓ PostgreSQL conectado
- ✓ Mailpit respondendo

### 7.2 Teste de Cobertura de Nós

```powershell
# Verificar execuções recentes
$wf01_exec = curl -s "http://localhost:5678/api/v1/workflows/xT6qaPlpVMq8gA0g/executions" -H "X-N8N-API-KEY: $(Get-Content api_key.txt)" | ConvertFrom-Json

# Analisar nós executados
$wf01_exec.data | ForEach-Object {
  $nodes = $_.data.resultData.runData | Get-Member -MemberType NoteProperty | Select-Object -ExpandProperty Name
  Write-Host "Execução $($_.id): $($nodes.Count) nós"
}
```

---

## 8. MONITORAMENTO EM TEMPO REAL

### 8.1 Logs n8n

```powershell
# Ver logs n8n em tempo real
docker logs -f n8n

# Ou via Dashboard:
# http://localhost:5678/debug
```

### 8.2 Logs GLPI

```powershell
docker logs -f glpi-app | Select-String "n8nwebhook"
```

### 8.3 Logs PostgreSQL

```powershell
# Ver últimos tickets inseridos
docker exec projeto-ic-postgres-1 psql -U glpi -d glpi -c "SELECT id, ticket_id, titulo, triagem_status, updated_at FROM tickets_processados ORDER BY updated_at DESC LIMIT 10;"
```

### 8.4 Logs Mailpit

```powershell
# Acessar UI
# http://localhost:1025

# Ou via CLI
docker exec mailpit mailpit --version
```

---

## 9. TROUBLESHOOTING COMUM

### Problema: "Webhook não dispara"

**Causas comuns:**
1. Plugin não ativado no GLPI
2. URL de webhook incorreta
3. Firewall bloqueando requisição

**Solução:**
```powershell
# 1. Verificar plugin
docker exec glpi-app php /var/www/html/glpi/bin/console --allow-superuser plugin:list | Select-String "n8nwebhook"

# 2. Testar URL webhook manualmente
curl -X POST "http://localhost:5678/webhook/glpi-ticket-novo-test" `
  -H "Content-Type: application/json" `
  -d '{"test": "ok"}'

# 3. Verificar logs
docker logs glpi-app | tail -50
docker logs n8n | tail -50
```

### Problema: "IA retorna erro"

**Mensagem:** "Classificacao não é valida"

**Causas:** API OpenAI indisponível, rate limit, prompt inadequado

**Solução:**
```powershell
# 1. Verificar chave API n8n
echo $env:OPENAI_API_KEY

# 2. Testar chamada IA manualmente
curl -X POST "https://api.openai.com/v1/chat/completions" `
  -H "Authorization: Bearer $env:OPENAI_API_KEY" `
  -d '{"model":"gpt-4","messages":[{"role":"user","content":"teste"}]}'

# 3. Ticket marcado como ERRO_IA para reprocessamento
```

### Problema: "PostgreSQL vazio"

**Sintoma:** Tabela `tickets_processados` não tem dados

**Solução:**
```powershell
# 1. Verificar tabela existe
docker exec projeto-ic-postgres-1 psql -U glpi -d glpi -c "\dt tickets_processados"

# 2. Se não existe, criar schema
docker exec projeto-ic-postgres-1 psql -U glpi -d glpi < 'Banco de dados chamados\init_schema.sql'

# 3. Executar WF01 manualmente para popular
```

### Problema: "Docker ports em conflito"

**Sintoma:** "Port 5678 already in use"

**Solução:**
```powershell
# Listar processos nas ports
netstat -ano | findstr "5678|8080|1025"

# Parar container
docker stop n8n glpi-app

# Ou liberar port
# taskkill /PID <PID> /F
```

---

## 10. BACKUP E RECUPERAÇÃO

### 10.1 Backup PostgreSQL

```powershell
# Backup completo
docker exec projeto-ic-postgres-1 pg_dump -U glpi glpi > "backup_$(Get-Date -Format 'yyyyMMdd_HHmmss').sql"

# Backup apenas tabela de tickets
docker exec projeto-ic-postgres-1 pg_dump -U glpi -t tickets_processados glpi > backup_tickets.sql
```

### 10.2 Restaurar PostgreSQL

```powershell
# Restaurar de arquivo
docker exec -i projeto-ic-postgres-1 psql -U glpi glpi < backup_tickets.sql
```

### 10.3 Backup Plugin GLPI

```powershell
# Copiar plugin
Copy-Item -Path 'glpi\plugins\n8nwebhook' `
          -Destination 'c:\backup\n8nwebhook_backup' `
          -Recurse
```

---

## 11. CHECKLIST DE VALIDAÇÃO FINAL

Antes de declarar 100% funcional:

- [ ] **Webhook:** Novo ticket no GLPI → WF01 dispara em <100ms
- [ ] **Schedule:** Executa 06h e 12h (sem bloquear webhook)
- [ ] **Manual:** Bootstrap executa com histórico completo
- [ ] **Classificação OBRA:** Email enviado, ticket fechado
- [ ] **Classificação DEMO:** Status → "Em atendimento (atribuído)"
- [ ] **Classificação SOB_DEMANDA:** Status → "Em atendimento (planejado)"
- [ ] **Deduplicação:** Detecta corretamente, marca [Duplicado]
- [ ] **Decisão Fiscal:** Confirmar fecha ticket, Rejeitar reclassifica
- [ ] **PostgreSQL:** Todos os tickets armazenados com status correto
- [ ] **Mailpit:** Emails OBRA entregues sem erro
- [ ] **Concorrência:** Webhook + Schedule simultâneos = OK
- [ ] **Sem gargalo:** Sem Loop Over Items, execução assíncrona

---

## 12. PRÓXIMOS PASSOS

1. **Configurar alertas/monitoring:**
   - Zabbix, Prometheus, ou similar
   - Notificações de falha em WF02/WF03

2. **Integrar histórico:**
   - Importar tickets antigos do GLPI
   - Popular PostgreSQL com dados históricos

3. **Customização:**
   - Ajustar prompts IA conforme necessário
   - Adicionar mais categorias/tipos de serviço

4. **Escalabilidade:**
   - Aumentar recursos container (CPU/RAM)
   - Implementar queue system (RabbitMQ, Redis)

---

**Status histórico:** V8 substituída; nenhuma garantia de correção total ou
prontidão produtiva é mantida.

Data: 07/05/2026
