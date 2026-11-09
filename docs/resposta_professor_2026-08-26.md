# Resposta objetiva ao professor — estado em 26/08/2026

> Atualização de 27/08/2026: a execução comparativa terminou parcialmente; os
> resultados e bloqueios abaixo substituem a formulação “ainda será executada”.

Professor, o modelo atualmente implantado é o `local-hybrid-v1.8.0`. Ele usa
TF-IDF de palavras e caracteres, o embedding multilíngue Granite 97M congelado
e classificadores lineares calibrados. Essa escolha foi inicialmente de
engenharia: precisava funcionar em CPU com 8 GB, em português, localmente, com
versão/hash reprodutíveis, baixa latência, probabilidade e possibilidade de
abstenção.

A base científica para testar embedding semântico é a literatura de
representações densas multilíngues, como E5, e os model cards do Granite e do
multilingual MiniLM. Ela sustenta a hipótese de que paráfrases com palavras
diferentes podem ser aproximadas. Não sustenta, sozinha, que Granite é o melhor
modelo para nossos chamados. Isso precisa ser demonstrado no nosso domínio.

Eu auditei a seleção que parecia validar o Granite e encontrei um problema
metodológico: o corpus tinha 80 núcleos nominais por classe, mas apenas 32
moldes-fonte independentes por classe; na deduplicação, 200 episódios vinham de
12 famílias-fonte. Derivados da mesma fonte podiam cair em dobras diferentes.
Além disso, o SHA do corpus da execução antiga não era reproduzível. Por isso,
os valores antigos de Macro-F1, acurácia, cobertura e SHAP foram formalmente
invalidados e não vou usá-los para defender o modelo.

Implementei e executei o protocolo 2.1, que agrupa todos os derivados pela
fonte real e inclui a comparação solicitada:

- Granite 97M, multilingual-e5-small e
  paraphrase-multilingual-MiniLM-L12-v2;
- TF-IDF isolado, embedding isolado, híbrido e variantes com metadados;
- regressão logística, árvore de decisão, SVM, MLP e XGBoost;
- validação cruzada aninhada e agrupada, calibração fora de dobra, bootstrap
  por grupo, comparação pareada, latência e SHAP.

As 35 configurações classificatórias terminaram: cinco dobras agrupadas por
configuração, 38.990 predições OOF e validação independente. Nenhum candidato
passou os limites de confiança. O provisório foi E5 + híbrido + SVM, com
Macro-F1 0,7987 (IC95% agrupado 0,7266–0,8598), cobertura 60,86% e risco
seletivo 6,93% (IC95% 2,29%–13,21%). O status correto é `UNDERPOWERED`, não
“melhor modelo validado”. A comparação pareada não demonstrou superioridade
inequívoca de E5 sobre Granite.

As 55 configurações de deduplicação foram bloqueadas antes do ajuste: existem
seis famílias independentes por classe, mas o protocolo exige cinco grupos
para ajuste e quatro para calibração dentro do treino externo. Reduzir esses
mínimos após observar a falha seria pós-hoc. O executor agora verifica a
viabilidade antes do treino, e a deduplicação só deve ser reaberta após ampliar
as fontes independentes.

O treinamento operacional da v1.8 terminou e o bundle está congelado. Porém, a
validação científica não terminou: faltam rótulos humanos independentes,
adjudicação, um holdout institucional intocado e um piloto prospectivo. O
estado correto do sistema hoje é `scientific_ready=false`.

Sobre o n8n, não posso garantir “100% correto”. Posso garantir somente o que
foi testado: os seis workflows V9 foram compilados, validados e publicados com
paridade; o caminho WF06 → WF02 → WF03 foi executado de ponta a ponta com caso
sintético isolado, sem fallback e sem DLQ, terminou em triagem manual e limpou
os dados de teste; o n8n e o GLPI também foram conferidos manualmente no
navegador. Ainda faltam carga, concorrência, falhas de dependência, segurança e
homologação produtiva.

Também confirmei que as oito versões anteriores estão guardadas em
`n8n/history/` como snapshots sanitizados e inativos. O pacote cobre V1–V8,
tem manifesto de origem e SHA-256 e passou no validador de determinismo,
inatividade e ausência dos padrões de segredo/runtime verificados. Ele serve
para rastrear a evolução, não para afirmar que as versões antigas eram corretas
ou prontas para reativação.

Portanto, a apresentação cientificamente correta é: temos um protótipo V9
funcional e auditável, um candidato local razoável e um protocolo comparativo
corrigido; ainda não temos evidência suficiente para dizer que o Granite é o
melhor embedding do domínio, que a IA está validada em chamados reais ou que o
sistema está pronto para autonomia produtiva.

## Próximos marcos verificáveis

1. preservar/reproduzir a seleção classificatória V2.1 e seus hashes;
2. ampliar as famílias-fonte independentes de deduplicação antes de novo
   protocolo;
3. construir gabarito real com dois revisores cegos e adjudicação;
4. congelar/pré-registrar o candidato antes do holdout;
5. executar o holdout uma única vez e publicar intervalos, calibração,
   risco-cobertura, erros críticos e latência;
6. fazer piloto em sombra, com revisão humana e rollback.

Detalhes, evidências e limitações estão em
`docs/auditoria_critica_completa_2026-08-26.md`.
