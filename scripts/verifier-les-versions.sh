#!/usr/bin/env bash
# Concordance des versions de langage entre le poste et les images de production.
#
# Trois déclarations doivent s'accorder : le Dockerfile, qui fait autorité ; `.python-version`, où `uv` prend l'interpréteur des contrôles locaux ; `interfaces/frontend/.nvmrc`, que `nvm use` lit sans argument. Aucun des deux fichiers ne peut dériver du Dockerfile — `nvm` attend une version en clair et `FROM` un littéral épinglé par empreinte — d'où ce rapprochement.
#
# La comparaison est exacte : les fichiers de version portent la précision du Dockerfile, qui s'arrête à la version mineure, le correctif venant de l'empreinte.
#
# S'y ajoute la version de Node du terminal, sous laquelle jouent les contrôles du frontend. Une version antérieure fait échouer l'environnement de test au chargement d'`undici`, sur une trace sans rapport apparent avec la cause : le refus vient donc d'abord, et la nomme.
set -euo pipefail

racine=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
eval "$("$racine/scripts/versions-des-images.sh")"

ecarts=()

confronter_fichier() {
    local chemin=$1 attendue=$2 lue
    lue=$(tr -d '[:space:]' <"$racine/$chemin")
    [ "$lue" = "$attendue" ] ||
        ecarts+=("$chemin porte $lue, les images de production $attendue.")
}

confronter_fichier .python-version "$python"
confronter_fichier interfaces/frontend/.nvmrc "$node"

courante=$(node --version | sed 's/^v//;s/\..*//')
[ "$courante" = "$node" ] ||
    ecarts+=("Node $courante dans ce terminal, $node attendu par interfaces/frontend/.nvmrc. Jouer: nvm use")

if [ ${#ecarts[@]} -gt 0 ]; then
    printf '%s\n' "${ecarts[@]}" >&2
    exit 1
fi
