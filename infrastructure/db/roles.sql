-- =============================================================
-- Rôles de connexion : ce que chaque processus exerce, et rien de plus
-- =============================================================
--
-- Trois processus atteignent la base, avec trois besoins distincts.
--
-- Les **migrations** créent, modifient et suppriment les objets du schéma. Elles se
-- connectent sous le propriétaire, et sont seules à le faire : c'est un geste ponctuel,
-- déclenché à la main, non un processus qui tourne.
--
-- L'**API** lit des données et en écrit quelques-unes, celles que ses points d'entrée
-- d'administration modifient. Elle ne touche à rien d'autre.
--
-- Le **pipeline** construit l'ensemble des données : il écrit presque partout, vide des
-- tables, rafraîchit des vues matérialisées et rafraîchit des statistiques. Il ne modifie
-- aucun objet du schéma.
--
-- Donner à chacun ses seuls privilèges évite qu'une faille ouvre des pouvoirs que le
-- processus n'exerce jamais. Pour l'API, seul composant exposé au réseau, cela écarte en
-- particulier `COPY … PROGRAM`, réservé au superutilisateur, qui exécute des commandes sur
-- la machine qui héberge la base. Pour le pipeline, seul composant à sortir sur le réseau
-- et à analyser des données qu'il ne produit pas, cela retire de l'exécution permanente le
-- seul mot de passe capable de modifier la structure.
--
-- Ce fichier crée les rôles de l'API et du pipeline, puis inclut `grants.sql`, qui leur
-- accorde leurs droits. `alembic/env.py` applique aussi `grants.sql` après toute migration
-- jouée.
--
-- Jouer une fois, à l'initialisation, **connecté comme le rôle qui applique les
-- migrations** — `ALTER DEFAULT PRIVILEGES` ne porte que sur les objets créés par le rôle
-- courant :
--
--   set -a; . ./.env; set +a
--   psql -d bibliometrie -f infrastructure/db/roles.sql
--
-- Les mots de passe sont lus dans l'environnement, où `.env` vient de les poser, et non
-- passés en argument : la ligne de commande d'un processus est lisible par tout compte de
-- la machine, et elle se dépose dans l'historique du shell.
--
-- Le fichier se rejoue sans dommage. Un rôle absent est créé, un rôle présent voit son mot
-- de passe réaligné sur l'environnement : changer une valeur dans `.env` puis rejouer suffit
-- à la faire tourner.

\set ON_ERROR_STOP on

\set app_password `printenv DB_APP_PASSWORD`
\set pipeline_password `printenv DB_PIPELINE_PASSWORD`

-- Le test passe par une variable psql : à l'intérieur d'un littéral délimité par dollars,
-- comme le corps d'un bloc `DO`, les variables ne sont pas substituées.
SELECT CASE
    WHEN :'app_password' = '' OR :'pipeline_password' = '' THEN 'on' ELSE 'off'
END AS mots_de_passe_manquants \gset

\if :mots_de_passe_manquants
\echo 'DB_APP_PASSWORD et DB_PIPELINE_PASSWORD sont requis, et vides. Poser les valeurs dans .env, puis: set -a; . ./.env; set +a'
\quit
\endif

SELECT format(
    CASE
        WHEN EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'bibliometrie_app')
            THEN 'ALTER ROLE %I PASSWORD %L'
        ELSE 'CREATE ROLE %I LOGIN PASSWORD %L'
    END,
    'bibliometrie_app', :'app_password')
\gexec

SELECT format(
    CASE
        WHEN EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'bibliometrie_pipeline')
            THEN 'ALTER ROLE %I PASSWORD %L'
        ELSE 'CREATE ROLE %I LOGIN PASSWORD %L'
    END,
    'bibliometrie_pipeline', :'pipeline_password')
\gexec

\ir grants.sql
