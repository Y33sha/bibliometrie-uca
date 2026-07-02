"""Génère le graphe illustratif de réconciliation des publications.

Nœuds = source_publications anonymes ; arêtes pleines = clés de confirmation
partagées ; pointillé = rattachement à une publication. Trois cas remarquables :
coupe DOI (2 DOI ≠ → 2 publications), fusion (2 publications reliées par une clé
→ collision → 1 seule), sans suite (composante orpheline hors-périmètre → aucune
publication).

Régénérer l'image (Graphviz requis) :

    python3 docs/img/graphs/reconciliation.py
    neato -Tpng docs/img/graphs/reconciliation.dot -o docs/img/graphs/reconciliation.png
"""

import os
import random

random.seed(11)

SP = "#dfe8f7"
SP_EDGE = "#8aa0c8"
PUB = "#7ea2e8"
KEY = "#9aa0a8"
ATTACH = "#b9c6de"
CUT = "#c0392b"
FUSE = "#2e8b57"

_n = [0]
L = []


def sp(orphan: bool = False) -> str:
    _n[0] += 1
    name = f"S{_n[0]}"
    fill, col = ("#f0d9d5", CUT) if orphan else (SP, SP_EDGE)
    L.append(f'  {name} [fillcolor="{fill}", color="{col}"];')
    return name


def cluster(size: int) -> list[str]:
    nodes = [sp() for _ in range(size)]
    for i in range(1, len(nodes)):
        L.append(f"  {nodes[i]} -- {nodes[random.randint(0, i - 1)]};")
    for _ in range(max(0, size - 3)):
        a, b = random.sample(nodes, 2)
        L.append(f"  {a} -- {b};")
    return nodes


def publication(name: str) -> None:
    L.append(
        f'  {name} [shape=box, style="filled,rounded", fillcolor="{PUB}", color="#4f74c4", '
        f'width=0.85, height=0.4, fixedsize=false, fontname="Helvetica", fontsize=11, '
        f'label="publication"];'
    )


def attach(nodes: list[str], p: str) -> None:
    for s in nodes:
        L.append(f'  {s} -- {p} [color="{ATTACH}", style=dotted, penwidth=0.8];')


# ── composantes ordinaires : petit paquet -> une publication ──
for name, size in [("Pa", 2), ("Pb", 3), ("Pc", 2), ("Pd", 4), ("Pe", 1)]:
    nodes = cluster(size)
    publication(name)
    attach(nodes, name)

# ── coupe DOI : deux paquets reliés par titre+année, DOI distincts -> 2 publis ──
c1, c2 = cluster(3), cluster(2)
publication("Pcut1")
publication("Pcut2")
attach(c1, "Pcut1")
attach(c2, "Pcut2")
L.append(
    f'  {c1[0]} -- {c2[0]} [color="{CUT}", style=dashed, penwidth=1.5, fontname="Helvetica", '
    f'fontsize=9, fontcolor="{CUT}", label="DOI différent\\n(coupée)"];'
)

# ── fusion : deux publications reliées par une clé -> collision -> 1 seule ──
f1, f2 = cluster(2), cluster(3)
publication("Pf1")
publication("Pf2")
attach(f1, "Pf1")
attach(f2, "Pf2")
L.append(
    f'  {f1[0]} -- {f2[0]} [color="{FUSE}", penwidth=1.8, fontname="Helvetica", fontsize=10, '
    f'fontcolor="{FUSE}", label="fusion\\n(1 seule conservée)"];'
)
# Arête invisible : rapproche les deux publications fusionnées dans le layout.
L.append("  Pf1 -- Pf2 [style=invis, len=1.0];")

# ── sans suite : losange orphelin (incomplet) hors-périmètre, aucune publication ──
o_t, o_l, o_r, o_b = sp(True), sp(True), sp(True), sp(True)
# Losange volontairement incomplet (arête o_b–o_r en moins) pour éviter l'effet trop régulier.
for a, b in [(o_t, o_l), (o_t, o_r), (o_b, o_l)]:
    L.append(f'  {a} -- {b} [color="{KEY}"];')
L.append(f'  {o_t} -- {o_b} [color="{KEY}", penwidth=1.3];')  # arête partagée, nœuds distants
L.append(
    f'  VOID [shape=plaintext, fontname="Helvetica", fontsize=10, fontcolor="{CUT}", '
    f'label="sans suite\\n(hors périmètre)"];'
)
L.append(f'  {o_r} -- VOID [style=dotted, color="{CUT}"];')

dot = (
    "graph reconciliation {\n"
    '  layout=neato; overlap=false; splines=true; sep="+14"; bgcolor="transparent";\n'
    "  outputorder=edgesfirst;\n"
    '  node [label="", shape=circle, style=filled, width=0.17, penwidth=0.8, fixedsize=true];\n'
    f'  edge [color="{KEY}", penwidth=0.7];\n' + "\n".join(L) + "\n}\n"
)

with open(os.path.join(os.path.dirname(__file__), "reconciliation.dot"), "w") as f:
    f.write(dot)
