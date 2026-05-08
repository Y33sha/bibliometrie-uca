# Sources de données — Bibliométrie UCA

## Vue d'ensemble

Le système intègre 6 sources bibliographiques principales, complétées par des imports manuels et des APIs d'enrichissement.

| Source | Type | Couverture | API |
|--------|------|-----------|-----|
| HAL | Archive ouverte | Publications déposées par les chercheurs UCA | Solr (search) + ref/author + ref/structure |
| OpenAlex | Base bibliométrique ouverte | Publications mondiales, rattachement institutionnel par affiliation | REST (works, sources) |
| Web of Science | Base bibliométrique commerciale | Publications indexées WoS, affiliation OG | REST (Expanded API, quota annuel) |
| ScanR | Portail officiel du MESRE | Publications de l'écosystème français de la recherche | Elasticsearch (DataESR) |
| theses.fr | Portail officiel des thèses françaises | Thèses soutenues + en cours, rattachement par PPN d'établissement | REST (data.gouv.fr) |
| CrossRef | Registre des DOI (autorité éditeur) | Métadonnées canoniques par DOI : doc_type, journal, dates, license, ORCIDs article-level, relations entre publications | REST (works, polite pool via mailto) |
| Unpaywall | Enrichissement OA | Statut Open Access par DOI | REST (gratuit, 100k req/jour) |
| Base RH | Import manuel | Personnel UCA (noms, départements, rôles) | Fichier CSV |
| Données APC | Import manuel | Paiements APC (montants, éditeurs) | Fichier CSV |

## Sources de données bibliographiques


### Spécificités

#### <span id='sources-affiliations'></span>Gestion des affiliations


- Dans **OpenAlex** et **WoS**, les liens authorships-structures sont résolus de manière algorithmique à partir des adresses liées aux publications. Ce processus génère beaucoup d'erreurs causées par des similitudes de noms (dans OpenAlex principalement). Mais la donnée-source (*raw affiliation string*) est présente et exploitable. On ignore donc les structure_ids présents dans les sources et **on reconstruit l'affiliation à partir des adresses brutes**. ([Phase `addresses` du pipeline](pipeline#phase-4--addresses--adresses-et-affiliations).)

##### /!\ Obsolète: à réécrire <!--TODO: Réécrire documentation Sources-->
- Dans **HAL**, les liens authorships-structures sont basés sur les affiliations renseignées dans les comptes HAL des auteurs au moment du dépôt (Cf [doc HAL](https://doc.hal.science/depot-fonctionnement-de-l-affiliation-automatique/#)), et éventuellement complétés manuellement par le déposant. Les métadonnées de HAL ne contiennent pas les adresses brutes. La seule option est donc de récupérer les affiliations telles quelles, via un *mapping* entre `hal_structures` et `structures` canoniques. Les erreurs sont détectées *a posteriori* (pages [hal-problems](guide-utilisateur#problemes-hal)).
Le *mapping* est géré via la page [admin/structures](guide-utilisateur#gestion-des-structures-adminstructures).
La résolution des affiliations se fait pendant la [phase `affiliations` du pipeline](pipeline#affiliations).

#### <span id='entites-auteurs'></span>Nature des entités auteurs

Chaque source contient ses propres identifiants internes pour les entités auteurs. Le traitement des auteurs correspond à la [phase `personnes`](pipeline#phase-7--persons--création-de-personnes) du pipeline.

**`source_persons`** est restreinte aux sources avec un **identifiant auteur stable** (cf. [chantier source_persons](chantiers/2026-04-28_source-persons.md)) :
- HAL avec `hal_person_id` (compte HAL identifié)
- ScanR avec idref
- Theses avec PPN

Pour les autres cas (OpenAlex, WoS, CrossRef, et les comptes HAL non identifiés / ScanR sans idref / theses sans PPN), aucun `source_persons` n'est créé : `source_authorships.source_person_id` reste NULL et les identifiants normalisés (orcid, idref, idhal, hal_person_id, researcher_id) vivent dans `source_authorships.identifiers` (JSONB).

- Dans **OpenAlex** et **WoS**, les entités auteurs présentes côté API sont algorithmiques et non fiables (un même auteur fréquemment divisé en entités multiples, ou plusieurs personnes confondues). On ne crée plus de `source_persons` pour ces sources : le matching personne se fait *de novo* à partir de `source_authorships.raw_author_name` et de `person_name_forms`. Les ORCIDs sont récupérés dans `source_authorships.identifiers->>'orcid'` puis remontés vers `person_identifiers` avec statut `pending` lors du matching.

- Dans **HAL**, deux cas de figure (pouvant coexister dans la même publication) :
    - L'auteur correspond à un compte HAL identifié (`hal_person_id` présent) : entité fiable, on crée un `source_persons` avec ce `hal_person_id`. Possibilité de récupérer d'autres identifiants (ORCID, IdRef, idHAL). Le `person_id` canonique est propagé à toutes les `source_authorships` du même compte HAL via l'Étape 0 du pipeline persons.
    - L'auteur n'est pas relié à un compte HAL identifié (form_id seul ou rien) : pas de `source_persons` HAL. On procède comme pour OpenAlex/WoS via `raw_author_name` + `identifiers`.

- Dans **ScanR** : `source_persons` créés uniquement avec un idref (= IdRef BNF). Sans idref, les ORCID éventuels vont dans `source_authorships.identifiers`.

- Dans **theses.fr** : `source_persons` créés uniquement avec un PPN (= IdRef BNF). Les non-auteurs (jurés, rapporteurs) sans PPN vivent uniquement dans `source_authorships`.

- Dans **CrossRef** : aucun `source_persons` (pas d'identité d'auteur stable côté API). L'ORCID éventuel va dans `source_authorships.identifiers`.

### HAL

#### API utilisées

**Search API** (`https://api.archives-ouvertes.fr/search`) — moissonnage des publications.
- Requête par collection labo (27 collections UCA) + portail global `clermont-univ`
- Champs Solr récupérés : voir `utils/hal.py` (`HAL_FIELDS`)
- Pagination par offset, 500 résultats/page, 0.5s de délai entre requêtes

**ref/author API** (`https://api.archives-ouvertes.fr/ref/author/`) — identifiants auteurs.
- Récupération ORCID et IdRef par `hal_person_id`
- Requête par batch (100 IDs par requête)

**ref/structure API** (`https://api.archives-ouvertes.fr/ref/structure/`) — métadonnées structures.
- Enrichissement des structures HAL (dates, parents, pays, identifiants externes)
- Requête par batch (50 IDs par requête)

#### Données récupérées

- **Publications** : titre, DOI, année, type de document, langue, journal, OA, URI
- **Auteurs** : nom complet, hal_person_id, idHAL, ORCID et IdRef (depuis le TEI `label_xml`)
- **Affiliations** : structures HAL rattachées à chaque auteur via `authIdHasStructure_fs` (pas d'adresses textuelles)
- **Collections** : `collCode_s` indique les collections auxquelles appartient le document

#### Particularités

- Les champs auteurs HAL "plats" (`authFullName_s`, `authQuality_s`) sont alignés par position. Les listes d'identifiants externes (`authORCIDIdExt_s`, `authIdRefIdExt_s`) sont **compactées** (valeurs non-null seulement) : l'alignement par auteur passe obligatoirement par le TEI `label_xml` où chaque `<author>` porte ses `<idno type="ORCID">` / `<idno type="IDREF">` / `<idno type="idhal">`.
- Le champ composite `authFullNameFormIDPersonIDIDHal_fs` contient form_id, person_id et idHAL dans un format à parser (`Nom_FacetSep_formId-personId_FacetSep_idhal`)
- Un même document peut apparaître dans plusieurs collections ; le champ `collection` en staging les agrège
- Les documents trouvés uniquement via le portail global (pas dans une collection labo) sont taggés `_portail_clermont-univ`
- Les documents cross-importés depuis OpenAlex ont `collection = NULL` (hors périmètre UCA)


### OpenAlex

#### API utilisée

**Works API** (`https://api.openalex.org/works`) — moissonnage des publications.
- Requête par institution (filtre `lineage`) + année
- Pagination par cursor, 200 résultats/page, 0.2s de délai (polite pool via email)
- L'API bulk tronque les authorships à 100 auteurs ; `refetch_truncated.py` re-télécharge individuellement les works concernés

**Sources API** (`https://api.openalex.org/sources`) — enrichissement APC des journaux.
- Récupération des prix APC catalogue (DOAJ) par openalex_id

#### Données récupérées

- **Publications** : titre, DOI, année, type, langue, OA status, citations, primary_location
- **Auteurs** : display_name, openalex_id, ORCID (attention : l'ORCID est sur l'entité auteur OA, pas toujours fiable pour l'authorship spécifique)
- **Affiliations** : `raw_affiliation_strings` (texte libre) + institutions structurées (openalex_id, ROR, pays)
- **Journaux/éditeurs** : source dans primary_location (titre, ISSN, type, OA model)

#### Particularités

- Le `raw_author_name` de l'authorship est plus fiable que `author.display_name` (ce dernier est un nom unifié par l'algo OA, qui peut être erroné)
- Le `meta_hash` (hash hors authorships) permet de détecter les vrais changements sans être perturbé par la troncature à 100 auteurs
- Si la `primary_location` pointe vers HAL (`hal.science/hal-XXXXX`), la publication est rattachée au document HAL existant plutôt que d'en créer une nouvelle
- Les ORCIDs OpenAlex sont sur `source_authorships.identifiers->>'orcid'` et utilisés avec prudence dans le pipeline persons (risque d'attribution erronée par l'algo OpenAlex — le matching nominal est appliqué avant de promouvoir un ORCID en `confirmed`)


### Web of Science

#### API utilisée

**Expanded API** (`https://api.clarivate.com/api/wos`) — moissonnage des publications.
- Requête par Organisation-Enhanced (OG) + année
- Pagination par offset (`firstRecord`), 100 résultats/page, 1s de délai
- Retry avec backoff exponentiel (API instable, rate limiting silencieux)
- Quota annuel limité (vérification au démarrage)

#### Données récupérées

- **Publications** : titre, DOI, année, type, langue, OA status
- **Auteurs** : display_name, last_name, first_name, daisng_id, researcher_id, ORCID
- **Affiliations** : adresses structurées dans le champ C1 (`[Author1; Author2] Address`)
- **Correspondant** : `reprint = "Y"` indique l'auteur correspondant

#### Particularités

- Deux formats de données : TSV (fichiers téléchargés) et API JSON (structure imbriquée `static_data`/`dynamic_data`). Le normaliseur gère les deux.
- Le DOI est profondément imbriqué : `dynamic_data.cluster_related.identifiers.identifier[].value` (peut être dict ou liste)
- La pagination par `queryId` ne fonctionne pas de manière fiable ; le script utilise `firstRecord` avec une nouvelle recherche à chaque page
- Pause longue toutes les 10 pages (15s) et entre chaque année (30s) pour ménager l'API
- Les DOI de preprints (10.48550, 10.21203, etc.) sont filtrés lors du cross-import

## APIs d'enrichissement

### Unpaywall

Script : `processing/enrich_oa_unpaywall.py`

Interroge l'API Unpaywall (`https://api.unpaywall.org/v2/{doi}`) pour chaque publication avec DOI. Met à jour `publications.oa_status`.

Règle métier : ne remplace jamais un statut `diamond` par `gold` (Unpaywall ne distingue pas le diamond OA du gold).

### OpenAlex Sources (APC)

Script : `processing/enrich_journal_apc.py`

Interroge l'API OpenAlex Sources pour les journaux avec `openalex_id`. Récupère les prix APC catalogue (DOAJ). Met à jour `journals.apc_amount`, `apc_currency`, `is_in_doaj`.

Note : ces données ne sont pas encore exploitées en aval dans l'application.


## Imports manuels

### <span id="donnees-rh"></span>Base RH (personnel UCA)

Fichier CSV importé via `interfaces/cli/import_rh.py` → table `persons_rh`.
- Contient : email, nom, prénom, département, rôle, dates de début/fin
- Rattaché à une personne du référentiel via `persons_rh.person_id`
- Sert de filtre dans l'annuaire personnes (filtre "Base RH")

Données fournies par la DPCG le 15/12/2025. La date est documentée dans la colonne `hr_export_date`. Cette extraction contient uniquement les **enseignants-chercheurs UCA**: pas les chercheurs CNRS, Inrae, etc., ni les personnels BIATSS UCA.

L'**affiliation** renseignée dans cette source est une chaîne de caractères (`UFR Médecine Pr Paramédic`, `IUT Info 43`) qui ne permet pas un mapping avec les laboratoires. Elle est affichée pour information, mais ne sert pas à créer les liens personne-structure dans l'appli. Les **liens personne-structure** dépendent des [*authorships*](glossaire#authorship).

La [création de personnes](pipeline#creation-personnes) se fait via les authorships des publications, indépendamment de l'existence d'une entrée `person_rh`.
La FK sur la table `person_rh` permet:
- d'enrichir les données sur les personnes;
- d'empêcher la suppression de ces personnes (lors de fusions ou de nettoyage en masse des personnes sans authorship UCA).

### <span id="donnees-apc"></span>Données APC

Données fournies par la Bibliothèque numérique le 11/03/2026.

Fichier CSV importé via `python -m interfaces.cli.imports.import_apc` → table `apc_payments`.
- Contient : DOI, montant en €, éditeur, labo payeur, année
- Rattaché aux publications par DOI et aux structures par nom

**Incomplet**. Cette extraction ne contient pas les APC payés après 2024, et contient des trous dans la colonne DOI.

A compléter par une extraction des [raw data](https://github.com/OpenAPC/openapc-de/blob/master/data/apc_de.csv) de [OpenAPC](https://treemaps.openapc.net/apcdata/clermont-u/). A ma connaissance OpenAPC ne propose pas d'API. **Fait: pas beaucoup mieux (les données s'arrêtent aussi en 2024)**
