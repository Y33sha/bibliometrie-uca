# Publications — cycle de vie

*À jour le 2026-10-21.*

Une publication est la référence unifiée d'un document : plusieurs enregistrements sources décrivant le même article ne donnent qu'une publication. Elle est **entièrement dérivée, jamais saisie** — la phase `publications` regroupe les enregistrements sources, et `refresh_from_sources` recalcule l'état consolidé depuis leur union.

`domain/publications/` contient les règles pures : les types d'identifiants qui valident et normalisent DOI, identifiant HAL, numéro national de thèse, PMID, PMCID et identifiant arXiv ; la nomenclature des types de document ; l'agrégation des métadonnées entre sources ; les règles de regroupement ; et le choix du statut *open access*.

## Tables

| Table | Rôle | Colonnes notables |
|---|---|---|
| `publications` | La référence unifiée | `doi` (unique sur sa forme minuscule), `doc_type`, `oa_status`, `publication_year`, `journal_id`, `publisher_id`, `doi_prefix` (préfixe du DOI, colonne générée), `sources` (sources contributrices), `in_perimeter`, `subjects_ingested_at`, `source_extras`, `corrections` |
| `contributions` | Lien personne ↔ publication | `publication_id`, `person_id`, `author_position`, `roles`, `is_corresponding`, `in_perimeter` |
| `publication_relations` | Lien orienté entre deux publications | `from_publication_id`, `relation_type`, `target_publication_id` **ou** `target_doi`, `source` |
| `apc_payments` | Frais de publication, importés puis corrigés à la main | `publication_id`, `doi`, `amount_eur_ht`, `billing_year` |
| `publications_detail` | Complément de métadonnées servi au détail | `publication_id`, recalculé à chaque `refresh_from_sources` |

En amont se trouvent les [enregistrements sources](source_records.md). La construction des `contributions` relève de la fiche [contributions](contributions.md) ; ils apparaissent ici comme le lien vers les [personnes](persons.md).

## Écriture par le pipeline

La phase `publications` constitue les publications ; les phases `relations`, `oa_status`, `countries` et `contributions` enrichissent ensuite certaines colonnes.

**Regroupement (`pipeline/transformation/publications/`).** `reconcile_components` charge les enregistrements sources marqués à reprendre et leurs voisins immédiats, puis calcule un plan avant d'écrire quoi que ce soit. Le plan regroupe par composante et par DOI, sous une règle absolue : deux DOI distincts ne se rejoignent jamais. Un enregistrement sans DOI peut en revanche rejoindre un groupe qui en a un. L'application du plan repointe les enregistrements, crée les publications manquantes, réunit celles qui doivent l'être — les dépendants sont repointés vers la publication conservée, puis la publication vidée est supprimée — et sépare celles qui ont été rapprochées à tort. Chaque publication conservée est ensuite rafraîchie.

**Recalcul de l'état consolidé (`refresh_from_sources`).** L'état est recalculé en entier, jamais complété au coup par coup : première valeur non nulle selon le classement des sources, statut d'accès le plus ouvert, réunion dédoublonnée des listes, arbitrage entre sous-types d'article. La règle de type de document dépendant de la revue est rejouée. L'éditeur est celui de la date de publication : le titulaire du préfixe du DOI Crossref, à défaut le premier éditeur des enregistrements sources selon le classement des sources. Une production hébergée sans être publiée (preprint, jeu de données, rapport, thèse…) n'a pas d'éditeur (`domain/publishers/attribution.py`). L'ensemble est ensuite enregistré avec la liste des sources contributrices et le complément de détail.

**Suppression (`pipeline/transformation/publications/lifecycle.py`).** Une publication existe si elle a au moins un enregistrement source, un type de document admissible et au moins une contribution. Après un recalcul, le module du cycle de vie supprime une publication sans enregistrement source ou de type non admissible ; ses enregistrements sources s'en détachent. La phase `finalize` supprime les publications sans contribution. Une publication réunie à une autre est dissoute : ses paiements APC passent à la publication conservée, son identifiant redirige vers elle, puis elle est supprimée.

**Relations (`pipeline/transformation/publications/relations.py`).** La table est reconstruite à chaque passage, à partir de trois signaux :

- les relations déclarées par DataCite et Crossref ;
- les clés de confirmation partagées entre deux DOI distincts, dont le type se déduit du couple de types de document ;
- la proximité des titres, qui relie un erratum à son article ou une prépublication à sa version publiée.

Les liens vont du dépendant vers le parent, et les liens inverses sont dédoublonnés. Le type imprécis `is_related_to` marque une paire à clé partagée que le couple de types de document ne permet pas de qualifier ; une relation précise déjà déclarée le remplace.

**Statut *open access* (`pipeline/transformation/publications/oa_status.py`).** Unpaywall est interrogé pour les publications à DOI jamais vérifiées ou dont la vérification a vieilli, et fait autorité — à une exception près : une archive ouverte détenant le fichier rouvre une publication annoncée fermée ou indéterminée.

**Pays et périmètre.** La phase `countries` propage les pays des adresses jusqu'à la publication ; la phase `finalize` y reporte l'appartenance au périmètre.

## Écriture par l'API

L'API n'écrit rien sur les publications. Une valeur consolidée fausse se corrige en amont, par une règle de `metadata_correction` sur l'enregistrement source. Les frais de publication arrivent par un import en ligne de commande (`interfaces/cli/imports/import_apc.py`) et l'API ne fait que les lire.

## Lecture par le pipeline

- La phase `finalize` lit les contributions pour reporter le périmètre sur les publications, et supprime les publications sans contribution rattachée.
- La phase `subjects` verse les thématiques des enregistrements sources vers les sujets, en ne reprenant que les publications dont le contenu a changé.
- La phase `countries` lit la propagation venue des adresses.

## Lecture par l'API

| Usage | Ce qui est servi |
|---|---|
| Détail (`GET /api/publications/{id}`) | Métadonnées consolidées jointes à la revue et à l'éditeur, provenance par source, auteurs consolidés et auteurs tels que chaque source les donne, relations entrantes et sortantes, sujets, identifiants externes |
| Enregistrements sources (`GET /api/publications/{id}/sources`) | Métadonnées de chaque enregistrement source : identifiants, titre, type, année, langue, statut d'accès, revue avec ses ISSN, éditeur, conteneur, volume, numéro, pages. La revue et l'éditeur y figurent deux fois : l'entrée du référentiel et le nom donné par la source |
| Listes, facettes, export | Liste paginée et export CSV, avec une douzaine de facettes dont le laboratoire, le statut de dépôt HAL et les frais de publication |
| Statistiques et tableaux croisés | Ventilations par année, statut d'accès, type de document, laboratoire, éditeur et revue ; collaborations d'après les pays |
