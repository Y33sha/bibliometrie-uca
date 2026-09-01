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
-- Jouer une fois, à l'initialisation, **connecté comme le rôle qui applique les
-- migrations** — `ALTER DEFAULT PRIVILEGES` ci-dessous ne porte que sur les objets
-- créés par le rôle courant :
--
--   psql -d bibliometrie -v app_password='motdepasse' -v pipeline_password='autre' \
--        -f infrastructure/db/roles.sql
--
-- Les guillemets simples protègent la valeur du shell, qui interpréterait sinon `$` et
-- les espaces ; la mise entre quotes SQL, elle, est faite par `:'app_password'` ci-dessous.
--
-- Les mots de passe se rangent ensuite dans `DB_APP_PASSWORD` et `DB_PIPELINE_PASSWORD`
-- (cf. `.env.example`), à côté de `DB_APP_USER` et `DB_PIPELINE_USER`. Adapter le nom des
-- rôles si l'hébergeur a ses conventions.

\if :{?app_password}
\else
\echo 'Renseigner les mots de passe : psql -v app_password=... -v pipeline_password=... -f infrastructure/db/roles.sql'
\quit
\endif

\if :{?pipeline_password}
\else
\echo 'Renseigner les mots de passe : psql -v app_password=... -v pipeline_password=... -f infrastructure/db/roles.sql'
\quit
\endif


-- =============================================================
-- Rôle applicatif : privilèges de l'API, et rien de plus
-- =============================================================

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


-- =============================================================
-- Rôle du pipeline : construire les données, sans toucher au schéma
-- =============================================================

CREATE ROLE bibliometrie_pipeline LOGIN PASSWORD :'pipeline_password';

-- Traverser le schéma, sans rien y créer.
GRANT USAGE ON SCHEMA public TO bibliometrie_pipeline;

-- Lecture et écriture de l'ensemble des données. Le pipeline construit le contenu de ces
-- tables et le reconstruit d'une exécution à l'autre : les énumérer ici n'ajouterait aucune
-- information — la liste serait celle du schéma — et vieillirait à chaque migration. La
-- restriction qui porte n'est pas la table atteinte, c'est ce qui reste hors d'atteinte : la
-- structure, la propriété des objets, et les deux exceptions retirées plus bas.
GRANT SELECT, INSERT, UPDATE, DELETE, TRUNCATE
    ON ALL TABLES IN SCHEMA public
    TO bibliometrie_pipeline;
-- `UPDATE` sur les séquences : `setval` le demande, et le pipeline remet à un le compteur des
-- tables qu'il reconstruit entièrement.
GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA public TO bibliometrie_pipeline;

-- `MAINTAIN` couvre `VACUUM`, `ANALYZE`, `REFRESH MATERIALIZED VIEW`, `CLUSTER`, `REINDEX` et
-- `LOCK TABLE`. Le pipeline exerce les trois premières : le staging est nettoyé après la
-- normalisation, les statistiques sont rafraîchies avant les jointures lourdes, et trois vues
-- matérialisées sont recalculées.
--
-- Ce privilège date de PostgreSQL 17. Avant lui, rafraîchir une vue matérialisée exigeait d'en
-- être propriétaire, faute de droit accordable : le pipeline se connectait alors sous le
-- propriétaire du schéma pour un pouvoir qu'il n'exerce pas.
GRANT MAINTAIN ON ALL TABLES IN SCHEMA public TO bibliometrie_pipeline;

-- Deux tables sont reprises, l'accord global les ayant d'abord couvertes. Les retirer après
-- coup dit ce qu'elles sont plutôt que de les oublier dans une énumération.
--
-- `audit_log` trace les décisions humaines prises depuis l'interface d'administration.
-- Le pipeline n'en prend aucune : l'écriture lui permettrait d'y déposer une trace
-- qu'aucune personne n'a produite, ce qui ôterait à la table ce qu'elle vaut.
--
-- `alembic_version` dit quelle migration la base porte. Elle appartient aux migrations,
-- que le pipeline ne joue pas.
REVOKE INSERT, UPDATE, DELETE, TRUNCATE
    ON audit_log, alembic_version
    FROM bibliometrie_pipeline;

-- Une table créée par une migration future est un produit du pipeline jusqu'à preuve du
-- contraire : elle lui est ouverte en écriture, là où l'API ne la reçoit qu'en lecture.
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE, TRUNCATE, MAINTAIN ON TABLES TO bibliometrie_pipeline;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO bibliometrie_pipeline;

-- Ce qui n'est délibérément pas accordé : la propriété des objets et `CREATE` sur le schéma,
-- donc toute modification de structure — création, altération, suppression de table, d'index
-- ou de vue. `CONNECT` sur la base et `TEMPORARY` viennent du rôle PUBLIC ; le pipeline
-- construit ses tables de travail en `CREATE TEMP TABLE`, qui relève de ce second droit et non
-- d'une création dans le schéma. Les rétablir nommément si l'hébergeur les retire à PUBLIC.
