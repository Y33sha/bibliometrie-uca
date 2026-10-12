# Chantier — Scripts en ligne de commande autonomes

## Contexte

`interfaces/cli/` contient les scripts lancés à la main : `imports/` (fichiers externes), `maintenance/` (opérations rejouables), `oneshot/` (scripts joués une fois, conservés comme trace, 33 au 2026-10-12).

Une partie de leur code est dispersée dans les couches : des services, des ports et des read models n'ont pas d'autre utilisateur qu'un script. Exemple : le rapport de cohérence du ROR, dont le service (`application/services/structures/ror.py`), le port de lecture et son implémentation ne servent qu'à `maintenance/report_ror_coherence.py`.

## Décisions

- **Un script est autonome au maximum** : ses requêtes et sa logique sont dans son module. Il importe le domaine, les modules techniques de l'infrastructure et le pipeline, pas un service ou un port créé pour lui seul. Modèle : `maintenance/enrich_publishers.py`.

## Phasage

### Phase 1 — Inventaire

- [ ] Recenser les services, ports et read models qu'un script est seul à utiliser.

### Phase 2 — Rapatriement

- [ ] Rapport de cohérence du ROR dans `maintenance/report_ror_coherence.py`.
- [ ] Les autres cas de l'inventaire.

### Phase 3 — Oneshot

- [ ] Trier les scripts `oneshot/` déjà joués.

## Questions ouvertes

- Scripts `imports/` et `maintenance/` : nœuds manuels du pipeline, ou outils à part ?
