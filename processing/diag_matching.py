#!/usr/bin/env python3
"""
Diagnostic : teste le matching sur quelques adresses connues.
Usage: python processing/diag_matching.py
"""

import os, sys, re, unicodedata

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from db.connection import get_connection


def normalize(text):
    if not text:
        return ""
    text = text.lower().strip()
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^a-z0-9\s]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def match_form(form_text, form_normalized, is_regex, text_norm):
    if is_regex:
        try:
            return bool(re.search(form_text, text_norm, re.IGNORECASE))
        except re.error:
            return False
    if not form_normalized:
        return False
    if len(form_normalized) <= 6:
        pattern = r"(?<![a-z0-9])" + re.escape(form_normalized) + r"(?![a-z0-9])"
        return bool(re.search(pattern, text_norm))
    return form_normalized in text_norm


conn = get_connection()
cur = conn.cursor()

# 1. Vérifier la structure UCA
print("=== 1. Structure UCA ===")
cur.execute("SELECT id, code, name, type::text FROM structures WHERE code = 'uca'")
row = cur.fetchone()
if row:
    print(f"  ID={row[0]}, code={row[1]}, name={row[2]}, type={row[3]}")
    uca_id = row[0]
else:
    print("  ⚠ STRUCTURE UCA INTROUVABLE !")
    cur.execute("SELECT id, code, name FROM structures WHERE type = 'universite'")
    for r in cur.fetchall():
        print(f"    → {r}")
    sys.exit(1)

# 2. Formes UCA
print("\n=== 2. Formes UCA ===")
cur.execute("""
    SELECT id, form_text, form_normalized, is_regex, requires_context_of
    FROM name_forms WHERE structure_id = %s AND is_active = TRUE
    ORDER BY id
""", (uca_id,))
uca_forms = cur.fetchall()
print(f"  {len(uca_forms)} formes actives")
for f in uca_forms[:5]:
    print(f"    id={f[0]}: text='{f[1]}' → norm='{f[2]}' regex={f[3]} ctx={f[4]}")
if len(uca_forms) > 5:
    print(f"    ... ({len(uca_forms) - 5} de plus)")

# 3. Test de normalisation
print("\n=== 3. Test normalisation ===")
test_texts = [
    "Université Clermont Auvergne",
    "Université Clermont Auvergne, CNRS, Institut Pascal, F-63000 Clermont-Ferrand",
]
for t in test_texts:
    norm = normalize(t)
    print(f"  '{t[:60]}...' → '{norm[:60]}...'")

# 4. Test matching sur une adresse connue UCA
print("\n=== 4. Test matching sur adresses ===")
cur.execute("""
    SELECT a.id, a.raw_text FROM addresses a
    WHERE a.raw_text ILIKE '%%Université Clermont Auvergne%%'
      AND EXISTS (
          SELECT 1 FROM address_structures ast
          WHERE ast.address_id = a.id AND ast.is_confirmed = TRUE
      )
    LIMIT 3
""")
test_addrs = cur.fetchall()
if not test_addrs:
    cur.execute("""
        SELECT id, raw_text FROM addresses
        WHERE raw_text ILIKE '%%Clermont Auvergne%%'
        LIMIT 3
    """)
    test_addrs = cur.fetchall()

cur.execute("""
    SELECT nf.id, nf.form_text, nf.form_normalized, nf.is_regex, nf.requires_context_of,
           nf.structure_id, s.code, s.type::text
    FROM name_forms nf
    JOIN structures s ON s.id = nf.structure_id
    WHERE nf.is_active = TRUE
    ORDER BY nf.id
""")
all_forms = cur.fetchall()

for addr_id, raw_text in test_addrs:
    text_norm = normalize(raw_text)
    print(f"\n  Adresse {addr_id}: '{raw_text[:80]}...'")
    print(f"  Normalisé: '{text_norm[:80]}...'")

    matches = []
    for f in all_forms:
        fid, ft, fn, ir, ctx, sid, scode, stype = f
        if match_form(ft, fn, ir, text_norm):
            matches.append((fid, ft, fn, ir, ctx, sid, scode, stype))

    if matches:
        print(f"  ✓ {len(matches)} formes matchent :")
        for m in matches:
            ctx_str = f" ctx={m[4]}" if m[4] else ""
            print(f"    form_id={m[0]} struct={m[6]}({m[7]}) text='{m[1]}'{ctx_str}")
    else:
        print(f"  ✗ AUCUNE FORME NE MATCHE !")

        # Essai manuel
        print(f"\n  Essai manuel pour 'universite clermont auvergne':")
        target = normalize("Université Clermont Auvergne")
        print(f"    Cible normalisée: '{target}'")
        print(f"    Présent dans texte: {target in text_norm}")

        # Vérifier char par char si proche
        if target not in text_norm:
            # Chercher un segment similaire
            idx = text_norm.find("universite")
            if idx >= 0:
                segment = text_norm[idx:idx+len(target)+10]
                print(f"    Segment trouvé: '{segment}'")
                print(f"    Attendu:        '{target}'")
                # Comparer byte par byte
                for i, (a, b) in enumerate(zip(segment, target)):
                    if a != b:
                        print(f"    Divergence à pos {i}: '{a}' ({ord(a)}) vs '{b}' ({ord(b)})")
                        break
            else:
                print(f"    'universite' introuvable dans le texte normalisé !")

# 5. Périmètre UCA
print("\n=== 5. Périmètre UCA ===")
cur.execute("""
    SELECT child_id FROM structure_relations
    WHERE parent_id = %s AND relation_type = 'est_tutelle_de'
""", (uca_id,))
tutelle_children = [r[0] for r in cur.fetchall()]
cur.execute("""
    SELECT child_id FROM structure_relations
    WHERE parent_id = %s AND relation_type = 'est_partenaire_de'
    UNION
    SELECT parent_id FROM structure_relations
    WHERE child_id = %s AND relation_type = 'est_partenaire_de'
""", (uca_id, uca_id))
partner_ids = [r[0] for r in cur.fetchall()]
total = 1 + len(tutelle_children) + len(partner_ids)
print(f"  UCA ({uca_id}) + {len(tutelle_children)} labos + {len(partner_ids)} partenaires = {total} structures")

conn.close()
print("\n=== Fin diagnostic ===")
