START TRANSACTION;

-- 1) OBRA -> encaminhado DDI/DG e encerrado no GLPI
INSERT INTO glpi_tickets (
  entities_id, name, date, solvedate, closedate, date_mod,
  users_id_lastupdater, users_id_recipient, requesttypes_id,
  content, urgency, impact, priority, itilcategories_id, type,
  status, is_deleted, locations_id, date_creation, tickettemplates_id
) VALUES (
  0,
  'Reforma estrutural do telhado do bloco C (obra)',
  NOW() - INTERVAL 40 DAY,
  NOW() - INTERVAL 38 DAY,
  NOW() - INTERVAL 38 DAY,
  NOW() - INTERVAL 38 DAY,
  2, 17, 1,
  'Demanda classificada como OBRA. Encaminhada para DDI/DG conforme fluxo da Prefeitura.',
  3, 3, 3, 0, 1,
  6, 0, 0, NOW() - INTERVAL 40 DAY, 0
);
SET @t1 = LAST_INSERT_ID();
INSERT INTO glpi_itilsolutions (itemtype, items_id, solutiontypes_id, content, date_creation, date_mod, users_id, status)
VALUES ('Ticket', @t1, 0, 'Chamado classificado como OBRA e encaminhado ao DDI/DG. Encerrado no GLPI por não se tratar de manutenção.', NOW() - INTERVAL 38 DAY, NOW() - INTERVAL 38 DAY, 2, 2);

INSERT INTO glpi_tickets (
  entities_id, name, date, solvedate, closedate, date_mod,
  users_id_lastupdater, users_id_recipient, requesttypes_id,
  content, urgency, impact, priority, itilcategories_id, type,
  status, is_deleted, locations_id, date_creation, tickettemplates_id
) VALUES (
  0,
  'Construção de nova cobertura na entrada principal (obra)',
  NOW() - INTERVAL 32 DAY,
  NOW() - INTERVAL 31 DAY,
  NOW() - INTERVAL 31 DAY,
  NOW() - INTERVAL 31 DAY,
  2, 17, 1,
  'Solicitação de obra civil, fora do escopo de manutenção predial.',
  3, 3, 3, 0, 1,
  6, 0, 0, NOW() - INTERVAL 32 DAY, 0
);
SET @t2 = LAST_INSERT_ID();
INSERT INTO glpi_itilsolutions (itemtype, items_id, solutiontypes_id, content, date_creation, date_mod, users_id, status)
VALUES ('Ticket', @t2, 0, 'Classificado como OBRA. Encaminhado para DDI/DG e encerrado no GLPI.', NOW() - INTERVAL 31 DAY, NOW() - INTERVAL 31 DAY, 2, 2);

INSERT INTO glpi_tickets (
  entities_id, name, date, solvedate, closedate, date_mod,
  users_id_lastupdater, users_id_recipient, requesttypes_id,
  content, urgency, impact, priority, itilcategories_id, type,
  status, is_deleted, locations_id, date_creation, tickettemplates_id
) VALUES (
  0,
  'Ampliação de banheiro no bloco administrativo (obra)',
  NOW() - INTERVAL 26 DAY,
  NOW() - INTERVAL 24 DAY,
  NOW() - INTERVAL 24 DAY,
  NOW() - INTERVAL 24 DAY,
  2, 17, 1,
  'Pedido de ampliação física do ambiente.',
  2, 3, 2, 0, 1,
  6, 0, 0, NOW() - INTERVAL 26 DAY, 0
);
SET @t3 = LAST_INSERT_ID();
INSERT INTO glpi_itilsolutions (itemtype, items_id, solutiontypes_id, content, date_creation, date_mod, users_id, status)
VALUES ('Ticket', @t3, 0, 'Caracterizado como OBRA. Encaminhamento ao DDI/DG realizado; chamado encerrado no GLPI.', NOW() - INTERVAL 24 DAY, NOW() - INTERVAL 24 DAY, 2, 2);

-- 2) INVIAVEL -> encerrado por inviabilidade tecnica/orcamentaria
INSERT INTO glpi_tickets (
  entities_id, name, date, solvedate, closedate, date_mod,
  users_id_lastupdater, users_id_recipient, requesttypes_id,
  content, urgency, impact, priority, itilcategories_id, type,
  status, is_deleted, locations_id, date_creation, tickettemplates_id
) VALUES (
  0,
  'Instalação de elevador panorâmico no bloco A',
  NOW() - INTERVAL 22 DAY,
  NOW() - INTERVAL 20 DAY,
  NOW() - INTERVAL 20 DAY,
  NOW() - INTERVAL 20 DAY,
  2, 17, 1,
  'Solicitação avaliada e considerada inviável no cenário atual.',
  2, 3, 2, 0, 1,
  6, 0, 0, NOW() - INTERVAL 22 DAY, 0
);
SET @t4 = LAST_INSERT_ID();
INSERT INTO glpi_itilsolutions (itemtype, items_id, solutiontypes_id, content, date_creation, date_mod, users_id, status)
VALUES ('Ticket', @t4, 0, 'Chamado finalizado como INVIÁVEL por restrição técnica e orçamentária.', NOW() - INTERVAL 20 DAY, NOW() - INTERVAL 20 DAY, 2, 2);

INSERT INTO glpi_tickets (
  entities_id, name, date, solvedate, closedate, date_mod,
  users_id_lastupdater, users_id_recipient, requesttypes_id,
  content, urgency, impact, priority, itilcategories_id, type,
  status, is_deleted, locations_id, date_creation, tickettemplates_id
) VALUES (
  0,
  'Substituição completa da fachada por pele de vidro',
  NOW() - INTERVAL 18 DAY,
  NOW() - INTERVAL 17 DAY,
  NOW() - INTERVAL 17 DAY,
  NOW() - INTERVAL 17 DAY,
  2, 17, 1,
  'Demanda sem viabilidade técnica para execução imediata.',
  2, 2, 2, 0, 1,
  6, 0, 0, NOW() - INTERVAL 18 DAY, 0
);
SET @t5 = LAST_INSERT_ID();
INSERT INTO glpi_itilsolutions (itemtype, items_id, solutiontypes_id, content, date_creation, date_mod, users_id, status)
VALUES ('Ticket', @t5, 0, 'Finalizado como INVIÁVEL após parecer técnico da equipe.', NOW() - INTERVAL 17 DAY, NOW() - INTERVAL 17 DAY, 2, 2);

INSERT INTO glpi_tickets (
  entities_id, name, date, solvedate, closedate, date_mod,
  users_id_lastupdater, users_id_recipient, requesttypes_id,
  content, urgency, impact, priority, itilcategories_id, type,
  status, is_deleted, locations_id, date_creation, tickettemplates_id
) VALUES (
  0,
  'Readequação completa da rede elétrica antiga sem projeto',
  NOW() - INTERVAL 14 DAY,
  NOW() - INTERVAL 13 DAY,
  NOW() - INTERVAL 13 DAY,
  NOW() - INTERVAL 13 DAY,
  2, 17, 1,
  'Solicitação depende de projeto executivo inexistente.',
  3, 3, 3, 0, 1,
  6, 0, 0, NOW() - INTERVAL 14 DAY, 0
);
SET @t6 = LAST_INSERT_ID();
INSERT INTO glpi_itilsolutions (itemtype, items_id, solutiontypes_id, content, date_creation, date_mod, users_id, status)
VALUES ('Ticket', @t6, 0, 'Encerrado por inviabilidade técnica no escopo atual.', NOW() - INTERVAL 13 DAY, NOW() - INTERVAL 13 DAY, 2, 2);

-- 3) CONCLUIDO -> manutenção executada
INSERT INTO glpi_tickets (
  entities_id, name, date, solvedate, closedate, date_mod,
  users_id_lastupdater, users_id_recipient, requesttypes_id,
  content, urgency, impact, priority, itilcategories_id, type,
  status, is_deleted, locations_id, date_creation, tickettemplates_id
) VALUES (
  0,
  'Troca de torneira com vazamento no banheiro térreo',
  NOW() - INTERVAL 10 DAY,
  NOW() - INTERVAL 9 DAY,
  NOW() - INTERVAL 9 DAY,
  NOW() - INTERVAL 9 DAY,
  4, 17, 1,
  'Manutenção corretiva de hidráulica solicitada pelo usuário.',
  2, 2, 2, 2, 1,
  6, 0, 0, NOW() - INTERVAL 10 DAY, 0
);
SET @t7 = LAST_INSERT_ID();
INSERT INTO glpi_itilsolutions (itemtype, items_id, solutiontypes_id, content, date_creation, date_mod, users_id, status)
VALUES ('Ticket', @t7, 0, 'Serviço concluído: torneira substituída e vazamento eliminado.', NOW() - INTERVAL 9 DAY, NOW() - INTERVAL 9 DAY, 4, 2);

INSERT INTO glpi_tickets (
  entities_id, name, date, solvedate, closedate, date_mod,
  users_id_lastupdater, users_id_recipient, requesttypes_id,
  content, urgency, impact, priority, itilcategories_id, type,
  status, is_deleted, locations_id, date_creation, tickettemplates_id
) VALUES (
  0,
  'Substituição de lâmpadas queimadas no corredor B',
  NOW() - INTERVAL 8 DAY,
  NOW() - INTERVAL 7 DAY,
  NOW() - INTERVAL 7 DAY,
  NOW() - INTERVAL 7 DAY,
  4, 17, 1,
  'Solicitação de troca de iluminação em área interna.',
  1, 1, 1, 1, 1,
  6, 0, 0, NOW() - INTERVAL 8 DAY, 0
);
SET @t8 = LAST_INSERT_ID();
INSERT INTO glpi_itilsolutions (itemtype, items_id, solutiontypes_id, content, date_creation, date_mod, users_id, status)
VALUES ('Ticket', @t8, 0, 'Manutenção concluída com reposição de lâmpadas.', NOW() - INTERVAL 7 DAY, NOW() - INTERVAL 7 DAY, 4, 2);

INSERT INTO glpi_tickets (
  entities_id, name, date, solvedate, closedate, date_mod,
  users_id_lastupdater, users_id_recipient, requesttypes_id,
  content, urgency, impact, priority, itilcategories_id, type,
  status, is_deleted, locations_id, date_creation, tickettemplates_id
) VALUES (
  0,
  'Ajuste de dobradiça em porta da sala 12',
  NOW() - INTERVAL 6 DAY,
  NOW() - INTERVAL 5 DAY,
  NOW() - INTERVAL 5 DAY,
  NOW() - INTERVAL 5 DAY,
  4, 17, 1,
  'Porta com dificuldade de fechamento por desgaste da dobradiça.',
  1, 1, 1, 3, 1,
  6, 0, 0, NOW() - INTERVAL 6 DAY, 0
);
SET @t9 = LAST_INSERT_ID();
INSERT INTO glpi_itilsolutions (itemtype, items_id, solutiontypes_id, content, date_creation, date_mod, users_id, status)
VALUES ('Ticket', @t9, 0, 'Chamado concluído após ajuste e reaperto das dobradiças.', NOW() - INTERVAL 5 DAY, NOW() - INTERVAL 5 DAY, 4, 2);

COMMIT;

START TRANSACTION;

-- LOTE HISTORICO: 12 a 6 meses atras (12 chamados)
INSERT INTO glpi_tickets (
  entities_id, name, date, solvedate, closedate, date_mod,
  users_id_lastupdater, users_id_recipient, requesttypes_id,
  content, urgency, impact, priority, itilcategories_id, type,
  status, is_deleted, locations_id, date_creation, tickettemplates_id
)
SELECT
  0,
  CONCAT('[SEED HIST][12-6M][',
    CASE
      WHEN MOD(n,3)=1 THEN 'OBRA'
      WHEN MOD(n,3)=2 THEN 'INVIAVEL'
      ELSE 'CONCLUIDO'
    END,
  '] #', LPAD(n,2,'0')),
  NOW() - INTERVAL (190 + n * 12 + 2) DAY,
  NOW() - INTERVAL (190 + n * 12 + 1) DAY,
  NOW() - INTERVAL (190 + n * 12) DAY,
  NOW() - INTERVAL (190 + n * 12) DAY,
  CASE WHEN MOD(n,3)=0 THEN 4 ELSE 2 END,
  17,
  1,
  CASE
    WHEN MOD(n,3)=1 THEN 'Chamado historico classificado como OBRA e encerrado apos encaminhamento para DDI/DG.'
    WHEN MOD(n,3)=2 THEN 'Chamado historico encerrado por inviabilidade tecnica/orcamentaria.'
    ELSE 'Chamado historico concluido pela equipe de manutencao.'
  END,
  2,
  2,
  2,
  CASE WHEN MOD(n,3)=0 THEN 1 WHEN MOD(n,3)=1 THEN 0 ELSE 2 END,
  1,
  6,
  0,
  0,
  NOW() - INTERVAL (190 + n * 12 + 2) DAY,
  0
FROM (
  SELECT 1 AS n UNION ALL SELECT 2 UNION ALL SELECT 3 UNION ALL SELECT 4
  UNION ALL SELECT 5 UNION ALL SELECT 6 UNION ALL SELECT 7 UNION ALL SELECT 8
  UNION ALL SELECT 9 UNION ALL SELECT 10 UNION ALL SELECT 11 UNION ALL SELECT 12
) AS nums
WHERE NOT EXISTS (
  SELECT 1 FROM glpi_tickets t
  WHERE t.name = CONCAT('[SEED HIST][12-6M][',
    CASE
      WHEN MOD(nums.n,3)=1 THEN 'OBRA'
      WHEN MOD(nums.n,3)=2 THEN 'INVIAVEL'
      ELSE 'CONCLUIDO'
    END,
  '] #', LPAD(nums.n,2,'0'))
);

-- LOTE HISTORICO: 6 a 3 meses atras (12 chamados)
INSERT INTO glpi_tickets (
  entities_id, name, date, solvedate, closedate, date_mod,
  users_id_lastupdater, users_id_recipient, requesttypes_id,
  content, urgency, impact, priority, itilcategories_id, type,
  status, is_deleted, locations_id, date_creation, tickettemplates_id
)
SELECT
  0,
  CONCAT('[SEED HIST][6-3M][',
    CASE
      WHEN MOD(n,3)=1 THEN 'OBRA'
      WHEN MOD(n,3)=2 THEN 'INVIAVEL'
      ELSE 'CONCLUIDO'
    END,
  '] #', LPAD(n,2,'0')),
  NOW() - INTERVAL (95 + n * 6 + 2) DAY,
  NOW() - INTERVAL (95 + n * 6 + 1) DAY,
  NOW() - INTERVAL (95 + n * 6) DAY,
  NOW() - INTERVAL (95 + n * 6) DAY,
  CASE WHEN MOD(n,3)=0 THEN 4 ELSE 2 END,
  17,
  1,
  CASE
    WHEN MOD(n,3)=1 THEN 'Chamado historico classificado como OBRA e encerrado apos encaminhamento para DDI/DG.'
    WHEN MOD(n,3)=2 THEN 'Chamado historico encerrado por inviabilidade tecnica/orcamentaria.'
    ELSE 'Chamado historico concluido pela equipe de manutencao.'
  END,
  2,
  2,
  2,
  CASE WHEN MOD(n,3)=0 THEN 1 WHEN MOD(n,3)=1 THEN 0 ELSE 2 END,
  1,
  6,
  0,
  0,
  NOW() - INTERVAL (95 + n * 6 + 2) DAY,
  0
FROM (
  SELECT 1 AS n UNION ALL SELECT 2 UNION ALL SELECT 3 UNION ALL SELECT 4
  UNION ALL SELECT 5 UNION ALL SELECT 6 UNION ALL SELECT 7 UNION ALL SELECT 8
  UNION ALL SELECT 9 UNION ALL SELECT 10 UNION ALL SELECT 11 UNION ALL SELECT 12
) AS nums
WHERE NOT EXISTS (
  SELECT 1 FROM glpi_tickets t
  WHERE t.name = CONCAT('[SEED HIST][6-3M][',
    CASE
      WHEN MOD(nums.n,3)=1 THEN 'OBRA'
      WHEN MOD(nums.n,3)=2 THEN 'INVIAVEL'
      ELSE 'CONCLUIDO'
    END,
  '] #', LPAD(nums.n,2,'0'))
);

-- LOTE HISTORICO: 3 meses a 1 dia atras (12 chamados)
INSERT INTO glpi_tickets (
  entities_id, name, date, solvedate, closedate, date_mod,
  users_id_lastupdater, users_id_recipient, requesttypes_id,
  content, urgency, impact, priority, itilcategories_id, type,
  status, is_deleted, locations_id, date_creation, tickettemplates_id
)
SELECT
  0,
  CONCAT('[SEED HIST][3M-1D][',
    CASE
      WHEN MOD(n,3)=1 THEN 'OBRA'
      WHEN MOD(n,3)=2 THEN 'INVIAVEL'
      ELSE 'CONCLUIDO'
    END,
  '] #', LPAD(n,2,'0')),
  NOW() - INTERVAL (2 + n * 7 + 2) DAY,
  NOW() - INTERVAL (2 + n * 7 + 1) DAY,
  NOW() - INTERVAL (2 + n * 7) DAY,
  NOW() - INTERVAL (2 + n * 7) DAY,
  CASE WHEN MOD(n,3)=0 THEN 4 ELSE 2 END,
  17,
  1,
  CASE
    WHEN MOD(n,3)=1 THEN 'Chamado historico classificado como OBRA e encerrado apos encaminhamento para DDI/DG.'
    WHEN MOD(n,3)=2 THEN 'Chamado historico encerrado por inviabilidade tecnica/orcamentaria.'
    ELSE 'Chamado historico concluido pela equipe de manutencao.'
  END,
  2,
  2,
  2,
  CASE WHEN MOD(n,3)=0 THEN 1 WHEN MOD(n,3)=1 THEN 0 ELSE 2 END,
  1,
  6,
  0,
  0,
  NOW() - INTERVAL (2 + n * 7 + 2) DAY,
  0
FROM (
  SELECT 1 AS n UNION ALL SELECT 2 UNION ALL SELECT 3 UNION ALL SELECT 4
  UNION ALL SELECT 5 UNION ALL SELECT 6 UNION ALL SELECT 7 UNION ALL SELECT 8
  UNION ALL SELECT 9 UNION ALL SELECT 10 UNION ALL SELECT 11 UNION ALL SELECT 12
) AS nums
WHERE NOT EXISTS (
  SELECT 1 FROM glpi_tickets t
  WHERE t.name = CONCAT('[SEED HIST][3M-1D][',
    CASE
      WHEN MOD(nums.n,3)=1 THEN 'OBRA'
      WHEN MOD(nums.n,3)=2 THEN 'INVIAVEL'
      ELSE 'CONCLUIDO'
    END,
  '] #', LPAD(nums.n,2,'0'))
);

-- Garante solucao para os chamados historicos sem duplicar
INSERT INTO glpi_itilsolutions (
  itemtype, items_id, solutiontypes_id, content, date_creation, date_mod, users_id, status
)
SELECT
  'Ticket',
  t.id,
  0,
  CASE
    WHEN t.name LIKE '%[OBRA]%' THEN 'Encerrado como OBRA e encaminhado para DDI/DG.'
    WHEN t.name LIKE '%[INVIAVEL]%' THEN 'Encerrado por inviabilidade tecnica/orcamentaria.'
    ELSE 'Manutencao executada e chamado concluido.'
  END,
  t.closedate,
  t.closedate,
  CASE WHEN t.name LIKE '%[CONCLUIDO]%' THEN 4 ELSE 2 END,
  2
FROM glpi_tickets t
LEFT JOIN glpi_itilsolutions s
  ON s.itemtype = 'Ticket' AND s.items_id = t.id
WHERE t.name LIKE '[SEED HIST]%'
  AND s.id IS NULL;

COMMIT;
