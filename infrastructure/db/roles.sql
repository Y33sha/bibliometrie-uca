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
--   psql -d bibliometrie -v app_password='motdepasse' -f infrastructure/db/roles.sql
--
-- Les guillemets simples protègent la valeur du shell, qui interpréterait sinon `$` et
-- les espaces ; la mise entre quotes SQL, elle, est faite par `:'app_password'` ci-dessous.
--
-- Le mot de passe se range ensuite dans `DB_APP_PASSWORD` (cf. `.env.example`), à
-- côté de `DB_APP_USER`. Adapter le nom du rôle si l'hébergeur a ses conventions.

\if :{?app_password}
\else
\echo 'Renseigner le mot de passe : psql -v app_password=... -f infrastructure/db/roles.sql'
\quit
\endif

CREATE ROLE bibliometrie_app LOGIN PASSWORD :'app_password';

-- Traverser le schéma, sans rien y créer.
GRANT USAGE ON SCHEMA public TO bibliometrie_app;

-- Lecture de tout : l'API sert des données bibliométriques, et aucune n'est réservée.
-- `ALL TABLES` couvre les vues matérialisées, qu'elle lit sans jamais les rafraîchir.
GRANT SELECT ON ALL TABLES IN SCHEMA public TO bibliometrie_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO bibliometrie_app;

-- Écriture sur les seules tables que les points d'entrée d'administration modifient, et
-- pour la seule opération que chacune reçoit. Une table qu'on ne fait que mettre à jour
-- n'accorde pas la suppression ; une table où l'on n'ajoute que des lignes n'accorde ni
-- l'une ni l'autre. Vider une colonne vaut presque une suppression : les deux droits se
-- refusent de la même façon.
--
-- Les autres tables — celles que le pipeline calcule, celles où il dépose ce qu'il extrait,
-- et la table des migrations — restent en lecture pour l'API : une écriture qui les viserait
-- échouerait au lieu d'aboutir.
--
-- Cette liste est vérifiée : les tests d'API se connectent sous ce rôle, si bien qu'un point
-- d'entrée écrivant hors de ces droits échoue en erreur de permission avant d'être déployé.

GRANT INSERT, UPDATE, DELETE ON
    address_structures, authorships, perimeters, person_name_forms,
    persons, rejected_authorships, structure_name_forms, structures
TO bibliometrie_app;

-- Un identifiant de personne s'ajoute et se rejette ; il ne se supprime pas, le rejet
-- gardant la trace qu'une attribution a été envisagée.
GRANT INSERT, UPDATE ON
    person_identifiers
TO bibliometrie_app;

GRANT INSERT, DELETE ON
    perimeter_structures, structure_relations
TO bibliometrie_app;

-- `INSERT … ON CONFLICT DO UPDATE` exige le droit de mise à jour, que la ligne entre en
-- conflit ou non.
GRANT INSERT, UPDATE, DELETE ON
    confirmed_authorships, distinct_publications
TO bibliometrie_app;

GRANT UPDATE, DELETE ON
    journal_name_forms, journals, publications, publisher_name_forms, publishers
TO bibliometrie_app;

GRANT INSERT ON
    audit_log
TO bibliometrie_app;

GRANT INSERT, UPDATE ON
    distinct_persons, publications_detail
TO bibliometrie_app;

GRANT UPDATE ON
    addresses, apc_payments, config, persons_rh, source_authorships, source_publications
TO bibliometrie_app;

-- Une table créée par une migration future est lisible, et rien de plus : sa nature se
-- tranche en l'ajoutant nommément ci-dessus, plutôt qu'en la découvrant écrite.
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT SELECT ON TABLES TO bibliometrie_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO bibliometrie_app;

-- Ce qui n'est délibérément pas accordé : TRUNCATE, l'écriture sur les tables du pipeline,
-- la propriété des objets, et CREATE sur le schéma. `CONNECT` sur la base et `TEMPORARY`
-- (l'API crée des tables temporaires en tâche de fond) viennent du rôle PUBLIC ; les
-- rétablir nommément si l'hébergeur les retire à PUBLIC.
