-- ============================================================================
--  Comptes canari dédiés (_canary_src / _canary_dst) sur une base EXISTANTE.
--  Le seed 02 les crée sur une base neuve ; ce script couvre les volumes
--  pgdata créés avant (où les ids 1/2 appartiennent déjà à d'autres clients).
--  Idempotent : rejouable sans `down -v` :
--    docker exec -i ra-postgres psql -U payuser -d paymentdb \
--      < services/payment-api/db/init/06_canary_accounts.sql
--
--  Utilisateurs verrouillés, mot de passe aléatoire jamais révélé : connexion
--  impossible, usage réservé à /internal/canary (payment-api).
-- ============================================================================

INSERT INTO app_user (username, password_hash, role, locked) VALUES
    ('_canary_src', crypt(gen_random_uuid()::text, gen_salt('bf')), 'customer', TRUE),
    ('_canary_dst', crypt(gen_random_uuid()::text, gen_salt('bf')), 'customer', TRUE)
ON CONFLICT (username) DO NOTHING;

-- Un compte par utilisateur canari, seulement s'il n'en a pas déjà un (base
-- neuve : créé par le seed 02). IBAN propres pour ne pas heurter ceux des
-- clients d'une ancienne base (FR76-FAKE-0001/0002).
INSERT INTO account (owner_id, iban_fake, balance, currency)
SELECT u.id, v.iban, 1000.00, 'EUR'
FROM (VALUES
    ('_canary_src', 'FR76-FAKE-CANARY-SRC'),
    ('_canary_dst', 'FR76-FAKE-CANARY-DST')
) AS v(uname, iban)
JOIN app_user u ON u.username = v.uname
WHERE NOT EXISTS (SELECT 1 FROM account a WHERE a.owner_id = u.id)
ON CONFLICT (iban_fake) DO NOTHING;
