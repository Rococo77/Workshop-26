-- ============================================================================
--  Honeytokens : comptes leurres que personne n'utilise. Leur seule
--  apparition (connexion, virement vers leur IBAN, présence dans une réponse
--  HTTP) prouve une fuite de la base -> alerte immédiate, sans modèle ML.
--  Idempotent : rejouable sur une base existante sans `down -v` :
--    docker exec -i ra-postgres psql -U payuser -d paymentdb \
--      < services/payment-api/db/init/07_honeytokens.sql
--
--  Noms crédibles (un attaquant qui lit app_user doit les trouver
--  intéressants), mot de passe aléatoire jamais révélé : la connexion est de
--  toute façon refusée par le service auth avant la vérification du mot de passe.
--  La liste des leurres vit dans une table à part : app_user ne les distingue pas.
-- ============================================================================

CREATE TABLE IF NOT EXISTS honeytoken (
    value TEXT PRIMARY KEY,
    kind  TEXT NOT NULL CHECK (kind IN ('username', 'iban'))
);

INSERT INTO app_user (username, password_hash, role) VALUES
    ('m.lefevre.dsi',     crypt(gen_random_uuid()::text, gen_salt('bf')), 'admin'),
    ('tresorerie.groupe', crypt(gen_random_uuid()::text, gen_salt('bf')), 'customer')
ON CONFLICT (username) DO NOTHING;

INSERT INTO account (owner_id, iban_fake, balance, currency)
SELECT u.id, 'FR76-FAKE-7341', 248000.00, 'EUR'
FROM app_user u
WHERE u.username = 'tresorerie.groupe'
ON CONFLICT (iban_fake) DO NOTHING;

INSERT INTO honeytoken (value, kind) VALUES
    ('m.lefevre.dsi',     'username'),
    ('tresorerie.groupe', 'username'),
    ('FR76-FAKE-7341',    'iban')
ON CONFLICT (value) DO NOTHING;
