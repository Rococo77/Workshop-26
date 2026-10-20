import { useEffect, useRef, useState } from "react";

// Photo envoyée à l'API : 480 px max en JPEG (~30-60 Ko en base64), sous la
// limite de corps de requête du WAF et suffisant pour la reconnaissance.
const MAX_SIDE = 480;
const QUALITY = 0.85;

// getUserMedia n'existe qu'en contexte sécurisé (HTTPS ou localhost). Ailleurs
// (ex. http://192.168.137.1:8080), repli sur un champ fichier : sur mobile, il
// ouvre directement la caméra frontale.
const hasCamera = () => window.isSecureContext && Boolean(navigator.mediaDevices?.getUserMedia);

function toJpeg(source, width, height) {
  const scale = Math.min(1, MAX_SIDE / Math.max(width, height));
  const canvas = document.createElement("canvas");
  canvas.width = Math.round(width * scale);
  canvas.height = Math.round(height * scale);
  canvas.getContext("2d").drawImage(source, 0, 0, canvas.width, canvas.height);
  return canvas.toDataURL("image/jpeg", QUALITY);
}

export default function FaceCapture({ busy, submitLabel, onSubmit, onCancel }) {
  const [camera] = useState(hasCamera);
  const videoRef = useRef(null);
  const [stream, setStream] = useState(null);
  const [photo, setPhoto] = useState(null);
  const [cameraError, setCameraError] = useState(null);

  // Caméra allumée uniquement pendant la prise de vue, coupée dès la photo prise.
  useEffect(() => {
    if (!camera || photo) return undefined;
    let active = true;
    let current = null;
    navigator.mediaDevices
      .getUserMedia({ video: { facingMode: "user", width: { ideal: 640 } }, audio: false })
      .then((s) => {
        if (!active) return s.getTracks().forEach((t) => t.stop());
        current = s;
        setStream(s);
      })
      .catch(() => {
        if (active) setCameraError("Accès à la caméra refusé. Autorisez-le, ou importez une photo.");
      });
    return () => {
      active = false;
      current?.getTracks().forEach((t) => t.stop());
      setStream(null);
    };
  }, [camera, photo]);

  useEffect(() => {
    if (videoRef.current && stream) videoRef.current.srcObject = stream;
  }, [stream]);

  const snap = () => {
    const v = videoRef.current;
    if (v?.videoWidth) setPhoto(toJpeg(v, v.videoWidth, v.videoHeight));
  };

  const pickFile = async (e) => {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    try {
      const bitmap = await createImageBitmap(file);
      setPhoto(toJpeg(bitmap, bitmap.width, bitmap.height));
      bitmap.close();
    } catch {
      setCameraError("Format d'image non pris en charge. Utilisez une photo JPEG ou PNG.");
    }
  };

  const fileInput = (label, className) => (
    <label className={className}>
      {label}
      <input type="file" accept="image/jpeg,image/png" capture="user" className="sr-only" onChange={pickFile} />
    </label>
  );

  const secondary =
    "cursor-pointer rounded-xl border border-rule px-4 py-3 text-center font-medium text-ink/80 hover:border-petrol hover:text-petrol";
  const primary =
    "w-full rounded-xl bg-petrol px-4 py-3 font-semibold text-white hover:bg-petrol-deep disabled:cursor-not-allowed disabled:opacity-40";

  return (
    <div className="space-y-3">
      <div className="relative aspect-[4/3] overflow-hidden rounded-xl bg-petrol-deep">
        {photo ? (
          <img src={photo} alt="Votre photo" className="h-full w-full object-cover" />
        ) : camera && !cameraError ? (
          <>
            {/* Miroir à l'affichage seulement (geste naturel) ; la photo n'est pas inversée. */}
            <video ref={videoRef} autoPlay playsInline muted className="h-full w-full -scale-x-100 object-cover" />
            <div
              aria-hidden="true"
              className="pointer-events-none absolute left-1/2 top-1/2 h-[70%] w-[42%] -translate-x-1/2 -translate-y-1/2 rounded-[50%] border-2 border-white/70"
            />
          </>
        ) : (
          <div className="flex h-full items-center justify-center p-6 text-center text-sm text-white/80">
            {cameraError ||
              "La caméra du navigateur exige une connexion sécurisée. Prenez ou importez une photo de votre visage."}
          </div>
        )}
      </div>

      {photo ? (
        <div className="space-y-2">
          {/* Envoi sans le préfixe data URL (filtré par le WAF), voir api.js. */}
          <button type="button" disabled={busy} onClick={() => onSubmit(photo.split(",")[1])} className={primary}>
            {busy ? "Vérification…" : submitLabel}
          </button>
          <button type="button" disabled={busy} onClick={() => setPhoto(null)} className={`w-full ${secondary}`}>
            Reprendre la photo
          </button>
        </div>
      ) : camera && !cameraError ? (
        <div className="space-y-2">
          <button type="button" disabled={!stream} onClick={snap} className={primary}>
            Prendre la photo
          </button>
          {fileInput("Importer une photo", `block ${secondary}`)}
        </div>
      ) : (
        fileInput("Prendre ou importer une photo", `block ${secondary}`)
      )}

      {onCancel && (
        <button
          type="button"
          disabled={busy}
          onClick={onCancel}
          className="w-full text-sm font-medium text-ink/60 hover:text-debit hover:underline"
        >
          Annuler
        </button>
      )}
    </div>
  );
}
