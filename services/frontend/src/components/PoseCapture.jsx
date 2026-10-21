import FaceCapture from "./FaceCapture.jsx";

// Ordre de capture du pool biométrique (voir payment-api/app/face.py::REQUIRED_POSES).
// Plusieurs angles par client -> reconnaissance ultérieure plus tolérante :
// une seule photo prise au login/virement est comparée aux 5, la plus
// proche suffit.
export const POSES = [
  { key: "right", label: "Tournez légèrement la tête vers la DROITE" },
  { key: "up", label: "Levez légèrement le menton (regardez en HAUT)" },
  { key: "down", label: "Baissez légèrement le menton (regardez en BAS)" },
  { key: "left", label: "Tournez légèrement la tête vers la GAUCHE" },
  { key: "face", label: "Regardez bien en FACE, pour finir" },
];

// Étape contrôlée par le parent (qui possède les photos déjà prises et
// décide, en cas d'échec API sur une pose précise, de ne faire reprendre
// que celle-là plutôt que tout le pool).
export default function PoseCapture({ step, retryKey = 0, busy, onPhoto, onCancel }) {
  const pose = POSES[step];
  return (
    <div className="space-y-3">
      <p className="text-sm font-medium text-ink/80">
        Photo {step + 1}/{POSES.length} — {pose.label}
      </p>
      <FaceCapture
        key={`${pose.key}-${retryKey}`}
        busy={busy}
        submitLabel={step + 1 < POSES.length ? "Photo suivante" : "Terminer"}
        onSubmit={(image) => onPhoto(pose.key, image)}
        onCancel={onCancel}
      />
    </div>
  );
}
