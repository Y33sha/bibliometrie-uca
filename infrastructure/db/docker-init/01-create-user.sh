#!/bin/bash
# Crée le rôle propriétaire du schéma s'il n'existe pas déjà.
# Le rôle applicatif, lui, est créé à part par infrastructure/db/roles.sql.
set -e

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    DO \$\$
    BEGIN
        IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '${DB_OWNER_USER}') THEN
            CREATE ROLE ${DB_OWNER_USER} WITH LOGIN PASSWORD '${DB_OWNER_PASSWORD}';
            GRANT ALL PRIVILEGES ON DATABASE ${POSTGRES_DB} TO ${DB_OWNER_USER};
            ALTER DATABASE ${POSTGRES_DB} OWNER TO ${DB_OWNER_USER};
        END IF;
    END
    \$\$;
EOSQL
