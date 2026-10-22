-- ============================================================================
--  Mode dégradé : pendant une remédiation, un virement validé (visage OK)
--  passe en file d'attente (`queued`) au lieu d'être réglé. Les fonds ne
--  bougent qu'au rejeu, après la reprise prouvée : aucun paiement perdu si
--  l'API redémarre pendant l'incident.
--  Idempotent : rejouable sur une base existante sans `down -v` :
--    docker exec -i ra-postgres psql -U payuser -d paymentdb \
--      < services/payment-api/db/init/08_degraded_mode.sql
-- ============================================================================

ALTER TABLE payment_tx DROP CONSTRAINT IF EXISTS payment_tx_status_check;
ALTER TABLE payment_tx ADD CONSTRAINT payment_tx_status_check
    CHECK (status IN ('pending', 'queued', 'settled', 'rejected'));
ALTER TABLE payment_tx ADD COLUMN IF NOT EXISTS queued_at TIMESTAMPTZ;

-- Une seule ligne : état de la plateforme, piloté par le moteur de remédiation.
CREATE TABLE IF NOT EXISTS platform_mode (
    id       SMALLINT    PRIMARY KEY CHECK (id = 1),
    degraded BOOLEAN     NOT NULL DEFAULT FALSE,
    since    TIMESTAMPTZ
);
INSERT INTO platform_mode (id) VALUES (1) ON CONFLICT (id) DO NOTHING;
