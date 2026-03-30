# Plan de rationalisation du pipeline — Bibliométrie UCA

## Problèmes résolus

- **1.1 Personnes et authorships** : person_id unifié sur les authorships sources (3 sources), script de création source-agnostique (6 passes), propagation UCA intégrée dans `build_authorships.py`.
- **1.2.1 Pays des publications** : propagation automatique en background après modification d'adresse. Script batch `refresh_publication_countries.sql` recalcule depuis les adresses (pas le staging OA).
- **1.2.2 Formes de noms** : déjà géré par `merge_persons.py` (array_replace + dedup).
- **Orchestrateur** : `run_pipeline.py` avec `--from`, `--only`, `--dry-run`, `--mode`.
- **Scripts morts** : archivés dans `archive/`.

---

## À faire

### Audit trail des fusions de personnes

Les fusions ne laissent aucune trace. Quand une fusion est mauvaise, il faut deviner quelles authorships ré-attribuer.

**Solution retenue** :
- Table `person_merge_log` légère (source_id, target_id, noms, raison, date, auteur)
- Depuis la page personne : consulter l'historique des fusions, bouton « annuler » qui recrée la personne source (avec son nom) mais ne touche pas aux authorships
- Réattribution des publications manuellement via la page admin/authorships — la réattribution met à jour les `person_id` des authorships (sources + vérité)
- Les `person_name_forms` sont reconstruites à partir des authorships réattribuées (pas besoin de les stocker dans le log)

### Page admin/authorships

Page listant les authorships sources avec filtres : par publication, par personne, par labo, par source, orphelines (`person_id IS NULL`).
- Permet de réattribuer manuellement une authorship à une personne (résolution des cas ambigus : même nom, plusieurs personnes)
- Permet de retrouver les authorships détachées après correction manuelle
- Sert aussi à la dé-fusion (réattribution des authorships après annulation d'une fusion)

### Automatisation

#### Mode weekly
- Extraction année en cours + n-1 uniquement
- Pas de cross-imports ni d'enrichissements
- Pas de `merge_lab_duplicates.py` (interactif)

#### Mode monthly
- Pipeline complet + cross-imports + enrichissements
- Nettoyage des orphelins (personnes sans authorships, publications sans sources)

#### Programmation cron
- Weekly : dimanche soir
- Monthly : 1er du mois
- Notification par email en cas d'erreur
