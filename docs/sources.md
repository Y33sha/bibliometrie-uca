# Sources de données — Bibliométrie UCA

*Document à jour au 2026-05-11.*

## Vue d'ensemble

Le système intègre 6 sources bibliographiques principales, complétées par des imports manuels et des APIs d'enrichissement.

> TODO: Documenter les credentials necessaires pour l'interrogation des API et comment se les procurer
> TODO: Documenter les modes d'interrogation possibles pour chaque source, celles qui sont utilisées ou non et pourquoi (par affiliation, par identifiant personne, par identifiant document)

| Source | Type | Couverture | API | Credentials |
|--------|------|-----------|-----|-----|
| HAL | Archive ouverte | Publications déposées par les chercheurs UCA | Solr (search) | aucun |
| OpenAlex | Base bibliométrique ouverte | Publications mondiales, rattachement institutionnel par affiliation | REST (works, sources) | clé API gratuite (créer un compte) |
| Web of Science | Base bibliométrique commerciale | Publications indexées WoS, affiliation OG | REST (Expanded API, quota annuel) | clé API sur demande (selon contrat établissement) |
| ScanR | Portail officiel du MESRE | Publications de l'écosystème français de la recherche | Elasticsearch (DataESR) | login et mot de passe sur demande (TODO: indiquer mail) |
| theses.fr | Portail officiel des thèses françaises | Thèses soutenues + en cours, rattachement par PPN d'établissement | REST (data.gouv.fr) | TODO: documenter |
| CrossRef | Registre des DOI (autorité éditeur) | Métadonnées canoniques par DOI : doc_type, journal, dates, license, ORCIDs article-level, relations entre publications | REST (works) | polite pool via mailto |
| Unpaywall | Enrichissement OA | Statut Open Access par DOI | REST (gratuit, 100k req/jour) |
| Base RH | Import manuel | Personnel UCA (noms, départements, rôles) | Fichier CSV |
| Données APC | Import manuel | Paiements APC (montants, éditeurs) | Fichier CSV |

## Sources de données bibliographiques

### Spécificités

#### <span id='sources-affiliations'></span>Gestion des affiliations

> **Section pas à jour**: à réécrire

- Dans **OpenAlex** et **WoS**, les liens authorships-structures sont résolus de manière algorithmique à partir des adresses liées aux publications. Ce processus génère beaucoup d'erreurs causées par des similitudes de noms (dans OpenAlex principalement). Mais la donnée-source (*raw affiliation string*) est présente et exploitable. On ignore donc les structure_ids présents dans les sources et **on reconstruit l'affiliation à partir des adresses brutes**. (Phase `affiliations` du pipeline.)

- Dans **HAL**, les liens authorships-structures sont basés sur les affiliations renseignées dans les comptes HAL des auteurs au moment du dépôt (Cf [doc HAL](https://doc.hal.science/depot-fonctionnement-de-l-affiliation-automatique/#)), et éventuellement complétés manuellement par le déposant. Les métadonnées de HAL ne contiennent pas les adresses brutes. La seule option est donc de récupérer les affiliations telles quelles : les noms de structures associés aux authorships sont traités fictivement comme des adresses par l'algo de résolution d'affiliation. Les erreurs sont détectées *a posteriori* (pages [hal-problems](guide-utilisateur#problemes-hal)).

La résolution des affiliations se fait pendant la phase `affiliations` du pipeline.

<!--TODO: Compléter avec les autres sources-->

#### <span id='entites-auteurs'></span>Nature des entités auteurs

Certaines sources (OpenAlex, WOS, HAL) possèdent leurs propres référentiels de personnes avec leurs propres identifiants internes, parfois associés à d'autres identifiants (ORCID sur la plupart des sources; IdRef et idHAL sur HAL). Les sources liées au MESRE (ScanR, theses.fr) s'appuient sur le référentiel personnes de l'ESR (IdRef).

Vu l'hétérogénéité des sources, il a été décidé de ne pas maintenir de table `source_persons`. Les informations récupérées depuis les sources (forme de nom, identifiants éventuels) sont portées par `source_authorships` (`source_identifiers` JSONB, `raw_author_name` pour traçabilité, `author_name_normalized` pour matching par nom). La déduplication / création des personnes canoniques se fait dans la phase `persons` du pipeline, à partir de ces éléments.

| Source | Identifiant auteur | Entité stable ? | Identifiants récupérés si présents |
|---|---|---|---|
| HAL avec compte | `hal_person_id` | ✅ | `hal_person_id`, `idhal`, `orcid`, `idref` |
| HAL sans compte | `formId` | ❌ identifie la chaîne de caractères | (aucun) |
| ScanR avec idref | `idref` | ✅ | `idref`, `orcid` |
| ScanR sans idref | rien | ❌ | (aucun) |
| theses.fr avec PPN | `ppn` (= `idref`) | ✅ | `idref` |
| theses.fr sans PPN | rien | ❌ | (aucun) |
| OpenAlex | `openalex_id` | ⚠️ entité algorithmique non fiable | `orcid` (peu fiable) |
| WoS | `daisng_id` | ⚠️ entité algorithmique non fiable | `orcid` (peu fiable), `researcher_id` |
| CrossRef | rien | ❌ | `orcid` (fiable, article-level) |

Deux principaux cas de figure:

- Dans **OpenAlex** et **WoS**, chaque auteur de chaque publication est identifié par une clé interne dans le référentiel personnes de la base. Ces entités auteurs sont algorithmiques et peu fiables (même personne fréquemment divisée en entités multiples, ou personnes distinctes confondues). La présence d'un identifiant ORCID sur ces sources ne prouve pas sa présence dans la publication: le rattachement peut provenir d'un matching par nom effectué par OpenAlex/WOS. Signal peu fiable.
- Les autres sources (**HAL**, **ScanR**, **theses.fr**, **Crossref**) sont plus conservatrices: pas de tentative d'identification systématique des auteurs. Une même publication peut avoir des auteurs avec ou sans identifiants (= simple chaîne de caractères).
    - **Crossref**: l'identifiant est toujours ORCID. Présent seulement lorsque l'auteur l'a fourni à l'éditeur: présent sur une faible minorité d'authorships, mais signal excellent (un ORCID présent sur Crossref vient forcément de l'auteur via l'éditeur).
    - **HAL**: l'identifiant est un `personId` interne à HAL, qui identifie un compte HAL. Y sont parfois joints d'autres identifiants (`idHAL`, `IdRef`, `ORCID`) lorsque l'auteur les a ajoutés à son profil HAL. Signal excellent à condition que le document soit rattaché au bon compte HAL (erreurs d'homonymie possibles sur les publis multi-auteurs avec identification automatisée des auteurs).
    - **ScanR**, **theses.fr**: lorsque présent, l'identifiant est toujours IdRef (référentiel personnes de l'ESR). Source du lien IdRef-publi: pas clair (algos ABES? Déclaratif pour les personnes liées aux thèses? (remplissage inégal) Moissonné depuis autres sources par ScanR?) A élucider. Globalement fiable.


### HAL

#### API utilisées

**Search API** (`https://api.archives-ouvertes.fr/search`) — moissonnage des publications.
- Requête par collection labo (27 collections UCA) + portail global `clermont-univ`
- Champs Solr récupérés : voir [infrastructure/hal.py](../infrastructure/hal.py) (`HAL_FIELDS`)
- Pagination par offset, 500 résultats/page, 0.5s de délai entre requêtes
- Les identifiants ORCID/IdRef des auteurs sont extraits depuis le TEI `label_xml` retourné par la search API ; aucun appel séparé à `ref/author` n'est nécessaire.

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
- L'API bulk tronque les authorships à 100 auteurs ; [infrastructure/sources/openalex/refetch_truncated.py](../infrastructure/sources/openalex/refetch_truncated.py) re-télécharge individuellement les works concernés

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

### ScanR

#### API utilisée

**Elasticsearch DataESR** (`https://cluster-production.elasticsearch.dataesr.ovh/scanr-publications/_search`) — moissonnage des publications du périmètre français de la recherche.

- Authentification HTTP Basic (`scanr_username` / `scanr_password` en config)
- Requête `bool` combinant un filtre `year` et un `should` sur `affiliations.id.keyword` (SIREN des structures déclarées dans le périmètre)
- Pagination par `search_after` sur `id.keyword`, taille `SCANR_PER_PAGE`, délai `SCANR_DELAY` entre requêtes
- Affiliation IDs dérivés du périmètre d'extraction (`structures.api_ids->'scanr'`)

#### Données récupérées

- **Publications** : id ScanR, title (dict multilingue `default`/`en`/`fr` ou string), year, type, isOa + oaEvidence, summary (multilingue), keywords (multilingue, liste ou CSV), topics/domains, cited_by_counts_by_year, URLs (landingPage, doiUrl, pdfUrl), externalIds (doi, hal, nnt, pmid)
- **Source** (journal/éditeur) : `source.title`, `source.issn`, `source.eissn`, `source.publisher`
- **Auteurs** : `fullName`, `role`, `affiliations`, `denormalized.orcid`, `denormalized.idref`
- **Affiliations auteur** : arbre de structures (tutelle → laboratoire), filtré par `select_leaf_affiliations` pour ne garder que les feuilles

#### Particularités

- L'`id` ScanR contient le NNT pour les thèses (pattern `nnt:<ppn>`) — extrait via `extract_nnt_from_scanr_id`, ce qui permet la reconciliation avec theses.fr
- Champs multilingues : la priorité est `default` > `en` > `fr` (même règle pour title / summary / keywords)
- `oa_status` dérivé via `derive_scanr_oa_status(isOa, oaEvidence)` plutôt que pris brut
- L'idref éventuel (ou l'ORCID seul) est porté par `source_authorships.person_identifiers` (JSONB)
- Adresses : les feuilles d'affiliation portent un `name` libre — passées à l'`AddressLinker` comme pour OpenAlex/WoS

### CrossRef

CrossRef n'est pas une source de périmètre : aucune requête par institution / année. La table `staging` n'est alimentée que pour les DOI absents (DOI-driven), via le mécanisme `fetch_missing_doi`. CrossRef est consultée en aval pour fiabiliser les métadonnées éditeur (journal, ISSN, license) et récupérer les ORCID article-level qui manquent ailleurs.

#### API utilisée

**Works API** (`https://api.crossref.org/works/{doi}`) — interrogation unitaire par DOI.

- Polite pool obtenu via `User-Agent: BibliometrieUCA-pipeline/1.0 (mailto:<email>)` (email lu via `get_crossref_email`, fallback `get_openalex_email`)
- Limites observées par CrossRef pour le polite pool : 10 req/s + 3 concurrentes. L'adapter colle exactement à ces limites (`max_concurrent=3`, `request_delay_s=0.1`)
- Les 404 sont matérialisés dans `staging` avec `not_found=TRUE` + `processed=TRUE` pour ne pas être réinterrogés à chaque run

#### Données récupérées

- **Publications** : DOI, title (liste, on prend le premier non-vide), container-title, ISSN/eISSN, publisher, type, abstract (en JATS XML inline — nettoyé via `strip_jats_tags`), subject (utilisé comme keywords), license, relation
- **Auteurs** : `given` + `family`, `ORCID` (URL), `affiliation` (texte libre, généralement tutelle)

#### Particularités

- Pas d'identité d'auteur stable côté API — l'ORCID éventuel va dans `source_authorships.person_identifiers` (JSONB)
- Affiliations CrossRef purement textuelles et génériques (tutelles, pas de structures détaillées) → stockées dans `source_authorships.source_data` pour traçabilité, **pas** d'insertion dans `addresses` / `source_authorship_addresses`
- `doc_type` stocké comme `NULL` à la normalisation ; le mapping taxonomie CrossRef → enum canonique est appliqué plus tard via `_SOURCE_MAPS`
- `oa_status` non dérivé de CrossRef (pas fiable) ; laissé à NULL — les autres sources arbitrent via `refresh_from_sources`
- Année de publication : extraite via `extract_crossref_pub_year` qui choisit entre `issued`, `published-print`, `published-online`, `created` avec un plafond `current_year + 1`

### Theses.fr — à documenter

Section à compléter, sur le même modèle (API utilisées, données récupérées, particularités).
Extracteur dans [infrastructure/sources/theses/](../infrastructure/sources/theses/),
normaliseur dans [application/pipeline/normalize/normalize_theses.py](../application/pipeline/normalize/normalize_theses.py).
Particularité connue : couvre thèses soutenues + en cours ; jurys et
rapporteurs matérialisés comme `source_authorships` (avec leurs `roles`)
— PPN éventuel porté par `person_identifiers->>'idref'`.

## APIs d'enrichissement

### Unpaywall

Script : [interfaces/cli/pipeline/enrich_oa_status.py](../interfaces/cli/pipeline/enrich_oa_status.py) (orchestration dans [application/pipeline/enrich/enrich_oa_status.py](../application/pipeline/enrich/enrich_oa_status.py)).

Interroge l'API Unpaywall (`https://api.unpaywall.org/v2/{doi}`) pour chaque publication avec DOI. Met à jour `publications.oa_status`.

Règle métier : ne remplace jamais un statut `diamond` par `gold` (Unpaywall ne distingue pas le diamond OA du gold).

### OpenAlex Sources (APC)

Script : [interfaces/cli/pipeline/enrich_journal_apc.py](../interfaces/cli/pipeline/enrich_journal_apc.py) (orchestration dans [application/pipeline/enrich/enrich_journal_apc.py](../application/pipeline/enrich/enrich_journal_apc.py)).

Interroge l'API OpenAlex Sources pour les journaux avec `openalex_id`. Récupère les prix APC catalogue (DOAJ). Met à jour `journals.apc_amount`, `apc_currency`, `is_in_doaj`.

Note : ces données ne sont pas encore exploitées en aval dans l'application.


## Imports manuels

### <span id="donnees-rh"></span>Base RH (personnel UCA)

Fichier CSV importé via [interfaces/cli/imports/import_persons.py](../interfaces/cli/imports/import_persons.py) → table `persons_rh`.
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
