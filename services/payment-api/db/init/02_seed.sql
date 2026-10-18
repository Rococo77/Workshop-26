-- ============================================================================
--  Jeu de données fictif. Hash bcrypt générés par pgcrypto (crypt + gen_salt),
--  vérifiables par passlib côté service -> aucun hash en dur dans le dépôt.
--  Mots de passe de démonstration (à documenter dans le runbook, pas en prod) :
--    admin    / Admin#2026
--    operator / Operator#2026
--    alice    / Alice#2026
--    bob      / Bob#2026
-- ============================================================================

INSERT INTO app_user (username, password_hash, role) VALUES
    ('admin',    crypt('Admin#2026',    gen_salt('bf')), 'admin'),
    ('operator', crypt('Operator#2026', gen_salt('bf')), 'operator'),
    ('alice',    crypt('Alice#2026',    gen_salt('bf')), 'customer'),
    ('bob',      crypt('Bob#2026',      gen_salt('bf')), 'customer')
ON CONFLICT (username) DO NOTHING;

INSERT INTO account (owner_id, iban_fake, balance, currency)
SELECT u.id, v.iban, v.bal, 'EUR'
FROM (VALUES
    ('alice', 'FR76-FAKE-0001', 5000.00),
    ('bob',   'FR76-FAKE-0002', 3000.00)
) AS v(uname, iban, bal)
JOIN app_user u ON u.username = v.uname
ON CONFLICT (iban_fake) DO NOTHING;
