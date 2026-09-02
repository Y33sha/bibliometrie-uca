#!/usr/bin/env bash
# Versions de Python et de Node portées par les images de production.
#
# Le Dockerfile épingle ses images par empreinte, ce qui l'oblige à en écrire la version en clair : il fait donc autorité, et rien d'autre n'a à la redéclarer. L'intégration continue y lit les interpréteurs qu'elle installe, et le contrôle d'avant envoi y confronte les fichiers de version du poste.
#
# Écrit deux lignes `clé=valeur`, telles que `$GITHUB_OUTPUT` les attend.
set -euo pipefail

racine=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
dockerfile="$racine/Dockerfile"

python=$(sed -n 's|^FROM python:\([0-9][0-9.]*\)-.*|\1|p' "$dockerfile" | head -1)
node=$(sed -n 's|^FROM node:\([0-9][0-9.]*\)-.*|\1|p' "$dockerfile" | head -1)

for langage in python node; do
    if [ -z "${!langage}" ]; then
        echo "Aucune image de base $langage lue dans $dockerfile." >&2
        exit 1
    fi
done

echo "python=$python"
echo "node=$node"
