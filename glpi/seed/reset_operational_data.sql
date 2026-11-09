-- Reset funcional da massa de chamados GLPI para testes V9.
-- Preserva instalacao, usuarios, categorias, localizacoes e configuracao da API.

SET FOREIGN_KEY_CHECKS = 0;

TRUNCATE TABLE glpi_changes_tickets;
TRUNCATE TABLE glpi_groups_tickets;
TRUNCATE TABLE glpi_items_tickets;
TRUNCATE TABLE glpi_olalevels_tickets;
TRUNCATE TABLE glpi_problems_tickets;
TRUNCATE TABLE glpi_projecttasks_tickets;
TRUNCATE TABLE glpi_slalevels_tickets;
TRUNCATE TABLE glpi_suppliers_tickets;
TRUNCATE TABLE glpi_ticketcosts;
TRUNCATE TABLE glpi_tickets_contracts;
TRUNCATE TABLE glpi_tickets_tickets;
TRUNCATE TABLE glpi_tickets_users;
TRUNCATE TABLE glpi_ticketsatisfactions;
TRUNCATE TABLE glpi_tickettasks;
TRUNCATE TABLE glpi_ticketvalidations;
TRUNCATE TABLE glpi_itilfollowups;
TRUNCATE TABLE glpi_itilsolutions;
TRUNCATE TABLE glpi_tickets;

DELETE FROM glpi_logs
WHERE itemtype IN ('Ticket', 'ITILFollowup', 'ITILSolution', 'TicketTask');

SET FOREIGN_KEY_CHECKS = 1;
