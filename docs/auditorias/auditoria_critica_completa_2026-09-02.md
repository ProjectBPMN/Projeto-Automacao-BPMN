# Auditoria crítica completa — 2 de setembro de 2026

## Parecer executivo

O projeto está funcional como protótipo local e homologação técnica sintética,
mas não está cientificamente confirmado nem certificado para produção. Essa
distinção é obrigatória: testes, proxy labels, E2E e paridade de workflow
validam engenharia nos cenários observados; não demonstram correção semântica
universal.

Em 02/09 foram concluídos os reparos operacionais executáveis sem chamados
reais, espera superior a um dia, revisão humana ou revisão em pares:

- DDL removido do WF05 e mantido em migração administrada;
- PostgreSQL separado em login de migração e login runtime de menor privilégio;
- sandbox do n8n ativa, acesso do Code node a `$env` bloqueado e runners
  externos endurecidos;
- healthchecks de n8n, GLPI, PostgreSQL, gateways e IA observados;
- coletor instalado como tarefa oculta com `pythonw.exe`, sem terminal visível;
- 84 DLQs históricas e 129 estados `ERRO_IA` reconciliados sem apagar a trilha;
- fila ativa, `ERRO_IA` e DLQ aberta zerados após o E2E final;
- carga limitada, falhas isoladas, restore do volume n8n e homologação isolada;
- três janelas técnicas aceleradas, disjuntas por grupo, com rótulos-proxy;
- E2E sintético WF06→WF02→WF03 aprovado e com cleanup completo;
- V1–V8 preservados em arquivo público sanitizado e validado;
- n8n inspecionado autenticado no navegador; GLPI abriu, mas sua sessão havia
  expirado e o novo login requer confirmação no momento de transmitir a senha;
- varredura de segredos executada na árvore candidata e no histórico Git.

## O que foi validado

| Área | Evidência | Resultado | Limite |
|---|---|---|---|
| Workflows V9 | build, validação estática, deploy e releitura | seis ativos e com paridade | não prova todas as entradas |
| E2E | `e2e-pipeline-local-v1.8.0-20260902-1950.json` | PASS, sintético, cleanup completo | não mede acurácia real |
| Fila/DLQ | `estado-runtime-final-20260902.json` | 0 ERRO_IA, 0 fila ativa, 0 DLQ aberta | fotografia operacional |
| PostgreSQL | `postgres-menor-privilegio-20260902.json` | DML permitido, DDL negado com 42501 | não substitui auditoria externa |
| n8n | Compose + auditoria estática | sandbox ativa; runners externos; segredos fora de Code | versão 2.10.3 requer plano de atualização |
| GLPI | healthcheck e HTTP | saudável em porta local 9180 | login visual final pendente |
| Carga | cenários C1 e C4 | C1 40/40; C4 saturou com 20/40 e 429 | carga limitada, não mensal |
| Restore n8n | `restore-volume-n8n-20260902.json` | PASS; 30 workflows exportados; RTO técnico 0,711 min | destino isolado |
| Homologação | `homologacao-isolada-20260902.json` | nove serviços saudáveis; zero tickets; role mínima | infraestrutura sem dados reais |
| Monitoramento | tarefa `ProjetoIC-Monitoramento` | oculta, execução 0, intervalo 1 min | coleta local, não SLO de produção |
| Janelas | `janelas-aceleradas-proxy-20260902.json` | 3/3 técnicas; sem vazamento de grupo | não longitudinal |
| Histórico | `n8n/history/validate_history.py` | 10 JSONs cobrem V1–V8; hashes íntegros | snapshots não provam correção antiga |

## Pontos fortes

### Engenharia

- builders determinísticos e separação entre fonte, JSON publicado e hash;
- fila com lock, lease, retry, DLQ, telemetria, reconciliação idempotente e
  limpeza controlada de ensaio;
- operação local-only sem fallback silencioso para Gemini;
- credenciais isoladas em proxies e role PostgreSQL runtime sem privilégios de
  criação, superusuário, replicação ou bypass de RLS;
- imagens Docker por digest, portas em loopback, runners read-only, sem
  privilégios novos e sem capabilities;
- evidência explícita para restore, carga, falha, E2E, homologação e estado da
  fila;
- histórico V1–V8 público, inativo, sanitizado e verificável.

### Método científico

- comparação uniforme de Granite 97M, E5-small e MiniLM-L12;
- ablações TF-IDF, embedding e híbrido;
- árvore, SVM, regressão logística, MLP e XGBoost no mesmo protocolo;
- agrupamento por dependência-fonte, OOF, calibração, risco-cobertura,
  bootstrap por grupo e comparações pareadas;
- SHAP com teste de aditividade e interpretação não causal;
- gates que bloqueiam deduplicação subdimensionada e candidatos com boa média,
  mas cobertura/risco inadequados;
- documentação distingue evidência técnica, desenvolvimento proxy e
  confirmação científica.

## Pontos fracos e críticas

### Ciência

1. Os rótulos são proxy/sintéticos. Eles medem concordância com o gerador ou
   regra, não correção institucional.
2. A decisão de excluir revisão humana e em pares impede um gabarito
   independente. Nenhum número deve ser chamado de confirmatório.
3. Deduplicação tem só 12 famílias; não há base para ajustar e validar 55
   configurações com independência adequada.
4. Nenhuma configuração classificatória passou todos os gates. O primeiro
   colocado hierárquico continua `UNDERPOWERED`.
5. O melhor Macro-F1 bruto foi do MLP/E5 com cobertura zero. Logo “maior
   Macro-F1” não significa “melhor automação”.
6. O híbrido não venceu claramente TF-IDF na comparação pareada; a justificativa
   do embedding ainda é hipótese plausível, não superioridade demonstrada.
7. As três janelas aceleradas variaram muito: risco seletivo proxy de 13,91%,
   1,77% e 4,95%. A média agregada esconderia heterogeneidade relevante.
8. SHAP explica atribuições no modelo/corpus; não valida causalidade, justiça ou
   semântica.

### Operação e segurança

1. O n8n 2.10.3 está atrás da versão oficial mais recente observada na
   auditoria; atualizar exige ensaio de compatibilidade dos runners e fluxos.
2. A auditoria n8n ainda aponta credencial Gemini não usada, workflows antigos
   no banco e alertas de SQL dinâmico. Eles não foram ocultados.
3. O GLPI deste host precisou mudar de 9080 para 9180 porque o Windows reserva o
   intervalo 9060–9159. Scripts agora derivam a porta configurada.
4. A homologação foi instanciada sem copiar tickets reais. Ela prova isolamento
   e infraestrutura, mas os workflows/credenciais de aplicação não foram
   promovidos como se fossem produção.
5. O monitoramento é local e os SLOs permanecem propostas não aprovadas. Três
   partições aceleradas não estimam disponibilidade de dias/meses.
6. A árvore candidata pode ser limpa, mas o histórico Git alcançável contém
   segredos antigos em `.env`, exportação de credenciais, memória e backup com
   chave privada. Remover no commit não apaga versões remotas anteriores.

## Estatísticas e seleção

Na classificação V2.1 foram avaliados 1.114 registros em 111 grupos, 35
configurações, 175 dobras e 38.990 predições OOF. O primeiro colocado pela regra
hierárquica — híbrido + multilingual-e5-small + SVM linear — teve Macro-F1
0,7987, acurácia 0,8312, cobertura 0,6086 e risco seletivo 0,0693. Seus
intervalos agrupados foram amplos e o limite superior unilateral do risco
crítico permaneceu em 4,57% com 64 grupos expostos.

Com zero eventos críticos, pelo menos 149 exposições independentes são
necessárias para limite unilateral inferior a 2%. Se as duas direções críticas
usarem grupos disjuntos, um planejamento inicial de 298 famílias, acrescido de
perdas e efeito de desenho, é coerente. Isso é planejamento de potência, não
garantia de resultado.

Os números completos, incluindo classificadores, recuperação e SHAP, estão em
`docs/resultados_estatisticos_e_comparativo_gemini.md`.

## Três janelas e SLO/drift sem esperar dias

O requisito foi reinterpretado dentro do escopo explicitamente permitido:
três janelas determinísticas por contagem, com grupos disjuntos, 372/371/371
registros proxy e três sondagens locais. O mecanismo técnico e os checks de
drift passaram, sem chamados reais e sem espera longitudinal.

Isso encerra a pendência de **teste das janelas técnicas**, mas não uma janela
de SLO de produção. `production_slo_estimated=false` permanece no artefato.
Trocar esse rótulo por “SLO mensal comprovado” seria inflar o resultado.

## Varredura de segredos e GitHub

A varredura final deve ser lida em duas partes:

- árvore candidata: precisa resultar sem achados de alta confiança antes do
  commit;
- histórico alcançável: contém credenciais/chaves antigas e exige rotação. Uma
  reescrita do histórico remoto seria destrutiva e não foi autorizada.

Por isso, um commit normal pode retirar segredos da ponta da branch, mas não
permite declarar o histórico limpo. O push só deve ocorrer depois de testes,
fetch/divergência e decisão explícita sobre rotação/reescrita quando necessária.

## Estado de prontidão

`production_ready=false`, `scientific_ready=false` e
`confirmatory_claim_allowed=false` são os estados corretos. O projeto está:

- funcional nos cenários locais e sintéticos exercitados;
- reproduzível no escopo classificatório proxy;
- protegido por abstinência/fail-closed e rollback técnico;
- não confirmado semanticamente;
- não certificado para disponibilidade longitudinal;
- não autorizado a alegar “melhor modelo” de forma geral.

## O que permanece fora do escopo por decisão

- chamados reais;
- observação superior a um dia;
- revisão humana;
- revisão em pares;
- holdout com gabarito independente.

Essas exclusões não impedem entregar um protótipo técnico forte. Elas impedem
somente transformar seus resultados em confirmação científica ou garantia de
produção.
