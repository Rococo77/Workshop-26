-- ============================================================================
--  Pool biométrique multi-poses + consentement RGPD.
--  Idempotent : rejouable sur une base existante sans `down -v` :
--    docker exec -i ra-postgres psql -U payuser -d paymentdb \
--      < services/payment-api/db/init/05_biometric_pool.sql
--
--  Avant : une empreinte unique par client (`face_enrollment.user_id` PK).
--  Après : un POOL de 5 empreintes par client (une par pose : droite, haut,
--  bas, gauche, face), capturées à l'inscription -> reconnaissance ultérieure
--  plus tolérante (une seule photo prise au login/virement est comparée aux
--  5, la plus proche suffit). Démonstrateur sans donnée de prod à préserver :
--  la table est reconstruite sous sa nouvelle forme si elle ne l'est pas déjà
--  (les clients existants devront se réenrôler, voir docs/runbook.md).
-- ============================================================================

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'face_enrollment' AND column_name = 'pose'
    ) THEN
        RETURN; -- déjà migré
    END IF;
    DROP TABLE IF EXISTS face_enrollment;
END $$;

CREATE TABLE IF NOT EXISTS face_enrollment (
    user_id    BIGINT             NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
    pose       TEXT               NOT NULL CHECK (pose IN ('face', 'left', 'right', 'up', 'down')),
    model_name TEXT               NOT NULL,
    embedding  DOUBLE PRECISION[] NOT NULL CHECK (cardinality(embedding) > 0),
    created_at TIMESTAMPTZ        NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, pose)
);

-- Date de consentement explicite à la biométrie (RGPD art. 9). La purge
-- automatique après 2 ans d'inactivité n'est PAS implémentée dans ce
-- démonstrateur (voir docs/architecture.md §3.1) : seule la date est tracée.
ALTER TABLE app_user ADD COLUMN IF NOT EXISTS biometric_consent_at TIMESTAMPTZ;
