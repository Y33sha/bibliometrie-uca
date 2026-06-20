# Chantier — Embargo HAL : statut OA intermédiaire « sous embargo »

Commencé le 2026-06-19 - Terminé le 2026-06-20

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

Volume (audité 2026-06-20 sur le raw store, 85 242 fichiers HAL) : **34 182** portent un `notBefore`, mais la plupart sont des dates **passées** (mise à disposition déjà échue, document réellement ouvert). **408** ont un `notBefore` futur (embargo en cours), dont **292** rattachés à une publication en base (les autres hors périmètre / non importés). Après `best_oa_status`, **68** sont ouverts ailleurs (une autre source les déclare green ou mieux) et **224** resteraient réellement `embargoed`.

## Décisions

*(Proposées, à valider — seul le Contexte ci-dessus est factuel.)*

1. **Nouveau membre d'enum `embargoed`**, intermédiaire entre `closed` et `green`. Sémantique : le dépôt existe (l'auteur a fait sa part), mais l'accès est légalement différé. Ni fermé (rien à reprocher à l'auteur) ni encore ouvert.
2. **`OA_RANK` re-numéroté** pour insérer `embargoed` entre `green` et `closed` : `diamond 8 > gold 7 > hybrid 6 > bronze 5 > green 4 > embargoed 3 > closed 2 > unknown 1`. Effet recherché : si une *autre* source atteste l'ouverture réelle ailleurs (OpenAlex `gold`, etc.), elle l'emporte sur `embargoed` ; `embargoed` ne « gagne » que face à `closed`/`unknown`/silence.
3. **Extraction au normalize HAL** de `ref[@type='file']/date/@notBefore` (à côté du parsing TEI existant), stockée dans une nouvelle colonne `source_publications.embargo_until DATE` (NULL = pas d'embargo connu).
4. **`derive_hal_oa_status` date-agnostique** : fichier présent + `embargo_until` renseigné ⇒ `embargoed`, sans regarder la date. La règle `file_main → green` ne s'applique plus dès qu'un embargo est connu. La **levée** à l'échéance n'est **pas** dans le derive — elle est portée par la règle de correction (décision 6), pour que la logique de date ne vive qu'à un seul endroit.
5. **UI intermédiaire** calquée sur les thèses « en cours » : icône sablier + mention « embargo » (et idéalement la date de levée), au lieu du cadenas ouvert. Pastille `oa-embargoed` dédiée.
6. **Promotion `embargoed → green` par une règle de correction `oa_status`, pas par une étape dédiée.** `effective_metadata` gagne une règle `oa_status == embargoed` + `embargo_expired` ⇒ `green`, où `embargo_expired` (`embargo_until <= current_date`) est calculé dans le **SQL de fetch** des corrections — la fonction reste pure (elle lit un booléen, pas d'horloge). La règle tourne dans `metadata_correction`, qui ré-examine **tous** les `source_publications` à chaque run : la promotion est donc automatique à l'échéance, sans ré-import HAL. Le persist des corrections pose déjà `keys_dirty` inconditionnellement, donc la phase `publications` ré-agrège `best_oa_status` et le canonique passe à `green`. Trivialement correct : si `publications.oa_status = 'embargoed'`, c'est qu'aucune source n'était plus ouverte (sinon `best_oa_status` aurait gagné), donc la levée mène toujours à `green`. La logique de date vit en un seul endroit (la règle), et il n'y a aucune phase de pipeline dédiée.

## Phasage

### 1. Audit volumétrie — ✓ (2026-06-20)
*Prérequis : confirme l'ampleur et valide le rang choisi (décision 2).*
- [x] `source_publications` HAL avec `notBefore` futur : **408** dans le raw store, **292** rattachés à une publication
- [x] Recouvrement : **68** déjà ouverts ailleurs (restent ouverts), **224** resteraient `embargoed` → rang validé (embargoed perd face à une source réellement ouverte, gagne sinon)

### 2. Migration (Alembic, SQL pur) — ✓
- [x] `ALTER TYPE oa_type ADD VALUE 'embargoed'` (`autocommit_block`, non transactionnel)
- [x] `ALTER TABLE source_publications ADD COLUMN embargo_until DATE`

Migration `b7e3f9a1c4d8`.

### 3. Domaine — ✓
- [x] `OA_RANK` renuméroté : `embargoed` (3) entre `green` (4) et `closed` (2)
- [x] Tests `best_oa_status` : `embargoed` > closed/unknown, perd face à green+, seul

### 4. Normalize HAL — ✓ (`28faa81b`)
- [x] Extraction `ref[@type='file']/date/@notBefore` → `embargo_until` via `active_embargo_until` ; **date future seulement** (embargo actif ; date échue ⇒ NULL, pas d'historique)
- [x] `derive_hal_oa_status` date-agnostique : fichier présent + `embargo_until` renseigné ⇒ `embargoed` (la levée est portée par la règle de correction, pas par le derive)
- [x] Tests unitaires : `derive` (avec/sans embargo, avec/sans `fileMain_s`) + `active_embargo_until` (future / échue / multi-fichiers / non-file / malformé)

### 5. Règle de correction `oa_status` — ✓ (`a1d28126`)
*La promotion `embargoed → green` est une règle de correction de métadonnées, pas une étape de pipeline dédiée (décision 6).*
- [x] `embargo_expired` (`embargo_until <= current_date`) calculé dans le SQL de fetch — `effective_metadata` reste pure (lit un booléen)
- [x] Prédicats `oa_status` (entrée) et `embargo_expired` ; règle `EMBARGO_EXPIRED_TO_GREEN` (`embargoed` + `embargo_expired` ⇒ `green`). `effective_metadata` corrige aussi `oa_status` (champs indépendants, pas de feed-forward — `# TODO` posé)
- [x] Tests : règle (échu / actif / non-`embargoed`) + `compute_update` + intégration (calcul SQL de la date)
- [x] Propagation au canonique acquise (`persist_corrections` pose déjà `keys_dirty` ⇒ ré-agrégation `best_oa_status` en phase `publications`)

### 6. Rattrapage du stock
- [x] Réimport HAL (`raw_hash=null`) pour repeupler `embargo_until` (nouvelle extraction au normalize) et repositionner le statut des documents concernés. **Bloqué** : l'extraction HAL incrémentale ne re-fetch pas les documents connus, donc `raw_hash=null` est sans effet → cf. [CODE_hal-extract-mono-requete](CODE_hal-extract-mono-requete.md)

### 7. API + UI — ✓
- [x] `oa_status='embargoed'` exposé dans l'API (la date n'est **pas** exposée — décision : pas d'affichage de la date de levée)
- [x] Libellé `Sous embargo` dans `oaLabelsMap` (`$lib/labels`)
- [x] Badge sablier (`hourglass.svg`, comme les thèses « en cours ») + pastille `oa-embargoed` ambre ; pas de date affichée
- [x] Facette « accès » : 3ᵉ catégorie « Sous embargo » entre ouvert et fermé (filtre `access=embargo` + comptage dédié)
- [x] Garde Unpaywall : `embargoed` non rétrogradé vers `closed`/`unknown` (un statut plus ouvert écrase bien)
- [x] Page stats : `embargoed` ajouté aux ventilations OA (résumé, graphe annuel, 3 tables éditeurs/revues/labos, légende), rangé par rang juste avant `closed` ; en-têtes/cellules OA mutualisées en snippets
- [x] Dashboards `persons/[id]` et `laboratories/[id]` : bucket `embargoed` dans le donut OA — corrige aussi un bug (`open_access` comptait les publis embargoed)

## Questions ouvertes — tranchées

- **`embargo_until` au niveau canonique ?** Non : la date n'apparaît pas en UI, donc rien à propager sur `publications`.
- **Facette « accès » open/closed.** 3ᵉ catégorie intermédiaire « Sous embargo » (ni ouvert ni fermé), pas côté fermé.
- **Autres sources d'embargo.** Non : strictement HAL pour l'instant (theses.fr n'expose rien).
- **Impact API Unpaywall.** Garde ajoutée : Unpaywall ne rétrograde pas `embargoed` vers `closed`/`unknown` ; un statut plus ouvert (green+) écrase. Règle spécifique, calquée sur le garde `diamond` existant — la généralisation « liste no-lower (diamond, embargoed) » a été écartée car elle changerait le comportement actuel de `diamond` (audit de fiabilité séparé à prévoir).
