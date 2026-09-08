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

La barre de progression est un objet d'affichage, distinct du journal. Elle s'écrit sur le terminal, s'efface, et ne laisse rien derrière elle. Le journal garde ce qui se relit après coup : le début d'une phase, son bilan, les anomalies.

La barre paraît seulement en terminal interactif, sous condition de `sys.stdout.isatty()`. Sans terminal — conteneur détaché, intégration continue, sortie redirigée —, le code écrit des lignes de journal espacées. Le fichier de journal et la sortie JSON ne reçoivent aucun retour chariot.

Le bilan d'une phase reste dans le journal. La barre montre l'avancement ; le bilan dit ce que la phase a produit.

## Phasage

### 1. Socle d'affichage

- [ ] Choisir l'outil. La phase `extract` lance cinq à six sources dans un `ThreadPoolExecutor` (`infrastructure/parallel.py`), soit autant de barres simultanées. `rich` porte plusieurs tâches dans un objet unique redessiné sous verrou ; `tqdm` demande de fixer la position de chaque barre et de poser un verrou entre threads ; une barre maison suppose de piloter le curseur du terminal.
- [ ] Router les messages de journal par l'objet d'affichage tant qu'une barre est ouverte : une écriture directe sur la sortie casse le rendu.
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
- `rich` et `tqdm` sont des dépendances de production, le pipeline tournant en conteneur. Le projet compte ses dépendances : laquelle accepter, ou faut-il écrire la barre ?
