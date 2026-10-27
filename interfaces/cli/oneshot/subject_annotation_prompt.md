Tu qualifies la pertinence de sujets OpenAlex attribués à des publications scientifiques. Tes verdicts servent à entraîner un classifieur.

Fichier d'entrée : {input}
Lis-le en entier avec l'outil Read. C'est une liste de publications : `title`, `abstract` (peut être null), `serial` (revue, peut être null), `year`, et `labels`. Chaque libellé OpenAlex contient `id`, `level` (domain, field, subfield, topic, du plus large au plus fin), `label` et `parent` (libellé du niveau au-dessus).

Verdicts :
- `pertinent` : la publication relève de ce domain ou de ce field, ou traite ce subfield ou ce topic ;
- `aberrant` : le libellé est sans rapport avec le contenu (mauvaise discipline, rapprochement lexical trompeur) ;
- `limite` : rapport secondaire ou tangentiel, ou information insuffisante pour trancher (titre seul et ambigu).

Règles :
- Juge d'après le titre, le résumé et la revue seulement, avec tes connaissances générales des disciplines. Pas de recherche web, pas d'accès à d'autres fichiers.
- Un libellé est inclus dans son parent. Juge de haut en bas : domains, puis fields, subfields, topics. Un libellé dont un ancêtre est aberrant est aberrant, même si son intitulé semble convenir. Un libellé pertinent rend ses ancêtres pertinents.
- Les quatre domains OpenAlex : Health Sciences ; Life Sciences ; Physical Sciences, avec l'ingénierie, l'informatique, les mathématiques, la chimie et les sciences de la Terre ; Social Sciences, avec les arts, les humanités, le droit, l'économie et la psychologie.
- Un libellé pertinent décrit ce que fait la publication, pas un mot qu'elle contient. Un topic plausible laisse son field aberrant si la publication relève d'une autre discipline.

Sortie : écris avec l'outil Write le fichier {output}, un objet JSON `{{"<id du libellé>": {{"v": "pertinent" | "aberrant" | "limite", "r": "<raison en français, 15 mots au plus ; chaîne vide si le verdict pertinent est évident>"}}}}`. Chaque id du fichier d'entrée y figure une seule fois. Vérifie ensuite, avec un court script lancé par `{python}`, que le JSON est valide et que tous les ids sont couverts.

Réponse finale : le nombre de libellés par verdict et la confirmation de couverture complète.
