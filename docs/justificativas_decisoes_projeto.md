# Justificativas técnicas, arquiteturais e metodológicas

**Revisão:** 26/08/2026

## Arquitetura V9

A V9 separa sincronização, deduplicação, classificação, decisão fiscal,
métricas e fila de IA em seis workflows. A separação reduz o raio de falha,
permite retentativa por estágio e torna observáveis as transições. PostgreSQL
mantém fila, leases, tentativas, decisões, eventos e DLQ; o GLPI permanece o
sistema visível de atendimento.

Essa divisão aumenta o número de contratos e pontos de falha. Por isso os JSONs
são gerados por builders, protegidos por snapshots e validados antes do deploy.
Paridade e E2E são necessários após qualquer mudança, mas não provam correção
universal.

## Execução local-first

O modelo primário é local para reduzir dependência de cota/rede, preservar
controle de versão e permitir auditoria do artefato. “Local” reduz transmissão
externa do texto na rota primária, mas não garante sozinho conformidade LGPD:
acesso, retenção, logs, backups, base legal e segurança continuam necessários.

O fallback remoto é contingência operacional e fica desabilitado em
experimentos. Uma falha remota não autoriza concluir que o modelo local é
semanticamente superior.

## Representação híbrida

TF-IDF de palavras/caracteres preserva vocabulário técnico, códigos e ruído
ortográfico. Embedding multilíngue acrescenta um sinal para paráfrases. A fusão
é uma hipótese de engenharia, não uma verdade presumida. Ela deve vencer, sob
o mesmo split e classificador, TF-IDF isolado e embedding isolado.

O Granite 97M foi mantido no v1.8 porque cabe no hardware-alvo, tem 384
dimensões, suporte multilíngue e artefato congelável. Isso o torna candidato;
não demonstra que ele é melhor que E5, MiniLM ou qualquer embedding disponível.

## Classificador e calibração

Modelos lineares são uma escolha inicial defensável para texto esparso e poucos
grupos: custo baixo, regularização e inspeção mais simples. O protocolo 2.1
também inclui árvore, SVM, MLP e XGBoost. Complexidade só é promovida se houver
ganho pareado com incerteza aceitável e custo operacional compatível.

Calibração é necessária para transformar escores em uma escala útil para
limiares. Ela fica dentro da validação cruzada e não pode usar o holdout.
Probabilidade calibrada em dados sintéticos ainda pode estar descalibrada no
GLPI real.

## Abstenção e segurança

O sistema não força decisões quando faltam ativo/local/sintoma, quando o caso é
fora de escopo ou quando a confiança não atende à política. `TRIAGEM_MANUAL` é
uma classe semântica; `ABSTENCAO` é uma rota operacional. Ambas precisam de
denominadores separados.

Erros têm custos distintos. Classificar indevidamente uma demanda como OBRA e
declarar ocorrências distintas como não duplicadas recebem guardas específicas.
A regra de decisão é hierárquica: segurança e limites primeiro, desempenho
depois. Isso evita esconder um risco crítico em escore médio composto.

## Seleção científica

O protocolo V2.1 compara:

- Granite 97M, multilingual-e5-small e multilingual MiniLM-L12-v2;
- TF-IDF, embedding, híbrido, metadados e híbrido+metadados;
- regressão logística, árvore, SVM linear, MLP e XGBoost;
- validação externa 5-fold e interna 3-fold por família-fonte;
- calibração fora de dobra, bootstrap agrupado, SHAP e latência.

A execução antiga foi invalidada por leakage entre derivados e divergência de
hash. Na rodada corrigida 2.1, a classificação terminou sem vencedor
qualificado e a deduplicação foi bloqueada por insuficiência de grupos. Esses
resultados são apenas de desenvolvimento; o resultado final depende de
gabarito humano e holdout institucional.

## XAI

SHAP é usado no finalista para inspecionar famílias de atributos, atalhos e
erros. O protocolo explica o escore-base, audita aditividade e agrega atributos
por família. SHAP não prova acerto, causalidade ou segurança e não substitui a
análise de erro por especialistas.

## Histórico e reprodutibilidade

V1–V8 ficam em `n8n/history/` como dez JSONs sanitizados e inativos, com
manifesto/hashes. A V9 fica em `n8n/workflows/Versão9/`. Datasets, configs,
modelos e execuções têm versões distintas. Nunca usar `latest`, sobrescrever
resultado citado ou versionar `.env`, credencial, dump, cache ou executável.

## Condição para produção

O E2E sintético aprovado demonstra integração local. Produção requer ainda
segurança, menor privilégio, backup/restore ensaiado, carga/concorrência,
alertas, SLOs, monitoramento de drift, homologação, rollback e aceite dos
responsáveis. Eficácia científica exige dados reais, dupla revisão, adjudicação
e holdout intocado.

Detalhes: `auditoria_critica_completa_2026-08-26.md`.
