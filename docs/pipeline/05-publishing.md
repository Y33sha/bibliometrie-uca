# Référentiels de l'édition

*À jour le 2026-11-01.*

La phase `publishing` complète les [référentiels de l'édition](../donnees/07-publishing.md) alimentés par la phase [normalize](03-normalize.md). Elle rattache chaque préfixe DOI à son éditeur. Elle vérifie les ISSN dans le Sudoc et rattache chaque enregistrement source à sa publication en série. Elle cherche le type et les listes de revues des publications en série auprès de sources externes. Elle fusionne les monographies en double et les rattache à leur collection. La phase [finalize](10-finalize.md) supprime les entrées vides. La phase [metadata_correction](06-metadata-correction.md), qui suit, corrige le type de document des publications d'après le `serial_type`.

## Agences d'enregistrement DOI (`resolve_ra`)

Phase à part, juste avant `publishing`. Elle interroge doi.org sur les préfixes de tous les DOI connus (enregistrements sources, DOI liés, cibles des relations) et enregistre leur agence d'enregistrement dans `doi_prefixes` : Crossref, DataCite ou inconnue. La recherche des documents manquants ([fetch_missing](02-harvest.md#documents-absents-dune-source-fetch_missing)) adresse ensuite chaque DOI à l'API de son agence.

## Éditeurs

- **`resolve_crossref_publishers`** — rattache chaque préfixe Crossref à son éditeur (membre Crossref), par l'API `/prefixes` de Crossref.
- **`resolve_datacite_publishers`** — rattache chaque préfixe DataCite à l'organisation qui dépose et à l'entrepôt (Zenodo, NAKALA…), par l'API `/prefixes` de DataCite.
- **`merge_duplicate_publishers`** — fusionne dans le titulaire d'un préfixe les autres noms du même éditeur, d'après les DOI de leurs enregistrements sources et la compatibilité des noms. Fusionne ensuite les éditeurs de même nom aux mots génériques près : « Brepols Publ » et « Brepols Publishers » (`domain/publishers/aliases.py`).

## Publications en série

- **`sync_issns`** — donne une ligne de `serial_issns` à chaque ISSN valide d'une série décrite par un enregistrement source (`biblio.journal`).
- **`check_issns_in_sudoc`** — lit la notice Sudoc de chaque ISSN jamais vérifié ([Sudoc](../sources/09-sources-supplementaires.md#sudoc)) : support, statut, titre, liens vers le titre précédent, le titre suivant, le supplément ou l'ISSN qui l'annule (`domain/serials/issn_facts.py`). Le nombre d'ISSN vérifiés par run est plafonné (`sudoc_max_per_run`).
- **`import_issnl_table`** — importe la table ISSN-L de l'[ISSN International Centre](../sources/09-sources-supplementaires.md#issn-international-centre) : l'ISSN-L de chaque ISSN de `serial_issns`, quand le dernier import date de plus de `issnl_table_refresh_after_days` jours.
- **`attach_serials`** — rattache chaque enregistrement source à sa publication en série (`domain/serials/attachment.py`). Une publication en série correspond à un ISSN-L : celui de la table de l'ISSN International Centre, à défaut celui de l'ISSN qui l'annule, à défaut celui d'OpenAlex, à défaut l'ISSN lui-même. Sans ISSN, l'enregistrement source rejoint la publication en série de son identifiant OpenAlex, à défaut celle de son titre. Une publication en série vidée est absorbée par celle qui reçoit ses enregistrements sources. Le titre d'une publication en série est celui de la notice Sudoc de son ISSN-L, sauf titre saisi à la main.
- **`check_serials_in_openalex`** — lit dans [OpenAlex](../sources/03-openalex.md) chaque revue jamais lue, ou lue depuis plus de `serial_openalex_recheck_after_days` jours. Une revue à ISSN prend la source OpenAlex de ses ISSN. Une revue sans ISSN prend la source la plus fréquente parmi ses enregistrements sources OpenAlex sans ISSN. La lecture pose l'identifiant OpenAlex de la revue, son type s'il est inconnu, et ses appartenances aux [listes de revues](../donnees/07-publishing.md#publications-en-série). Une source retenue par plusieurs revues donne son identifiant à celle qui a le plus de publications.
- **`type_proceedings_serials`** — type en recueil d'actes les revues composées surtout d'articles de congrès, et les revues sans ISSN au titre nommant une édition datée ou des actes (« proceedings »).
- **`type_journal_serials`** — type en revue les entrées de type inconnu composées en majorité d'articles.
- **`learn_serial_doi_namespaces`** — calcule les espaces de noms DOI qui désignent une revue (`10.1016/j.physletb.`), d'après les DOI de ses enregistrements sources (`domain/serials/doi_namespaces.py`).
- **`enrich_serials_from_doaj`** — importe l'export CSV du [DOAJ](../sources/09-sources-supplementaires.md#doaj) : fiche DOAJ de chaque revue, rattachée par ISSN. Une entrée de type inconnu présente dans le DOAJ devient une revue. Une revue du Diamond Discovery Hub, ou du DOAJ sans APC ni autres frais, est classée diamant.

## Monographies

- **`merge_duplicate_monographs`** — fusionne les monographies de même titre créées sans éditeur ou sans ISBN (`domain/monographs/matching.py`).
- **`link_monographs_to_collections`** — rattache chaque monographie à sa collection, ou à une série formée des volumes de même titre chez le même éditeur (`domain/serials/series.py`, `domain/monographs/collection.py`).
- **`type_proceedings_volumes`** — distingue les volumes d'actes des livres (`domain/monographs/proceedings.py`).

## Import manuel d'un export DOAJ

`interfaces/cli/imports/import_doaj_csv.py` rejoue le même import à partir d'un CSV fourni, par exemple pour amorcer la base depuis un export récupéré à part.
