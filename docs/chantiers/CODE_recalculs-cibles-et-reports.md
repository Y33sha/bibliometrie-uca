# Chantier — Recalculs ciblés et reports au run suivant

## Contexte

L'API déclenche sept recalculs du pipeline après une édition. Ils sont exportés par `pipeline/public.py` :

- clôture des périmètres, après l'édition d'un périmètre, d'une structure ou d'une tutelle ;
- `in_perimeter` des signatures, après la revue d'une adresse ;
- `in_perimeter` des publications, après l'exclusion d'une personne ;
- construction des authorships, à l'attribution de signatures orphelines ;
- pays des notices et des publications d'un lot d'adresses ;
- requalification des publications d'une revue, et fusion de revues ;
- `pub_count` d'un éditeur fusionné.

Le pipeline reporte aussi des traitements au run suivant. `pipeline/graph.py` déclare 39 lectures de données du run précédent (`previous_run`). D'autres données attendent le run suivant sans lecture à rebours : `fetch_missing` n'est pas récursif, donc un document rapatrié déclenche ses propres recherches au run suivant.

Les deux questions concernent ce qui attend le run suivant : une édition de l'administration pour les recalculs ciblés, une donnée produite plus loin dans le run pour les reports.

## Décisions

- Un recalcul ciblé se garde seulement s'il produit un effet immédiat attendu dans l'interface.

## Phasage

### Phase 1 — Inventaire

Voir l'[inventaire](CODE_recalculs-cibles-et-reports_inventaire.md).

- [x] Pour chaque recalcul ciblé : l'édition qui le déclenche, l'effet visible dans l'interface, le délai sans lui.
- [x] Pour chaque report : la donnée concernée, le retard qu'il introduit.
- [ ] Pour chaque report : le coût de sa suppression.

### Phase 2 — Décisions

- [ ] Garder ou retirer chaque recalcul ciblé.
- [ ] Garder ou supprimer chaque report.

### Phase 3 — Mise en œuvre

- [ ] Retirer les recalculs écartés, leur port et leur export dans `pipeline/public.py`.
- [ ] Supprimer les reports écartés, et mettre à jour leurs déclarations dans `pipeline/graph.py`.

## Questions ouvertes

- Une donnée laissée au run suivant : l'interface signale-t-elle qu'elle attend un recalcul ?
