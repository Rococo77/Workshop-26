-- ============================================================================
--  Auto-inscription + connexion mot de passe + visage.
--  Idempotent : rejouable sur une base existante sans `down -v` :
--    docker exec -i ra-postgres psql -U payuser -d paymentdb \
--      < services/payment-api/db/init/04_auth_self_service.sql
--
--  `face_verification_log.purpose` doit désormais aussi accepter 'login'
--  (vérification faciale au moment de la connexion, en plus de
--  l'enrôlement et de la confirmation de virement).
-- ============================================================================

ALTER TABLE face_verification_log
    DROP CONSTRAINT IF EXISTS face_verification_log_purpose_check;

ALTER TABLE face_verification_log
    ADD CONSTRAINT face_verification_log_purpose_check
    CHECK (purpose IN ('enroll', 'confirm', 'login'));
