import React, { useEffect, useState } from "react";
import { getOverview } from "../api.js";

// Tableau de bord de reprise : état des services, score d'anomalie du modèle,
// file des remédiations (avec preuve de reprise canari) et IP bloquées.
export default function SupervisionPanel() {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    let active = true;
    const poll = async () => {
      try {
        const d = await getOverview();
        if (active) {
          setData(d);
          setError(null);
        }
      } catch (e) {
        if (active) setError(e.message);
      }
    };
    poll();
    const id = setInterval(poll, 3000);
    return () => {
      active = false;
      clearInterval(id);
    };
  }, []);

  const services = data?.services || {};
  const detector = data?.detector || {};
  const events = data?.remediation?.events || [];
  const blocked = data?.remediation?.blocked_ips || [];
  const score = detector.last_score ?? 0;
  const decision = detector.last_decision || "n/a";

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {Object.entries(services).map(([svc, up]) => (
          <div key={svc} className={`rounded-lg p-3 border ${up ? "border-emerald-600 bg-emerald-950/40" : "border-red-600 bg-red-950/40"}`}>
            <div className="text-xs uppercase text-slate-400">{svc}</div>
            <div className={`text-lg font-semibold ${up ? "text-emerald-400" : "text-red-400"}`}>
              {up ? "UP" : "DOWN"}
            </div>
          </div>
        ))}
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
        <div className="rounded-lg p-4 bg-slate-900 border border-slate-700">
          <div className="text-xs uppercase text-slate-400">Score d'anomalie (ML)</div>
          <div className={`text-3xl font-bold ${score > 0.5 ? "text-red-400" : "text-emerald-400"}`}>
            {score.toFixed(2)}
          </div>
          <div className="text-sm text-slate-400 mt-1">décision : {decision}</div>
        </div>
        <div className="rounded-lg p-4 bg-slate-900 border border-slate-700">
          <div className="text-xs uppercase text-slate-400">IP bloquées au WAF</div>
          <div className="text-3xl font-bold text-amber-400">{blocked.length}</div>
          <div className="text-sm text-slate-400 mt-1 break-all">{blocked.join(", ") || "—"}</div>
        </div>
        <div className="rounded-lg p-4 bg-slate-900 border border-slate-700">
          <div className="text-xs uppercase text-slate-400">Remédiations</div>
          <div className="text-3xl font-bold text-sky-400">{events.length}</div>
          <div className="text-sm text-slate-400 mt-1">dernières 50</div>
        </div>
      </div>

      {error && <div className="text-amber-400 text-sm">Supervision : {error}</div>}

      <div className="rounded-lg bg-slate-900 border border-slate-700">
        <div className="px-4 py-2 border-b border-slate-700 text-sm font-semibold">
          Événements de remédiation (le plus récent en haut)
        </div>
        <div className="max-h-80 overflow-auto divide-y divide-slate-800">
          {events.length === 0 && <div className="p-4 text-slate-500 text-sm">Aucun incident.</div>}
          {events.map((ev, i) => (
            <div key={i} className="p-3 text-sm">
              <div className="flex items-center gap-2 flex-wrap">
                <span className="font-mono text-xs text-slate-500">{ev.ts}</span>
                <Badge type={ev.type} />
                <Outcome recovered={ev.recovered} contained={ev.contained} outcome={ev.outcome} />
                {ev.source_ip && <span className="text-xs text-amber-400">src {ev.source_ip}</span>}
                {typeof ev.anomaly_score === "number" && (
                  <span className="text-xs text-slate-400">score {ev.anomaly_score}</span>
                )}
              </div>
              <ul className="mt-1 ml-4 list-disc text-slate-300">
                {(ev.steps || []).map((s, j) => <li key={j}>{s}</li>)}
              </ul>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function Badge({ type }) {
  const colors = {
    dos_flood: "bg-orange-900 text-orange-300",
    injection_attempt: "bg-purple-900 text-purple-300",
    service_unavailable: "bg-red-900 text-red-300",
  };
  return (
    <span className={`text-xs px-2 py-0.5 rounded ${colors[type] || "bg-slate-800 text-slate-300"}`}>
      {type}
    </span>
  );
}

function Outcome({ recovered, outcome }) {
  if (recovered) return <span className="text-xs px-2 py-0.5 rounded bg-emerald-900 text-emerald-300">reprise prouvée</span>;
  if (outcome === "contained") return <span className="text-xs px-2 py-0.5 rounded bg-sky-900 text-sky-300">confiné</span>;
  return <span className="text-xs px-2 py-0.5 rounded bg-red-900 text-red-300">échec</span>;
}
