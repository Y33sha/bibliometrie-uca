# Roadmap transmission DSI

2. Robustesse en production

* La version bac à sable pour retester le pipeline de novo — sans ça, impossible de valider que le seed + schema + migrations = base fonctionnelle. Personne ne reprendra un outil qu'il ne peut pas réinstaller.
* Le processus de détection des publications disparues — sans ça, la base accumule des fantômes.

3. Pérennité des données

* L'archivage des raw JSON (json.gz par document) — ça sécurise à la fois l'auditabilité et la future purge du bloat. C'est le prérequis pour toute optimisation de taille.

* Les 388k doublons de position WoS — c'est de la dette de données qui grossit à chaque run.

