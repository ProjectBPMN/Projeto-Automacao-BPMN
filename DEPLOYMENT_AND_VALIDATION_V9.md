# Implantação e validação da arquitetura V9

**Revisão:** 03/09/2026
**Status:** candidata operacional validada tecnicamente no ambiente local;
eficácia científica e prontidão produtiva pendentes.

## Arquitetura

```text
GLPI/plugin
  → WF06 autentica, enfileira e reserva
  → WF02 deduplica
  → WF03 classifica
  → WF04 aplica decisão fiscal/comunicação
  → WF05 consolida telemetria
  ↔ WF01 sincroniza/reconcilia
  ↔ PostgreSQL registra fila, eventos, tentativas e decisões
  ↔ local_ai executa o bundle v1.8 congelado
```

## Publicação

Depois de configurar `.env` locais e subir os composes:

```powershell
python n8n/workflows/Versão9/validate_v9_static.py
python -m pytest -q n8n/workflows/Versão9/test_v9_hard.py
python n8n/workflows/Versão9/deploy.py
```

O deploy deve mostrar seis workflows ativos e paridade canônica. O ambiente
auditado usa `TEST_MODE=false`, `TEST_AUTO_HUMAN_CONFIRMATION=false`, escopo de
fila vazio e bundle `local-hybrid-v1.8.0`.

## Evidência exigida

| Nível | O que demonstra | O que não demonstra |
|---|---|---|
| teste hermético | contratos e regressões de código | serviço live |
| validação estática | estrutura e invariantes dos JSONs | execução |
| paridade de deploy | lógica publicada igual à canônica | eficácia |
| smoke live | health, banco e rejeição segura | caminho completo |
| E2E sintético | integração WF06→WF02→WF03 e rollback | acurácia real |
| benchmark agrupado por proxy | discriminação no corpus sintético definido | correção semântica institucional |

A rodada E2E final de 03/09/2026 passou, sem fallback, sem interferência
estranha, com fila/DLQ zeradas e cleanup completo. n8n e GLPI foram
inspecionados autenticados no navegador. Isso não autoriza a expressão “100%
correto”.

## Hardening antes de produção

1. rotação dos segredos encontrados no histórico Git;
2. TLS, firewall, cookies seguros e revisão dos nós `Code`;
3. assinatura/replay protection do webhook;
4. manter backup e restauração ensaiados periodicamente;
5. ampliar carga/concorrência sem ultrapassar o limite observado de 429;
6. aprovar institucionalmente SLOs, alertas, runbooks e rollback versionado;
7. LGPD, retenção e acesso a dados;
8. promover workflows sintéticos para a homologação separada e obter aceite;
9. manter avaliação somente por proxy, explicitando que não confirma semântica;
10. monitorar drift, cobertura, abstenção e erros proxy sem retreinamento automático.

## Homologação isolada

A stack `projeto-ic-homolog` usa portas 15678/55432/19080/28025, volumes,
redes e segredos próprios. Em 03/09 os nove serviços ficaram saudáveis, o
PostgreSQL tinha 40 tabelas, zero tickets e role runtime sem privilégios
administrativos. Não foram copiados chamados reais.

## Monitoramento sem janela visível

`avaliacao/operacional/install_monitoring.ps1` remove a antiga tarefa agendada
defeituosa e registra `ProjetoICMonitoramento` em
`HKCU\Software\Microsoft\Windows\CurrentVersion\Run`. O daemon usa
`pythonw.exe`, rejeita instâncias duplicadas e registra apenas estado sanitizado
em `avaliacao/runtime/monitoring/daemon-status.json`. Chamadas curtas ao Docker
usam `CREATE_NO_WINDOW`, evitando o terminal que aparecia a cada minuto.

Procedimento detalhado, incluindo smokes, E2E, histórico e seleção científica:
`docs/tutorial_reproducao_e_implantacao.md`.
