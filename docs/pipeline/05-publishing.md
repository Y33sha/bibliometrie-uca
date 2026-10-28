# Référentiels de l'édition

*À jour le 2026-10-26.*

La phase `publishing` complète les [référentiels de l'édition](../donnees/07-publishing.md) que la phase [normalize](03-normalize.md) alimente. Elle rattache chaque préfixe DOI à son éditeur et vérifie les ISSN des publications en série. Elle cherche leur type auprès de sources externes. Elle fusionne les doublons et rattache les monographies à leur collection. La phase [finalize](10-finalize.md) supprime les entrées vides. La phase [metadata_correction](06-metadata-correction.md), qui suit, corrige le type de document des publications d'après le `serial_type`.

## Agences d'enregistrement DOI (`resolve_ra`)

Phase à part, juste avant `publishing`. Résout l'agence d'enregistrement (Crossref ou DataCite, colonne `ra`) des préfixes de tous les DOI connus : DOI des enregistrements sources, DOI liés, cibles des relations, DOI arXiv. Le nombre de préfixes reste petit : aucun filtre de périmètre. Elle suit la normalisation, donc les DOI moissonnés dans le run sont résolus dans le run.

Interroge `doi.org/ra` sur les préfixes absents de la table `doi_prefixes`, par lots de 100 préfixes, et enregistre leur agence. Un préfixe que doi.org ne connaît pas reçoit l'agence `unknown`. Un préfixe d'une requête en échec reste à résoudre.

Une ligne `doi_prefixes` naît ici avec la seule agence d'enregistrement ; les sous-étapes des [éditeurs](#éditeurs) la complètent ensuite (nom et `publisher_id` via les API `/prefixes`). La recherche des documents manquants ([fetch_missing](02-harvest.md#documents-absents-dune-source-fetch_missing)), au run suivant, adresse chaque DOI à l'API de son agence.

## Éditeurs

Deux sous-étapes, une par agence d'enregistrement, interrogent `/prefixes/{prefix}` pour connaître le détenteur d'un préfixe DOI, puis rattachent le `publisher_id` correspondant. L'agence posée par la phase [resolve_ra](#agences-denregistrement-doi-resolve_ra) choisit les préfixes. Une API qui trouve un préfixe d'agence `unknown` corrige son agence. Une API qui a répondu marque le préfixe vu (`crossref_checked_at`, `datacite_checked_at`), qu'elle le connaisse ou non, et il n'est pas retenté. Un préfixe dont l'API est indisponible est repris au run suivant.

1. **`resolve_crossref_publishers`** — interroge Crossref, qui rend l'éditeur. Sont repris les préfixes d'agence Crossref ou `unknown` que Crossref n'a pas vus.

2. **`resolve_datacite_publishers`** — interroge DataCite, qui rend le provider, avec l'entrepôt (Zenodo, NAKALA…) qui a déposé les DOI. Sont repris les préfixes d'agence DataCite que DataCite n'a pas vus, et les préfixes d'agence `unknown` que Crossref n'a pas trouvés.

3. **`merge_duplicate_publishers`** — fusionne dans le titulaire de préfixe un autre nom du même éditeur. Un éditeur que nomment les sources, sans préfixe DOI, rejoint le titulaire Crossref quand deux signaux concordent. D'abord, au moins 5 de ses enregistrements sources ont un DOI Crossref, dont 90 % chez ce titulaire ; les préfixes des plateformes d'éditeurs ne comptent pas. Ensuite, les noms sont compatibles : l'un abrège l'autre, l'emboîte ou en est l'acronyme, aux mots génériques et formes juridiques près (« Amer Physical Soc » et « American Physical Society (APS) », « Karger Publishers » et « S. Karger »). Une marque ou un éditeur racheté reste distinct (« BioMed Central » et Springer). La fusion est celle de l'administration des éditeurs : les formes de nom passent au titulaire, qui reconnaît ensuite ce nom. Les règles sont dans `domain/publishers/aliases.py`.

## Publications en série

4. **`enrich_serials_from_openalex`** — lit les [sources OpenAlex](../sources/03-openalex.md) pour renseigner le type de la revue. Sont reprises les revues qui ont un `openalex_id` et dont le type est inconnu (`serial_type = 'unknown'`).

5. **`check_serials_in_sudoc`** — vérifie les ISSN des revues dans le [Sudoc](../sources/09-sources-supplementaires.md#sudoc). Sont reprises les revues dont un ISSN n'est pas vérifié, et celles dont un enregistrement contient un ISSN absent de leurs ISSN. Les notices Sudoc regroupent les ISSN de la revue par publication. Le groupe principal reste actif et donne l'ISSN-L. Les autres ISSN de la même revue prennent un statut : annulé, titre précédent ou suivant (`430`, `440`), supplément (`421`, `422`). Les ISSN d'une autre publication quittent la revue et sont gardés sans revue : erreurs de source, titres issus d'une scission, d'une fusion ou d'une absorption. Une valeur mal formée est corrigée à une faute de frappe près. Chaque ISSN reçoit le support de sa notice Sudoc et une date de vérification. Les règles sont détaillées dans `domain/serials/issn_check.py`. Un ISSN nouveau attend sa vérification. Une revue dont une requête échoue reste à vérifier, et le run suivant la reprend. Le nombre de revues vérifiées par run est plafonné (`sudoc_max_per_run`, 10 000 par défaut, réglable dans `admin/config`).

6. **`merge_duplicate_serials`** — fusionne les revues en double, selon cinq règles appliquées dans l'ordre :
    - revues vérifiées qui partagent leur ISSN-L ;
    - revues où le même ISSN est actif, sous des titres emboîtés (« BMJ » et « BMJ-BRITISH MEDICAL JOURNAL ») ;
    - revues vérifiées dont l'une a, inactif, un ISSN actif dans l'autre : titre précédent ou suivant de la même revue, supplément ;
    - paires de même titre dont au moins une revue est sans ISSN, et dont les enregistrements partagent un préfixe DOI ;
    - revues que les enregistrements d'une même publication désignent, sous des titres compatibles, et qui n'ont pas chacune des ISSN sans aucun en commun. Deux titres sont compatibles quand l'un abrège l'autre, mot à mot (« Phys.Rev.Lett. » et « Physical Review Letters ») ou par acronyme (« JINST » et « Journal of Instrumentation »). Ils le sont aussi quand ils diffèrent seulement par la casse, la ponctuation, un titre parallèle ou un sous-titre. Les règles de comparaison sont dans `domain/serials/titles.py`.

    La revue qui a le plus de publications absorbe les autres. Pour la troisième règle, la revue dont le premier document est le plus tardif passe avant : le titre suivant absorbe le précédent. Pour la dernière, une revue qui a un ISSN passe avant. La fusion est celle de l'administration des revues : publications et métadonnées passent à la cible, dont le `serial_type` requalifie les publications absorbées, puis la source est supprimée. Les ISSN de la source hors des colonnes de la cible rejoignent ses ISSN rejetés. Le journal d'exécution garde le titre, l'éditeur et les ISSN des deux revues.

7. **`type_proceedings_serials`** — type en recueil d'actes (`proceedings`) trois sortes de revues :
    - les revues de type inconnu dont la majorité des documents sont des articles de congrès, d'après le type donné par chaque source ;
    - les revues sans ISSN, de n'importe quel type, dont le titre nomme une édition datée (« NuFACT 2022 », « 2024 IEEE SENSORS ») ;
    - les revues sans ISSN, de n'importe quel type, dont le titre contient « proceedings » sans nommer une société savante, une académie ou une institution.

8. **`type_journal_serials`** — type en revue (`journal`) les entrées de type inconnu dont la majorité stricte des documents sont des articles, d'après le type donné par chaque source. Le typage en recueil d'actes passe avant.

9. **`learn_serial_doi_namespaces`** — recalcule la table `serial_doi_namespaces`. Un espace de noms est un préfixe de DOI coupé à une frontière de segment (`10.1016/j.physletb.`, `10.1038/s41598-`). Il désigne une revue quand il réunit au moins 5 DOI et que 90 % d'entre eux désignent cette revue, d'après les enregistrements de toutes les sources. Un dépôt, un serveur de preprints ou une collection de livres n'est désigné par aucun espace de noms. Les règles sont dans `domain/serials/doi_namespaces.py`.

10. **`enrich_serials_from_doaj`** — télécharge l'export CSV du [DOAJ](../sources/09-sources-supplementaires.md#doaj), puis met à jour toutes les revues en une passe, par appariement sur l'ISSN : la fiche DOAJ (`doaj_payload`) et le drapeau `is_in_doaj`. Le drapeau `is_in_doaj` est remis à `false` partout, puis à `true` pour les seules revues présentes dans l'export. Un export où aucune revue n'est reconnue laisse les revues en l'état, et l'étape le signale. Le téléchargement a lieu seulement si le dernier import date de plus que le délai `doaj_refresh_after_days` (30 jours par défaut, réglable dans `admin/config`). Quand l'export est inaccessible, les revues restent en l'état et l'import est repris au run suivant. À chaque run, une entrée de type inconnu présente dans le DOAJ devient une revue (`journal`), puisque le DOAJ répertorie seulement des revues. Un type saisi à la main reste en l'état.

## Monographies

11. **`merge_duplicate_monographs`** — fusionne les monographies en double. Deux monographies de même titre naissent quand l'éditeur ou l'ISBN manque à l'une des sources, puis arrive par une autre. Une monographie rejoint la seule monographie compatible de son titre, quand celle-ci en dit davantage. Les règles sont dans `domain/monographs/matching.py`.

12. **`link_monographs_to_collections`** — choisit l'entrée de `serials` de chaque monographie : sa collection à ISSN, à défaut sa série sans ISSN, à défaut l'entrée sans ISSN qui décrit le volume lui-même, à défaut aucune. Les monographies sans collection à ISSN se regroupent en séries : titres de volume (année, ordinal d'édition, numéro de volume) de même titre de série, chez le même éditeur, à partir de deux volumes. Une série reçoit son entrée dans `serials`, sans ISSN, typée recueil d'actes si tous ses volumes sont des actes, collection de livres sinon. Une monographie dont les enregistrements désignent plusieurs entrées au même niveau reste en l'état, signalée. Les règles sont dans `domain/serials/series.py` et `domain/monographs/collection.py`.

13. **`type_proceedings_volumes`** — recalcule la nature de chaque monographie, volume d'actes ou livre. Trois signaux suffisent chacun : un enregistrement issu d'un congrès, une collection typée recueil d'actes, un titre anglais qui annonce des actes. Les règles sont dans `domain/monographs/proceedings.py`.

## Import manuel d'un export DOAJ

`interfaces/cli/imports/import_doaj_csv.py` rejoue le même import à partir d'un CSV fourni, par exemple pour amorcer la base depuis un export récupéré à part.
