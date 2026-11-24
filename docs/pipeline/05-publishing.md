# Référentiel des DOI et référentiels de l'édition

*À jour le 2026-11-20.*

## Référentiel des DOI (`dois`)

La phase `dois` suit les référentiels ROR et HAL. Elle tient les faits obtenus sur chaque DOI connu, lus par le moissonnage, l'édition, la correction et la consolidation des publications. Les DOI connus sont les DOI actifs des enregistrements sources et les cibles des relations (vue `known_dois`), plus la forme sans version de chaque DOI à suffixe de version.

- **`resolve_prefixes`** — demande à doi.org l'agence d'enregistrement de chaque préfixe nouveau, et l'enregistre dans `doi_prefixes` : Crossref, DataCite ou inconnue. La recherche des documents manquants ([fetch_missing](02-harvest.md#documents-absents-dune-source-fetch_missing)) adresse ensuite chaque DOI à l'API de son agence.
- **`resolve_dois`** — demande à l'API des handles de doi.org l'existence et l'URL de résolution de chaque DOI connu (`dois.registered`, `dois.registered_url`). Un DOI inconnu de doi.org sort de la recherche des documents manquants, et la correction le retire des enregistrements sources.
Les publications d'un DOI dont la réponse change entrent dans la file de consolidation. doi.org reçoit seulement les DOI sans réponse, ou à réponse plus ancienne que `doi_resolution_recheck_after_days` (180 jours), dans la limite de `doi_resolution_max_per_run` (10 000) par exécution. Ces réglages se modifient dans `admin/config`. Quand le service est indisponible, le DOI est repris au run suivant.

## Référentiels de l'édition (`publishing`)

La phase `publishing` complète les [référentiels de l'édition](../donnees/07-publishing.md) alimentés par la phase [normalize](03-normalize.md). Elle rattache chaque enregistrement source à son éditeur, à sa publication en série et à sa monographie. La phase [finalize](10-finalize.md) nettoie ces référentiels après la résolution des entités. La phase [metadata_correction](06-metadata-correction.md), qui suit, corrige le type de document des publications d'après le `serial_type`.

### Préfixes DOI

- **`resolve_crossref_publishers`** — rattache chaque préfixe Crossref à son éditeur (membre Crossref), par l'API `/prefixes` de Crossref.
- **`resolve_datacite_publishers`** — rattache chaque préfixe DataCite à l'organisation qui dépose et à l'entrepôt (Zenodo, NAKALA…), par l'API `/prefixes` de DataCite.

Ces deux étapes corrigent aussi l'agence d'un préfixe inconnu de doi.org, trouvé chez Crossref ou DataCite.

### Éditeurs

- **`attach_publishers`** — rattache chaque enregistrement source à l'éditeur qu'il nomme, et crée les éditeurs nouveaux avec leurs formes de nom. Une production hébergée sans être publiée reste sans éditeur.
- **`merge_duplicate_publishers`** — fusionne dans le titulaire d'un préfixe les autres noms du même éditeur, d'après les DOI de leurs enregistrements sources et la compatibilité des noms. Fusionne ensuite les éditeurs de même nom aux mots génériques près : « Brepols Publ » et « Brepols Publishers » (`domain/publishers/aliases.py`).

### Publications en série

- **ISSN**
   - **`sync_issns`** — donne une ligne de `serial_issns` à chaque ISSN valide d'une série décrite par un enregistrement source (`biblio.journal`).
   - **`check_issns_in_sudoc`** — cherche la notice Sudoc de chaque ISSN jamais vérifié ([Sudoc](../sources/09-sources-supplementaires.md#sudoc)) : support, statut, titre, liens vers le titre précédent, le titre suivant, le supplément ou l'ISSN qui l'annule (`domain/serials/issn_facts.py`). Le nombre d'ISSN vérifiés par run est plafonné (`sudoc_max_per_run`).
   - **`import_issnl_table`** — importe la table ISSN-L de l'[ISSN International Centre](../sources/09-sources-supplementaires.md#issn-international-centre) : l'ISSN-L de chaque ISSN de `serial_issns`, quand le dernier import date de plus de `issnl_table_refresh_after_days` jours.
- **`attach_serials`** — rattache chaque enregistrement source à sa publication en série (`domain/serials/attachment.py`). Une publication en série correspond à un ISSN-L : celui de la table de l'ISSN International Centre, à défaut celui de l'ISSN qui l'annule, à défaut celui d'OpenAlex, à défaut l'ISSN lui-même. Sans ISSN, l'enregistrement source rejoint la publication en série de son identifiant OpenAlex, à défaut celle de son titre. Une publication en série vidée est absorbée par celle qui reçoit ses enregistrements sources. Le titre d'une publication en série est celui de la notice Sudoc de son ISSN-L, sauf titre saisi à la main.
- **Qualification**
   - **`check_serials_in_openalex`** — cherche dans [OpenAlex](../sources/03-openalex.md) les métadonnées de chaque revue jamais cherchée, ou cherchée depuis plus de `serial_openalex_recheck_after_days` jours. Une revue à ISSN prend la source OpenAlex de ses ISSN. Une revue sans ISSN prend la source la plus fréquente parmi ses enregistrements sources OpenAlex sans ISSN. La recherche pose l'identifiant OpenAlex de la revue, son type s'il est inconnu, son open access intégral avec l'année de son passage à l'open access intégral, et ses appartenances aux [listes de revues](../donnees/07-publishing.md#publications-en-série). Une source retenue par plusieurs revues donne son identifiant à celle qui a le plus de publications.
   - **`type_proceedings_serials`** — type en recueil d'actes les revues composées surtout d'articles de congrès, et les revues sans ISSN au titre nommant une édition datée ou des actes (« proceedings »).
   - **`type_journal_serials`** — type en revue les entrées de type inconnu composées en majorité d'articles.
   - **`enrich_serials_from_doaj`** — importe l'export CSV du [DOAJ](../sources/09-sources-supplementaires.md#doaj) : fiche DOAJ de chaque revue, rattachée par ISSN. Une entrée de type inconnu présente dans le DOAJ devient une revue.
   - **`model_serials`** — écrit le modèle open access de chaque revue, sauf modèle saisi à la main. Une revue du Diamond Discovery Hub, ou du DOAJ sans APC ni autres frais, est `diamond`. Une autre revue en open access intégral d'après OpenAlex est `full_oa`, une revue présente dans OpenAlex hors open access intégral `subscription`. Le modèle d'une revue absente d'OpenAlex est inconnu.
### Monographies

- **`attach_monographs`** — rattache chaque enregistrement source qui décrit un volume à sa monographie (`domain/monographs/attachment.py`). Plusieurs monographies d'un même volume fusionnent dans la plus ancienne. Un volume sans monographie en crée une.
- **`link_monographs_to_collections`** — rattache chaque monographie à sa collection, ou à une série formée des volumes de même titre chez le même éditeur (`domain/serials/series.py`, `domain/monographs/collection.py`).
- **`type_proceedings_volumes`** — distingue les volumes d'actes des livres (`domain/monographs/proceedings.py`).

### Espaces de noms DOI

- **`learn_serial_doi_namespaces`** — calcule les espaces de noms DOI qui désignent une revue (`10.1016/j.physletb.`), d'après les DOI de ses enregistrements sources (`domain/serials/doi_namespaces.py`). Une collection de livres est sans espace de noms : la suite du DOI désigne le livre.
- **`serial_by_doi`** — renseigne `serial_id` lorsqu'il est vide et que les DOI actifs de l'enregistrement source tombent dans l'espace de noms d'une seule revue. Les DOI de serveur de preprints restent hors du rattachement : la discussion d'un article Copernicus partage l'espace de noms de sa revue.

## Import manuel d'un export DOAJ

`interfaces/cli/imports/import_doaj_csv.py` rejoue le même import à partir d'un CSV fourni, par exemple pour amorcer la base depuis un export récupéré à part.
