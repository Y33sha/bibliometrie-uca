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

Un objet de transport unique porte l'écriture. Une dataclass `SourcePublicationRow` réunit toutes les colonnes de `source_publications`, les champs hors périmètre d'une source restant à `None`. Elle vit dans `application/ports/pipeline/normalize/source_publications.py`, auprès du port `SourcePublicationQueries` qui la consomme, lequel n'expose qu'une méthode `upsert_source_publication(conn, row) -> int` servie par une seule implémentation Pg. Disparaissent les sept méthodes de port bespoke, les sept fonctions libres et les sept méthodes de délégation ; cinq des sept ports par source (`crossref`, `datacite`, `hal`, `scanr`, `wos`), qui ne portaient que leur upsert, disparaissent avec elles.

La construction est keyword-only (`kw_only`), comme l'étaient les signatures qu'elle remplace : les champs se déclarent par groupe logique (identité, rattachement, métadonnées bibliographiques, contenu, accès ouvert, métriques, colonnes propres à une source) sans que les champs obligatoires aient à précéder les autres.

La clé de conflit `(source, source_id)` porte un `source` littéral par source : **une source n'entre jamais en conflit qu'avec ses propres lignes**. Les colonnes propres à une source (`hal_collections`, `embargo_until`, `is_retracted`) ne sont donc jamais renseignées ailleurs, et `embargo_until` n'a d'autre écrivain que le normaliseur HAL — appliquer leurs règles de fusion depuis le statement commun est un no-op pour les autres sources.

L'implémentation Pg porte un seul statement SQL listant toutes les colonnes. La faisabilité tient à une condition : chaque règle de fusion du `DO UPDATE` doit dégrader en no-op quand la colonne vaut `None` pour la source qui écrit. C'est vérifiable colonne par colonne — `COALESCE(EXCLUDED.x, existant.x)` garde l'existant quand `EXCLUDED` est `NULL` ; `GREATEST(existant, EXCLUDED)` ignore les `NULL` et remplace la forme `GREATEST(COALESCE(EXCLUDED, 0), COALESCE(existant, 0))` qui, elle, convertit un `NULL` en `0` ; le merge de tableau avec `COALESCE(..., '{}')` laisse l'existant inchangé quand l'apport est `NULL`. C'est un chemin d'écriture : l'audit de chaque règle précède la bascule et se double d'une couverture de tests.

Le périmètre des champs par source est conservé tel quel — ce chantier factorise la mécanique d'écriture, il ne comble ni n'ajoute de colonnes.

Hors périmètre : les méthodes de port qui ne sont pas l'upsert de publication restent en place — `count_openalex_table` / `count_theses_table`, et les gestes d'authorship de theses (`upsert_theses_source_authorship`, `clear_source_authorships_for_publication`).

## Phasage

### Phase 1 — objet et port

- [x] `SourcePublicationRow` (dataclass `kw_only`, toutes colonnes, champs propres à une source par défaut `None`) et port `SourcePublicationQueries` (méthode unique `upsert_source_publication(conn, row) -> int`) dans `application/ports/pipeline/normalize/source_publications.py`.

### Phase 2 — implémentation

- [x] Audit colonne par colonne des règles de fusion du `DO UPDATE` — voir *Audit des règles de fusion* ci-dessous.
- [ ] Un seul statement SQL et une seule implémentation Pg.

### Phase 3 — bascule et suppressions

Les suppressions ne peuvent précéder la bascule des appelants : jusque-là, les méthodes par source restent appelées.

- [ ] Les sept normaliseurs construisent `SourcePublicationRow` au lieu d'appeler la méthode par source.
- [ ] Bascule des tests de normalisation sur l'objet et la méthode unique.
- [ ] Suppression des sept méthodes de port bespoke, des sept fonctions libres et des sept méthodes de délégation ; suppression des cinq ports par source devenus vides (`crossref`, `datacite`, `hal`, `scanr`, `wos`) et de leurs adapters.

## Audit des règles de fusion

Union des colonnes écrites, et règle de `DO UPDATE` par source. `title`, `title_normalized`, `pub_year` et `staging_id` sont **insert-only** chez les sept : aucune ne figure dans un `DO UPDATE`. `publication_id` (`COALESCE(existant, EXCLUDED)`), `external_ids` (concaténation), `doc_type` / `journal_id` / `oa_status` / `language` / `container_title` (`COALESCE(EXCLUDED, existant)`), `keywords`, `keys_dirty` et `updated_at` sont uniformes chez les sept.

Les colonnes que seules certaines sources renseignent (`abstract`, `biblio`, `meta`, `topics`, `urls`, `is_retracted`) suivent partout `COALESCE(EXCLUDED, existant)`, qui dégrade en no-op quand l'apport est `NULL` : leur généralisation au statement commun est neutre.

`external_ids` exige la substitution `None → {}` avant binding : `existant || NULL` vaut `NULL` et effacerait la colonne. Cette substitution, faite en Python dans chaque adapter, est à conserver dans l'implémentation commune.

Deux règles ne se généralisent pas telles quelles :

- **`cited_by_count`** — les cinq sources qui le fournissent appliquent `GREATEST(COALESCE(EXCLUDED, 0), COALESCE(existant, 0))`, qui force un résultat non-`NULL`. Généralisée à HAL et theses.fr, qui ne le fournissent jamais, cette forme convertirait leur `NULL` en `0` à chaque ré-upsert. La forme `GREATEST(existant, EXCLUDED)` ignore les `NULL` et redevient un no-op pour eux ; elle change en contrepartie, pour les cinq autres, le cas où l'existant et l'apport sont tous deux `NULL` : le résultat reste `NULL` au lieu de devenir `0`. C'est le comportement que l'INSERT pose déjà (il écrit `NULL` quand la source ne fournit rien).
- **`doi`** — `COALESCE(existant.doi, EXCLUDED.doi)` (renseigner si absent, ne jamais écraser) figure chez `crossref`, `datacite`, `hal` et `scanr`, mais `openalex`, `theses` et `wos` ne mettent pas `doi` à jour du tout. La règle commune renseignerait donc un `doi` resté `NULL` sur ces trois sources, ce qu'elles ne font pas aujourd'hui.

## Questions ouvertes

- **`cited_by_count` : `NULL` ou `0` quand rien n'est connu ?** La bascule vers `GREATEST(existant, EXCLUDED)` est nécessaire pour que le statement commun soit neutre sur HAL et theses.fr ; elle aligne l'`UPDATE` sur l'`INSERT`, au prix d'un `NULL` là où un `0` était posé quand les deux valeurs manquaient.
- **`doi` : renseigner si absent, pour les sept ?** Uniformiser étend aux trois sources qui n'y touchent pas (`openalex`, `theses`, `wos`) le comportement des quatre autres. À trancher : uniformisation, ou conservation à l'identique via une règle qui distingue les sources.
