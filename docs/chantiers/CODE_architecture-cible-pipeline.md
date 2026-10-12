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

Cinq questions, dans cet ordre. Chacune s'appuie sur les précédentes. La mise en pratique et les fiches chantier viennent après.

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

**À mettre en œuvre**
- Les schémas de domaine et le rattachement de chaque table. Proposition : `sources`, `persons`, `publications`, `containers` (revues, éditeurs, monographies), `structures` (structures, adresses, périmètres), `ref` (pays, langues, ROR, configuration), `ops` (audit, exécutions, migrations).

### 4. Graphe

Le graphe est un contrat vérifié par les tests. Ses nœuds et son critère sont posés dans le chantier [Graphe de dépendances du pipeline](archived/2026-10-11_CODE_pipeline-dag.md) ; la déclaration est `pipeline/graph.py`.

**Acquis**
- Les nœuds, avec les données qu'ils lisent et écrivent et leurs lectures du run précédent ; un test vérifie que l'ordre d'exécution les respecte.
- Une seule boucle d'acquisition ciblée, gardée : `fetch_missing` cherche les documents des publications du périmètre établi au run précédent.
- `resolve_ra` résout les DOI du run, juste avant `publishers_journals`. Les référentiels vides sont supprimés dans le run qui les vide.
- Le recalcul est incrémental, et documenté nœud par nœud.
- Les appels réseau restent dans les nœuds qui en ont besoin, certains après des transformations. Leur code est regroupé dans `pipeline/ingestion`.

**Ouvert**
- À étudier : des phases réduites à des groupes d'affichage, et l'exécution en parallèle des nœuds sans dépendance entre eux (`affiliations` et `publishers_journals`, les quatre enrichissements finaux).
- Reports au run suivant : peser chaque lecture `previous_run` que déclare `pipeline/graph.py`, et les données différées sans lecture à rebours (`fetch_missing` n'est pas récursif), puis garder ou supprimer chaque report.

### 5. Organisation du code

Traité par le chantier [Le pipeline en paquet racine](archived/2026-10-12_CODE_pipeline-package-racine.md).

**Acquis**
- Un paquet racine `pipeline/`, hors des couches hexagonales, sans ports : chaque nœud contient son SQL. Les règles pures restent dans `domain/`.
- `pipeline/ingestion/<source>` contient l'extraction et la normalisation de chaque source, et les clients des enrichissements. La transformation est rangée par entité : `structures`, `containers`, `publications`, `persons`.
- L'API importe seulement `pipeline/public.py`, qui exporte les recalculs ciblés. Les écritures directes d'une entité existent de chaque côté, avec leurs règles dans `domain/`.
- `import-linter` vérifie ces règles d'import.

**Hypothèses**
- Fusion des métadonnées d'une publication : un fichier par champ consolidé, qui liste ses règles par ordre de priorité des sources.
- Tests sur le [jeu de données commun](CODE_jeu-de-donnees-commun.md).

**Ouvert**
- Recalculs ciblés appelés par l'API : lesquels garder, lesquels laisser au run suivant ? Concerne la clôture des périmètres, `in_perimeter` après la revue d'une adresse ou l'exclusion d'une personne, la construction des authorships à l'attribution d'orphelines, les pays d'un lot d'adresses, la requalification et la fusion des revues, le `pub_count` d'un éditeur fusionné. Chaque recalcul gardé se justifie par un effet immédiat attendu dans l'interface.
- Priorités entre sources et seuils : dans le domaine, testés avec le code (`SOURCE_PRIORITY`), ou dans un fichier de configuration modifiable sans toucher au code ?

## Hors de la cible, à décider plus tard

- Résolution des entités (algorithme, forme par paires) : chantier [Résolution des entités avec Splink](CODE_resolution-splink.md).
- Outillage : orchestrateur par *assets* (Dagster), dbt, publication en bloc après contrôle (*Write-Audit-Publish*).

## Mise en pratique

Après les cinq questions. La refonte avance nœud par nœud. Elle commence par un test de non-régression : sur une copie figée de la base, on compare les tables produites avant et après chaque modification.

## Documents liés

- [benchmark-pipelines.md](benchmark-pipelines.md) : idées relevées dans le code d'autres pipelines de publications (Stanford, CRISalid, ReCiter, OpenAIRE), avec les liens vers les fichiers.
