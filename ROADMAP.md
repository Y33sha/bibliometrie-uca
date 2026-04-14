# Roadmap transmission DSI

Taches prioritaires pour rendre le code transmissible et institution-agnostique.

## 1. Programmation cron du pipeline

**Impact : operationnel en prod**

- [ ] Documenter la configuration cron pour les modes daily/weekly/monthly
- [ ] Ou fournir un exemple de crontab / systemd timer

## 2. Semantique publications → documents (optionnel)

**Impact : coherence du vocabulaire metier**

- [ ] Decider si le renommage est justifie
- [ ] Si oui : table, colonnes FK, routes API, frontend, docs
