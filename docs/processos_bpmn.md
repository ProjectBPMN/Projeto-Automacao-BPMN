# 📐 Modelagem de Processos de Negócio (BPMN 2.0)

**Projeto:** Automação de Triagem e Classificação de Chamados GLPI com IA  
**Contexto:** Gerenciamento de Serviços de TI e Manutenção Predial (ITIL Service Desk)  
**Instituição:** IF Sudeste MG - Campus Rio Pomba  

---

## 1. Processo AS-IS (Manual Tradicional)

No processo legada (*AS-IS*), todos os chamados abertos por servidores, alunos ou colaboradores entram diretamente em uma fila única do GLPI e dependem exclusivamente da triagem manual por um fiscal/atendente humano:

`mermaid
sequenceDiagram
    actor Solicitante
    participant GLPI as GLPI Helpdesk
    actor Fiscal as Fiscal / Triador Humano
    actor Equipe as Equipe Executora (DEMO / Terceirizada)

    Solicitante->>GLPI: Abre chamado com descrição e local
    Note over GLPI: Chamado fica com status 'Novo' em fila única
    Fiscal->>GLPI: Acessa painel e lê chamados pendentes
    Fiscal->>Fiscal: Analisa manualmente se é duplicado
    Fiscal->>Fiscal: Analisa escopo (Manutenção rotineira vs Obra estrutural)
    Fiscal->>Fiscal: Identifica executor adequado (DEMO vs Contrato Terceirizado)
    Fiscal->>GLPI: Atualiza categoria, status e atribui grupo
    GLPI->>Equipe: Notifica equipe técnica responsável
    Equipe->>Solicitante: Inicia atendimento físico
`

### Gargalos e Fragilidades do Processo AS-IS:
1. **Tempo de Resposta Elevado:** Chamados críticos podem aguardar horas ou dias até a triagem manual inicial.
2. **Duplicidade Despercebida:** Múltiplos chamados para o mesmo incidente (ex.: falta de energia em um bloco) geram alocações redundantes de técnicos.
3. **Inconsistência de Categorização:** Diferentes fiscais aplicam critérios subjetivos distintos para delimitar manutenção rotineira de obras estruturais.
4. **Sobrecarga Cognitiva:** Grande volume de chamados triviais consome tempo que deveria ser dedicado à gestão fiscal de contratos complexos.

---

## 2. Processo TO-BE (Automação Híbrida Local-First com Human-in-the-Loop)

No processo automatizado (*TO-BE*), o sistema intercepta os chamados via webhook assíncrono e executa deduplicação e classificação determinístico-probabilística com abstenção conservadora:

`mermaid
flowchart TD
    Start([Novo Chamado Aberto no GLPI]) --> Webhook[Hook HTTP Assíncrono]
    Webhook --> WF06[WF06: Fila IA Ingress com Advisory Lock]
    WF06 --> DB[(PostgreSQL: Fila & Proveniência)]
    
    DB --> WF01[WF01: Sincronizador / Despachante]
    WF01 --> WF02[WF02: Deduplicação Híbrida]
    
    subgraph Triagem_Deduplicacao [WF02: Deduplicação Semântica]
        WF02 --> CheckDedup{Similaridade Vetorial >= 0.95 & Margem >= 0.035?}
        CheckDedup -- Sim --> MarkDup[Marcar como Duplicado no GLPI]
        CheckDedup -- Abstenção / Dúvida --> RouteFiscalDedup[Encaminhar para Validação Humana]
        CheckDedup -- Não --> AdvanceClassif[Prosseguir para Classificação]
    end
    
    AdvanceClassif --> WF03[WF03: Classificação Híbrida]
    
    subgraph Classificacao_IA [WF03: Classificação com Gates]
        WF03 --> CheckGates{Passou nos Gates Determinísticos?<br/>Informação Suficiente & Sem Contradição}
        CheckGates -- Falha / Baixa Confiança < 0.65 --> Abstain[Abstenção Segura: TRIAGEM_MANUAL]
        CheckGates -- Aprovado --> PredModel[IBM Granite 97M + TF-IDF + Calibrador]
        PredModel --> CheckRisk{Classe Predita}
        CheckRisk -- OBRA --> ObraGate[Gate de Segurança: Requer Evidência Estrutural Explícita]
        ObraGate -- Aprovado --> TargetOBRA[Encaminhar DDI/DG]
        ObraGate -- Ambíguo --> Abstain
        CheckRisk -- DEMO --> TargetDEMO[Atribuir Equipe Interna DEMO]
        CheckRisk -- SOB_DEMANDA --> TargetSD[Encaminhar Empresa Especializada]
    end
    
    Abstain --> WF04[WF04: Decisão Fiscal / Notificação]
    TargetOBRA --> WF04
    TargetDEMO --> WF04
    TargetSD --> WF04
    MarkDup --> EndDup([Chamado Duplicado Vinculado])
    
    WF04 --> UpdateGLPI[Atualizar GLPI: Status, Categoria & Followup Privado com Confiança]
    UpdateGLPI --> EndAuto([Chamado Triado com Rastreabilidade Completa])
`

---

## 3. Matriz Comparativa: AS-IS vs. TO-BE

| Dimensão de Análise | Processo Legado (AS-IS) | Processo Automatizado (TO-BE) |
|---|---|---|
| **Arquitetura de Triagem** | Síncrona, manual, fila única | Assíncrona, baseada em microsserviços orientados a eventos (n8n + PostgreSQL) |
| **Tempo até Primeira Ação** | Horas a dias (dependente de escala humana) | ~2,5 segundos (mediana ponta-a-ponta) |
| **Deduplicação de Incidentes** | Visual e empírica (alta taxa de perda) | Vetorial densa + sparse com garantia de 0 falsos negativos em benchmark |
| **Segurança Operacional** | Suscetível a erros humanos em obras | Gates determinísticos com limite superior de erro crítico $\text{UCB}_{95} \le 2,30\%$ |
| **Governança e Auditoria** | Histórico básico de alterações no GLPI | Rastreamento integral em banco relacional (un_id, prompt_version, latência, tensores) |
| **Tratamento de Incerteza** | Decisão forçada ou acúmulo de fila | Abstenção formal (*selective classification*) com encaminhamento priorizado ao fiscal |
