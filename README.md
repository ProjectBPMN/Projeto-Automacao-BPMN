# Triagem e Classificação Inteligente de Chamados de Manutenção com n8n, GLPI e IA Local

Repositório de artefatos de pesquisa e plataforma de reprodutibilidade experimental para o artigo submetido sobre automação de processos de triagem, detecção de duplicidade e classificação de chamados de manutenção predial institucional.

A arquitetura combina orquestração de processos orientada a BPMN implementada em **n8n**, integração com **GLPI**, persistência transacional em **PostgreSQL** e um microsserviço de **IA local** (arquitetura híbrida TF-IDF + embeddings semânticos) voltado à privacidade, soberania de dados e operação em hardware convencional.

---

## Visão Geral da Arquitetura

O sistema opera de forma desacoplada por meio de mensageria com garantia de entrega e trilhas completas de auditoria:

```text
[ GLPI / Usuário ]
        │  (Webhook de abertura de chamado)
        ▼
┌────────────────────────────────────────────────────────────────────────┐
│ n8n — Orquestração de Processos (V9)                                   │
│                                                                        │
│  WF06 (Ingresso & Fila) ──► WF02 (Deduplicação) ──► WF03 (Classificação)│
│                                                            │           │
│  WF01 (Reconciliação)   ◄── WF05 (Telemetria)   ◄── WF04 (Execução)    │
└──────────────┬─────────────────────────────┬───────────────────────────┘
               │                             │
               ▼                             ▼
       ┌───────────────┐             ┌────────────────┐
       │  PostgreSQL   │             │    Local AI    │
       │ Fila, Eventos │             │ (Microserviço  │
       │   & Decisões  │             │  Híbrido CPU)  │
       └───────────────┘             └────────────────┘
```

### Componentes Principais

- **WF06 — Ingresso e Fila**: Autentica requisições externas, higieniza cargas e enfileira tickets no PostgreSQL com bloqueio transacional seguro contra concorrência (*lease*).
- **WF02 — Deduplicação**: Recupera candidatos históricos relevantes e consulta o serviço de IA para aferir similaridade semântica e contextual, prevenindo retrabalho em equipes de manutenção.
- **WF03 — Classificação**: Encaminha o chamado para as categorias de serviço apropriadas (`DEMO`, `OBRA`, `SOB_DEMANDA` ou `TRIAGEM_MANUAL`), registrando probabilidades para auditoria.
- **WF04 — Execução e Notificação**: Atualiza o status do chamado no GLPI via REST API e emite comunicações rastreáveis.
- **WF05 & WF01 — Telemetria e Reconciliação**: Monitora latência, desvios e garante reprocessamento controlado de pendências sem perda de dados.
- **Local AI**: Serviço leve em Python/PyTorch FP32 executado inteiramente em CPU, eliminando dependência de APIs em nuvem e garantindo confidencialidade institucional estrita.

---

## Estrutura do Repositório

```text
├── .github/workflows/       # Pipeline de Integração Contínua (CI)
├── avaliacao/               # Protocolos estatísticos, datasets sintéticos e scripts de validação
│   ├── config/              # Parâmetros experimentais e configurações de modelos
│   ├── datasets/            # Corpus sintético controlado para testes e validação
│   ├── operacional/         # Auditoria de segredos, telemetria e controles operacionais
│   ├── resultados/          # Evidências e recibos de execução com hashes criptográficos
│   ├── scripts/             # Scripts executáveis de treinamento, calibração e auditoria
│   └── tests/               # Testes automatizados da esteira de avaliação científica
├── glpi/                    # Docker Compose e configurações de inicialização do GLPI
├── local_ai/                # Microsserviço de inferência local (embeddings e classificação)
├── n8n/                     # Definições, histórico e builders dos fluxos de trabalho
│   ├── history/             # Snapshots públicos sanitizados das versões históricas (V1 a V8)
│   └── workflows/Versão9/   # Especificações ativas, builders e testes da arquitetura V9
├── scripts/                 # Validadores de integridade, perfil TLS e barreiras de distribuição
├── CITATION.cff             # Metadados formais de citação de software
├── DEPLOYMENT_AND_VALIDATION_V9.md # Checklist de implantação e hardening técnico
├── LICENSE                  # Licença de código aberto Apache-2.0
├── NOTICE                   # Avisos de direitos autorais e governança de dados
├── QUICK_START.md           # Guia direto de configuração e subida local
├── requirements.txt         # Dependências Python reproduzíveis
└── SECURITY.md              # Diretrizes de segurança e divulgação de vulnerabilidades
```

---

## Instruções para Avaliadores (Peer Review)

Para avaliar e reproduzir os resultados do trabalho, o repositório oferece tanto a suíte hermética automatizada quanto a opção de subida completa dos contêineres locais.

### Pré-requisitos

- **Python**: versão 3.12 ou superior
- **Docker & Docker Compose** (para testes com as interfaces completas do n8n e GLPI)
- **Git**

---

### Procedimento de Instalação e Teste Rápido

#### 1. Clonar o repositório e preparar o ambiente Python

```bash
git clone https://github.com/ProjectBPMN/Projeto-Automacao-BPMN.git
cd Projeto-Automacao-BPMN

python -m venv .venv
# Linux/macOS:
source .venv/bin/activate
# Windows:
.venv\Scripts\activate

pip install --upgrade pip
pip install -r requirements.txt
```

#### 2. Configurar variáveis de ambiente de teste

Copie os arquivos de modelo (os exemplos já possuem configurações prontas para testes locais seguros):

```bash
# Windows (PowerShell):
if (!(Test-Path n8n/.env)) { Copy-Item n8n/.env.example n8n/.env }

# Linux/macOS (Bash):
[ ! -f n8n/.env ] && cp n8n/.env.example n8n/.env
```

#### 3. Executar a suíte de testes de reprodução

Para validar todos os contratos do microsserviço de IA, verificações de integridade criptográfica, segurança operacional e barreiras de consistência sem necessidade de subir contêineres:

```bash
python -m pytest -q -m "not live_integration" -p no:cacheprovider
```

*Resultado esperado: 414 testes aprovados sem falhas.*

#### 4. Validar os artefatos estáticos e o histórico de workflows

```bash
# Validação da barreira de integridade pública
python scripts/validate_public_release.py --source manifest --json

# Validação estrutural dos workflows n8n e do histórico sanitizado
python n8n/workflows/Versão9/validate_v9_static.py
python n8n/history/validate_history.py --check-sources

# Auditoria de consistência conceitual da documentação
python avaliacao/scripts/validar_consistencia_cientifica_docs.py
python scripts/validate_tls_profile.py
```

---

### Execução Completa com Contêineres (Opcional)

Caso deseje inspecionar as interfaces gráficas e a execução ponta a ponta:

1. **Subir os serviços**:
   ```powershell
   docker compose -f glpi/docker-compose.yml up -d
   docker compose -f n8n/docker-compose.yml up -d
   ```
2. **Iniciar o microsserviço local de IA**:
   ```powershell
   ./local_ai/scripts/start-local-ai.ps1 -CpuThreads 2 -MaxEmbedBatch 1
   ```
3. **Publicar os workflows na instância do n8n**:
   ```powershell
   python n8n/workflows/Versão9/deploy.py
   ```
   *Painéis disponíveis localmente:*
   - n8n: `http://localhost:5678`
   - GLPI: `http://localhost:9080` (ou porta configurada no `.env`)
   - Local AI (healthcheck): `http://127.0.0.1:8090/health`

---

## Reprodutibilidade e Rigor Metodológico

- **Preservação Histórica e Evolutiva**: O diretório `n8n/history/` preserva as versões anteriores (V1 a V8) devidamente auditadas e sanitizadas, permitindo acompanhar a evolução da maturidade dos processos de automação.
- **Corpus Experimental Controlado**: Em observância à LGPD e às diretrizes de revisão duplo-cego (*double-blind review*), os chamados utilizados nos testes automatizados e nas suítes públicas utilizam dados sintéticos controlados e núcleos narrativos anonimizados.
- **Rastreabilidade Criptográfica**: Todos os conjuntos de dados de desenvolvimento, parâmetros de planos de teste e saídas de sumarização possuem hashes SHA-256 validados automaticamente por testes de regressão.
- **Transparência Científica**: O repositório documenta com rigor os limites de escopo das validações em ambiente de laboratório, distinguindo testes herméticos de integração de testes longitudinais em ambiente produtivo.

---

## Anonimização para Avaliação por Pares (Double-Blind)

Este repositório foi sanitizado especificamente para a submissão do artigo:
- Todas as identidades de autores, credenciais privadas, tokens de acesso, endereços de rede institucionais e caminhos absolutos de máquinas de desenvolvimento foram descaracterizados ou substituídos por valores de demonstração seguros.
- O histórico de commits e os metadados do projeto foram padronizados sob a identidade anônima de pesquisa `ProjectBPMN`.

---

## Licença

Este projeto é disponibilizado sob a licença de código aberto **Apache 2.0**. Consulte o arquivo [LICENSE](LICENSE) e os esclarecimentos de governança em [NOTICE](NOTICE).

Para citar este trabalho em publicações acadêmicas, consulte os metadados em formato padrão no arquivo [CITATION.cff](CITATION.cff).
