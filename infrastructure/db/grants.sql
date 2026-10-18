-- =============================================================
-- Droits des rôles de connexion de l'API et du pipeline
-- =============================================================
--
-- SQL pur, sans commande psql : `alembic/env.py` l'applique après toute migration jouée,
-- et `roles.sql` l'inclut après avoir créé les rôles. Les droits d'une base suivent ainsi la
-- version de son schéma : une table recréée par une migration retrouve les siens.
--
-- Les ordres s'appliquent sous le propriétaire du schéma — `ALTER DEFAULT PRIVILEGES` ne porte
-- que sur les objets créés par le rôle courant. Le fichier se rejoue sans dommage : chaque
-- passage aligne les droits sur son contenu.


-- =============================================================
-- Rôle applicatif : privilèges de l'API, et rien de plus
-- =============================================================

-- Traverser les schémas, sans rien y créer.
GRANT USAGE ON SCHEMA public, sources, publications, persons, publishing, structures, ref, ops TO bibliometrie_app;

-- Lecture de tout : l'API sert des données bibliométriques, et aucune n'est réservée.
-- `ALL TABLES` couvre les vues matérialisées, qu'elle lit sans jamais les rafraîchir.
GRANT SELECT ON ALL TABLES IN SCHEMA public, sources, publications, persons, publishing, structures, ref, ops TO bibliometrie_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public, sources, publications, persons, publishing, structures, ref, ops TO bibliometrie_app;

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

REVOKE INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public, sources, publications, persons, publishing, structures, ref, ops FROM bibliometrie_app;

GRANT INSERT, UPDATE, DELETE ON
    structures.address_structures, publications.authorships, structures.perimeters, persons.person_name_forms,
    persons.persons, persons.rejected_authorships, structures.structure_name_forms, structures.structures
TO bibliometrie_app;

-- Un identifiant de personne s'ajoute et se rejette ; il ne se supprime pas, le rejet
-- gardant la trace qu'une attribution a été envisagée.
GRANT INSERT, UPDATE ON
    persons.person_identifiers
TO bibliometrie_app;

-- Un pays saisi à la main s'ajoute en candidat `manual`, et se retire.
GRANT INSERT, DELETE ON
    structures.address_country_candidates, structures.perimeter_structures, structures.structure_tutelles
TO bibliometrie_app;

-- `INSERT … ON CONFLICT DO UPDATE` exige le droit de mise à jour, que la ligne entre en
-- conflit ou non.
GRANT INSERT, UPDATE, DELETE ON
    persons.confirmed_authorships
TO bibliometrie_app;

GRANT UPDATE, DELETE ON
    publishing.journal_name_forms, publishing.journals, publications.publications, publishing.publisher_name_forms, publishing.publishers
TO bibliometrie_app;

-- Les ISSN d'une revue s'éditent à l'administration, et rejoignent la revue qui en absorbe une autre.
GRANT INSERT, UPDATE, DELETE ON
    publishing.journal_issns
TO bibliometrie_app;

GRANT INSERT ON
    ops.audit_log
TO bibliometrie_app;

GRANT INSERT, UPDATE ON
    persons.distinct_persons, public.merge_redirects, publications.publications_detail
TO bibliometrie_app;

GRANT UPDATE ON
    structures.addresses, publishing.apc_payments, ops.config, publishing.doi_prefixes, publishing.monographs, sources.source_authorships,
    sources.source_publications, publications.source_authorship_groups
TO bibliometrie_app;

-- Une table créée par une migration future est lisible, et rien de plus : sa nature se
-- tranche en l'ajoutant nommément ci-dessus, plutôt qu'en la découvrant écrite.
ALTER DEFAULT PRIVILEGES IN SCHEMA public, sources, publications, persons, publishing, structures, ref, ops
    GRANT SELECT ON TABLES TO bibliometrie_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public, sources, publications, persons, publishing, structures, ref, ops
    GRANT USAGE, SELECT ON SEQUENCES TO bibliometrie_app;

-- Ce qui n'est délibérément pas accordé : TRUNCATE, l'écriture sur les tables du pipeline,
-- la propriété des objets, et CREATE sur les schémas. `CONNECT` sur la base et `TEMPORARY`
-- (l'API crée des tables temporaires en tâche de fond) viennent du rôle PUBLIC ; les
-- rétablir nommément si l'hébergeur les retire à PUBLIC.


-- =============================================================
-- Rôle du pipeline : construire les données, sans toucher au schéma
-- =============================================================

-- Traverser les schémas, sans rien y créer.
GRANT USAGE ON SCHEMA public, sources, publications, persons, publishing, structures, ref, ops TO bibliometrie_pipeline;

-- Lecture et écriture de l'ensemble des données. Le pipeline construit le contenu de ces
-- tables et le reconstruit d'une exécution à l'autre : les énumérer ici n'ajouterait aucune
-- information — la liste serait celle du schéma — et vieillirait à chaque migration. La
-- restriction qui porte n'est pas la table atteinte, c'est ce qui reste hors d'atteinte : la
-- structure, la propriété des objets, et les deux exceptions retirées plus bas.
GRANT SELECT, INSERT, UPDATE, DELETE, TRUNCATE
    ON ALL TABLES IN SCHEMA public, sources, publications, persons, publishing, structures, ref, ops
    TO bibliometrie_pipeline;
-- `UPDATE` sur les séquences : `setval` le demande, et le pipeline remet à un le compteur des
-- tables qu'il reconstruit entièrement.
GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA public, sources, publications, persons, publishing, structures, ref, ops TO bibliometrie_pipeline;

-- `MAINTAIN` couvre `VACUUM`, `ANALYZE`, `REFRESH MATERIALIZED VIEW`, `CLUSTER`, `REINDEX` et
-- `LOCK TABLE`. Le pipeline exerce les trois premières : le staging est nettoyé après la
-- normalisation, les statistiques sont rafraîchies avant les jointures lourdes, et trois vues
-- matérialisées sont recalculées.
--
-- Ce privilège date de PostgreSQL 17. Avant lui, rafraîchir une vue matérialisée exigeait d'en
-- être propriétaire, faute de droit accordable : le pipeline se connectait alors sous le
-- propriétaire du schéma pour un pouvoir qu'il n'exerce pas.
GRANT MAINTAIN ON ALL TABLES IN SCHEMA public, sources, publications, persons, publishing, structures, ref, ops TO bibliometrie_pipeline;

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
    ON ops.audit_log, alembic_version
    FROM bibliometrie_pipeline;

-- Une table créée par une migration future est un produit du pipeline jusqu'à preuve du
-- contraire : elle lui est ouverte en écriture, là où l'API ne la reçoit qu'en lecture.
ALTER DEFAULT PRIVILEGES IN SCHEMA public, sources, publications, persons, publishing, structures, ref, ops
    GRANT SELECT, INSERT, UPDATE, DELETE, TRUNCATE, MAINTAIN ON TABLES TO bibliometrie_pipeline;
ALTER DEFAULT PRIVILEGES IN SCHEMA public, sources, publications, persons, publishing, structures, ref, ops
    GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO bibliometrie_pipeline;

-- Ce qui n'est délibérément pas accordé : la propriété des objets et `CREATE` sur les schémas,
-- donc toute modification de structure — création, altération, suppression de table, d'index
-- ou de vue. `CONNECT` sur la base et `TEMPORARY` viennent du rôle PUBLIC ; le pipeline
-- construit ses tables de travail en `CREATE TEMP TABLE`, qui relève de ce second droit et non
-- d'une création dans un schéma. Les rétablir nommément si l'hébergeur les retire à PUBLIC.
