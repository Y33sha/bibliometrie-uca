# Enrichissement des référentiels publishers et journals

*À jour le 2026-09-06.*

La phase `publishers_journals` complète deux référentiels que la phase [normalize](03-normalize.md) alimente au fil des documents : elle rattache chaque préfixe DOI à son éditeur, et va chercher auprès de sources externes le type des revues et leurs frais de publication. Le `journal_type` qu'elle pose nourrit la correction `journal_type → doc_type` de la phase [metadata_correction](06-metadata-correction.md), d'où sa place dans le pipeline.

1. **`resolve_publishers`** — interroge `/prefixes/{prefix}` chez Crossref ou DataCite pour connaître le détenteur d'un préfixe DOI, puis rattache le `publisher_id` correspondant à ce préfixe. Le routage vers l'une ou l'autre API suit la Registration Agency posée par la phase [resolve_ra](02-extract.md#agences-denregistrement-doi) ; un préfixe de Registration Agency `unknown` est présenté aux deux, et celle qui répond corrige la Registration Agency. Crossref rend l'éditeur ; DataCite rend le provider, avec l'entrepôt (Zenodo, NAKALA…) qui a déposé les DOI. Sont repris les préfixes sans éditeur et jamais interrogés (`publisher_id` et `publisher_checked_at` nuls) : chaque préfixe est marqué interrogé, succès ou échec, pour qu'un préfixe non trouvé ne soit pas retenté.

2. **`enrich_journals_from_openalex`** — lit les [sources OpenAlex](../sources/03-openalex.md) pour renseigner le type de revue, le montant et la devise des frais de publication (APC). Sont reprises les revues qui portent un `openalex_id` et dont le type est inconnu (`journal_type = 'unknown'`).

3. **`enrich_journals_from_doaj`** — télécharge l'export CSV du [DOAJ](../sources/09-sources-supplementaires.md#doaj), puis met à jour toutes les revues en une passe, par appariement sur l'ISSN : la fiche DOAJ (`doaj_payload`) et le drapeau `is_in_doaj`. Le drapeau `is_in_doaj` est remis à `false` partout, puis à `true` pour les seules revues présentes dans l'export. L'étape se déclenche seulement si le dernier import date de plus de 30 jours.

## Import manuel d'un export DOAJ

`interfaces/cli/imports/import_doaj_csv.py` rejoue le même import à partir d'un CSV fourni, par exemple pour amorcer la base depuis un export récupéré à part.
