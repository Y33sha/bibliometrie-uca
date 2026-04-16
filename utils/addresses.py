"""Utilitaire de gestion des adresses.

Utilisé par les scripts de normalisation pour créer les adresses
et les liens source_authorship_addresses au moment de l'INSERT
des source_authorships.
"""

from utils.normalize import normalize_text


# Cache module-level pour éviter les lookups répétés dans un même run
_addr_cache: dict[str, int] = {}


def clear_cache():
    """Vide le cache d'adresses (à appeler en fin de run)."""
    _addr_cache.clear()


def _get_or_create_address(cur, text: str) -> int | None:
    """Crée ou retrouve une adresse. Retourne l'id."""
    addr_id = _addr_cache.get(text)
    if addr_id is not None:
        return addr_id

    norm = normalize_text(text)
    cur.execute("""
        INSERT INTO addresses (raw_text, normalized_text)
        VALUES (%s, %s)
        ON CONFLICT (md5(raw_text)) DO NOTHING
        RETURNING id
    """, (text, norm))
    row = cur.fetchone()
    if row:
        addr_id = row[0] if isinstance(row, tuple) else row["id"]
    else:
        cur.execute("SELECT id FROM addresses WHERE md5(raw_text) = md5(%s)", (text,))
        row = cur.fetchone()
        addr_id = row[0] if row else None

    if addr_id:
        _addr_cache[text] = addr_id
    return addr_id


def link_addresses(cur, authorship_id: int, addr_texts: list[str],
                   countries: list[str] | None = None) -> int:
    """Crée les adresses et les liens pour une authorship.

    addr_texts : liste de textes d'adresses individuels (déjà splittés).
    countries : codes pays à propager sur les adresses créées (optionnel,
                utilisé par ScanR qui fournit les pays détectés).

    Retourne le nombre de liens créés.
    """
    if not addr_texts:
        return 0

    links = 0
    for text in addr_texts:
        text = text.strip()
        if not text:
            continue

        addr_id = _get_or_create_address(cur, text)
        if not addr_id:
            continue

        # Propager les pays si fournis et pas encore renseignés
        if countries:
            cur.execute("""
                UPDATE addresses SET countries = %s
                WHERE id = %s AND countries IS NULL
            """, (countries, addr_id))

        cur.execute("""
            INSERT INTO source_authorship_addresses (source_authorship_id, address_id)
            VALUES (%s, %s)
            ON CONFLICT (source_authorship_id, address_id) DO NOTHING
        """, (authorship_id, addr_id))
        links += 1

    return links
