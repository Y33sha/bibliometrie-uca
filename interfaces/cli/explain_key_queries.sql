-- EXPLAIN ANALYZE sur les requêtes clés du backend
-- Usage: psql -U lalecoz -d bibliometrie -f scripts/explain_key_queries.sql

\echo '=== 1. Liste publications (page principale) ==='
EXPLAIN ANALYZE
SELECT p.id, p.title, p.pub_year, p.doc_type::text, p.doi, p.oa_status::text,
       j.title AS journal_title
FROM publications p
LEFT JOIN journals j ON j.id = p.journal_id
WHERE EXISTS (
    SELECT 1 FROM authorships a WHERE a.publication_id = p.id AND a.is_uca = TRUE
)
ORDER BY p.pub_year DESC, p.id DESC
LIMIT 50 OFFSET 0;

\echo ''
\echo '=== 2. Facettes publications (filtre par labo) ==='
EXPLAIN ANALYZE
SELECT s.id, COALESCE(s.acronym, s.name) AS label, COUNT(DISTINCT a.publication_id) AS count
FROM authorships a
JOIN publications p ON p.id = a.publication_id
CROSS JOIN LATERAL unnest(a.structure_ids) AS struct_id
JOIN structures s ON s.id = struct_id
WHERE a.is_uca = TRUE AND s.structure_type = 'laboratory'
GROUP BY s.id, s.acronym, s.name
ORDER BY count DESC;

\echo ''
\echo '=== 3. Annuaire personnes ==='
EXPLAIN ANALYZE
SELECT p.id, p.last_name, p.first_name,
       (SELECT COUNT(*) FROM authorships a WHERE a.person_id = p.id) AS pub_count
FROM persons p
LEFT JOIN persons_rh prh ON prh.person_id = p.id
WHERE p.rejected = FALSE
  AND EXISTS (SELECT 1 FROM persons_rh prh2 WHERE prh2.person_id = p.id)
ORDER BY p.last_name_normalized, p.first_name_normalized
LIMIT 50 OFFSET 0;

\echo ''
\echo '=== 4. Statistiques par année ==='
EXPLAIN ANALYZE
SELECT p.pub_year, p.doc_type::text,
       COUNT(DISTINCT p.id) AS count
FROM publications p
JOIN authorships a ON a.publication_id = p.id
WHERE a.is_uca = TRUE
GROUP BY p.pub_year, p.doc_type
ORDER BY p.pub_year;

\echo ''
\echo '=== 5. find_by_doi (pipeline, après index) ==='
EXPLAIN ANALYZE
SELECT id, doc_type, title_normalized
FROM publications
WHERE lower(doi) = lower('10.1000/test.example')
LIMIT 1;
