# Vue d'ensemble

*Document à jour au 2026-05-11.*

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

## <span id='sources-affiliations'></span>Gestion des affiliations

> **Section pas à jour**: à réécrire

- Dans **OpenAlex** et **WoS**, les liens authorships-structures sont résolus de manière algorithmique à partir des adresses liées aux publications. Ce processus génère beaucoup d'erreurs causées par des similitudes de noms (dans OpenAlex principalement). Mais la donnée-source (*raw affiliation string*) est présente et exploitable. On ignore donc les structure_ids présents dans les sources et **on reconstruit l'affiliation à partir des adresses brutes**. (Phase `affiliations` du pipeline.)

- Dans **HAL**, les liens authorships-structures sont basés sur les affiliations renseignées dans les comptes HAL des auteurs au moment du dépôt (Cf [doc HAL](https://doc.hal.science/depot-fonctionnement-de-l-affiliation-automatique/#)), et éventuellement complétés manuellement par le déposant. Les métadonnées de HAL ne contiennent pas les adresses brutes. La seule option est donc de récupérer les affiliations telles quelles : les noms de structures associés aux authorships sont traités fictivement comme des adresses par l'algo de résolution d'affiliation. Les erreurs sont détectées *a posteriori* (pages [hal-problems](../guide-utilisateur#problemes-hal)).

La résolution des affiliations se fait pendant la phase `affiliations` du pipeline.

<!--TODO: Compléter avec les autres sources-->

## <span id='entites-auteurs'></span>Nature des entités auteurs

Certaines sources (OpenAlex, WOS, HAL) possèdent leurs propres référentiels de personnes avec leurs propres identifiants internes, parfois reliés à d'autres identifiants (ORCID sur la plupart des sources; IdRef et idHAL sur HAL). Les sources liées au MESRE (ScanR, theses.fr) s'appuient sur le référentiel personnes de l'ESR (IdRef).

Deux cas de figure:

- Dans **OpenAlex** et **WoS**, chaque auteur de chaque publication est identifié par une clé interne dans le référentiel personnes de la base. Ces entités auteurs sont algorithmiques et peu fiables (même personne fréquemment divisée en entités multiples, ou personnes distinctes confondues). La présence d'un identifiant ORCID sur ces sources ne prouve pas sa présence dans la publication: le rattachement peut provenir d'un matching par nom effectué par OpenAlex/WOS. Signal peu fiable.
- Les autres sources (**HAL**, **ScanR**, **theses.fr**, **Crossref**) sont plus conservatrices: pas de tentative d'identification systématique des auteurs. Une même publication peut avoir des auteurs avec ou sans identifiants (= simple chaîne de caractères).
    - **Crossref**: l'identifiant est toujours ORCID. Présent seulement lorsque l'auteur l'a fourni à l'éditeur: présent sur une faible minorité d'authorships, mais signal excellent (un ORCID présent sur Crossref vient forcément de l'auteur via l'éditeur).
    - **HAL**: l'identifiant est un `personId` interne à HAL, qui identifie un compte HAL. Y sont parfois joints d'autres identifiants (`idHAL`, `IdRef`, `ORCID`) lorsque l'auteur les a ajoutés à son profil HAL. Signal excellent à condition que le document soit rattaché au bon compte HAL (erreurs d'homonymie possibles sur les publis multi-auteurs avec identification automatisée des auteurs).
    - **ScanR**, **theses.fr**: lorsque présent, l'identifiant est toujours IdRef (référentiel personnes de l'ESR). Source du lien IdRef-publi: pas clair (algos ABES? Déclaratif pour les personnes liées aux thèses? (remplissage inégal) Moissonné depuis autres sources par ScanR?) A élucider. Globalement fiable.

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

Vu l'hétérogénéité des entités personnes selon les sources, il a été décidé de ne pas maintenir de table `source_persons`. Les informations récupérées depuis les sources (forme de nom, identifiants éventuels) sont portées par `source_authorships` (`raw_author_name` pour traçabilité, `author_name_normalized` pour matching par nom, `source_identifiers` JSONB pour les identifiants persistants associés (ORCID, IdRef, idHAL)). La déduplication / création des personnes canoniques se fait dans la phase `persons` du pipeline, à partir de ces éléments.
