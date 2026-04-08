# scripts à lancer
merge_versioned_doi_duplicates.py

backfiller le staging HAL (sous-types, authQuality_s) par des appels API: le script n'existe pas encore

rerun wos normalize pour insérer roles (attention: le filtre role != author a sauté; vérifier d'abord s'il est pertinent de conserver les non auteurs)


# points à résoudre
enum roles?
thèses en cours dans scanr: clé d'alignement?

* [ ] cache pour améliorer la perf?
* [ ] dumps automatisés sur le cloud (Backblaze B2 + rclone + GPG)
* [ ] imports quotidiens (mode rapide, seulement nouveaux docts)