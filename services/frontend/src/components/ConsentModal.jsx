import { useState } from "react";

// Pop-up obligatoire avant toute capture de visage à l'inscription : le
// consentement est tracé côté API (app_user.biometric_consent_at). La
// suppression automatique après 2 ans d'inactivité n'est pas implémentée
// dans ce démonstrateur (limite documentée, docs/architecture.md §3.1).
export default function ConsentModal({ onAccept, onDecline }) {
  const [checked, setChecked] = useState(false);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-ink/50 p-4">
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="consent-title"
        className="w-full max-w-md rounded-2xl bg-white p-6 shadow-xl"
      >
        <h2 id="consent-title" className="text-lg font-semibold">
          Vos données biométriques
        </h2>
        <p className="mt-3 text-sm text-ink/70">
          Pour sécuriser votre connexion et vos virements, nous enregistrons une empreinte numérique
          calculée à partir de plusieurs photos de votre visage — jamais les photos elles-mêmes. Ces
          données seront supprimées automatiquement 2 ans après votre dernière utilisation du service.
        </p>
        <label className="mt-4 flex items-start gap-2 text-sm text-ink/80">
          <input
            type="checkbox"
            className="mt-1"
            checked={checked}
            onChange={(e) => setChecked(e.target.checked)}
          />
          J&apos;ai lu et j&apos;accepte l&apos;enregistrement de mon empreinte faciale.
        </label>
        <div className="mt-5 flex gap-3">
          <button
            type="button"
            disabled={!checked}
            onClick={onAccept}
            className="flex-1 rounded-xl bg-petrol px-4 py-3 font-semibold text-white hover:bg-petrol-deep disabled:cursor-not-allowed disabled:opacity-40"
          >
            Continuer
          </button>
          <button
            type="button"
            onClick={onDecline}
            className="flex-1 rounded-xl border border-rule px-4 py-3 font-medium text-ink/80 hover:border-petrol hover:text-petrol"
          >
            Annuler
          </button>
        </div>
      </div>
    </div>
  );
}
