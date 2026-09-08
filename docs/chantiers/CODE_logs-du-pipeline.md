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

- **La barre porte l'avancement, le journal garde le bilan.** La barre s'écrit sur le terminal et s'efface. Un bilan qu'elle porterait disparaîtrait avec elle.
- **Sans terminal, le code écrit des lignes de journal espacées**, sous condition de `sys.stdout.isatty()`. Une barre écrite sans terminal encombrerait la sortie capturée de retours chariot.
- **L'affichage passe par `tqdm`** : 1 paquet, 356 Ko, contre 4 paquets et 7,1 Mo pour `rich`. Les barres concurrentes demandent en contrepartie de fixer leur position et de poser un verrou entre threads.
- **`tqdm` est une dépendance de développement**, importée sous `try` : son absence conduit au même repli que l'absence de terminal, et l'image de production n'embarque rien. `deptry` signale un tel import par la règle `DEP004`, à déclarer dans `per_rule_ignores`.

## Phasage

### 1. Socle d'affichage

- [ ] Fixer la position de chaque barre et poser `tqdm.set_lock()`. La phase `extract` lance cinq à six sources dans un `ThreadPoolExecutor` (`infrastructure/parallel.py`), soit autant de barres simultanées.
- [ ] Router les messages de journal par `tqdm.write()` tant qu'une barre est ouverte : une écriture directe sur la sortie casse le rendu.
- [ ] Écrire l'objet de progression : ouverture avec un total, avancement, fermeture. Sans terminal, il n'écrit rien.
- [ ] Poser le repli des runs non interactifs : une ligne de journal par tranche d'avancement.
- [ ] Tester les deux modes, terminal et sortie capturée, dont le cas de plusieurs barres concurrentes.

### 2. Remplacement des lignes répétées

- [ ] Recenser les boucles qui écrivent une ligne par lot ou par document.
- [ ] Les remplacer par la barre, en gardant le bilan de fin.
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
