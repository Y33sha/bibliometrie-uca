-- =============================================================
-- Droits des rôles de connexion de l'API et du pipeline
-- =============================================================
--
-- SQL pur, sans commande psql : `alembic/env.py` l'applique après toute migration jouée,
-- et `roles.sql` l'inclut après avoir créé les rôles. Les droits d'une base suivent ainsi la
-- version de son schéma : une table recréée par une migration retrouve les siens. Une
-- modification de ce fichier atteint les bases existantes par une migration, vide au besoin.
--
-- Les ordres s'appliquent sous le propriétaire du schéma — `ALTER DEFAULT PRIVILEGES` ne porte
-- que sur les objets créés par le rôle courant. Le fichier se rejoue sans dommage : chaque
-- passage aligne les droits sur son contenu.
--
-- Les droits sur tout le contenu de la base s'accordent schéma par schéma, dans un bloc `DO`
-- qui parcourt les schémas de la base, hors schémas système. Un schéma créé par une migration
-- les reçoit sans modification de ce fichier.


-- =============================================================
-- Rôle applicatif : privilèges de l'API, et rien de plus
-- =============================================================

-- Pour chaque schéma :
-- - traverser le schéma, sans rien y créer ;
-- - lire tout : l'API sert des données bibliométriques, et aucune n'est réservée. `ALL TABLES`
--   couvre les vues matérialisées, qu'elle lit sans jamais les rafraîchir ;
-- - retirer toute écriture, accordée ensuite table par table ;
-- - lire seulement les tables créées par une migration future : sa nature se tranche en
--   l'ajoutant nommément ci-dessous, plutôt qu'en la découvrant écrite.
DO $$
DECLARE
    s text;
BEGIN
    FOR s IN
        SELECT nspname FROM pg_namespace
        WHERE nspname NOT LIKE 'pg\_%' AND nspname <> 'information_schema'
    LOOP
        EXECUTE format('GRANT USAGE ON SCHEMA %I TO bibliometrie_app', s);
        EXECUTE format('GRANT SELECT ON ALL TABLES IN SCHEMA %I TO bibliometrie_app', s);
        EXECUTE format('GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA %I TO bibliometrie_app', s);
        EXECUTE format('REVOKE INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA %I FROM bibliometrie_app', s);
        EXECUTE format('ALTER DEFAULT PRIVILEGES IN SCHEMA %I GRANT SELECT ON TABLES TO bibliometrie_app', s);
        EXECUTE format('ALTER DEFAULT PRIVILEGES IN SCHEMA %I GRANT USAGE, SELECT ON SEQUENCES TO bibliometrie_app', s);
    END LOOP;
END
$$;

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
--
-- Toute écriture est d'abord retirée : rejouer le fichier aligne les droits sur cette liste,
-- y compris quand une table en sort.

GRANT INSERT, UPDATE, DELETE ON
    structures.address_structures, structures.perimeters, persons.person_name_forms,
    persons.persons, persons.rejected_contributions, structures.structure_name_forms, structures.structures
TO bibliometrie_app;

-- Un identifiant de personne s'ajoute et se rejette ; il ne se supprime pas, le rejet
-- gardant la trace qu'une attribution a été envisagée.
GRANT INSERT, UPDATE ON
    persons.person_identifiers
TO bibliometrie_app;

-- Un pays saisi à la main s'ajoute en candidat `manual`, et se retire.
GRANT INSERT, DELETE ON
    structures.address_country_candidates, structures.perimeter_structures, structures.structure_parents
TO bibliometrie_app;

-- `INSERT … ON CONFLICT DO UPDATE` exige le droit de mise à jour, que la ligne entre en
-- conflit ou non.
GRANT INSERT, UPDATE, DELETE ON
    persons.confirmed_source_contributions
TO bibliometrie_app;

-- Une saisie manuelle de pays marque l'adresse saisie, et les adresses dont le pays change.
-- Une décision sur un ORCID ou un IdRef, ou la correction d'un prénom, marque les
-- publications à regrouper. Une correction d'adresse marque les enregistrements sources sans
-- publication qui entrent dans le périmètre, et les groupes des contributions sources dont les
-- indices de périmètre changent. Le rejet d'un identifiant ou d'une forme de nom marque les
-- groupes dont la personne est à redécider. Le marquage passe par `INSERT … ON CONFLICT DO UPDATE`.
GRANT INSERT, UPDATE ON
    queues.address_candidates_queue, queues.address_countries_queue,
    queues.publication_contributions_queue, queues.source_record_keys_queue,
    queues.contribution_attributes_queue, queues.contribution_resolution_queue
TO bibliometrie_app;

GRANT UPDATE, DELETE ON
    publishing.serials, publications.publications, publishing.publisher_name_forms, publishing.publishers
TO bibliometrie_app;

-- La fusion d'une revue sans ISSN dans une autre revue est gardée comme décision de l'administration.
GRANT INSERT, UPDATE, DELETE ON
    publishing.serial_title_decisions
TO bibliometrie_app;

-- Les ISSN d'une revue absorbée par une fusion rejoignent la revue conservée.
GRANT UPDATE ON
    publishing.serial_issns
TO bibliometrie_app;

GRANT INSERT ON
    ops.audit_log
TO bibliometrie_app;

-- Une fusion manuelle de publications s'enregistre ; elle ne se modifie pas. Elle réaligne
-- les auteurs de la publication conservée, donc récrit ses contributions.
GRANT INSERT ON
    publications.manual_merges, publications.manual_merge_source_records
TO bibliometrie_app;

GRANT INSERT, DELETE ON
    publications.contributions, publications.aligned_source_contributions
TO bibliometrie_app;

-- Au démarrage, l'API crée l'utilisateur `ADMIN_USER` et lui attribue le rôle admin s'ils
-- manquent. `INSERT … ON CONFLICT DO NOTHING` n'exige que le droit d'insertion.
GRANT INSERT ON
    ops.users, ops.user_roles
TO bibliometrie_app;

GRANT INSERT, UPDATE ON
    public.merge_redirects, publications.publications_detail
TO bibliometrie_app;

-- Une décision « personnes distinctes » s'annule depuis le volet de la personne.
GRANT INSERT, UPDATE, DELETE ON
    persons.distinct_persons
TO bibliometrie_app;

GRANT UPDATE ON
    structures.addresses, publishing.apc_payments, ops.config, publishing.doi_prefixes, publishing.monographs, sources.source_contributions,
    sources.source_records, sources.source_record_identifiers, publications.contributions
TO bibliometrie_app;

-- Ce qui n'est délibérément pas accordé : TRUNCATE, l'écriture sur les tables du pipeline,
-- la propriété des objets, et CREATE sur les schémas. `CONNECT` sur la base et `TEMPORARY`
-- (l'API crée des tables temporaires en tâche de fond) viennent du rôle PUBLIC ; les
-- rétablir nommément si l'hébergeur les retire à PUBLIC.


-- =============================================================
-- Rôle du pipeline : construire les données, sans toucher au schéma
-- =============================================================

-- Pour chaque schéma :
-- - traverser le schéma, sans rien y créer ;
-- - lire et écrire l'ensemble des données. Le pipeline construit le contenu de ces tables et
--   le reconstruit d'une exécution à l'autre : les énumérer ici n'ajouterait aucune
--   information — la liste serait celle du schéma — et vieillirait à chaque migration. La
--   restriction qui porte n'est pas la table atteinte, c'est ce qui reste hors d'atteinte : la
--   structure, la propriété des objets, et les deux exceptions retirées plus bas ;
-- - `UPDATE` sur les séquences : `setval` le demande, et le pipeline remet à un le compteur
--   des tables qu'il reconstruit entièrement ;
-- - `MAINTAIN`, qui couvre `VACUUM`, `ANALYZE`, `REFRESH MATERIALIZED VIEW`, `CLUSTER`,
--   `REINDEX` et `LOCK TABLE`. Le pipeline exerce les trois premières : le staging est nettoyé
--   après la normalisation, les statistiques sont rafraîchies avant les jointures lourdes, et
--   trois vues matérialisées sont recalculées. Ce privilège date de PostgreSQL 17. Avant lui,
--   rafraîchir une vue matérialisée exigeait d'en être propriétaire ;
-- - ouvrir en écriture les tables créées par une migration future : une telle table est un
--   produit du pipeline jusqu'à preuve du contraire, là où l'API ne la reçoit qu'en lecture.
DO $$
DECLARE
    s text;
BEGIN
    FOR s IN
        SELECT nspname FROM pg_namespace
        WHERE nspname NOT LIKE 'pg\_%' AND nspname <> 'information_schema'
    LOOP
        EXECUTE format('GRANT USAGE ON SCHEMA %I TO bibliometrie_pipeline', s);
        EXECUTE format('GRANT SELECT, INSERT, UPDATE, DELETE, TRUNCATE ON ALL TABLES IN SCHEMA %I TO bibliometrie_pipeline', s);
        EXECUTE format('GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA %I TO bibliometrie_pipeline', s);
        EXECUTE format('GRANT MAINTAIN ON ALL TABLES IN SCHEMA %I TO bibliometrie_pipeline', s);
        EXECUTE format('ALTER DEFAULT PRIVILEGES IN SCHEMA %I GRANT SELECT, INSERT, UPDATE, DELETE, TRUNCATE, MAINTAIN ON TABLES TO bibliometrie_pipeline', s);
        EXECUTE format('ALTER DEFAULT PRIVILEGES IN SCHEMA %I GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO bibliometrie_pipeline', s);
    END LOOP;
END
$$;

-- Des tables sont reprises, l'accord global les ayant d'abord couvertes. Les retirer après
-- coup dit ce qu'elles sont plutôt que de les oublier dans une énumération.
--
-- `audit_log` trace les décisions humaines prises depuis l'interface d'administration.
-- Le pipeline n'en prend aucune : l'écriture lui permettrait d'y déposer une trace
-- qu'aucune personne n'a produite, ce qui ôterait à la table ce qu'elle vaut.
--
-- `users`, `roles` et `user_roles` disent qui ouvre une session et avec quels droits. Le
-- script `manage_users` les écrit sous le propriétaire du schéma.
--
-- `alembic_version` dit quelle migration la base porte. Elle appartient aux migrations,
-- que le pipeline ne joue pas.
--
-- `manual_merges` et `manual_merge_source_records` gardent les fusions de publications
-- décidées par l'administration. Le pipeline les lit seulement.
REVOKE INSERT, UPDATE, DELETE, TRUNCATE
    ON ops.audit_log, ops.users, ops.roles, ops.user_roles, alembic_version,
    publications.manual_merges, publications.manual_merge_source_records
    FROM bibliometrie_pipeline;

-- Ce qui n'est délibérément pas accordé : la propriété des objets et `CREATE` sur les schémas,
-- donc toute modification de structure — création, altération, suppression de table, d'index
-- ou de vue. `CONNECT` sur la base et `TEMPORARY` viennent du rôle PUBLIC ; le pipeline
-- construit ses tables de travail en `CREATE TEMP TABLE`, qui relève de ce second droit et non
-- d'une création dans un schéma. Les rétablir nommément si l'hébergeur les retire à PUBLIC.
