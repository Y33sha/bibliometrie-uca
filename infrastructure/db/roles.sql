-- =============================================================
-- Rôle applicatif : privilèges de l'API, et rien de plus
-- =============================================================
--
-- L'API n'a besoin que de lire et d'écrire des données. Modifier la structure du
-- schéma, rafraîchir les vues matérialisées et vider des tables sont l'affaire des
-- migrations, du pipeline et des scripts de maintenance, qui se connectent avec
-- l'identité principale — propriétaire du schéma.
--
-- Séparer les deux évite qu'une faille de l'application, seul composant exposé au
-- réseau, ouvre des pouvoirs qu'elle n'exerce jamais. Elle écarte en particulier
-- `COPY … PROGRAM`, réservé au superutilisateur, qui exécute des commandes sur la
-- machine qui héberge la base.
--
-- Jouer une fois, à l'initialisation, **connecté comme le rôle qui applique les
-- migrations** — `ALTER DEFAULT PRIVILEGES` ci-dessous ne porte que sur les objets
-- créés par le rôle courant :
--
--   psql -d bibliometrie -v app_password="motdepasse" -f infrastructure/db/roles.sql
--
-- Le mot de passe se range ensuite dans `DB_APP_PASSWORD` (cf. `.env.example`), à
-- côté de `DB_APP_USER`. Adapter le nom du rôle si l'hébergeur a ses conventions.

\if :{?app_password}
\else
\echo 'Renseigner le mot de passe : psql -v app_password="…" -f infrastructure/db/roles.sql'
\quit
\endif

CREATE ROLE bibliometrie_app LOGIN PASSWORD :'app_password';

-- Traverser le schéma, sans rien y créer.
GRANT USAGE ON SCHEMA public TO bibliometrie_app;

-- Lecture et écriture des données existantes. `ALL TABLES` couvre les vues
-- matérialisées, que l'API lit sans jamais les rafraîchir.
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO bibliometrie_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO bibliometrie_app;

-- Mêmes droits sur ce que les migrations futures créeront, sans avoir à y repenser.
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO bibliometrie_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO bibliometrie_app;

-- Ce qui n'est délibérément pas accordé : TRUNCATE, la propriété des objets, et
-- CREATE sur le schéma. `CONNECT` sur la base et `TEMPORARY` (l'API crée des tables
-- temporaires en tâche de fond) viennent du rôle PUBLIC ; les rétablir nommément si
-- l'hébergeur les retire à PUBLIC.
