# Chantier — Pagination par curseur

## Contexte

Les listes se paginent par `page` et `per_page`, que l'adapter traduit en `OFFSET`. Le coût d'une page tient au produit du rang par la taille de page : la base produit toutes les lignes précédentes et les jette. Un middleware refuse donc une lecture dont le décalage dépasse `max_pagination_offset`, fixé à 500 000 (`interfaces/api/app.py`).

Le tri par clé remplace « saute N lignes » par « rends ce qui suit cette ligne ». Avec un index sur la clé de tri, la base se positionne directement : une page profonde coûte ce que coûte la première, et il n'y a plus de croissance à borner. La méthode garantit en outre qu'aucune ligne stable n'est sautée ni répétée pendant le parcours, là où `OFFSET` décale tout dès qu'une ligne s'insère avant la position courante.

Le plafond des exports CSV, `MAX_EXPORT_ROWS` dans `infrastructure/read_models/publications/list.py`, porte le même nombre mais relève d'une autre cause : la mémoire. Un export sans filtre pèse 59 Mo pour 61 877 publications, et le processus en porte cinq de front au maximum. Les deux plafonds sont indépendants — la garde du middleware ne se déclenche que sur la présence d'un paramètre `page`, que la route d'export ne porte pas.

## Décisions

- **Le plafond reste en place tant qu'il ne gêne pas.** La bascule se fera le jour où un ensemble servi approchera les 500 000 lignes, ou lorsque la mémoire des exports deviendra contraignante. Cette fiche existe pour ce jour-là.
- **Tranches successives plutôt que curseur serveur.** Un `DECLARE ... CURSOR` impose de tenir une transaction ouverte du début à la fin de l'envoi, ce qui empêche PostgreSQL de récupérer les lignes mortes pendant toute la durée — coûteux sur une base que le pipeline réécrit en masse. Des requêtes courtes et successives (« les N lignes après cette clé ») prennent une connexion, la rendent, et ne laissent rien ouvert entre deux.
- **L'export perd l'instantané cohérent, et c'est accepté.** Une publication ajoutée pendant le parcours peut apparaître, une supprimée manquer. Le pipeline tourne la nuit et les exports se font en journée : le recouvrement est rare et sans conséquence. La garantie qui compte — aucun doublon ni saut à l'intérieur d'un même export — est celle que le tri par clé apporte.
- **Chaque ordre de tri exige une clé totale et son index.** Trier par année seule ne départage pas deux publications de la même année : la clé associe la colonne de tri et l'identifiant, et l'index porte sur les deux. La liste des publications propose dix ordres — année, titre, frais de publication, soutenance, inscription, chacun dans les deux sens.

## Phasage

### Phase 1 — Périmètre et contrat

- [ ] Recenser les listes paginées et leur volume réel, pour distinguer celles qui peuvent croître de celles qui resteront courtes (périmètres, éditeurs).
- [ ] Trancher si toutes basculent ou seulement les grandes. Faire cohabiter deux mécanismes de pagination dans la même API a un coût de lisibilité ; convertir des listes de quelques dizaines de lignes en a un autre.
- [ ] Arrêter la forme du curseur dans le contrat d'API : paramètre porté, opacité de la valeur, forme de la réponse (`next`, `previous`).

### Phase 2 — Interface

- [ ] `Pagination.svelte` affiche les numéros de page et « Page 3/412 » : le curseur ne les permet plus. Décider ce qui les remplace — « suivant » et « précédent » seuls, ou un défilement continu.
- [ ] Décider du sort du compte total, que les listes affichent et qu'un curseur ne fournit pas. Un `COUNT` séparé reste possible, au prix d'une seconde requête.

### Phase 3 — Lecture par clé

- [ ] Ajouter les index composites (colonne de tri, identifiant) pour chaque ordre retenu.
- [ ] Écrire la lecture par clé dans les modèles de lecture, ordre par ordre.
- [ ] Retirer le middleware de plafonnement du décalage, et le réglage `max_pagination_offset` qui l'alimente.

### Phase 4 — Exports en flux

- [ ] Faire parcourir l'ensemble par tranches à l'export, et envoyer chaque tranche au fur et à mesure.
- [ ] Tenir la connexion pendant l'envoi du corps : FastAPI la referme à la fin de la dépendance, avant que le flux ne s'écoule.
- [ ] Reprendre le plafond d'exports simultanés : il borne aujourd'hui la mémoire, il bornera les places du pool de connexions qu'un téléchargement lent retient.
- [ ] Décider du sort de `MAX_EXPORT_ROWS`, que la mémoire ne justifie plus une fois l'export en flux.

## Questions ouvertes

- Un export en flux ne peut plus signaler une erreur survenue en cours de route : l'en-tête et le statut 200 sont déjà partis, et le client reçoit un fichier tronqué qui a l'air complet. Reste à décider comment le lui dire — une ligne finale attendue, ou rien.
- Le reverse-proxy de l'hébergement peut porter un délai d'expiration de réponse qu'un export long dépasserait. À vérifier au déploiement.
