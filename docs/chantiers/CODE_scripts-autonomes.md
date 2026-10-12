# Chantier — Scripts en ligne de commande autonomes

## Contexte

`interfaces/cli/` contient les scripts lancés à la main : `imports/` (fichiers externes), `maintenance/` (opérations rejouables), `oneshot/` (scripts joués une fois, conservés comme trace, 33 au 2026-10-12).

Une partie de leur code est dispersée dans les couches : des services, des ports et des read models n'ont pas d'autre utilisateur qu'un script. Exemple : le rapport de cohérence du ROR, dont le service (`application/services/structures/ror.py`), le port de lecture et son implémentation ne servent qu'à `maintenance/report_ror_coherence.py`.

## Décisions

- **Un script est autonome au maximum** : ses requêtes et sa logique sont dans son module. Il importe le domaine, les modules techniques de l'infrastructure et le pipeline, pas un service ou un port créé pour lui seul. Modèle : `maintenance/enrich_publishers.py`.

## Phasage

### Phase 1 — Inventaire

- [x] Recenser les services, ports et read models qu'un script est seul à utiliser.
  - `maintenance/report_ror_coherence.py` : service `structures/ror.py`, port `RorCoherenceQueries`, read model `read_models/ror.py`.
  - `imports/import_persons.py` : service `import_rh_person` ; méthodes `find_rh_person_duplicate` et `insert_rh_record` du repository des personnes.
  - `maintenance/import_authenticated_orcids.py` : service `authenticate_orcids` ; méthodes `begin_authenticated_orcid_import`, `authenticate_orcid`, `find_identifier_holders` et `map_rh_emails_to_person_ids` du repository des personnes.
  - `oneshot/propagate_identifier_decisions.py` : méthode `hal_account_peers` du repository des personnes.

### Phase 2 — Rapatriement

- [x] Rapport de cohérence du ROR dans `maintenance/report_ror_coherence.py`.
- [ ] Import RH dans `imports/import_persons.py`.
- [ ] Import des ORCID authentifiés dans `maintenance/import_authenticated_orcids.py`.

### Phase 3 — Oneshot

- [ ] Trier les scripts `oneshot/` déjà joués.

## Questions ouvertes

- Scripts `imports/` et `maintenance/` : nœuds manuels du pipeline, ou outils à part ?
