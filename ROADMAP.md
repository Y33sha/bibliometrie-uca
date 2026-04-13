# Roadmap transmission DSI

Taches prioritaires pour rendre le code transmissible et institution-agnostique.

## 1. Supprimer les valeurs hardcodees UCA

**Impact : bloquant pour reutilisation**

- [ ] Remplacer `budget_structure_id = 169` (~20 occurrences dans publications.py et pub_stats.py) par une lecture de la config ou du perimetre racine
- [ ] Remplacer les fallbacks `s.code = 'uca'` dans uca_perimeter.py par une config
- [ ] Auditer les `IN ('hal', 'openalex', 'wos')` (11 occurrences) : remplacer par constante Python selon le contexte

## ~~2. Renommer uca_perimeter → perimeter~~ FAIT

Fichier renomme, alias supprimes, 8 fichiers appelants mis a jour.

## 3. Programmation cron du pipeline

**Impact : operationnel en prod**

- [ ] Documenter la configuration cron pour les modes daily/weekly/monthly
- [ ] Ou fournir un exemple de crontab / systemd timer

## ~~4. Tests d'idempotence des phases restantes~~ FAIT

Toutes les phases sont couvertes (8 classes dans test_idempotence.py).

## 5. Semantique publications → documents (optionnel)

**Impact : coherence du vocabulaire metier**

- [ ] Decider si le renommage est justifie
- [ ] Si oui : table, colonnes FK, routes API, frontend, docs
- [ ] A faire avant transmission (apres = personne ne le fera)
