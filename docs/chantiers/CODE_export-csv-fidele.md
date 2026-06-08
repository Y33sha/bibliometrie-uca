# Chantier — Export CSV fidèle à l'affichage (+ nettoyage du whitespace des titres)

Issu de deux items TODO_LAURA sur l'export CSV des publications (« balises HTML → sauts de ligne », « filtre sources non pris en compte ») élargis en cours d'analyse : l'export doit **refléter exactement le tableau affiché** (filtres + colonnes + contenu des cellules).

## Contexte

L'export CSV (publications et thèses) diverge du tableau affiché sur trois plans :

- **Filtres partiels.** Le routeur `export_publications_csv` ([interfaces/api/routers/publications.py](../../interfaces/api/routers/publications.py)) ne déclare qu'un sous-ensemble des Query params de `list_publications` (manquent `access`, `has_apc`, `country`, `hal_status`, `in_perimeter`, `is_corresponding`, `subject_id`) — alors que le front les **envoie déjà** (`buildFilterParams` dans [PublicationsListView.svelte](../../interfaces/frontend/src/lib/components/PublicationsListView.svelte)). Et la query utilise `_build_export_clauses` (volontairement partiel : sa docstring note que `hal_status`/`in_perimeter` ne sont pas appliqués) au lieu du `_build_list_clauses` de la liste. Résultat : filtre sources (et d'autres) ignorés à l'export.
- **Colonnes fixes ≠ colonnes affichées.** Le CSV émet un jeu fixe (Année, Type, Titre, DOI, Revue, Éditeur, Laboratoires, Accès, Sources) sans tenir compte du menu de visibilité des colonnes (`useColumnVisibility`/`ColumnMenu`). Trompeur : on peut masquer une colonne à l'écran et la retrouver dans le CSV (et inversement).
- **Titre brut.** Le tableau affiche le titre **rendu/nettoyé** (`sanitizeTitle` + `{@html}`), mais le CSV écrit `row.title` brut → balises HTML littérales dans la cellule, et sauts de ligne pour les titres dont le markup source est indenté.

**Audit des titres en base** (read-only, prod-like) : 1025 / 66 882 titres (~1,5 %) contiennent `\n`/`\t` ; 902 avec balises HTML (indentation autour de `<i>`/`<mml:math>`), 123 sans balise (texte source retourné à la ligne). Tous sont des artefacts de mise en forme indésirables. Les balises HTML elles-mêmes sont **voulues** (rendu à l'écran) ; seul le whitespace est à normaliser.

## Décisions

*(Proposées, questionnables. Le Contexte est factuel ; Décisions / Phasage / Questions restent à valider.)*

1. **Synchro filtres.** L'export réutilise le **même `ListFilters` complet** que `list_publications` (routeur) et le **même `_build_list_clauses`** (query). Suppression de `_build_export_clauses` (partiel) une fois inutilisé. Idem vérifier la cohérence liste↔export côté thèses.
2. **Synchro colonnes.** Le front transmet la **liste des colonnes visibles** à l'endpoint d'export ; le backend n'émet que celles-ci, dans l'ordre d'affichage. (Mapping display↔CSV à arrêter — cf. Questions.)
3. **Titre dans le CSV : export-strip** (validé). On retire les balises HTML et on collapse le whitespace (`\n`/`\t`/espaces multiples → un espace, trim) au moment de l'écriture CSV → texte brut = ce qui s'affiche. Aucune donnée modifiée, pas de rerun.
4. **Whitespace des titres : collapser en amont, à la création des publications** (indésirable de toute façon, pas que pour le CSV ; les balises HTML restent). Backfill du **stock** via une **migration Alembic** (SQL pur, `regexp_replace` du whitespace → un espace + trim), pas un full rerun. Bénéficie aussi à l'affichage. **À-côté** à traiter plus tard dans le chantier (indépendant des phases 1-2 grâce à l'export-strip).

## Phasage

### Phase 1 — Export fidèle aux filtres + titre nettoyé
- [ ] Routeur export (publications) : ajouter les Query params manquants, construire le `ListFilters` identique à `list_publications`.
- [ ] Query export : `_build_export_clauses` → `_build_list_clauses(conn, filters, apc_structure_ids)` ; retirer `_build_export_clauses` si plus utilisé.
- [ ] Titre : strip HTML + collapse whitespace dans la cellule (publications + thèses).
- [ ] Vérifier/aligner l'export thèses (filtres liste↔export).

### Phase 2 — Colonnes du CSV = colonnes affichées
- [ ] Front : transmettre les colonnes visibles (clés `useColumnVisibility`) à l'endpoint d'export.
- [ ] Backend : émettre uniquement les colonnes demandées, dans l'ordre, avec le bon libellé/contenu par colonne.
- [ ] Mapping (décidé) : une colonne CSV par colonne d'affichage visible (Année↔year, Type↔type, Titre↔title, Revue↔journal, Labo(s)↔labs, Corresp.↔corr, APC↔apc, Accès↔oa, Voie OA↔oa_path, Statut HAL↔hal_status). **DOI + Sources** = contenu de la colonne « Liens » (colonne fixe) → **toujours présents**. **Éditeur** : présent dans le CSV **ssi « Revue » est visible**.

### Phase 3 — Nettoyage du whitespace des titres (données, à-côté)
- [ ] Localiser l'étape de création du titre canonique (normalize / `effective_metadata` / match_or_create) — à tracer, ne pas supposer.
- [ ] Y collapser le whitespace du titre (`\n`/`\t`/espaces multiples → un espace, trim) ; conserver les balises HTML.
- [ ] Migration Alembic (SQL pur) pour backfiller le stock (~1025 titres) sur la base de prod (par Laura).

## Questions ouvertes

- **Colonne « Éditeur » dans l'UI ?** À trancher plus tard (Laura) : ajouter une colonne « Éditeur » après « Revue » (masquée par défaut) + filtres correspondants. En attendant, l'Éditeur suit la visibilité de « Revue » dans le CSV.
- **Étape de normalisation du titre** (phase 3) : à tracer avant de coder (ne pas supposer).
- **Strip HTML pour le CSV** : strip regex simple vs lib dédiée — les titres contiennent du HTML/MathML restreint ; un strip de balises + dé-échappement d'entités + collapse d'espaces suffit probablement.
