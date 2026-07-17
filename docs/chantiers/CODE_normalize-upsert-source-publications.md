# Normalize : factoriser l'upsert des `source_publications`

## Contexte

Les sept normaliseurs de source (`crossref`, `datacite`, `hal`, `openalex`, `scanr`, `theses`, `wos`) exposent chacun une méthode de port `upsert_<source>_source_publication` à 15-20 paramètres keyword-only, adossée à une fonction libre d'environ 80 lignes de SQL, elle-même doublée d'une méthode de classe qui recopie tous les paramètres pour redéléguer à la fonction libre. Cette délégation ne mutualise rien : chaque source a un seul adapter.

L'ossature SQL est identique partout : `INSERT INTO source_publications (...) VALUES (...) ON CONFLICT (source, source_id) DO UPDATE SET ... RETURNING id`, avec le calcul de `title_normalized`, la substitution `external_ids None → {}`, et `keys_dirty = true, updated_at = clock_timestamp()`.

Les divergences réelles d'une source à l'autre sont de deux ordres. D'abord les colonnes présentes : l'identifiant natif (`doi` pour crossref et datacite, `hal_id`, `openalex_id`, `scanr_id`, `theses_id`, `ut`), et selon la source `abstract`, `cited_by_count`, `urls`, `topics`, `meta`, plus `hal_collections` et `embargo_until` propres à HAL et `is_retracted` propre à OpenAlex. Cette présence reflète ce que chaque source fournit — theses n'expose pas de résumé, HAL et theses ne fournissent pas de compte de citations : ce ne sont pas des oublis.

Ensuite un jeu de règles de fusion dans le `DO UPDATE` — `COALESCE(EXCLUDED.x, source_publications.x)` uniforme, `COALESCE(source_publications.doi, EXCLUDED.doi)` pour le DOI, concaténation des `external_ids`, `GREATEST` sur `cited_by_count`, merge de tableau sur `hal_collections` — qui toutes conservent des valeurs d'imports antérieurs.

Par-dessus s'ajoute du bruit purement cosmétique, sans valeur sémantique et appliqué de façon non uniforme : le suffixe `_json` sur `topics_json` (openalex, theses) contre `topics` (hal, scanr, wos), et sur `source_meta_json` (theses) alors que le paramètre alimente simplement la colonne `meta` — le type `JsonValue` dit déjà que la donnée est du JSON ; l'ordre des paramètres diffère aussi d'une signature à l'autre, ce qui empêche de lire les sept en diff.

Un développeur extérieur voit sept variantes d'un même geste, sans pouvoir distinguer d'un coup d'œil ce qui varie par nécessité de ce qui varie par accident.

## Décisions

Un objet de transport unique porte l'écriture. Une dataclass `SourcePublicationRow` réunit toutes les colonnes de `source_publications`, les champs hors périmètre d'une source restant à `None`. Elle vit dans `application/ports/pipeline/normalize/source_publications.py`, auprès du port `SourcePublicationQueries` qui la consomme, lequel n'expose qu'une méthode `upsert_source_publication(conn, row) -> int` servie par une seule implémentation Pg. Disparaissent les sept méthodes de port bespoke, les sept fonctions libres et les sept méthodes de délégation ; cinq des sept ports par source (`crossref`, `datacite`, `hal`, `scanr`, `wos`), qui ne portaient que leur upsert, disparaissent avec elles.

La construction est keyword-only (`kw_only`), comme l'étaient les signatures qu'elle remplace : les champs se déclarent par groupe logique (identité, rattachement, métadonnées bibliographiques, contenu, accès ouvert, métriques, colonnes propres à une source) sans que les champs obligatoires aient à précéder les autres.

**Une `source_publication` est la vue normalisée d'un import, et le dernier import fait autorité.** Aucune règle de fusion n'a donc lieu d'être : le `DO UPDATE` réécrit chaque colonne depuis la ligne fournie (`col = EXCLUDED.col`). Une valeur que l'import courant ne porte pas disparaît — un `cited_by_count` à 500 devenu absent repasse à `NULL`. Rien ne persiste d'un import à l'autre sinon l'identité `(source, source_id)`, qui maintient l'`id` de la ligne stable pour les tables qui la référencent : c'est la raison d'être de l'UPSERT face à un DELETE suivi d'un INSERT.

L'UPSERT n'écrit que les colonnes que la ligne porte ; les autres le traversent intactes. `publication_id` en fait partie : c'est le rattachement que pose la phase `publications`, qu'aucun import ne renseigne, et que l'UPSERT n'a donc pas à toucher. Chaque écriture repassant `keys_dirty` à `true`, cette phase recalcule le rattachement des lignes touchées. Il en va de même du cache `countries` et de `created_at`.

Le périmètre des champs par source est conservé tel quel — ce chantier factorise la mécanique d'écriture, il ne comble ni n'ajoute de colonnes.

**Le stat de fin de run disparaît.** `summary_stats` est un hook optionnel que deux normaliseurs sur sept surchargent, via un `count_<source>_table` qui est la même requête au littéral de source près. Cinq sources s'en passent ; les sept s'en passent.

**Les signatures de thèse sans rang d'auteur.** Les rôles non-auteur (direction, rapport, jury, présidence) portent un `author_position` nul, que le remap par position du writer batch ne sait pas retrouver : theses écrit ses signatures une par une, avec `RETURNING`. Ce besoin est réel, mais il ne justifie pas un port par source — le port partagé des authorships expose `upsert_source_authorship(conn, item) -> int`, paramétré par la source. Le `clear` que theses déclarait en double revient au même port partagé, qu'il reçoit déjà.

Au terme du chantier, `application/ports/pipeline/normalize/` ne contient plus aucun port par source : `authorships.py`, `source_publications.py`, `staging.py`.

## Phasage

### Phase 1 — objet et port

- [x] `SourcePublicationRow` (dataclass `kw_only`, toutes colonnes, champs propres à une source par défaut `None`) et port `SourcePublicationQueries` (méthode unique `upsert_source_publication(conn, row) -> int`) dans `application/ports/pipeline/normalize/source_publications.py`.

### Phase 2 — implémentation

- [x] Relevé des colonnes écrites et de leurs règles de fusion, source par source, qui établit que `title`, `title_normalized`, `pub_year` et `staging_id` ne figuraient dans aucun `DO UPDATE` — quatre colonnes qu'un ré-import laissait figées.
- [x] Un seul statement SQL et une seule implémentation Pg, dont les listes de colonnes se dérivent des champs de la ligne.

### Phase 3 — bascule et suppressions

Les suppressions ne peuvent précéder la bascule des appelants : jusque-là, les méthodes par source restent appelées.

- [x] Les sept normaliseurs construisent `SourcePublicationRow` au lieu d'appeler la méthode par source.
- [x] `upsert_source_authorship` sur le port partagé des authorships ; theses y bascule, avec son `clear`.
- [x] Suppression de `summary_stats` et des `count_<source>_table`.
- [x] Bascule des tests de normalisation sur l'objet et la méthode unique ; test d'intégration du ré-import (identité stable, écrasement, effacement d'une valeur absente).
- [x] Suppression des sept ports par source et de leurs adapters, des sept fonctions libres et des sept méthodes de délégation ; câblage du composition root sur l'adapter unique.
- [x] Suppression du paramètre `publication_id`, mort chez les sept appelants.

## Questions ouvertes

Aucune.
