import { useState } from "react";
import { enrollFace } from "../api.js";
import FaceCapture from "./FaceCapture.jsx";

// Enrôlement unique du visage de référence, préalable à tout virement.
export default function FaceEnrollment({ token, onEnrolled, onFailure }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [attempt, setAttempt] = useState(0);

  const submit = async (image) => {
    setBusy(true);
    setError(null);
    try {
      await enrollFace(token, image);
      onEnrolled();
    } catch (err) {
      if (err.code === "already_enrolled") return onEnrolled();
      setError(err.message);
      setAttempt((n) => n + 1); // remonte la capture : retour à la caméra
      if (!err.code) onFailure(err);
    } finally {
      setBusy(false);
    }
  };

  return (
    <section aria-labelledby="enroll-title" className="rounded-2xl border border-rule bg-white p-6">
      <h2 id="enroll-title" className="text-lg font-semibold">
        Activez la validation par visage
      </h2>
      <p className="mt-2 text-sm text-ink/70">
        Chaque virement sera confirmé par une photo de votre visage. La photo n&apos;est pas conservée : seule
        une empreinte numérique calculée à partir d&apos;elle est enregistrée.
      </p>
      <div className="mt-5">
        <FaceCapture key={attempt} busy={busy} submitLabel="Enregistrer mon visage" onSubmit={submit} />
      </div>
      <div aria-live="polite">
        {error && <p className="mt-4 rounded-xl bg-debit/10 px-4 py-3 text-sm text-debit">{error}</p>}
      </div>
    </section>
  );
}
