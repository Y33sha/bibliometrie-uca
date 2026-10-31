# Référentiels de l'édition

*À jour le 2026-10-31.*

La phase `publishing` complète les [référentiels de l'édition](../donnees/07-publishing.md) alimentés par la phase [normalize](03-normalize.md). Elle rattache chaque préfixe DOI à son éditeur. Elle vérifie les ISSN dans le Sudoc et rattache chaque enregistrement source à sa publication en série. Elle cherche le type des publications en série auprès de sources externes. Elle fusionne les monographies en double et les rattache à leur collection. La phase [finalize](10-finalize.md) supprime les entrées vides. La phase [metadata_correction](06-metadata-correction.md), qui suit, corrige le type de document des publications d'après le `serial_type`.

## Agences d'enregistrement DOI (`resolve_ra`)

Phase à part, juste avant `publishing`. Elle interroge doi.org sur les préfixes de tous les DOI connus (enregistrements sources, DOI liés, cibles des relations, DOI arXiv) et enregistre leur agence d'enregistrement dans `doi_prefixes` : Crossref, DataCite ou inconnue. La recherche des documents manquants ([fetch_missing](02-harvest.md#documents-absents-dune-source-fetch_missing)) adresse ensuite chaque DOI à l'API de son agence.

## Éditeurs

- **`resolve_crossref_publishers`** — rattache chaque préfixe Crossref à son éditeur (membre Crossref), par l'API `/prefixes` de Crossref.
- **`resolve_datacite_publishers`** — rattache chaque préfixe DataCite à l'organisation qui dépose et à l'entrepôt (Zenodo, NAKALA…), par l'API `/prefixes` de DataCite.
- **`merge_duplicate_publishers`** — fusionne dans le titulaire d'un préfixe les autres noms du même éditeur, d'après les DOI de leurs enregistrements sources et la compatibilité des noms (`domain/publishers/aliases.py`).

## Publications en série

- **`sync_issns`** — donne une ligne de `serial_issns` à chaque ISSN valide d'une série décrite par un enregistrement source (`biblio.journal`).
- **`check_issns_in_sudoc`** — lit la notice Sudoc de chaque ISSN jamais vérifié ([Sudoc](../sources/09-sources-supplementaires.md#sudoc)) : ISSN-L, support, statut, titre, liens vers le titre précédent, le titre suivant ou le supplément (`domain/serials/issn_facts.py`). Le nombre d'ISSN vérifiés par run est plafonné (`sudoc_max_per_run`).
- **`attach_serials`** — rattache chaque enregistrement source à sa publication en série (`domain/serials/attachment.py`). Une publication en série correspond à un ISSN-L : celui du Sudoc, à défaut celui d'OpenAlex, à défaut l'ISSN lui-même. Sans ISSN, l'enregistrement source rejoint la publication en série de son identifiant OpenAlex, à défaut celle de son titre. Une publication en série vidée est absorbée par celle qui reçoit ses enregistrements sources. Le titre d'une publication en série est celui de la notice Sudoc de son ISSN-L, sauf titre saisi à la main.
- **`enrich_serials_from_openalex`** — renseigne d'après [OpenAlex](../sources/03-openalex.md) le type des revues de type inconnu.
- **`type_proceedings_serials`** — type en recueil d'actes les revues composées surtout d'articles de congrès, et les revues sans ISSN au titre nommant une édition datée ou des actes (« proceedings »).
- **`type_journal_serials`** — type en revue les entrées de type inconnu composées en majorité d'articles.
- **`learn_serial_doi_namespaces`** — calcule les espaces de noms DOI qui désignent une revue (`10.1016/j.physletb.`), d'après les DOI de ses enregistrements sources (`domain/serials/doi_namespaces.py`).
- **`enrich_serials_from_doaj`** — importe l'export CSV du [DOAJ](../sources/09-sources-supplementaires.md#doaj) : fiche DOAJ et présence dans le DOAJ de chaque revue, appariée par ISSN. Une entrée de type inconnu présente dans le DOAJ devient une revue.

## Monographies

- **`merge_duplicate_monographs`** — fusionne les monographies de même titre créées sans éditeur ou sans ISBN (`domain/monographs/matching.py`).
- **`link_monographs_to_collections`** — rattache chaque monographie à sa collection, ou à une série formée des volumes de même titre chez le même éditeur (`domain/serials/series.py`, `domain/monographs/collection.py`).
- **`type_proceedings_volumes`** — distingue les volumes d'actes des livres (`domain/monographs/proceedings.py`).

## Import manuel d'un export DOAJ

`interfaces/cli/imports/import_doaj_csv.py` rejoue le même import à partir d'un CSV fourni, par exemple pour amorcer la base depuis un export récupéré à part.
