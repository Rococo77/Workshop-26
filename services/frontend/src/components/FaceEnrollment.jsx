import { useState } from "react";
import { enrollFace } from "../api.js";
import PoseCapture, { POSES } from "./PoseCapture.jsx";

// Enrôlement unique du pool de référence (5 poses), préalable à tout
// virement ou connexion. Parcours de rattrapage pour un compte créé sans
// pool complet ; le consentement a déjà été donné à l'inscription.
export default function FaceEnrollment({ token, onEnrolled, onFailure }) {
  const [images, setImages] = useState({});
  const [step, setStep] = useState(0);
  const [retryKey, setRetryKey] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const submitAll = async (allImages) => {
    setBusy(true);
    setError(null);
    try {
      await enrollFace(token, allImages);
      onEnrolled();
    } catch (err) {
      if (err.code === "already_enrolled") return onEnrolled();
      setError(err.message);
      if (err.pose) {
        const idx = POSES.findIndex((p) => p.key === err.pose);
        setStep(idx >= 0 ? idx : 0);
      } else {
        setImages({});
        setStep(0);
      }
      setRetryKey((n) => n + 1);
      if (!err.code) onFailure(err);
    } finally {
      setBusy(false);
    }
  };

  const onPhoto = (poseKey, image) => {
    const next = { ...images, [poseKey]: image };
    setImages(next);
    if (Object.keys(next).length === POSES.length) {
      submitAll(next);
    } else {
      setStep((s) => s + 1);
    }
  };

  return (
    <section aria-labelledby="enroll-title" className="rounded-2xl border border-rule bg-white p-6">
      <h2 id="enroll-title" className="text-lg font-semibold">
        Activez la validation par visage
      </h2>
      <p className="mt-2 text-sm text-ink/70">
        Chaque virement et chaque connexion seront confirmés par une photo de votre visage. 5 photos
        sous différents angles sont nécessaires : les photos ne sont pas conservées, seules des
        empreintes numériques calculées à partir d&apos;elles sont enregistrées.
      </p>
      <div className="mt-5">
        <PoseCapture step={step} retryKey={retryKey} busy={busy} onPhoto={onPhoto} />
      </div>
      <div aria-live="polite">
        {error && <p className="mt-4 rounded-xl bg-debit/10 px-4 py-3 text-sm text-debit">{error}</p>}
      </div>
    </section>
  );
}
