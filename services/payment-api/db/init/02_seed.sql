-- ============================================================================
--  Jeu de données minimal. Hash bcrypt générés par pgcrypto (crypt + gen_salt),
--  vérifiables par bcrypt côté service -> aucun hash en dur dans le dépôt.
--
--  Comptes « clients » (customer) : AUCUN n'est semé ici. Un client s'inscrit
--  lui-même (POST /api/auth/register, mot de passe + visage) ; voir
--  docs/runbook.md.
--
--  Comptes d'exploitation (démo, à documenter dans le runbook, pas en prod) :
--    admin    / Admin#2026
--    operator / Operator#2026
--
--  Comptes canari (_canary_src / _canary_dst) : verrouillés (`locked`),
--  mot de passe aléatoire jamais révélé -> connexion impossible. Utilisés
--  uniquement par /internal/canary (remediation-engine), jamais par un
--  humain. Retrouvés par nom d'utilisateur (service.canary_route), pas par
--  id ; sur une base existante, voir 06_canary_accounts.sql.
-- ============================================================================

INSERT INTO app_user (username, password_hash, role, locked) VALUES
    ('_canary_src', crypt(gen_random_uuid()::text, gen_salt('bf')), 'customer', TRUE),
    ('_canary_dst', crypt(gen_random_uuid()::text, gen_salt('bf')), 'customer', TRUE)
ON CONFLICT (username) DO NOTHING;

INSERT INTO app_user (username, password_hash, role) VALUES
    ('admin',    crypt('Admin#2026',    gen_salt('bf')), 'admin'),
    ('operator', crypt('Operator#2026', gen_salt('bf')), 'operator')
ON CONFLICT (username) DO NOTHING;

INSERT INTO account (owner_id, iban_fake, balance, currency)
SELECT u.id, v.iban, v.bal, 'EUR'
FROM (VALUES
    ('_canary_src', 'FR76-FAKE-0001', 1000.00),
    ('_canary_dst', 'FR76-FAKE-0002', 1000.00)
) AS v(uname, iban, bal)
JOIN app_user u ON u.username = v.uname
ON CONFLICT (iban_fake) DO NOTHING;
