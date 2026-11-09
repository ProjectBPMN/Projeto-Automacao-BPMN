# Invalidação pós-auditoria da seleção supervisionada V2

**Data:** 2026-08-26  
**Estado:** `INVALIDATED_POST_AUDIT`  
**Uso permitido:** somente auditoria histórica.

Esta execução não pode ser reproduzida nem usada para selecionar um modelo:

1. o protocolo e os resultados congelaram o SHA-256
   `620a2004ace1b2fb86673d753e967083539775d82ad417046ea1dd8510b80219`;
2. o único corpus correspondente disponível e regerável no início da auditoria
   tinha SHA-256
   `a43a722dc8d1b9be3373c7b949f8f8b8ee1b7f92e96b96cb61cfdb03e18050e2`;
3. a validação independente do diretório falhou com `Corpus congelado
   divergente`;
4. as 80 especificações nominais de cada classe derivavam de 32
   famílias-fonte, mas eram agrupadas como 80 núcleos;
5. os 200 episódios de deduplicação reutilizavam apenas 12 moldes-fonte, mas
   eram agrupados como 200 unidades independentes.

Consequência: Macro-F1, intervalos de confiança, limites superiores de erro,
cobertura, ranking e comparações pareadas desta pasta podem ser consultados
para diagnosticar a execução antiga, mas não podem sustentar uma conclusão
científica, uma promoção operacional ou uma alegação no artigo.

## Correção aplicada

O corpus `desenvolvimento-local-v2.1.0` agora contém
`source_dependency_group_sha256`. O protocolo 2.1 agrupa tanto classificação
quanto deduplicação por esse campo. Essa regra mantém juntas todas as
realizações que reutilizam a mesma família-fonte e torna explícito o tamanho
amostral efetivo: 32 grupos por classe e 12 grupos para deduplicação.

Uma nova seleção deve usar outro diretório de saída. Não sobrescrever esta
pasta preserva a rastreabilidade da falha.
