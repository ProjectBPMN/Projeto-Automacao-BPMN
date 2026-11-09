#!/bin/sh
set -eu

# Executado somente pelo entrypoint oficial em um volume PostgreSQL vazio.
# O DDL permanece em 01-init-schema.sql/02-postgres-menor-privilegio.sql; este
# script apenas provisiona o login runtime com a senha recebida por ambiente.
: "${POSTGRES_RUNTIME_USER:?POSTGRES_RUNTIME_USER ausente}"
: "${POSTGRES_RUNTIME_PASSWORD:?POSTGRES_RUNTIME_PASSWORD ausente}"

psql --set=ON_ERROR_STOP=1 \
  --username "$POSTGRES_USER" \
  --dbname "$POSTGRES_DB" \
  --set=runtime_user="$POSTGRES_RUNTIME_USER" \
  --set=runtime_password="$POSTGRES_RUNTIME_PASSWORD" <<'EOSQL'
SELECT CASE
  WHEN EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'runtime_user')
  THEN format(
    'ALTER ROLE %I LOGIN PASSWORD %L NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS',
    :'runtime_user', :'runtime_password'
  )
  ELSE format(
    'CREATE ROLE %I LOGIN PASSWORD %L NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS',
    :'runtime_user', :'runtime_password'
  )
END
\gexec

SELECT format('GRANT triagem_runtime TO %I', :'runtime_user')
\gexec
EOSQL
