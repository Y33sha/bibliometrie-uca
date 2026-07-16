# Normalize : factoriser l'upsert des `source_publications`

## Contexte

Les sept normaliseurs de source (`crossref`, `datacite`, `hal`, `openalex`, `scanr`, `theses`, `wos`) exposent chacun une méthode de port `upsert_<source>_source_publication` à 15-20 paramètres keyword-only, adossée à une fonction libre d'environ 80 lignes de SQL, elle-même doublée d'une méthode de classe qui recopie tous les paramètres pour redéléguer à la fonction libre. Cette délégation ne mutualise rien : chaque source a un seul adapter.

L'ossature SQL est identique partout : `INSERT INTO source_publications (...) VALUES (...) ON CONFLICT (source, source_id) DO UPDATE SET ... RETURNING id`, avec le calcul de `title_normalized`, la substitution `external_ids None → {}`, et `keys_dirty = true, updated_at = clock_timestamp()`.

Les divergences réelles d'une source à l'autre sont de deux ordres. D'abord les colonnes présentes : l'identifiant natif (`doi` pour crossref et datacite, `hal_id`, `openalex_id`, `scanr_id`, `theses_id`, `ut`), et selon la source `abstract`, `cited_by_count`, `urls`, `topics`, `meta`, plus `hal_collections` et `embargo_until` propres à HAL et `is_retracted` propre à OpenAlex. Cette présence reflète ce que chaque source fournit — theses n'expose pas de résumé, HAL et theses ne fournissent pas de compte de citations : ce ne sont pas des oublis. Ensuite quelques règles de fusion spéciales dans le `DO UPDATE`, tout le reste étant un `COALESCE(EXCLUDED.x, source_publications.x)` uniforme :

- `doi` garde l'existant : `COALESCE(source_publications.doi, EXCLUDED.doi)` ;
- `external_ids` se concatène : `source_publications.external_ids || EXCLUDED.external_ids` ;
- `cited_by_count` prend le maximum : `GREATEST(COALESCE(EXCLUDED, 0), COALESCE(existant, 0))` ;
- `hal_collections` fusionne les deux tableaux en dédupliquant (`array_agg(DISTINCT ... ORDER BY)`), propre à HAL ;
- `embargo_until` écrase sans condition (`EXCLUDED.embargo_until`), propre à HAL.

Par-dessus ces différences légitimes s'ajoute du bruit purement cosmétique, sans valeur sémantique et appliqué de façon non uniforme : le suffixe `_json` sur `topics_json` (openalex, theses) contre `topics` (hal, scanr, wos), et sur `source_meta_json` (theses) alors que le paramètre alimente simplement la colonne `meta` — le type `JsonValue` dit déjà que la donnée est du JSON ; l'ordre des paramètres diffère aussi d'une signature à l'autre, ce qui empêche de lire les sept en diff.

Un développeur extérieur voit sept variantes d'un même geste, sans pouvoir distinguer d'un coup d'œil ce qui varie par nécessité de ce qui varie par accident.

## Décisions

Un objet de transport unique porte l'écriture. Une dataclass `SourcePublicationRow` réunit toutes les colonnes de `source_publications`, les champs hors périmètre d'une source restant à `None`. Elle vit dans `application/ports/pipeline/normalize/_common.py`, sur le modèle de `UpsertOutcome` dans `extract/_common.py`. Le port n'expose plus qu'une méthode `upsert_source_publication(conn, row) -> int`, et une seule implémentation Pg la sert. Disparaissent les sept méthodes de port bespoke, les sept fonctions libres et les sept méthodes de délégation.

L'implémentation Pg porte un seul statement SQL listant toutes les colonnes. La faisabilité tient à une condition : chaque règle de fusion du `DO UPDATE` doit dégrader en no-op quand la colonne vaut `None` pour la source qui écrit. C'est vérifiable colonne par colonne — `COALESCE(EXCLUDED.x, existant.x)` garde l'existant quand `EXCLUDED` est `NULL` ; `GREATEST(existant, EXCLUDED)` ignore les `NULL` et remplace la forme `GREATEST(COALESCE(EXCLUDED, 0), COALESCE(existant, 0))` qui, elle, convertit un `NULL` en `0` ; le merge de tableau avec `COALESCE(..., '{}')` laisse l'existant inchangé quand l'apport est `NULL`. C'est un chemin d'écriture : l'audit de chaque règle précède la bascule et se double d'une couverture de tests.

Le périmètre des champs par source est conservé tel quel — ce chantier factorise la mécanique d'écriture, il ne comble ni n'ajoute de colonnes.

Hors périmètre : les méthodes de port qui ne sont pas l'upsert de publication restent en place — `count_openalex_table` / `count_theses_table`, et les gestes d'authorship de theses (`upsert_theses_source_authorship`, `clear_source_authorships_for_publication`).

## Phasage

### Phase 1 — objet et port

- [ ] `SourcePublicationRow` (dataclass, toutes colonnes, champs source-spécifiques par défaut `None`) dans `application/ports/pipeline/normalize/_common.py`.
- [ ] Méthode unique `upsert_source_publication(conn, row) -> int` sur un port partagé ; suppression des sept méthodes bespoke des ports par source.

### Phase 2 — implémentation

- [ ] Audit colonne par colonne des règles de fusion du `DO UPDATE` (garde-existant, concaténation, `GREATEST`, merge de tableau, écrasement inconditionnel, `COALESCE`), en vérifiant le no-op sur `None`.
- [ ] Un seul statement SQL et une seule implémentation Pg ; suppression des sept fonctions libres et des sept méthodes de délégation.

### Phase 3 — appelants et tests

- [ ] Les sept normaliseurs construisent `SourcePublicationRow` au lieu d'appeler la méthode par source.
- [ ] Bascule des tests de normalisation sur l'objet et la méthode unique.

## Questions ouvertes

- L'ordre des champs dans la dataclass et dans le statement (regroupement logique : identité, métadonnées bibliographiques, contenu, liens, drapeaux).
