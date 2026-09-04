# Publications — cycle de vie

*À jour le 2026-09-04.*

Une publication est la référence unifiée d'un document : plusieurs enregistrements sources décrivant le même article ne donnent qu'une publication. Elle est **entièrement dérivée, jamais saisie** — la phase `publications` regroupe les enregistrements sources, et `refresh_from_sources` recalcule l'état canonique depuis leur union. La curation se limite à réunir deux publications ou à déclarer qu'elles sont distinctes.

`domain/publications/` porte les règles pures : les types d'identifiants qui valident et normalisent DOI, identifiant HAL, numéro national de thèse, PMID, PMCID et identifiant arXiv ; la nomenclature des types de document ; l'agrégation des métadonnées entre sources ; les règles de regroupement ; et le choix du statut d'accès ouvert.

## Tables

| Table | Rôle | Colonnes notables |
|---|---|---|
| `publications` | La référence unifiée | `doi` (unique sur sa forme minuscule), `doc_type`, `oa_status`, `pub_year`, `journal_id`, `sources` (sources contributrices), `in_perimeter`, `unpaywall_checked_at`, `meta` |
| `authorships` | Lien personne ↔ publication | `publication_id`, `person_id`, `author_position`, `roles`, `is_corresponding`, `in_perimeter` |
| `publication_relations` | Lien orienté entre deux publications | `from_publication_id`, `relation_type`, `target_publication_id` **ou** `target_doi`, `source` |
| `distinct_publications` | Paires déclarées comme deux documents différents | `(pub_id_a, pub_id_b)`, avec `a < b` |
| `apc_payments` | Frais de publication, importés et curés | `publication_id`, `doi`, `amount_eur_ht`, `billing_year` |
| `publications_detail` | Complément de métadonnées servi au détail | `publication_id`, recalculé à chaque `refresh_from_sources` |

En amont se trouvent les [enregistrements sources](source_publications.md). La construction des `authorships` relève de la fiche [authorships](authorships.md) ; ils apparaissent ici comme le lien vers les [personnes](persons.md).

## Écriture par le pipeline

La phase `publications` constitue les publications ; les phases `relations`, `oa_status`, `countries` et `authorships` enrichissent ensuite certaines colonnes.

**Regroupement (`application/pipeline/publications/`).** `reconcile_components` charge les enregistrements sources marqués à retraiter et leurs voisins immédiats, puis calcule un plan avant d'écrire quoi que ce soit. Le plan regroupe par composante et par DOI, sous une règle absolue : deux DOI distincts ne se rejoignent jamais. Un enregistrement sans DOI peut en revanche rejoindre un groupe qui en porte un. L'application du plan repointe les enregistrements, crée les publications manquantes, réunit celles qui doivent l'être — les dépendants sont repointés vers la publication conservée, puis la publication vidée est supprimée — et sépare celles qui ont été rapprochées à tort. Chaque publication conservée est ensuite rafraîchie.

**Recalcul de l'état canonique (`refresh_from_sources`).** L'état est recalculé en entier, jamais complété au coup par coup : première valeur non nulle selon le classement des sources, statut d'accès le plus ouvert, réunion dédoublonnée des listes, arbitrage entre sous-types d'article. La règle de type de document dépendant de la revue est rejouée, puis l'ensemble est enregistré avec la liste des sources contributrices et le complément de détail. Une publication qu'aucune source n'atteste plus, ou dont le type de document est exclu, est supprimée ; ses enregistrements sources s'en détachent.

**Relations (`application/pipeline/relations/`).** La table est reconstruite à chaque passage, signal par signal, à partir de trois éléments : les relations déclarées par DataCite et Crossref, les clés de confirmation partagées entre deux DOI distincts — le type se déduisant alors du couple de types de document —, et le rapprochement par titre, qui relie un erratum à son article ou une prépublication à sa version publiée. Les liens vont du dépendant vers le parent ; les liens inverses sont dédoublonnés, et un type imprécis cède la place à une relation précise déjà déclarée.

**Statut d'accès ouvert (`application/pipeline/oa_status/`).** Unpaywall est interrogé pour les publications à DOI jamais vérifiées ou dont la vérification a vieilli, et fait autorité — à une exception près : une archive ouverte détenant le fichier rouvre une publication annoncée fermée ou indéterminée.

**Pays et périmètre.** La phase `countries` propage les pays des adresses jusqu'à la publication ; la phase `authorships` y reporte l'appartenance au périmètre.

## Écriture par l'API — curation

Deux opérations seulement, dans `interfaces/api/routers/publications.py`. Une commande vaut une transaction.

**Réunir deux doublons** (`POST /api/publications/duplicates/merge`). L'opération est refusée si les deux portent des DOI différents. Les enregistrements sources sont repointés, les authorships dédoublonnés et repointés, les paires déclarées distinctes réordonnées, puis la publication absorbée est supprimée et la survivante rafraîchie. La cible est celle dont l'identifiant est le plus petit ; le sens de la fusion est sans conséquence, l'union des sources étant la même.

**Déclarer deux publications distinctes** (`POST /api/publications/duplicates/mark-distinct`) inscrit la paire, sans effet si elle y figure déjà.

**Aucune métadonnée canonique ne s'édite.** Une valeur fausse se corrige en amont, par une règle de `metadata_correction` sur l'enregistrement source, ou en réunissant ou séparant des doublons. Les frais de publication arrivent par un import en ligne de commande (`interfaces/cli/imports/import_apc.py`) et l'API ne fait que les lire.

## Lecture par le pipeline

- La phase `authorships` consolide les signatures en `authorships` et lit les publications pour y reporter le périmètre.
- La phase `subjects` verse les thématiques des enregistrements sources vers les sujets, en ne retraitant que les publications dont le contenu a changé.
- La phase `countries` lit la propagation venue des adresses.

## Lecture par l'API

| Usage | Ce qui est servi |
|---|---|
| Détail (`GET /api/publications/{id}`) | Métadonnées canoniques jointes à la revue et à l'éditeur, provenance par source, auteurs canoniques et auteurs tels que chaque source les donne, relations entrantes et sortantes, sujets, identifiants externes |
| Listes, facettes, export | Liste paginée et export CSV, avec une douzaine de facettes dont le laboratoire, le statut de dépôt HAL et les frais de publication |
| Statistiques et tableaux croisés | Ventilations par année, statut d'accès, type de document, laboratoire, éditeur et revue ; collaborations d'après les pays |
| Candidat au dédoublonnage (`GET /api/publications/duplicates/next`) | Paires proches par le titre, l'année et le DOI, hors paires déclarées distinctes — c'est cette lecture qui alimente la fusion manuelle |

## Points d'attention

**Rien ne permet de corriger une métadonnée sur la publication.** C'est délibéré : la publication est un dérivé de ses sources, et la réparation se fait en amont. Il n'existe donc pas de correction rapide côté administration.

**Les relations sont reconstruites en entier à chaque passage**, signal par signal, sans traitement incrémental. Le type imprécis `is_related_to` sert d'attente : il marque une paire à clé partagée dont le couple de types de document ne permet pas encore de conclure.

## Invariants métier

**Un DOI, une publication.** Trois garde-fous : le regroupement ne réunit jamais deux DOI distincts, un index unique sur le DOI en minuscules l'interdit en base, et la fusion manuelle la refuse. Une publication sans DOI peut en revanche rejoindre une publication qui en porte un.

**La publication est dérivée.** Hors fusion et déclaration de distinction, elle n'est jamais écrite à la main : `refresh_from_sources` recalcule tout depuis l'union de ses sources.

**Ce qui n'est plus attesté disparaît.** Une publication qu'aucune source n'atteste, ou dont le type de document est exclu, est supprimée ; ses enregistrements sources s'en détachent sans produire ni authorship ni personne.

**Unpaywall fait autorité sur l'accès ouvert.** Une fois la vérification faite, l'agrégation cesse de recalculer le statut depuis les sources, sauf lorsqu'une archive ouverte détient le fichier.

**Identité des authorships.** Le couple `(publication_id, person_id)` est unique, et une authorship n'existe pas sans sa publication.
