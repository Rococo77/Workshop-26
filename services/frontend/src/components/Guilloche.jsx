// Motif guilloché (lignes ondulées entrelacées des billets et chèques) :
// l'impression anti-contrefaçon comme signature visuelle de la plateforme.
// Généré une fois, purement décoratif (aria-hidden).

const W = 400;
const H = 250;

function wave(i, count) {
  const phase = (i / count) * Math.PI * 2;
  const pts = [];
  for (let x = 0; x <= W; x += 4) {
    const y =
      H / 2 +
      58 * Math.sin(x / 46 + phase) +
      22 * Math.sin(x / 15 - phase * 2) +
      (i - count / 2) * 2.2;
    pts.push(`${x},${y.toFixed(1)}`);
  }
  return `M${pts.join(" L")}`;
}

const PATHS = Array.from({ length: 28 }, (_, i) => wave(i, 28));

export default function Guilloche({ className = "" }) {
  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      preserveAspectRatio="none"
      className={className}
      aria-hidden="true"
    >
      {PATHS.map((d, i) => (
        <path key={i} d={d} fill="none" stroke="currentColor" strokeWidth="0.6" />
      ))}
    </svg>
  );
}
