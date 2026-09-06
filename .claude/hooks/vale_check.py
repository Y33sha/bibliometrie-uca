import json, pathlib, re, subprocess, sys

# 2 : le rapport part vers Claude, qui corrige tout de suite.
# 1 : le rapport ne s'affiche que pour toi, Claude n'est pas interrompu.
CODE_SORTIE = 2

data = json.load(sys.stdin)
payload = data.get("tool_input") or data.get("inputs") or {}
path = payload.get("file_path", "")

if not path or pathlib.Path(path).suffix not in {".py", ".md"}:
    sys.exit(0)

# `.claude/` porte la configuration de l'outillage, pas la documentation du projet.
if ".claude" in pathlib.Path(path).parts:
    sys.exit(0)


def lignes_modifiees(chemin: str) -> set[int] | None:
    """Numéros de ligne que le fichier a gagnés ou changés depuis `HEAD`.

    Rend `None` quand tout le fichier est à considérer : fichier hors du suivi git, ou dépôt
    inaccessible.
    """
    suivi = subprocess.run(
        ["git", "ls-files", "--error-unmatch", chemin], capture_output=True, text=True
    )
    if suivi.returncode != 0:
        return None
    diff = subprocess.run(
        ["git", "diff", "HEAD", "--unified=0", "--", chemin], capture_output=True, text=True
    )
    if diff.returncode != 0:
        return None
    lignes: set[int] = set()
    for entete in re.finditer(r"^@@ -\S+ \+(\d+)(?:,(\d+))? @@", diff.stdout, re.MULTILINE):
        debut = int(entete.group(1))
        longueur = int(entete.group(2) or 1)
        lignes.update(range(debut, debut + longueur))
    return lignes


rapport = subprocess.run(["vale", "--output=JSON", path], capture_output=True, text=True)
try:
    alertes = [a for fichier in json.loads(rapport.stdout).values() for a in fichier]
except (json.JSONDecodeError, AttributeError):
    sys.exit(0)

modifiees = lignes_modifiees(path)
if modifiees is not None:
    alertes = [a for a in alertes if a.get("Line") in modifiees]

if alertes:
    lignes_rapport = "\n".join(
        f"{path}:{a['Line']}:{a['Span'][0]}:{a['Check']}:{a['Message']}" for a in alertes
    )
    print(
        "Style de doc à corriger (voir la skill doc-style) :\n" + lignes_rapport[:8000],
        file=sys.stderr,
    )
    sys.exit(CODE_SORTIE)
sys.exit(0)
