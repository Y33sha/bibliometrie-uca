#!/bin/bash
# Crée l'utilisateur applicatif s'il n'existe pas déjà
set -e

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    DO \$\$
    BEGIN
        IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '${DB_USER}') THEN
            CREATE ROLE ${DB_USER} WITH LOGIN PASSWORD '${DB_PASSWORD}';
            GRANT ALL PRIVILEGES ON DATABASE ${POSTGRES_DB} TO ${DB_USER};
            ALTER DATABASE ${POSTGRES_DB} OWNER TO ${DB_USER};
        END IF;
    END
    \$\$;
EOSQL
