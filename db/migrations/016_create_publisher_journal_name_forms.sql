-- Formes de noms pour les éditeurs et les journaux.
-- Permettent de mapper plusieurs variantes (ex. "Elsevier BV", "ELSEVIER SCI LTD")
-- vers une même entité canonique.

CREATE TABLE IF NOT EXISTS publisher_name_forms (
    id              SERIAL PRIMARY KEY,
    publisher_id    INTEGER NOT NULL REFERENCES publishers(id) ON DELETE CASCADE,
    form_normalized TEXT NOT NULL,
    created_at      TIMESTAMPTZ DEFAULT now(),
    UNIQUE (form_normalized)
);

CREATE INDEX IF NOT EXISTS idx_pub_nf_publisher ON publisher_name_forms (publisher_id);

CREATE TABLE IF NOT EXISTS journal_name_forms (
    id              SERIAL PRIMARY KEY,
    journal_id      INTEGER NOT NULL REFERENCES journals(id) ON DELETE CASCADE,
    form_normalized TEXT NOT NULL,
    publisher_id    INTEGER REFERENCES publishers(id),
    created_at      TIMESTAMPTZ DEFAULT now(),
    UNIQUE (form_normalized, publisher_id)
);

CREATE INDEX IF NOT EXISTS idx_jnl_nf_journal ON journal_name_forms (journal_id);
