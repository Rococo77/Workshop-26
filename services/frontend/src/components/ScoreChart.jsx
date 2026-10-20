// Score d'anomalie du modèle sur les dernières minutes, seuil de décision à 0,5.
// La partie de courbe au-dessus du seuil change de couleur : c'est là que le
// modèle déclare l'anomalie.
const W = 600;
const H = 150;
const PAD = 8;
const THRESHOLD = 0.5;

const y = (score) => PAD + (1 - score) * (H - 2 * PAD);

export default function ScoreChart({ samples }) {
  const step = samples.length > 1 ? W / (samples.length - 1) : W;
  const points = samples.map((s, i) => `${(i * step).toFixed(1)},${y(s.score).toFixed(1)}`).join(" ");
  const yT = y(THRESHOLD);

  return (
    <div>
      {/* preserveAspectRatio="none" : la courbe occupe toute la largeur ;
          non-scaling-stroke garde un trait net malgré l'étirement. */}
      <svg
        viewBox={`0 0 ${W} ${H}`}
        preserveAspectRatio="none"
        className="h-40 w-full"
        role="img"
        aria-label="Évolution du score d'anomalie"
      >
        <defs>
          <clipPath id="above">
            <rect x="0" y="0" width={W} height={yT} />
          </clipPath>
          <clipPath id="below">
            <rect x="0" y={yT} width={W} height={H - yT} />
          </clipPath>
        </defs>
        <line
          x1="0"
          x2={W}
          y1={yT}
          y2={yT}
          className="stroke-debit/50"
          strokeDasharray="6 5"
          vectorEffect="non-scaling-stroke"
        />
        {samples.length > 1 &&
          [
            ["stroke-petrol", "url(#below)"],
            ["stroke-debit", "url(#above)"],
          ].map(([color, clip]) => (
            <polyline
              key={color}
              points={points}
              fill="none"
              strokeWidth="2.5"
              className={color}
              clipPath={clip}
              vectorEffect="non-scaling-stroke"
            />
          ))}
      </svg>
      {/* Légende hors du tracé : elle ne masque jamais la courbe. */}
      <p className="mt-2 flex items-center gap-2 text-[13px] text-ink/60">
        <span className="inline-block w-6 border-t-2 border-dashed border-debit/60" aria-hidden="true" />
        Seuil d&apos;anomalie (0,50) : au-dessus, le modèle déclare une anomalie
      </p>
    </div>
  );
}
