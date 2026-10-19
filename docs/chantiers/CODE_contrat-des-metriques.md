# Chantier — Contrat des métriques de phase

## Contexte

Chaque nœud rend un `PhaseMetrics`. Ses compteurs propres vont dans `extras`, un dictionnaire de chaînes vers entiers. Ses indicateurs d'observabilité vont dans `details`, lu selon les conventions `summary` et `table`.

Une clé s'écrit en plusieurs endroits, sans définition commune :

- l'étape qui compte (`metrics.add(journals_merged=1)`) ;
- `LIBELLES_EXTRAS` (`pipeline/runtime/observability/metrics.py`), pour le journal ;
- l'assemblage de la phase, par exemple `_TABLE` dans `publishers_journals.py` ;
- `PHASE_VIEWS` (`routes/admin/pipeline/phase-views.ts`), pour les clés de `details`.

Les lectures passent par `extras.get(clé, 0)` : une faute de frappe dans une clé donne zéro, sans erreur. L'interface relit les clés des runs enregistrés dans `pipeline_phase_executions`.

## Décisions

- Les compteurs propres d'un nœud sont déclarés une fois, avec leur libellé.

## Phasage

### Phase 1 — Déclaration des compteurs

- [ ] Forme de la déclaration : énumération de clés et libellés, ou compteurs typés par nœud.
- [ ] `LIBELLES_EXTRAS` et les assemblages des phases lisent la déclaration.
- [ ] Test : toute clé comptée est déclarée.

### Phase 2 — Indicateurs de `details`

- [ ] Clés de `summary` et de `table` déclarées par phase.
- [ ] Concordance avec `PHASE_VIEWS` : types générés pour le frontend, ou test.

### Phase 3 — Documentation

- [ ] Mise à jour de `docs/exploitation`.

## Questions ouvertes

- Lecture des runs enregistrés quand une clé change de nom.
