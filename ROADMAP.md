# Roadmap transmission DSI

2. Robustesse en production

* [ ] Le processus de détection des publications disparues — sans ça, la base accumule des fantômes.

3. Pérennité des données

* L'archivage des raw JSON (json.gz par document) — ça sécurise à la fois l'auditabilité et la future purge du bloat. C'est le prérequis pour toute optimisation de taille.

* Les 388k doublons de position WoS — c'est de la dette de données qui grossit à chaque run.

