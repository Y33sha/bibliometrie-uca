-- Table des paiements APC (source: enquête nationale)
CREATE TABLE IF NOT EXISTS apc_payments (
    id SERIAL PRIMARY KEY,
    lab_name TEXT,
    publisher_name TEXT,
    publisher_type TEXT,
    journal_name TEXT,
    issn TEXT,
    journal_type TEXT,
    doi TEXT,
    article_title TEXT,
    amount_eur_ht NUMERIC(12,2),
    billing_year SMALLINT,
    pub_year SMALLINT,
    budget TEXT,
    institution TEXT,
    institution_type TEXT,
    coman_id INT,
    all_surveys_answered TEXT,
    shared_payment TEXT,
    source_file TEXT,
    expense_type TEXT,
    remarks TEXT,
    -- FK mappées après import
    publication_id INT REFERENCES publications(id) ON DELETE SET NULL,
    journal_id INT REFERENCES journals(id) ON DELETE SET NULL,
    publisher_id INT REFERENCES publishers(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_apc_doi ON apc_payments (LOWER(doi)) WHERE doi IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_apc_pub ON apc_payments (publication_id) WHERE publication_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_apc_institution ON apc_payments (institution);
CREATE INDEX IF NOT EXISTS idx_apc_billing_year ON apc_payments (billing_year);
