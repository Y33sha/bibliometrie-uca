# Chantier — Correction des métadonnées canoniques

Commencé le 2026-05-27

## Contexte

Trois chantiers actifs (`METIER_publishers-journals`, `METIER_metadata-deduplication`, `METIER_doc-types`) convergent sur un même besoin sans le nommer : un point unique où appliquer les règles de correction métadonnées qui s'appuient sur plusieurs tables référentielles (journal, publisher, doi_prefixes…). Faute de ce point, chaque chantier ré-invente sa propre stratégie et leurs ordonnancements respectifs se conditionnent.

Trois contraintes structurent le chantier :

1. **`source_publications` inviolable** : trace fidèle de ce que chaque source a renvoyé, jamais muter pour des corrections de cohérence. Garantit l'auditabilité et la réversibilité d'une règle qui se révélerait fausse ou trop stricte.

2. **`refresh_from_sources` est déjà le point unique de matérialisation du canonique** ([`domain/publications/aggregation.py:28`](../../domain/publications/aggregation.py#L28)). Toute correction cross-table s'y branche naturellement, sans introduire de vue ni de table sidecar.

3. **`correct_openalex_doc_type` est une dette** : cascade dans le normalizer OpenAlex qui mute `source_publications.doc_type` à l'ingestion. Héritage de l'époque pré-correction, justifiable tant qu'il n'existait pas d'autre point de correction. Avec ce chantier, l'exception devient lisiblement gênante et se résorbe.

## Patron architectural

**Fonction pure** `effective_metadata(sp, journal, publisher, doi_prefix) → CorrectedFields` dans `domain/`. Prend les inputs bruts (une SourcePublication + ses entités liées) et retourne les champs corrigés. Aucune I/O, aucun effet de bord.

**Deux appelants** :

- `refresh_from_sources` : appelle `effective_metadata` sur chaque source agrégée pour calculer les champs canoniques corrigés. Le canonique persisté est *déjà* corrigé.
- `match_or_create_publications` : appelle `effective_metadata` sur la SP entrante avant les queries de dedup metadata, qui matchent ainsi sur les champs corrigés.

**Audit dans `publications.meta`** : trace de la règle appliquée (`meta.doc_type_corrected_by = "JOURNAL_TYPE_PROCEEDINGS_RULE"` par exemple). Introduit à la première règle figée, pas avant. Permet le re-run ciblé et la lisibilité des corrections dans l'UI.

## Cascade interne d'`effective_metadata`

Ordre déterministe, dicté par les dépendances entre champs :

1. **`journal_id`** d'abord. Une correction du journal change `journal.type` / `journal.status` / `journal.apc`, qui sont les inputs des règles suivantes. Le journal corrigé est re-fetché avant la suite.
2. **`doc_type`** ensuite. Consomme `journal.type` (proceedings → conference_paper, media → intervention_média, …), les helpers de détection (`is_supplement_title`, `is_figshare_doi`, …), et les regex sur titre (« Erratum », « Corrigendum », « Interview », …).
3. **`oa_status`** enfin. Consomme `journal.status` / `journal.apc` (oa_status `subscription` sur revue DOAJ → incohérence ; `gold` sur revue subscription → incohérence) et `oa_model` une fois figé.

**Champs hors-scope du chantier** : `sujets` (chantier sémantique distinct, bien plus ambitieux).

## Frontière correction vs détection-seulement

Tous les patterns d'incohérence ne se prêtent pas à une règle de correction automatique. Exemples observés :

- Pattern qui se corrige : `journal.type=proceedings ⇒ doc_type=conference_paper` (règle universelle).
- Pattern à détecter sans corriger automatiquement : DOI préfixe d'éditeur A sur publi dans revue d'éditeur B (peut être un preprint légitime, peut être un faux). Décision humaine requise.
- Pattern à étudier : article sans `journal_id` (préprint sur archive ? entrée à supprimer ? journal manquant à créer ?).

Ce chantier ne traite que les patterns **avec règle de correction déterministe**. Les patterns détectables-mais-pas-corrigibles relèvent d'un chantier futur de revue manuelle des incohérences.

## Hooks admin (principe)

Tout changement d'un input externe doit déclencher `refresh_from_sources` sur les publications impactées, via le service propriétaire de la table modifiée :

- Changement de `journal.type` / `journal.status` / `journal.apc_amount` → re-run sur les publications du journal.
- Fusion de journals ou de publishers → re-run sur les publications impactées par la fusion.
- Changement de `publisher.type` → re-run sur les publications des journals du publisher.

Sans ces hooks, le canonique se désynchronise des référentiels jusqu'au prochain passage du pipeline complet. La mise en œuvre est différée à Phase 3 : tant qu'aucune règle de correction n'exploite un input admin-éditable, les hooks seraient du scaffold inactif et risqueraient le bit-rot.

## Phases

### Phase 1 — Structure

- [x] Squelette de `domain/publications/correction.py` : `effective_metadata(...)` qui retourne ses inputs inchangés (aucune règle).
- [x] Branchement dans `refresh_from_sources` : appel d'`effective_metadata` sur chaque source agrégée.
- [x] Branchement dans `match_or_create_publications` : appel sur la SP entrante avant les queries de dedup metadata.
- [x] Tests : non-régression complète (la phase ne change aucun comportement).

### Phase 2 — Liquidation de `correct_openalex_doc_type`

Première application réelle du patron. Les règles migrées (theses.fr / dumas) sont mono-source et déterministes, et leurs inputs (URL OpenAlex) ne sont pas admin-éditables — pas de hooks à introduire.

**Découverte qui requalifie cette phase** : `correct_openalex_doc_type` est du dead code. `extract_pub_metadata` calcule bien le `doc_type` corrigé, mais `insert_openalex_document` ne lit jamais ce champ de `pub_meta` — il recalcule `doc_type = work.get("type")` (brut) indépendamment. La sortie corrigée est calculée puis jetée. Conséquences :

- La règle « `source_publications.doc_type` OpenAlex = brut » est *déjà* l'état de fait. La supprimer ne change rien à ce qui est persisté côté SP.
- La correction theses.fr → `thesis` / dumas → `memoir` n'a en réalité **jamais tourné**. Le canonique des theses.fr/dumas orphelines (SP OpenAlex seule, sans SP theses.fr en parallèle) suit le `map_doc_type` du brut OpenAlex (`article` reste `article`, `dissertation` devient `thesis`). Seules les pubs ayant une SP theses.fr en parallèle obtiennent `thesis`, via la priorité de source à l'agrégation.

La phase se scinde donc en deux gestes distincts que l'ancien code mélangeait :

1. **Suppression du dead code** (vrai no-op) : retrait de `correct_openalex_doc_type` + son appel + le plumbing `doc_type` orphelin dans `extract_pub_metadata`. Zéro changement de comportement, zéro écriture DB.
2. **Activation des règles** (première règle réellement active) : les implémenter dans `effective_metadata`, c'est les rendre actives pour la 1re fois — donc audit `meta.doc_type_corrected_by` et re-run ciblé, exactement la mécanique réservée à Phase 3, **moins les hooks** (inputs NNT/URL non admin-éditables). « Comportement identique à l'existant » était faux : c'est un changement de comportement assumé qui corrige un bug silencieux.

**Câblage des inputs** : une fois la règle dans `effective_metadata`, elle reçoit une `SourcePublication`, plus le `work` OpenAlex. Les signaux se reconstruisent depuis la SP persistée : theses.fr et dumas se détectent sur `sp.urls` (`theses.fr/`, `dumas.`). Le côté `refresh` charge déjà `urls` ; côté match_or_create, `_sp_from_row` ne le peuplait pas — ajout de `urls` à `SourcePublicationRow` + projection SQL + helper. La capture systématique des URL comme métadonnée vaut quelle que soit la source.

- [x] Suppression du dead code `correct_openalex_doc_type` (fonction + appel + plumbing `doc_type` dans `extract_pub_metadata` + tests). `f24ddcac`
- [x] Câblage `urls` sur `SourcePublicationRow`, sa projection SQL et `_sp_from_row`.
- [x] Implémentation des règles `THESES_FR_URL_TO_THESIS` / `DUMAS_URL_TO_MEMOIR` dans `effective_metadata` + audit `meta.doc_type_corrected_by` (posé côté `refresh` seulement quand la valeur change réellement).
- [x] Tests : règles `effective_metadata` + audit `_apply_corrections`.
- [ ] Re-run ciblé `refresh_from_sources` sur le stock impacté (écriture DB).

### Phase 3 — Première règle admin-sensible + introduction des hooks

Première règle dont les inputs sont éditables côté admin (typiquement `journal.type` ou `journal.status`). C'est elle qui matérialise le besoin de hooks ; on les introduit à ce moment-là, calibrés sur les dépendances réelles de la règle.

- [ ] Choix de la règle : à arbitrer au moment de Phase 3 selon ce qui aura mûri côté chantiers connexes (candidats probables : `JOURNAL_TYPE_PROCEEDINGS_TO_CONFERENCE_PAPER`, `JOURNAL_TYPE_MEDIA_TO_INTERVENTION_MEDIA`).
- [ ] Implémentation de la règle dans `effective_metadata` + audit `meta.<field>_corrected_by`.
- [ ] Introduction des hooks admin sur les inputs effectivement consommés par la règle (UPDATE `journal.type`, `merge_journals`, etc. selon les dépendances). Méthodes repo associées (`find_publication_ids_by_journal_id`, …).
- [ ] Re-run ciblé sur le stock impacté.
- [ ] Tests : régression sur la règle + couverture des hooks.

### Phase 4+ — Règles suivantes au fil de l'eau

Une règle figée = un commit (règle dans `effective_metadata` + audit + tests + re-run ciblé + extension éventuelle des hooks si nouvelle dépendance d'input). Les règles arrivent depuis les chantiers connexes au rythme de leur maturation.

Pipeline d'arrivée prévisible (non exhaustif, non contraignant) :

- **Depuis `METIER_doc-types`** : règles figshare/zenodo/supplément (doc_type=other), préprint OA gold avec revue inconnue, helpers de détection titre/préfixe DOI.
- **Depuis `METIER_publishers-journals` Phase 4** : incohérences `oa_status` vs `journal.status` (DOAJ), `journal.type=media ⇒ doc_type=intervention_média` (type à créer), et tout ce qui n'a pas été pris en Phase 3.
- **Côté `journal_id`** : règles à concevoir au cas par cas (DOI préfixe ↔ journal éditeur, journal détecté absent → création ou rattachement).

## Décisions différées

- **Conflits entre règles** sur un même champ : ordre de priorité explicite ou erreur ? À trancher à la 2e règle qui touche le même champ.
- **Re-run ciblé vs global** : aujourd'hui un re-run global de `refresh_from_sources` reste tenable. Quand le stock impacté deviendra pénible à recalculer, introduire un mécanisme de re-run par règle (via l'audit `meta.X_corrected_by`).
- **Périmètre des hooks admin** : posé Phase 3 selon les inputs réels de la 1re règle admin-sensible, puis étendu Phase 4+ au fil des nouvelles dépendances. Toute action admin ajoutée ultérieurement doit être revue pour évaluer si elle invalide un canonique.

## Liens

- [`METIER_publishers-journals.md`](METIER_publishers-journals.md) — Phase 4 fournit les règles côté cohérence éditoriale.
- [`METIER_doc-types.md`](METIER_doc-types.md) — fournit les règles côté types de documents ; ce chantier-ci absorbe la migration de `correct_openalex_doc_type`.
- [`METIER_metadata-deduplication.md`](METIER_metadata-deduplication.md) — bénéficiaire : les règles de dedup matchent désormais sur le canonique corrigé.
- [`CODE_normalizers-pub-meta-drift.md`](CODE_normalizers-pub-meta-drift.md) — chantier voisin : le dead code `correct_openalex_doc_type` est un symptôme d'une dérive plus large où `insert_*_document` recalcule les champs au lieu de consommer `pub_meta`.
