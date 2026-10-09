# Enrichissement des référentiels publishers et journals

*À jour le 2026-10-09.*

La phase `publishers_journals` complète les référentiels d'éditeurs, de revues et de monographies que la phase [normalize](03-normalize.md) alimente au fil des documents : elle rattache chaque préfixe DOI à son éditeur, vérifie les ISSN des revues, va chercher auprès de sources externes le type des revues et leurs frais de publication, fusionne les doublons, rattache les monographies à leur collection et supprime les entrées vides. Le `journal_type` qu'elle pose nourrit la correction `journal_type → doc_type` de la phase [metadata_correction](06-metadata-correction.md), d'où sa place dans le pipeline.

Les sous-étapes forment quatre groupes, chacun sous son titre dans le journal : éditeurs, revues, monographies, nettoyage. Chaque sous-étape y tient une ligne de bilan.

## Éditeurs

1. **`resolve_publishers`** — interroge `/prefixes/{prefix}` chez Crossref ou DataCite pour connaître le détenteur d'un préfixe DOI, puis rattache le `publisher_id` correspondant à ce préfixe. Le routage vers l'une ou l'autre API suit l'agence d'enregistrement posée par la phase [resolve_ra](02-extract.md#agences-denregistrement-doi-resolve_ra) ; un préfixe dont l'agence est `unknown` est présenté aux deux, et celle qui répond la corrige. Crossref rend l'éditeur ; DataCite rend le provider, avec l'entrepôt (Zenodo, NAKALA…) qui a déposé les DOI. Sont repris les préfixes sans éditeur et jamais interrogés (`publisher_id` et `publisher_checked_at` nuls) : chaque préfixe est marqué interrogé, succès ou échec, pour qu'un préfixe non trouvé ne soit pas retenté.

## Revues

2. **`enrich_journals_from_openalex`** — lit les [sources OpenAlex](../sources/03-openalex.md) pour renseigner le type de revue, le montant et la devise des frais de publication (APC). Sont reprises les revues qui portent un `openalex_id` et dont le type est inconnu (`journal_type = 'unknown'`).

3. **`check_journals_in_sudoc`** — vérifie les ISSN des revues dans le [Sudoc](../sources/09-sources-supplementaires.md#sudoc). Sont reprises les revues dont un ISSN n'est pas vérifié, et celles dont un enregistrement porte un ISSN absent de leurs ISSN. Les notices Sudoc regroupent les ISSN de la revue par publication. Le groupe principal reste actif et donne l'ISSN-L. Les autres ISSN de la même revue prennent un statut : annulé, titre précédent ou suivant (`430`, `440`), supplément (`421`, `422`). Les ISSN d'une autre publication quittent la revue et sont gardés sans revue : erreurs de source, titres issus d'une scission, d'une fusion ou d'une absorption. Une valeur mal formée est corrigée à une faute de frappe près. Chaque ISSN reçoit le support de sa notice et une date de vérification. Les règles sont détaillées dans `domain/journals/issn_check.py`. Un ISSN nouveau attend sa vérification. Les revues sont vérifiées 4 à la fois, à 5 requêtes par seconde au plus. Une revue dont une requête échoue reste à vérifier, et le run suivant la reprend.

4. **`merge_duplicate_journals`** — fusionne les revues en double, selon cinq règles appliquées dans l'ordre :
    - revues vérifiées qui partagent leur ISSN-L ;
    - revues où le même ISSN est actif, sous des titres emboîtés (« BMJ » et « BMJ-BRITISH MEDICAL JOURNAL ») ;
    - revues vérifiées dont l'une porte, inactif, un ISSN actif dans l'autre : titre précédent ou suivant de la même revue, supplément ;
    - paires de même titre dont au moins une revue est sans ISSN, et dont les enregistrements partagent un préfixe DOI ;
    - revues que les enregistrements d'une même publication portent, sous des titres compatibles, et qui n'ont pas chacune des ISSN sans aucun en commun. Deux titres sont compatibles quand l'un abrège l'autre, mot à mot (« Phys.Rev.Lett. » et « Physical Review Letters ») ou par acronyme (« JINST » et « Journal of Instrumentation »). Ils le sont aussi quand ils diffèrent seulement par la casse, la ponctuation, un titre parallèle ou un sous-titre. Les règles de comparaison sont dans `domain/journals/titles.py`.

    La revue qui porte le plus de publications absorbe les autres. Pour la troisième règle, la revue dont le premier document est le plus tardif passe avant : le titre suivant absorbe le précédent. Pour la dernière, une revue qui a un ISSN passe avant. La fusion est celle de l'administration des revues : publications et métadonnées passent à la cible, dont le `journal_type` requalifie les publications absorbées, puis la source est supprimée. Les ISSN de la source hors des colonnes de la cible rejoignent ses ISSN rejetés. Le journal d'exécution garde le titre, l'éditeur et les ISSN des deux revues.

5. **`type_proceedings_journals`** — type en recueil d'actes (`proceedings`) trois sortes de revues :
    - les revues de type inconnu dont la majorité des documents sont des articles de congrès, d'après le type donné par chaque source ;
    - les revues sans ISSN, de n'importe quel type, dont le titre nomme une édition datée (« NuFACT 2022 », « 2024 IEEE SENSORS ») ;
    - les revues sans ISSN, de n'importe quel type, dont le titre contient « proceedings » sans nommer une société savante, une académie ou une institution.

6. **`learn_journal_doi_namespaces`** — recalcule la table `journal_doi_namespaces`. Un espace de noms est un préfixe de DOI coupé à une frontière de segment (`10.1016/j.physletb.`, `10.1038/s41598-`). Il désigne une revue quand il réunit au moins 5 DOI et que 90 % d'entre eux portent cette revue, d'après les enregistrements de toutes les sources. Un dépôt, un serveur de preprints, une plateforme de livres ou une collection de livres n'est désigné par aucun espace de noms. Les règles sont dans `domain/journals/doi_namespaces.py`.

7. **`enrich_journals_from_doaj`** — télécharge l'export CSV du [DOAJ](../sources/09-sources-supplementaires.md#doaj), puis met à jour toutes les revues en une passe, par appariement sur l'ISSN : la fiche DOAJ (`doaj_payload`) et le drapeau `is_in_doaj`. Le drapeau `is_in_doaj` est remis à `false` partout, puis à `true` pour les seules revues présentes dans l'export. L'étape se déclenche seulement si le dernier import date de plus que le délai `doaj_refresh_after_days` (30 jours par défaut, réglable dans `admin/config`).

## Monographies

8. **`merge_duplicate_monographs`** — fusionne les monographies en double. Deux monographies de même titre naissent quand l'éditeur ou l'ISBN manque à l'une des sources, puis arrive par une autre. Une monographie rejoint la seule monographie compatible de son titre, quand celle-ci en dit davantage. Les règles sont dans `domain/monographs/matching.py`.

9. **`link_monographs_to_collections`** — choisit l'entrée de `journals` de chaque monographie : sa collection à ISSN, à défaut sa série sans ISSN, à défaut l'entrée sans ISSN qui décrit le volume lui-même, à défaut aucune. Les monographies sans collection à ISSN se regroupent en séries : titres de volume (année, ordinal d'édition, numéro de volume) de même titre de série, chez le même éditeur, à partir de deux volumes. Une série reçoit son entrée dans `journals`, sans ISSN, typée recueil d'actes si tous ses volumes sont des actes, collection de livres sinon. Une monographie dont les enregistrements portent plusieurs entrées au même niveau reste en l'état, signalée. Les règles sont dans `domain/journals/series.py` et `domain/monographs/collection.py`.

10. **`type_proceedings_volumes`** — recalcule la nature de chaque monographie, volume d'actes ou livre. Trois signaux suffisent chacun : un enregistrement issu d'un congrès, une collection typée recueil d'actes, un titre anglais qui annonce des actes. Les règles sont dans `domain/monographs/proceedings.py`.

## Nettoyage

11. **`delete_empty_monographs`** — supprime les monographies sans enregistrement ni publication.

12. **`delete_empty_journals`** — supprime les revues sans enregistrement, sans publication, sans monographie et sans paiement APC, avec leurs formes de nom. Le journal d'exécution garde le titre, l'éditeur et les ISSN de chaque revue supprimée.

13. **`delete_empty_publishers`** — supprime les éditeurs sans revue, sans monographie, sans préfixe DOI, sans paiement APC et sans forme de nom de revue.

## Import manuel d'un export DOAJ

`interfaces/cli/imports/import_doaj_csv.py` rejoue le même import à partir d'un CSV fourni, par exemple pour amorcer la base depuis un export récupéré à part.
