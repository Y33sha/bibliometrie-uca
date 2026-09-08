# Chantier — Journal du pipeline

## Contexte

Le pipeline écrit 351 lignes de journal réparties sur ses phases. Elles servent deux usages opposés : suivre un run en cours dans un terminal, et relire un run passé. Le suivi demande peu de lignes qui bougent ; la relecture demande une trace complète et archivable.

La sortie part sur la console, et sur un fichier quand `LOG_TO_FILE` l'active. Le format est JSON par défaut, texte quand `LOG_FORMAT=text` (`infrastructure/observability/log.py`). En production, le pipeline tourne en conteneur détaché, sans terminal.

Quatre défauts se cumulent.

Le vocabulaire suppose le schéma connu. Les messages nomment les tables par leur identifiant technique — `authorships`, `source_publications`, `staging`, `halIds`. Une personne qui découvre l'application ne sait pas ce que chaque phase produit.

Les conventions divergent. Certaines sous-étapes portent un numéro, d'autres non. Un même objet se nomme de plusieurs façons selon le module.

Le volume vient de lignes répétées. Une phase qui traite par lots écrit une ligne par lot.

Des traces de mise au point subsistent. `application/pipeline/timings.py` écrit une ligne par document dépassant un demi-seconde, avec le détail par étape.

## Décisions

- **Sans terminal, le code écrit des lignes de journal espacées**, sous condition de `sys.stdout.isatty()`. Une barre écrite sans terminal encombrerait la sortie capturée de retours chariot.
- **L'affichage passe par `tqdm`** : 1 paquet, 356 Ko, contre 4 paquets et 7,1 Mo pour `rich`. Les barres concurrentes demandent en contrepartie de fixer leur position et de poser un verrou entre threads.
- **`tqdm` est une dépendance de développement**, importée sous `try` : son absence conduit au même repli que l'absence de terminal, et l'image de production n'embarque rien. `deptry` signale un tel import par la règle `DEP004`, à déclarer dans `per_rule_ignores`.
- **Les jalons d'avancement partent au journal en mode non interactif.** Un run long en conteneur se suit alors dans les logs.
- **Les jalons suivent un intervalle de temps**, 30 secondes, et portent le débit. Un pas exprimé en éléments traités espace ses lignes quand le traitement ralentit, au moment où l'avancement intéresse le plus.

## Phasage

### 1. Socle d'affichage

- [ ] Fixer la position de chaque barre et poser `tqdm.set_lock()`. La phase `extract` lance cinq à six sources dans un `ThreadPoolExecutor` (`infrastructure/parallel.py`), soit autant de barres simultanées.
- [ ] Router les messages de journal par `tqdm.write()` tant qu'une barre est ouverte : une écriture directe sur la sortie casse le rendu.
- [ ] Écrire l'objet de progression : ouverture avec un total, avancement, fermeture. Sans terminal, il n'écrit rien.
- [ ] Poser le repli des runs non interactifs : une ligne de journal par tranche d'avancement.
- [ ] Tester les deux modes, terminal et sortie capturée, dont le cas de plusieurs barres concurrentes.

### 2. Remplacement des lignes répétées

Barres simultanées, une par source, sous `ThreadPoolExecutor` :

- [ ] `extract/extract_hal.py` — une ligne par page
- [ ] `extract/extract_openalex.py` — une ligne par page
- [ ] `extract/extract_wos.py` — une ligne par page
- [ ] `extract/extract_scanr.py` — toutes les 500 notices
- [ ] `extract/extract_theses.py` — toutes les 1000 notices
- [ ] `fetch_missing/doi.py` — tous les 100 DOI
- [ ] `fetch_missing/hal.py` — une ligne par lot

Barre unique :

- [ ] `extract/fetch_truncated.py` — une ligne par lot
- [ ] `extract/fetch_stale.py` — une ligne par lot
- [ ] `normalize/base.py` — une ligne par lot, pour chaque source à son tour
- [x] `affiliations/resolve_addresses.py` — une ligne par lot
- [ ] `persons/cascade.py` — deux boucles, toutes les 5000 signatures
- [ ] `publications/reconcile_components.py` — toutes les 5000 publications
- [ ] `subjects/ingestion.py` — toutes les 2000 publications sources
- [ ] `oa_status/phase.py` — tous les 50 DOI

Puis :

- [ ] Retirer le détail par document lent de `application/pipeline/timings.py`. La durée totale et le nombre de documents traités restent au bilan.

### 3. Vocabulaire

- [ ] Établir le lexique : un mot par notion, en langue courante, pour les objets que le journal nomme — document moissonné, publication, signature, personne, structure.
- [ ] Réécrire les messages de chaque phase avec ce lexique.
- [ ] Dire ce que chaque phase produit à son ouverture, en une ligne lisible sans connaître le schéma.

### 4. Conventions

- [ ] Trancher la numérotation des sous-étapes : partout ou nulle part.
- [ ] Uniformiser la forme du début de phase, de la fin de phase et du bilan.
- [ ] Vérifier que toutes les phases s'y tiennent.

## Questions ouvertes

- Le mode texte et le mode JSON portent-ils le même contenu ?
- Les bilans de phase passent par des tables d'observabilité (`metrics.details["table"]`). Leur rendu entre-t-il dans ce chantier ?
- Un niveau de détail réglable est-il utile, ou le partage entre terminal et journal suffit-il ?
