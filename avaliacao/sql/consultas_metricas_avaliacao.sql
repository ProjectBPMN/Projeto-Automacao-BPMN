-- Consultas V2 isoladas por execução.
-- Uso:
-- docker exec -i glpi-dedup-db psql -U triagem_user -d triagem \
--   -v run_id="'BENCHMARK-...'" -f consultas_metricas_avaliacao.sql

\if :{?run_id}
\else
\echo 'ERRO: informe -v run_id="''RUN-ID''"'
\quit 3
\endif

SELECT * FROM experimentos_avaliacao WHERE run_id=:run_id;

SELECT *
FROM vw_dataset_controle_resultados r
JOIN dataset_controle d ON d.id=r.dataset_id
WHERE d.run_id=:run_id
ORDER BY d.scenario_id,d.episode_id,d.order_in_episode;

SELECT * FROM vw_kpi_classificacao WHERE run_id=:run_id;

SELECT *
FROM vw_matriz_confusao_classificacao
WHERE run_id=:run_id
ORDER BY classe_correta,classe_predita_pela_ia;
-- A coluna proporcao é a matriz normalizada por classe correta.

SELECT *
FROM vw_metricas_assertividade_classificacao
WHERE run_id=:run_id
ORDER BY classe;

SELECT * FROM vw_auc_classificacao
WHERE run_id=:run_id ORDER BY classe;

SELECT * FROM vw_average_precision_classificacao
WHERE run_id=:run_id ORDER BY classe;

SELECT * FROM vw_log_loss_classificacao WHERE run_id=:run_id;
SELECT * FROM vw_brier_classificacao WHERE run_id=:run_id;

SELECT * FROM vw_metricas_deduplicacao WHERE run_id=:run_id;
SELECT * FROM vw_auc_deduplicacao WHERE run_id=:run_id;
SELECT * FROM vw_average_precision_deduplicacao WHERE run_id=:run_id;
SELECT * FROM vw_log_loss_deduplicacao WHERE run_id=:run_id;

SELECT *
FROM vw_risco_cobertura_classificacao
WHERE run_id=:run_id
ORDER BY threshold;

SELECT
  i.etapa,i.modelo_ia,i.versao_modelo,i.prompt_version,i.generation_profile,
  COUNT(*)::int AS decisoes,
  COUNT(*) FILTER (WHERE i.erro_ia)::int AS erros_ia,
  COUNT(*) FILTER (
    WHERE i.erro_ia=FALSE AND i.probabilidades_validas=FALSE
  )::int AS probabilidades_invalidas
FROM ia_decisoes i
WHERE i.run_id=:run_id
GROUP BY i.etapa,i.modelo_ia,i.versao_modelo,i.prompt_version,i.generation_profile
ORDER BY i.etapa;

SELECT
  w.workflow,w.fase,
  COUNT(*)::int AS eventos,
  COUNT(*) FILTER (WHERE w.erro)::int AS erros,
  ROUND(AVG(w.duracao_ms),2) AS duracao_media_ms,
  percentile_cont(0.50) WITHIN GROUP (ORDER BY w.duracao_ms) AS p50_ms,
  percentile_cont(0.95) WITHIN GROUP (ORDER BY w.duracao_ms) AS p95_ms,
  percentile_cont(0.99) WITHIN GROUP (ORDER BY w.duracao_ms) AS p99_ms
FROM workflow_eventos w
JOIN dataset_controle d ON d.ticket_id=w.ticket_id
WHERE d.run_id=:run_id AND w.duracao_ms IS NOT NULL
GROUP BY w.workflow,w.fase
ORDER BY w.workflow,w.fase;

SELECT *
FROM fila_ia_metricas
WHERE run_id=:run_id
ORDER BY criado_em;

WITH pares AS (
  SELECT
    etapa,revisao_id,
    (array_agg(classe_correta ORDER BY id))[1] AS rotulo_1,
    (array_agg(classe_correta ORDER BY id))[2] AS rotulo_2
  FROM avaliacoes_humanas
  WHERE run_id=:run_id
    AND fonte_gabarito='REVISAO_HUMANA'
    AND adjudicada=FALSE
  GROUP BY etapa,revisao_id
  HAVING COUNT(*)=2
),
totais AS (
  SELECT etapa,COUNT(*)::numeric AS n,
         AVG((rotulo_1=rotulo_2)::int)::numeric AS po
  FROM pares GROUP BY etapa
),
margem_1 AS (
  SELECT etapa,rotulo_1 AS rotulo,COUNT(*)::numeric AS n
  FROM pares GROUP BY etapa,rotulo_1
),
margem_2 AS (
  SELECT etapa,rotulo_2 AS rotulo,COUNT(*)::numeric AS n
  FROM pares GROUP BY etapa,rotulo_2
),
esperada AS (
  SELECT t.etapa,t.n,t.po,
         SUM((m1.n/t.n)*(m2.n/t.n)) AS pe
  FROM totais t
  JOIN margem_1 m1 ON m1.etapa=t.etapa
  JOIN margem_2 m2 ON m2.etapa=t.etapa AND m2.rotulo=m1.rotulo
  GROUP BY t.etapa,t.n,t.po
)
SELECT etapa,n::int,po AS concordancia_observada,pe AS concordancia_esperada,
       CASE WHEN pe<1 THEN (po-pe)/(1-pe) ELSE 1 END AS cohen_kappa
FROM esperada
ORDER BY etapa;
