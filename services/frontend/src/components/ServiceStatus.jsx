import { useEffect, useRef, useState } from "react";
import { getStatus } from "../api.js";

// État du service vu par le client : ce qu'une banque afficherait pendant un
// incident, sans exposer la mécanique interne (détection, remédiation...).
const FAILURE_WINDOW_MS = 15000; // une erreur récente du client = service perturbé
const RECOVERED_MS = 20000; // durée d'affichage de "service rétabli"

export function useServiceStatus(lastFailureAt) {
  const [healthy, setHealthy] = useState(true);
  const [now, setNow] = useState(() => Date.now());
  const [recoveredAt, setRecoveredAt] = useState(0);
  const wasDegraded = useRef(false);

  useEffect(() => {
    let active = true;
    const poll = async () => {
      let ok;
      try {
        ok = (await getStatus()).ok !== false;
      } catch {
        ok = false;
      }
      if (active) {
        setHealthy(ok);
        setNow(Date.now());
      }
    };
    poll();
    const id = setInterval(poll, 4000);
    return () => {
      active = false;
      clearInterval(id);
    };
  }, []);

  const degraded = !healthy || now - lastFailureAt < FAILURE_WINDOW_MS;

  useEffect(() => {
    if (wasDegraded.current && !degraded) setRecoveredAt(Date.now());
    wasDegraded.current = degraded;
  }, [degraded]);

  if (degraded) return "degraded";
  return now - recoveredAt < RECOVERED_MS ? "recovered" : "ok";
}

const PILL = {
  ok: { dot: "bg-credit", text: "Paiements opérationnels" },
  degraded: { dot: "bg-warn animate-pulse motion-reduce:animate-none", text: "Paiements perturbés" },
  recovered: { dot: "bg-credit", text: "Service rétabli" },
};

export function StatusPill({ state }) {
  const p = PILL[state];
  return (
    <span className="inline-flex items-center gap-2 text-sm text-ink/75" role="status">
      <span className={`h-2 w-2 rounded-full ${p.dot}`} aria-hidden="true" />
      {p.text}
    </span>
  );
}

export function StatusBanner({ state }) {
  if (state === "ok") return null;
  const degraded = state === "degraded";
  return (
    <div
      role="alert"
      className={`border-b px-4 py-3 text-sm ${
        degraded ? "border-warn/30 bg-warn/10 text-warn" : "border-credit/30 bg-credit/10 text-credit"
      }`}
    >
      <div className="mx-auto max-w-5xl">
        {degraded
          ? "Nos services de paiement sont perturbés. Vos fonds sont en sécurité ; les virements peuvent échouer, réessayez dans quelques instants."
          : "Le service de paiement est rétabli. Vous pouvez de nouveau effectuer vos virements."}
      </div>
    </div>
  );
}
