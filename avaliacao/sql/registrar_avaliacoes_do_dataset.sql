-- Materializa o gabarito sintético de um único run.
-- Preferência: use conferir_gabarito.py --run-id ... --registrar-gabarito.
-- Uso manual com psql: -v run_id="'RUN-ID'"

\if :{?run_id}
\else
\echo 'ERRO: informe -v run_id="''RUN-ID''"'
\quit 3
\endif

SELECT EXISTS (
  SELECT 1
  FROM dataset_controle d
  LEFT JOIN tickets_processados t ON t.id=d.ticket_id
  WHERE d.run_id=:run_id AND t.id IS NULL
) AS missing_tickets \gset
\if :missing_tickets
\echo 'ERRO: o run possui ticket_id ausente em tickets_processados'
\quit 4
\endif

WITH gold AS (
  SELECT
    d.run_id,d.case_id,d.episode_id,d.ticket_id,
    'DEDUPLICACAO'::text AS etapa,
    CASE WHEN d.duplicado_esperado THEN 'DUPLICADO'
         ELSE 'NAO_DUPLICADO' END AS classe_correta
  FROM dataset_controle d
  WHERE d.run_id=:run_id AND d.duplicado_esperado IS NOT NULL
  UNION ALL
  SELECT
    d.run_id,d.case_id,d.episode_id,d.ticket_id,
    'CLASSIFICACAO',d.classificacao_esperada
  FROM dataset_controle d
  WHERE d.run_id=:run_id
    AND NULLIF(d.classificacao_esperada,'') IS NOT NULL
),
predicted AS (
  SELECT
    g.*,
    COALESCE((
      SELECT i.predicao
      FROM ia_decisoes i
      WHERE i.ticket_id=g.ticket_id AND i.etapa=g.etapa
      ORDER BY i.criado_em DESC,i.id DESC
      LIMIT 1
    ),'SEM_DECISAO') AS decisao_ia
  FROM gold g
)
INSERT INTO avaliacoes_humanas(
  ticket_id,etapa,decisao_ia,decisao_humana,classe_correta,
  ia_estava_correta,avaliador,status_avaliacao,origem_amostra,
  avaliado_em,concluido_em,run_id,case_id,episode_id,
  fonte_gabarito,adjudicada
)
SELECT
  p.ticket_id,p.etapa,p.decisao_ia,p.classe_correta,p.classe_correta,
  p.decisao_ia=p.classe_correta,'ORACULO_DATASET','CONCLUIDA',
  'DATASET_EPISODICO',NOW(),NOW(),p.run_id,p.case_id,p.episode_id,
  CASE WHEN e.rotulos_validados
       THEN 'SINTETICO_VALIDADO' ELSE 'SINTETICO_NAO_VALIDADO' END,
  FALSE
FROM predicted p
JOIN experimentos_avaliacao e ON e.run_id=p.run_id
WHERE NOT EXISTS (
  SELECT 1
  FROM avaliacoes_humanas a
  WHERE a.run_id=p.run_id AND a.case_id=p.case_id AND a.etapa=p.etapa
    AND a.fonte_gabarito IN ('SINTETICO_VALIDADO','SINTETICO_NAO_VALIDADO')
);
