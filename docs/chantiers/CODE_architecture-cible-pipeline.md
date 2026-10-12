# Réflexion — Architecture cible du pipeline

## Contexte

Le pipeline alimente la base de données. L'objectif est un pipeline clair, lisible, maintenable et conforme aux pratiques courantes du domaine.

### Constats (code au 2026-10-10)

- **19 tables ont deux écrivains, l'API et le pipeline** : `publications`, `persons`, `source_authorships`, `journals`, `addresses`… Les tables `structures`, `perimeters`, `structure_name_forms`, `structure_tutelles` et `config` sont écrites par l'API et le seed seulement.
- **Le code circule dans les deux sens entre API et pipeline.** L'API instancie 5 adaptateurs du pipeline. 14 modules du pipeline appellent des services de l'API.
- **Acquisition et transformation s'entremêlent.** `publishers_journals` interroge Crossref, OpenAlex, le Sudoc et le DOAJ au milieu de la résolution. `oa_status` interroge Unpaywall en fin de run.
- **Plusieurs phases lisent des données du run précédent.**
- **72 des 105 modules de `application/pipeline/` passent par des ports.** Pour une suite de transformations de tables en tables, cette séparation entre logique et SQL est artificielle : la logique est souvent le SQL.
- **Les décisions humaines disparaissent avec les entités auxquelles elles se rattachent.** En base locale, sur 761 rejets journalisés, 53 ont disparu avec leur publication et environ 440 avec leur personne.

## Démarche

Six questions, dans cet ordre. Chacune s'appuie sur les précédentes. La mise en pratique et les fiches chantier viennent après.

### 1. Identités stables

Quelles entités gardent leur identifiant d'un run à l'autre, et que devient l'identifiant d'une entité qui disparaît ?

**Constat**
- `publications.id` : la réconciliation reconduit la publication qui a le DOI, sinon celle de la plus petite notice.
- `persons.id` : stable tant que les signatures gardent leur `person_id` ; la phase `persons` supprime les personnes devenues vides.
- Un identifiant absorbé par une fusion disparaît.

**Décisions**
- **La clé interne d'une entité n'a pas à être pérenne.** On accède aux données par l'interface ; un utilisateur de l'API filtre sur des critères, pas sur une clé interne.
- **Pas de redirection sans cas d'usage qui en prouve l'utilité.** Une entité qui disparaît emporte ses identifiants.
- **Une décision humaine s'appuie sur des identifiants naturels quand ils existent** : DOI, ROR, ISSN, membre Crossref, ORCID, IdRef. Sinon, la question 2 fixe son rattachement.
- **Personnes : pas d'identifiant naturel général.** À la fusion de deux personnes, leurs décisions sont reportées sur la personne conservée.
- **Un regroupement recalculé en entier peut renuméroter ses entités.**

### 2. Décisions humaines et données de référence

Comment une intervention humaine survit-elle aux recalculs du pipeline ? Traité par le chantier [Décisions humaines durables](archived/2026-10-11_DATA_decisions-humaines-durables.md).

**Acquis**
- Trois formes de stockage : tables dédiées (rejets, confirmations, non-doublons) ; statuts dans des tables que le pipeline remplit aussi (identifiants, formes de nom, liens adresse-structure) ; marqueurs dans la ligne (`journals.manual_fields`, `persons.exclusion`).
- Un champ saisi à la main n'est plus écrit par le pipeline. Le journal d'audit garde l'auteur et la date.
- Un rejet vise les notices d'une publication : il survit aux fusions et scissions de la réconciliation. Une signature confirmée l'emporte sur le rejet.
- Une entité visée par un lien confirmé ou rejeté, ou par une exclusion, n'est pas supprimée quand elle se vide.
- Chaque fusion (personnes, revues, éditeurs) applique la règle de fusion de chaque donnée de l'entité, recensée dans le domaine ; un test confronte ce recensement au schéma.

- Fusions automatiques : aucun besoin de veto constaté pour les revues. Pour les publications, des verdicts durables de scission et de fusion forcée, relus par la réconciliation : chantier [Gestion des publications dans l'administration](METIER_gestion-admin-des-publications.md).

### 3. Nature de chaque table

Chaque table relève d'une catégorie :

- **brut** : ce que les sources ont renvoyé (`staging`) ;
- **décision** : ce qu'un humain a tranché (rejets, confirmations, non-doublons, statuts) ;
- **référentiel tenu à la main** : structures, périmètres, configuration, formes de nom des structures ;
- **état conservé d'un run à l'autre** : ce que le pipeline ne sait pas recalculer, comme les identifiants stables ou les échecs de recherche (`failed_lookups`) ;
- **dérivé recalculable** : tout le reste ;
- **diffusion** : ce que lisent les consommateurs en lecture seule, construit à partir du dérivé et des référentiels. L'API publique d'abord ; d'autres consommateurs ensuite, si la trajectoire se confirme.

**Décision : un schéma PostgreSQL par domaine.** Les tables centrales (personnes, revues, publications, signatures) sont mixtes : un découpage par catégorie les rangerait toutes dans le dérivé, sans dire qui écrit quoi. Le découpage par domaine suit la lecture du modèle. La catégorie de chaque table reste documentée ; les droits la vérifient là où elle est nette (décisions, référentiels).

**Décision : la diffusion est un schéma de vues.** Les consommateurs en lecture seule lisent un schéma `diffusion` fait de vues sur les tables des domaines, et n'ont aucun droit ailleurs. Les vues fixent le contrat (noms, colonnes, filtres) : les tables internes changent sans toucher les consommateurs. Reporté : ce n'est pas urgent.

**Contrat de la résolution** : en entrée, les notices et les signatures sources, plus les décisions ; en sortie, une table de correspondance entre chaque notice ou signature et son entité. Le contrat tient quel que soit l'algorithme.

Une forme possible, celle des modèles par paires (dnet-dedup, Splink). Chaque étape lit en base ce que la précédente a écrit :

1. **paires candidates** : les paires de notices ou de signatures qui concordent, avec leur origine ou leur score ;
2. **décisions** : les confirmations ajoutent des paires, les rejets et les non-doublons en retirent ;
3. **groupes** : composantes connexes sur les paires retenues ;
4. **identifiant** : chaque groupe reçoit un identifiant ;
5. **entité** : construite à partir des membres du groupe.

La table des paires est du dérivé recalculable. C'est la sortie d'un modèle probabiliste comme de règles déterministes.

**Acquis**
- L'inventaire des lectures et écritures de chaque table : [inventaire](archived/2026-10-11_CODE_pipeline-dag_inventaire.md).

**Classement proposé** (51 tables et vues matérialisées)
- **brut** : `staging`, `ror_organizations`, `ror_relations`, `ror_dump_imports`, `persons_rh`, `apc_payments`.
- **référentiel tenu à la main** : `structures`, `structure_name_forms`, `structure_tutelles`, `perimeters`, `config`, `countries`, `languages`, `language_forms`, `place_name_forms`.
- **décision** : `rejected_authorships`, `confirmed_authorships`, `distinct_persons`, `audit_log`.
- **état conservé** : `failed_lookups`, `pipeline_phase_executions`, `alembic_version`.
- **dérivé, sans décision** : `source_publications`, `author_identifying_keys`, `source_authorship_addresses`, `source_authorship_rors`, `publications_detail`, `authorships`, `publication_relations`, `publication_subjects`, `subjects`, `journal_doi_namespaces`, `journal_name_forms`, `publisher_name_forms`, `doi_prefixes`, `monographs`, `perimeter_structures`.
- **dérivé, avec des décisions dans la ligne** : `persons` (exclusion, nom), `person_identifiers` et `person_name_forms` (statuts), `address_structures` (lien confirmé ou rejeté), `addresses` (pays), `journals` (`manual_fields`), `journal_issns`, `publishers`, `source_authorships` (personne d'une signature confirmée), `publications`.
- **vues matérialisées, lues par l'API** : `source_authorship_structures`, `authorship_structures`, `publication_structures`, `subject_cooccurrences`.

Les tables mixtes sont les entités centrales : un schéma par catégorie les range dans le dérivé, et les droits ne disent plus qui écrit quoi. Seules les tables de décision et les référentiels tenus à la main relèvent de l'API seule.

**Ouvert**
- Liste des schémas de domaine et rattachement de chaque table. Proposition : `sources`, `persons`, `publications`, `containers` (revues, éditeurs, monographies), `structures` (structures, adresses, périmètres), `ref` (pays, langues, ROR, configuration), `ops` (audit, exécutions, migrations).
- Forme par paires : les composantes connexes ne respectent pas les interdictions. La réconciliation des publications sépare toujours deux DOI différents, ce que la transitivité des paires ne garantit pas. L'étape 3 devient alors un regroupement sous contraintes, et l'étape 2 reçoit aussi les interdictions issues des règles.
- Forme par paires : les décisions sur les personnes visent des entités (un rejet vise un couple publication-personne, un non-doublon deux personnes), non des paires de signatures. Leur traduction en contraintes sur les signatures dépend de la question 2.
- La cascade des personnes rattache une signature à une personne existante, sans comparer les signatures entre elles : forme de ReCiter, autre que la forme par paires.

### 4. Graphe

Le graphe est un contrat vérifié par les tests. Ses nœuds et son critère sont posés dans le chantier [Graphe de dépendances du pipeline](archived/2026-10-11_CODE_pipeline-dag.md) ; la déclaration est `pipeline/graph.py`.

**Acquis**
- Les nœuds, avec les données qu'ils lisent et écrivent et leurs lectures du run précédent ; un test vérifie que l'ordre d'exécution les respecte.
- Une seule boucle d'acquisition ciblée, gardée : `fetch_missing` cherche les documents des publications du périmètre établi au run précédent.
- `resolve_ra` résout les DOI du run, juste avant `publishers_journals`. Les référentiels vides sont supprimés dans le run qui les vide.

**Ouvert**
- Recalcul complet ou incrémental, nœud par nœud, d'après la nature de ses tables. Dépend de la durée d'un recalcul complet. Le pipeline de Stanford est passé du recalcul complet à l'incrémental.
- `publications.reconcile`, aujourd'hui un seul nœud : le scinder selon les étapes de la forme par paires, si elle est retenue.
- Place des appels réseau. Hypothèse : acquisition séparée de la transformation, qui se rejoue alors sur une copie de la base.
- Phases réduites à des groupes d'affichage ; exécution en parallèle des nœuds sans dépendance entre eux (`affiliations` et `publishers_journals`, les quatre enrichissements finaux).

### 5. Organisation du code

**Constat (2026-10-11)**
- Le pipeline tient sur quatre couches : `application/pipeline` (106 modules), `application/ports/pipeline` (50), `infrastructure/pipeline` (37), `interfaces/cli/phases` (18 câblages). Les clients HTTP des sources sont dans `infrastructure/sources` (59).
- Les opérations « trouver ou créer » (éditeur, revue, monographie), la création de publication et le rattachement d'une signature vivent dans `application/services`, mais seul le pipeline les appelle.
- Partages réels avec l'API : création et nom d'une personne ; recalcul d'une publication ; propagation du périmètre et des pays d'une adresse ; fermeture des périmètres ; reconstruction d'une authorship.

**Décisions**
- **Un paquet racine `pipeline/`, hors des couches hexagonales.** L'architecture hexagonale ne convient pas au pipeline : pas de ports, chaque nœud contient son SQL. Les règles pures restent dans `domain/`.
- **Le pipeline possède ses opérations.** L'API passe par une interface publique du pipeline, limitée aux recalculs ciblés ; les partages se réduisent au strict nécessaire, et chaque recalcul ciblé se justifie par un effet immédiat attendu dans l'interface.
- **Découpage par domaine**, aligné sur les schémas : `pipeline/sources/<source>` (acquisition, normalisation et client HTTP de chaque source), `pipeline/structures`, `pipeline/containers`, `pipeline/publications`, `pipeline/persons` ; `graph.py` et l'orchestrateur à la racine.
- **Migration une phase à la fois**, sous contrats d'import, en commençant par une phase petite et autonome (`countries` ou `relations`).
- **Le câblage `interfaces/cli/phases` disparaît** avec les ports. Le point d'entrée `run_pipeline` passe dans `pipeline/`.

**Hypothèses**
- Fusion des métadonnées d'une publication : un fichier par champ consolidé, qui liste ses règles par ordre de priorité des sources.
- Tests en miroir de l'arborescence, sur le [jeu de données commun](CODE_jeu-de-donnees-commun.md).
- Règles d'import vérifiées par `import-linter` : `pipeline/` importe `domain/` et les modules techniques neutres (connexion, réglages, journalisation), jamais `application/` ; seul un adaptateur de l'API importe l'interface publique du pipeline.

**Ouvert**
- Recalculs ciblés : lesquels garder, lesquels laisser au run suivant ?
- Scripts `imports/` et `maintenance/` : nœuds manuels du pipeline, ou outils à part ? Tri des scripts `oneshot/` déjà joués.
- Priorités entre sources et seuils : dans le domaine, testés avec le code (`SOURCE_PRIORITY`), ou dans un fichier de configuration modifiable sans toucher au code ?

### 6. Épreuves

La cible est confrontée à des situations concrètes pendant la migration ([Le pipeline en paquet racine](CODE_pipeline-package-racine.md)) : chaque phase migrée éprouve les situations qui la concernent. Ce qui ne tient pas sort de la cible.

Situations :
- fusion de revues, faite par l'admin ou par le pipeline ;
- fusion de personnes, dont l'une est rejetée sur une publication de l'autre ;
- DOI d'une notice corrigé entre deux runs ;
- signature rejetée par l'admin, seule signature du périmètre de sa publication ;
- notice OpenAlex de plus de 100 auteurs rapatriée par DOI ;
- panne d'une API au milieu d'un run ;
- nouvelle source ;
- règle de correction modifiée ;
- deux publications regroupées à tort par un DOI commun ;
- cascade des personnes remplacée par Splink.

## Hors de la cible, à décider plus tard

- Algorithme de résolution des personnes : cascade de règles ou modèle probabiliste, et avec lui le recalcul complet de la résolution. Le contrat de la résolution (question 3) doit tenir dans les deux cas.
  - Pour le probabiliste : Splink plutôt qu'un modèle maison.
  - Splink additionne les comparaisons comme si elles étaient indépendantes : revue, sujet et structure, corrélés, sont à regrouper en une seule comparaison.
  - Splink ne prévoit pas les liens imposés ou interdits : les décisions s'appliquent à l'étape 2 du contrat.
- Conception de la résolution, deux idées de ReCiter : enregistrer ce qui a concordé et pas seulement la règle ; réutiliser les confirmations et les rejets d'une personne comme indices pour ses autres signatures.
- Outillage : orchestrateur par *assets* (Dagster), dbt, publication en bloc après contrôle (*Write-Audit-Publish*).

## Mise en pratique

Après les six questions. La refonte avance nœud par nœud. Elle commence par un test de non-régression : sur une copie figée de la base, on compare les tables produites avant et après chaque modification.

## Documents liés

- [benchmark-pipelines.md](benchmark-pipelines.md) : idées relevées dans le code d'autres pipelines de publications (Stanford, CRISalid, ReCiter, OpenAIRE), avec les liens vers les fichiers.
