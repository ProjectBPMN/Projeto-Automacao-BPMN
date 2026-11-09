# Auditoria de continuidade — 9 de setembro de 2026

## Escopo e conclusão científica

Esta rodada usa somente cenários sintéticos e rótulos-proxy. Não executa revisão
humana/em pares, não usa chamados reais para avaliação e não abre o holdout.
O objetivo é verificar funcionamento e consistência dos resultados, não produzir
um resultado favorável predeterminado. `scientific_ready=false`,
`production_ready=false` e `semantic_correctness_confirmed=false` permanecem
corretos. A rota técnica `TRIAGEM_MANUAL` representa abstenção do modelo; não
significa que alguém tenha revisado ou confirmado o chamado.

## Defeitos encontrados e correções

1. **Inicialização do Docker:** sockets locais obsoletos impediam a inicialização.
   Os diretórios `Docker/run` e `docker-secrets-engine`, em AppData/Local, foram
   preservados com sufixo `.stale-20260909-1355` e recriados vazios. Nenhum volume,
   banco, imagem ou histórico do projeto foi removido. A recorrência ainda é um
   risco do host; recuperar uma inicialização não prova solução permanente.
2. **E2E interrompido:** o cleanup exigia um ticket já materializado no PostgreSQL.
   Uma falha anterior ao ingresso deixava o caso registrado e o perfil isolado.
   A propriedade agora pode ser comprovada pelo dataset/experimento sintéticos,
   mesmo sem `tickets_processados`. Cardinalidades são verificadas antes do
   commit; casos não comprovados continuam recusados.
3. **Readiness incompleta:** o healthcheck do n8n principal não demonstra execução
   pelo runner externo. O E2E agora exige a resposta 422 e o texto esperado da
   rota `Code → IF → rejeição`, usando `ticket_id=0`, antes de criar o chamado.
   Essa rota não alcança PostgreSQL ou GLPI. Os subprocessos têm timeout e
   `CREATE_NO_WINDOW`. A reinicialização resolveu o runner não responsivo nesta
   rodada; a causa permanente dos 403 de conexão não foi demonstrada.
4. **Editor desconectado:** logs demonstraram divergência entre Origin
   `localhost:5678` e Host `localhost`. O proxy agora preserva a porta com
   `$http_host` em Host e X-Forwarded-Host. A validação de origem não foi
   desativada. O navegador confirmou a reconexão e execuções WF06 bem-sucedidas.
5. **Métricas temporais incorretas:** o coletor anterior repetia métricas de 30 dias
   e os mesmos snapshots em diferentes janelas. O coletor 1.1 registra intervalos,
   deduplica decisões por ID e respeita limites temporais. Timestamps são
   comparados como instantes UTC, inclusive quando há offsets diferentes.
   Sem cobertura ou decisões novas, o resultado é insuficiente, não erro zero.
6. **Drift sem dados numéricos:** histogramas vazios agora produzem
   `INSUFFICIENT_DATA`, não exceção ou aprovação. `STOP` é diagnóstico somente
   leitura; não existe atuação automática no runtime. Percentis de percentis da
   fila não são apresentados como p95 das esperas individuais.
7. **Contagem da fila:** a captura inclui também estados de classificação e espera
   de classificação, e registra o instante da coleta. Os relatórios anteriores
   com enumeração reduzida permanecem como evidência histórica limitada.
8. **Ambiente Python incompleto:** a `.venv` foi reconstruída a partir dos
   requirements fixados; `pip check` não encontrou dependências incompatíveis.
   O primeiro startup da IA excedeu o prazo; a segunda inicialização, com caches
   aquecidos e prazo de 180 s, passou. Isso não é evidência de startup frio rápido.
9. **Trava incompleta do WF06:** a atualização do controlador com fila vazia
   podia dispensar o CTE que adquiria o advisory lock. As mutações de reserva
   expirada, quarentena, controlador e métricas agora dependem explicitamente
   de `bloqueio`. `lock-fila-20260909.json` demonstrou SQLSTATE `55P03` ao disputar
   a trava, em transação revertida. O WF06 foi regenerado, publicado e sua
   paridade confirmada. A recriação no E2E usa `--no-deps` e permite somente uma
   reinicialização de recuperação do runner, sempre exigindo a prova 422.

As tentativas `20260909-final` e `20260909-pos-readiness` permanecem falhas:
a primeira não passou readiness; a segunda concluiu as decisões mas falhou
na restauração exata do controlador. Elas motivaram os reparos e não podem ser
substituídas silenciosamente por uma rodada aprovada.

## Evidências revalidadas

| Item | Evidência desta rodada | Limite |
|---|---|---|
| Recuperação E2E 08/09 | `recuperacao-e2e-20260909.json`: perfil/controlador restaurados; GLPI ausente; removidos apenas 1 caso e 1 experimento sintéticos | o relatório de falha original permanece falho |
| Homologação | `homologacao-isolada-20260909.json`: PASS, nove serviços isolados, zero tickets, runtime sem privilégios administrativos | infraestrutura, não homologação funcional completa com tráfego |
| Histórico V1–V8 | validador `--check-sources`: PASS, dez artefatos, hashes íntegros | snapshots antigos inativos e sanitizados |
| Comparação científica | `validacao-comparativa-20260909.json`: `VALID_PARTIAL_TASK_SCOPE` | apenas classificação, desenvolvimento proxy |
| Regressão | 381 testes e 117 subtestes passaram em 135,71 s; teste posterior de offsets incluído na suíte do monitor | houve aviso WMI/Windows 0x8007000e durante import; processo terminou com código 0 |
| Navegador | login autorizado n8n/GLPI, seis V9 publicados, editor reconectado, listagem GLPI e execuções WF06 `Succeeded` | inspeção técnica, não revisão semântica dos chamados |
| Monitor | daemon `pythonw.exe`, intervalo de 60 s, inicialização HKCU Run, arquivos atualizados | coleta local, não disponibilidade contínua comprovada |
| Segredos | `varredura-segredos-20260909.json`: árvore candidata PASS/0; histórico FAIL/15 em 14.956 blobs | padrões não provam ausência absoluta; rotação continua necessária |

Os caminhos JSON da tabela, salvo indicação contrária, ficam em
`avaliacao/resultados/operacional/`. O novo E2E e a contagem pós-teste são
registrados separadamente; apenas os respectivos relatórios concluídos podem
ser usados para afirmar aprovação.

## As três janelas: o que realmente significam

`reanalise-janelas-20260909.json` reaplica o coletor corrigido à telemetria já
existente e identifica três blocos intradiários legados de quatro horas. Não
espera novos dias nem fabrica observações. As contagens de sondagens permitem
descrever disponibilidade amostrada; não demonstram disponibilidade contínua.
Nenhuma janela legada possui cobertura intervalar completa das decisões para
reconstituir latência, erro ou drift temporal. Portanto não há aprovação de SLO.
`TECHNICAL_WINDOWS_COMPLETE` significa somente duração e número de sondagens.

As três partições disjuntas por grupo do relatório
`janelas-aceleradas-proxy-20260902.json` são uma evidência diferente: exercitam
cálculos de qualidade/drift por proxy, não passagem real do tempo. Uma não
substitui a outra. Para ensaios adicionais dentro de um dia, os limites temporais
e a carga sintética devem ser definidos antes, sem reduzir duração ou tamanho
de amostra retroativamente para obter PASS. Drift requer pelo menos 200 decisões
em cada distribuição pelo protocolo atual; ausência de tráfego não é aprovação.

## Comparação e crítica dos resultados

A recomputação verifica 1.114 registros, 111 grupos de dependência, 35
configurações de classificação, 175 dobras e 38.990 predições OOF. Inclui Granite
97M, E5-small e MiniLM-L12, TF-IDF, embedding e híbrido, além de metadados. O
agrupamento reduz vazamento entre variantes da mesma fonte. Isso não transforma
fontes sintéticas em amostras representativas de chamados institucionais.

As primeiras cinco linhas mostram o maior Macro-F1 de cada família, não os
vencedores da regra hierárquica. A última linha mostra o candidato hierárquico.

| Família/configuração | Macro-F1 proxy | Cobertura automática | Risco seletivo | Gate |
|---|---:|---:|---:|---|
| Árvore, híbrido/MiniLM | 0,6962 | 0 | não estimável | FAIL |
| SVM, embedding/E5 | 0,8004 | 0,4767 | 0,1111 | FAIL |
| MLP, embedding/E5 | 0,8036 | 0 | não estimável | FAIL |
| XGBoost, híbrido/E5 | 0,7493 | 0,0844 | 0,0638 | FAIL |
| Regressão logística, híbrido/E5 | 0,7912 | 0,5799 | 0,0650 | UNDERPOWERED |
| Candidato hierárquico SVM, híbrido/E5 | 0,7987 | 0,6086 | 0,0693 | UNDERPOWERED |

O maior Macro-F1 não define sozinho o vencedor: cobertura, risco, calibração,
incerteza por grupo e erros críticos também importam. O candidato hierárquico
não passou o gate de suficiência. Em 64 grupos expostos e zero eventos críticos,
o limite superior unilateral de 95% é aproximadamente 4,57%, acima de 2%.
149 grupos independentes expostos são o mínimo matemático de zero eventos para
ficar abaixo de 2% (não uma garantia de poder nem uma meta de paráfrases).

A deduplicação permanece bloqueada: 12 famílias, seis por classe, não suportam
o desenho definido. Os 2.000 registros de detalhe de retrieval são descritivos
e não devem ser contados como 2.000 famílias independentes. SHAP foi verificado
em um finalista, com residual de aditividade próximo de 5,77e-15; explica
atribuições do score, não confirma acerto, causalidade ou equidade.

Manter Granite v1.8 no runtime preserva um artefato técnico congelado; não é
prova de superioridade sobre E5, MiniLM, árvores, MLP, XGBoost ou Gemini. O
comparativo antigo V2 continua invalidado. Não foi feita nova seleção para
favorecer o modelo operacional, nem nova abertura de holdout.

## Pendências para uma entrega produtiva

- Corrigir/rotacionar credenciais históricas com seus emissores. A árvore limpa
  não revoga chaves que já foram expostas em commits anteriores.
- O GLPI exibiu aviso de senha padrão para `normal`, `post-only` e `tech`.
  Resolver essas contas sem interromper dependências exige decisão de acesso;
  nenhuma senha foi alterada silenciosamente nesta inspeção.
- Autenticar o GitHub: o fetch de `origin` falhou por falta de credencial.
  Não houve push, reescrita de histórico ou envio ao remoto de outro projeto.
- Não existe evidência atual suficiente de SLO/drift aprovado, carga E2E sob
  concorrência, operação longitudinal, alerta externo ou atuação automática de
  `STOP`. Carga local e restore isolado anteriores permanecem evidências datadas.
- Aumentar famílias independentes por proxy pode ampliar a comparação técnica,
  mas não superar a ausência de gabarito semântico independente. Não se promete
  completar essa lacuna dentro das restrições atuais.
- Aprovação de risco, responsáveis, retenção/LGPD e aceite de produção continuam
  pendentes. A matriz local NIST AI RMF é parcial, não uma certificação.
