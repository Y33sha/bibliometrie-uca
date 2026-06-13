# Chantier — Embargo HAL : statut OA intermédiaire « sous embargo »

Issu d'un item TODO_LAURA (« embargos HAL : ajouter l'extraction de `ref[@type='file']/date/@notBefore` ») et d'une investigation 2026-06-07 sur le comportement réel du statut OA pendant l'embargo.

## Contexte

Quand un auteur dépose le fichier de sa publication dans HAL mais que l'éditeur impose un embargo, HAL renseigne le document avec `openAccess_bool=false`, un `fileMain_s` **déjà peuplé** (l'URL du document existe), et une date de fin d'embargo portée **uniquement dans le TEI** (`label_xml`), à l'attribut `@notBefore` du `<date>` sous `<ref type="file">`. Cette date n'est exposée par aucun champ Solr autonome (testé : `fileDateEmbargoed_*`, `whenEndEmbargoed`, `whenEndEmbargoed_s/_tdate` renvoient tous vide en `fl=`). On récupère déjà `label_xml` (cf. [`HAL_FIELDS`](../../infrastructure/sources/hal/fields.py)) et on le parse déjà au normalize pour les ORCID/IdRef ([`parse_tei_author_identifiers`](../../application/pipeline/normalize/normalize_hal.py)) : la donnée est donc déjà dans nos payloads bruts, il n'y a rien à changer côté extraction ni `fl=`.

Comportement actuel, vérifié de bout en bout sur des documents réellement sous embargo (date `notBefore` future) : ils sont tagués **`green`**, pas `closed`. Cause : [`derive_hal_oa_status`](../../domain/sources/hal.py) teste `if file_main: return "green"` **avant** de regarder `openAccess_bool`. Le `green` se propage tel quel à `source_publications.oa_status` puis à `publications.oa_status` (l'agrégation [`best_oa_status`](../../domain/publications/metadata.py) retient le statut le plus ouvert toutes sources, et `green` domine les sources silencieuses). Conséquence : un document non encore accessible est compté et affiché comme libre d'accès.

Le passage de la date d'embargo ne corrige rien automatiquement, pour deux raisons cumulées : (1) HAL lui-même est en retard — des documents dont l'embargo a expiré 1-2 jours plus tôt renvoient encore `openAccess_bool=false` en live, hash identique à notre snapshot ; (2) même après bascule HAL, `fileMain_s` reste présent, donc notre logique re-dériverait `green` des deux côtés. Le statut n'est donc pas « `closed` qui deviendra `green` » : il est `green` du début à la fin, donc faux pendant toute la durée de l'embargo. Le ré-import fonctionne par ailleurs correctement (l'upsert HAL remet `processed=FALSE` quand `raw_hash` change, [`extract_hal.py`](../../infrastructure/sources/hal/extract_hal.py)), mais sans effet ici puisque le statut dérivé ne change pas.

État des lieux des briques concernées :

- Enum PG `oa_type` : `gold, hybrid, bronze, green, closed, unknown, diamond`.
- Rangs d'ouverture `OA_RANK` ([`metadata.py`](../../domain/publications/metadata.py)) : `diamond 7 > gold 6 > hybrid 5 > bronze 4 > green 3 > closed 2 > unknown 1`.
- `source_publications.oa_status` et `publications.oa_status` portent l'enum `oa_type` ; `publications.oa_status` est NOT NULL (défaut `unknown`).
- Affichage front ([`PublicationsListView.svelte`](../../interfaces/frontend/src/lib/components/PublicationsListView.svelte)) : cadenas ouvert/fermé + pastille `oa-{status}` ; libellés dans [`$lib/labels`](../../interfaces/frontend/src/lib/labels.ts) ; la catégorie « accès » open/closed range aujourd'hui tout ce qui n'est pas `closed`/`unknown` du côté ouvert.
- Précédent UI d'un statut « de facto fermé mais non ouvrable par nature » : les thèses « en cours » (`doc_type=ongoing_thesis`).

Volume : ~32 952 payloads HAL portent un `notBefore` mais la plupart sont des dates **passées** (mise à disposition déjà échue, document réellement ouvert). Les vrais cas sous embargo futur sont quelques centaines (à chiffrer précisément en phase 1).

## Décisions

*(Proposées, à valider — seul le Contexte ci-dessus est factuel.)*

1. **Nouveau membre d'enum `embargoed`**, intermédiaire entre `closed` et `green`. Sémantique : le dépôt existe (l'auteur a fait sa part), mais l'accès est légalement différé. Ni fermé (rien à reprocher à l'auteur) ni encore ouvert.
2. **`OA_RANK` re-numéroté** pour insérer `embargoed` entre `green` et `closed` : `diamond 8 > gold 7 > hybrid 6 > bronze 5 > green 4 > embargoed 3 > closed 2 > unknown 1`. Effet recherché : si une *autre* source atteste l'ouverture réelle ailleurs (OpenAlex `gold`, etc.), elle l'emporte sur `embargoed` ; `embargoed` ne « gagne » que face à `closed`/`unknown`/silence.
3. **Extraction au normalize HAL** de `ref[@type='file']/date/@notBefore` (à côté du parsing TEI existant), stockée dans une nouvelle colonne `source_publications.embargo_until DATE` (NULL = pas d'embargo connu).
4. **`derive_hal_oa_status` rendu conscient de l'embargo** : si une date de fin d'embargo est dans le futur, renvoyer `embargoed` au lieu de `green`, même quand `fileMain_s` est présent. La règle `file_main → green` ne s'applique plus que hors embargo.
5. **UI intermédiaire** calquée sur les thèses « en cours » : icône sablier + mention « embargo » (et idéalement la date de levée), au lieu du cadenas ouvert. Pastille `oa-embargoed` dédiée.
6. **Promotion `embargoed → green` par le pipeline, pas à la lecture.** La date étant stockée, une étape de pipeline (à chaque run) promeut en `green` tout `embargoed` dont `embargo_until <= current_date`, indépendamment d'un éventuel ré-import HAL (qui est en retard). Le statut en base reste la vérité, pas de dérivation au read-time. Propriété qui le rend trivialement correct : si `publications.oa_status = 'embargoed'`, c'est qu'aucune source n'était plus ouverte (sinon `best_oa_status` aurait déjà gagné), donc la levée mène toujours à `green`.

## Phasage

1. **Audit volumétrie** : compter les `source_publications` HAL avec `notBefore` futur, et le recouvrement avec d'autres sources qui les déclarent déjà ouverts (combien resteraient réellement `embargoed` après `best_oa_status`). Confirme l'ampleur et valide le rang choisi.
2. **Migration** : `ALTER TYPE oa_type ADD VALUE 'embargoed'` + `ALTER TABLE source_publications ADD COLUMN embargo_until DATE`. (Alembic, SQL pur ; `ADD VALUE` est non transactionnel — vérifier le découpage Alembic.)
3. **Domaine** : `OA_RANK` mis à jour ; tests de `best_oa_status` couvrant `embargoed` vs sources ouvertes/fermées.
4. **Normalize HAL** : extraction `notBefore` → `embargo_until` ; `derive_hal_oa_status` prend la date en paramètre et renvoie `embargoed` si futur. Tests unitaires (embargo futur, échu, absent ; avec/sans `fileMain_s`).
5. **Rattrapage du stock** : re-normalisation HAL `raw_hash=null` (selon le mode de re-run habituel) pour repositionner le statut des documents concernés.
6. **API + UI** : exposer `oa_status='embargoed'` (et la date) ; libellé `$lib/labels` ; rendu sablier + mention « embargo » ; décider du rangement dans la facette « accès » (cf. questions).

## Questions ouvertes

- **Cible de la promotion `embargoed → green` (décision 6).** L'`UPDATE` à l'échéance porte-t-il sur `source_publications` (puis re-agrégation `best_oa_status` des publications touchées) ou directement sur `publications` ? Le direct exige `embargo_until` au niveau canonique (cf. point suivant) ; sinon, jointure `publications → source_publications` HAL. Choisir où placer l'étape dans le pipeline (proche de la phase oa_status / enrich).
- **`embargo_until` au niveau canonique ?** Le propager sur `publications` (pour afficher « embargo jusqu'au X » et faire la promotion directement sur la table canonique) ou le garder seulement sur `source_publications` (UI et promotion via jointure) ?
- **Facette « accès » open/closed.** `embargoed` va du côté fermé (cohérent : pas encore accessible) ou forme une 3ᵉ catégorie ? Idem pour les décomptes OA des dashboards.
- **Autres sources d'embargo.** theses.fr n'expose rien (vérifié). Les autres sources (OpenAlex…) peuvent-elles signaler un embargo, ou est-ce strictement HAL pour l'instant ?
- **Dates `notBefore` passées.** Confirmer qu'une date échue n'a aucun effet (document traité comme ouvert normal) et ne pollue pas `embargo_until` (NULL vs date passée conservée pour historique ?).
- **Quel impact de l'API Unpaywall?** Ne pas écraser un statut *embargoed* par un statut *closed*. Si un statut plus ouvert est trouvé: écraser.
