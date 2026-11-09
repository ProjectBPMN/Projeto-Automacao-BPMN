-- Migração idempotente de separação entre propriedade/DDL e execução/DML.
-- Execute somente em janela aprovada, por um administrador diferente do login runtime.
-- As duas roles são grupos NOLOGIN; a credencial de login é provisionada fora deste arquivo.

DO $roles$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'triagem_migration_owner') THEN
    CREATE ROLE triagem_migration_owner NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'triagem_runtime') THEN
    CREATE ROLE triagem_runtime NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;
  END IF;
END
$roles$;

ALTER ROLE triagem_migration_owner NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
ALTER ROLE triagem_runtime NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;

-- Retira a propriedade das relações runtime. O administrador que executa esta
-- migração deve possuir os objetos ou ser superuser; a aplicação nunca recebe
-- membership em triagem_migration_owner.
DO $ownership$
DECLARE
  item record;
  command text;
BEGIN
  FOR item IN
    SELECT n.nspname, c.relname, c.relkind
    FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = 'public'
      AND c.relkind IN ('r', 'p', 'v', 'm', 'S', 'f')
      -- Sequências OWNED BY acompanham a tabela e não aceitam troca direta
      -- de owner. Mantemos no loop apenas sequências independentes.
      AND (
        c.relkind <> 'S'
        OR NOT EXISTS (
          SELECT 1
          FROM pg_depend d
          WHERE d.classid = 'pg_class'::regclass
            AND d.objid = c.oid
            AND d.deptype IN ('a', 'i')
        )
      )
  LOOP
    command := CASE item.relkind
      WHEN 'v' THEN 'ALTER VIEW'
      WHEN 'm' THEN 'ALTER MATERIALIZED VIEW'
      WHEN 'S' THEN 'ALTER SEQUENCE'
      WHEN 'f' THEN 'ALTER FOREIGN TABLE'
      ELSE 'ALTER TABLE'
    END;
    EXECUTE format('%s %I.%I OWNER TO triagem_migration_owner', command, item.nspname, item.relname);
  END LOOP;

  FOR item IN
    SELECT n.nspname, p.proname, p.prokind, pg_get_function_identity_arguments(p.oid) AS arguments
    FROM pg_proc p
    JOIN pg_namespace n ON n.oid = p.pronamespace
    WHERE n.nspname = 'public'
  LOOP
    command := CASE WHEN item.prokind = 'p' THEN 'ALTER PROCEDURE' ELSE 'ALTER FUNCTION' END;
    EXECUTE format(
      '%s %I.%I(%s) OWNER TO triagem_migration_owner',
      command,
      item.nspname,
      item.proname,
      item.arguments
    );
  END LOOP;

  ALTER SCHEMA public OWNER TO triagem_migration_owner;
END
$ownership$;

REVOKE CREATE ON SCHEMA public FROM PUBLIC;
REVOKE ALL ON SCHEMA public FROM triagem_runtime;
GRANT USAGE ON SCHEMA public TO triagem_runtime;

REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public FROM triagem_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO triagem_runtime;
REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public FROM triagem_runtime;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO triagem_runtime;

ALTER DEFAULT PRIVILEGES FOR ROLE triagem_migration_owner IN SCHEMA public
  REVOKE ALL ON TABLES FROM PUBLIC;
ALTER DEFAULT PRIVILEGES FOR ROLE triagem_migration_owner IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO triagem_runtime;
ALTER DEFAULT PRIVILEGES FOR ROLE triagem_migration_owner IN SCHEMA public
  REVOKE ALL ON SEQUENCES FROM PUBLIC;
ALTER DEFAULT PRIVILEGES FOR ROLE triagem_migration_owner IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO triagem_runtime;

DO $database_privileges$
BEGIN
  EXECUTE format('REVOKE CREATE ON DATABASE %I FROM triagem_runtime', current_database());
  EXECUTE format('GRANT CONNECT ON DATABASE %I TO triagem_runtime', current_database());
END
$database_privileges$;

COMMENT ON ROLE triagem_migration_owner IS
  'Grupo NOLOGIN proprietário do esquema; reservado a migrações aprovadas.';
COMMENT ON ROLE triagem_runtime IS
  'Grupo NOLOGIN runtime; somente CONNECT/USAGE e DML nas relações public.';
