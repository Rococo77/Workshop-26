import { useCallback, useEffect, useState } from "react";
import { getOverview, getReport, login, summarizeReport } from "./api.js";
import ScoreChart from "./components/ScoreChart.jsx";

// Supervision de la reprise (jury, opérateur) : raconte l'incident avant /
// pendant / après. Grafana reste l'outil d'analyse fine des métriques.

const POLL_MS = 2000;
const WINDOW = 90; // échantillons gardés pour la courbe (~3 min)
const RECENT_MS = 120000; // une remédiation récente qualifie l'état "rétabli"
const CRITICAL = ["auth", "payment-api", "waf"];

const INCIDENT = {
  dos_flood: "Déni de service",
  injection_attempt: "Tentative d'injection",
  service_unavailable: "Service indisponible",
  honeytoken_triggered: "Compte leurre utilisé",
};
const COMPONENT = {
  waf: "WAF, point d'entrée",
  auth: "Authentification",
  "payment-api": "API de paiement",
  "ml-detector": "Détection ML",
  remediation: "Moteur de remédiation",
  prometheus: "Prometheus",
  "waf-metrics": "Collecte des journaux WAF",
};
const SIGNALS = [
  ["req_rate", "Requêtes entrantes", (v) => `${v.toFixed(1)} /s`],
  ["waf_block_rate", "Rejets du WAF", (v) => `${v.toFixed(1)} /s`],
  ["err_ratio", "Erreurs 5xx", (v) => `${(v * 100).toFixed(1)} %`],
  ["p95_latency", "Latence p95", (v) => `${(v * 1000).toFixed(0)} ms`],
  ["auth_fail_rate", "Échecs de connexion", (v) => `${v.toFixed(1)} /s`],
];

const clock = new Intl.DateTimeFormat("fr-FR", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
const hhmmss = (iso) => clock.format(new Date(iso));

const isIncident = (data) =>
  (data.detector?.last_decision || "normal") !== "normal" ||
  CRITICAL.some((s) => data.services?.[s] === false);

// Première preuve canari obtenue après le début de l'incident (événements du
// plus récent au plus ancien).
const firstProof = (events, startedAt) =>
  startedAt === null ? null : events.findLast((e) => e.recovered && Date.parse(e.ts) >= startedAt) || null;

function phaseOf(data, now, proof) {
  const decision = data.detector?.last_decision || "normal";
  const last = data.remediation?.events?.[0];
  if (decision === "honeytoken_triggered") return { kind: "compromised", event: last };
  if (isIncident(data)) {
    // Le modèle voit encore l'attaque (fenêtre glissante) mais la reprise est
    // déjà prouvée : le service est maintenu, ce n'est plus une panne.
    if (proof) return { kind: "mitigated", decision, event: proof };
    return { kind: "incident", decision, down: CRITICAL.filter((s) => data.services?.[s] === false) };
  }
  if (last && now - Date.parse(last.ts) < RECENT_MS) {
    // Fuite de données : le service tourne, mais ce n'est pas une « reprise ».
    if (last.type === "honeytoken_triggered") return { kind: "compromised", event: last };
    return { kind: last.recovered ? "recovered" : last.contained ? "contained" : "failed", event: last };
  }
  return { kind: "nominal" };
}

// Jeton opérateur conservé le temps de l'onglet (rechargement sans reconnexion).
const TOKEN_KEY = "ra-supervision-token";
export function saveSupervisionToken(token) {
  try {
    sessionStorage.setItem(TOKEN_KEY, token);
  } catch {
    // stockage indisponible (navigation privée) : reconnexion au rechargement
  }
}
function readSupervisionToken() {
  try {
    return sessionStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}
function clearSupervisionToken() {
  try {
    sessionStorage.removeItem(TOKEN_KEY);
  } catch {
    // rien à effacer
  }
}

const SUPERVISION_ROLES = new Set(["operator", "admin"]);

function useSupervision(token, onAuthError) {
  const [data, setData] = useState(null);
  const [samples, setSamples] = useState([]);
  const [lastOk, setLastOk] = useState(0);
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    let active = true;
    const poll = async () => {
      try {
        const d = await getOverview(token);
        if (!active) return;
        setData(d);
        setLastOk(Date.now());
        setSamples((s) => [...s, { t: Date.now(), score: d.detector?.last_score ?? 0 }].slice(-WINDOW));
      } catch (err) {
        if (err.status === 401) onAuthError("Votre session a expiré. Reconnectez-vous.");
        else if (err.status === 403) onAuthError("Ce compte n'a pas accès à la supervision.");
        // sinon (attaque en cours, 429...) : on garde le dernier affichage
      }
      if (active) setNow(Date.now());
    };
    poll();
    const id = setInterval(poll, POLL_MS);
    return () => {
      active = false;
      clearInterval(id);
    };
  }, [token, onAuthError]);

  return { data, samples, stale: lastOk > 0 && now - lastOk > 3 * POLL_MS, lastOk, now };
}

// Temps de reprise : de la détection (horodatage serveur du détecteur) à la
// première transaction canari réussie. Conservé après la clôture de l'incident.
function useRecoveryClock(data, events) {
  const [startedAt, setStartedAt] = useState(null);
  const [lastMeasured, setLastMeasured] = useState(null);
  const proof = firstProof(events, startedAt);
  const measured = proof ? Math.max(0, Math.round((Date.parse(proof.ts) - startedAt) / 1000)) : null;
  const incident = data ? isIncident(data) : false;
  const detectedAt = data?.detector?.last_ts;

  useEffect(() => {
    if (incident && startedAt === null) {
      setStartedAt(Date.parse(detectedAt) || Date.now());
      setLastMeasured(null);
    } else if (!incident && startedAt !== null) {
      setLastMeasured(measured);
      setStartedAt(null);
    }
  }, [incident, startedAt, detectedAt, measured]);

  return { startedAt, proof, measured: measured ?? lastMeasured };
}

// Accès réservé aux rôles operator et admin (vérifié aussi côté BFF).
export default function Supervision() {
  const [token, setToken] = useState(readSupervisionToken);
  const [notice, setNotice] = useState(null);
  const onAuthError = useCallback((message) => {
    clearSupervisionToken();
    setNotice(message);
    setToken(null);
  }, []);

  if (!token) {
    return (
      <SupervisionLogin
        notice={notice}
        onLogin={(t) => {
          saveSupervisionToken(t);
          setNotice(null);
          setToken(t);
        }}
      />
    );
  }
  return <Console token={token} onAuthError={onAuthError} onLogout={() => onAuthError(null)} />;
}

function SupervisionLogin({ notice, onLogin }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState(null);

  const submit = async (e) => {
    e.preventDefault();
    setPending(true);
    setError(null);
    try {
      const res = await login(username.trim(), password);
      if (!SUPERVISION_ROLES.has(res.role)) {
        setError("Ce compte n'a pas accès à la supervision. Utilisez un compte opérateur.");
        setPending(false);
        return;
      }
      onLogin(res.access_token);
    } catch (err) {
      setError(err.message);
      setPending(false);
    }
  };

  return (
    <main className="flex min-h-screen items-center justify-center px-6">
      <div className="w-full max-w-sm">
        <span className="text-xl font-bold tracking-tight text-petrol">Alpha</span>
        <h1 className="mt-6 text-2xl font-semibold tracking-tight">Supervision de la reprise</h1>
        <p className="mt-2 text-ink/70">Accès réservé à l&apos;exploitation (rôle opérateur).</p>
        <form onSubmit={submit} className="mt-8 space-y-5">
          <div>
            <label htmlFor="sup-username" className="block text-sm font-medium">
              Identifiant
            </label>
            <input
              id="sup-username"
              className="field"
              autoComplete="username"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              required
            />
          </div>
          <div>
            <label htmlFor="sup-password" className="block text-sm font-medium">
              Mot de passe
            </label>
            <input
              id="sup-password"
              type="password"
              className="field"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
          </div>
          <button
            disabled={pending}
            className="w-full rounded-xl bg-petrol px-4 py-3 font-semibold text-white hover:bg-petrol-deep disabled:opacity-50"
          >
            {pending ? "Connexion…" : "Ouvrir la supervision"}
          </button>
          <div aria-live="polite">
            {(error || notice) && (
              <p className="rounded-xl bg-debit/10 px-4 py-3 text-sm text-debit">{error || notice}</p>
            )}
          </div>
        </form>
      </div>
    </main>
  );
}

function Console({ token, onAuthError, onLogout }) {
  const { data, samples, stale, lastOk, now } = useSupervision(token, onAuthError);
  const events = data?.remediation?.events || [];
  const { startedAt, proof, measured } = useRecoveryClock(data, events);
  const phase = data ? phaseOf(data, now, proof) : { kind: "loading" };

  const features = data?.detector?.last_features || {};
  const score = data?.detector?.last_score ?? 0;

  return (
    <div className="min-h-screen">
      <header className="border-b border-rule bg-white">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-x-6 gap-y-2 px-4 py-4">
          <span className="text-xl font-bold tracking-tight text-petrol">Alpha</span>
          <span className="font-medium">Supervision de la reprise</span>
          <span className="ml-auto text-sm text-ink/60" aria-live="polite">
            {stale
              ? `Données figées depuis ${Math.round((now - lastOk) / 1000)} s`
              : `Actualisé toutes les ${POLL_MS / 1000} s`}
          </span>
          <button onClick={onLogout} className="text-sm font-medium text-petrol hover:underline">
            Se déconnecter
          </button>
        </div>
      </header>

      <PhaseBanner phase={phase} score={score} startedAt={startedAt} measured={measured} now={now} />

      <main className="mx-auto grid max-w-6xl gap-8 px-4 py-8 lg:grid-cols-[1fr_320px]">
        <div className="space-y-10">
          <section aria-labelledby="score-title">
            <div className="flex items-baseline justify-between gap-4">
              <h2 id="score-title" className="text-lg font-semibold">
                Score d&apos;anomalie du modèle
              </h2>
              <span className={`tabular text-2xl font-semibold ${score > 0.5 ? "text-debit" : "text-petrol"}`}>
                {score.toFixed(2)}
              </span>
            </div>
            <div className="mt-3 rounded-2xl border border-rule bg-white p-4">
              <ScoreChart samples={samples} />
              <dl className="mt-4 grid grid-cols-2 gap-x-6 gap-y-3 sm:grid-cols-5">
                {SIGNALS.map(([key, label, fmt]) => (
                  <div key={key}>
                    <dt className="text-[13px] text-ink/60">{label}</dt>
                    <dd className="tabular font-medium">{key in features ? fmt(features[key]) : "—"}</dd>
                  </div>
                ))}
              </dl>
            </div>
          </section>

          <section aria-labelledby="timeline-title">
            <h2 id="timeline-title" className="text-lg font-semibold">
              Remédiations automatiques
            </h2>
            {events.length === 0 ? (
              <p className="mt-3 text-ink/60">
                Aucune remédiation pour l&apos;instant. Chaque incident détecté apparaîtra ici avec
                les actions engagées et la preuve de reprise.
              </p>
            ) : (
              <ol className="mt-4 space-y-4">
                {events.slice(0, 8).map((ev) => (
                  <EventCard key={ev.ts} ev={ev} token={token} />
                ))}
              </ol>
            )}
          </section>
        </div>

        <aside className="space-y-8">
          <Components services={data?.services || {}} />
          <Alerts alerts={data?.alerts || []} />
          <section aria-labelledby="blocked-title">
            <h2 id="blocked-title" className="font-semibold">
              Sources bloquées au WAF
            </h2>
            {(data?.remediation?.blocked_ips || []).length === 0 ? (
              <p className="mt-2 text-sm text-ink/60">Aucune adresse bloquée.</p>
            ) : (
              <ul className="mt-2 space-y-1">
                {data.remediation.blocked_ips.map((ip) => (
                  <li key={ip} className="tabular text-sm">
                    {ip}
                  </li>
                ))}
              </ul>
            )}
          </section>
        </aside>
      </main>
    </div>
  );
}

function PhaseBanner({ phase, score, startedAt, measured, now }) {
  const elapsed = startedAt ? Math.round((now - startedAt) / 1000) : null;
  const views = {
    loading: ["bg-white text-ink", "Connexion à la supervision…", ""],
    nominal: [
      "bg-credit text-white",
      "Service nominal",
      "Aucune anomalie détectée. Les paiements sont traités normalement.",
    ],
    incident: [
      "bg-debit text-white",
      `Incident en cours : ${INCIDENT[phase.decision] || "composant injoignable"}`,
      phase.down?.length
        ? `Injoignable : ${phase.down.map((s) => COMPONENT[s] || s).join(", ")}. Remédiation automatique engagée.`
        : `Anomalie détectée par le modèle (score ${score.toFixed(2)}). Remédiation automatique engagée.`,
    ],
    mitigated: [
      "bg-warn text-white",
      "Attaque en cours, service maintenu",
      phase.event
        ? `Reprise prouvée par transaction canari à ${hhmmss(phase.event.ts)}${
            measured !== null ? `, ${measured} s après la détection` : ""
          }. Le modèle observe encore le trafic anormal.`
        : "",
    ],
    recovered: [
      "bg-petrol text-white",
      "Service rétabli sans intervention humaine",
      phase.event
        ? `Preuve : transaction canari réussie à ${hhmmss(phase.event.ts)}.${
            measured !== null ? ` Reprise en ${measured} s après la détection.` : ""
          }`
        : "",
    ],
    compromised: [
      "bg-debit text-white",
      "Fuite de données détectée",
      "Un compte leurre a été utilisé : la base de comptes a fuité. Source confinée, service maintenu. Investigation et notification à engager.",
    ],
    contained: [
      "bg-warn text-white",
      "Attaque confinée, reprise non prouvée",
      "La source est bloquée mais la transaction canari échoue encore.",
    ],
    failed: [
      "bg-debit text-white",
      "Reprise non prouvée",
      "La transaction canari échoue encore : appliquer la procédure manuelle du PRA.",
    ],
  };
  const [tone, title, detail] = views[phase.kind];

  return (
    <div className={`${tone} transition-colors duration-500 motion-reduce:transition-none`} role="status">
      <div className="mx-auto flex max-w-6xl flex-wrap items-end justify-between gap-4 px-4 py-8">
        <div>
          <p className="text-[clamp(1.6rem,4vw,2.4rem)] font-semibold leading-tight tracking-tight">{title}</p>
          {detail && <p className="mt-2 max-w-2xl text-white/85">{detail}</p>}
        </div>
        {(phase.kind === "incident" || phase.kind === "mitigated") && elapsed !== null && (
          <p className="tabular text-[clamp(1.6rem,4vw,2.4rem)] font-semibold" aria-label="Durée de l'incident">
            {Math.floor(elapsed / 60)}:{String(elapsed % 60).padStart(2, "0")}
          </p>
        )}
      </div>
    </div>
  );
}

const OUTCOME = {
  recovered: ["text-credit", "Reprise prouvée par canari"],
  contained: ["text-warn", "Confiné"],
  failed: ["text-debit", "Reprise non prouvée"],
};

function EventCard({ ev, token }) {
  const [color, label] = OUTCOME[ev.outcome] || OUTCOME.failed;
  const [open, setOpen] = useState(false);
  return (
    <li className="rounded-2xl border border-rule bg-white p-5">
      <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
        <span className="tabular text-sm text-ink/60">{hhmmss(ev.ts)}</span>
        <span className="font-semibold">{INCIDENT[ev.type] || ev.type}</span>
        <span className={`text-sm font-semibold ${color}`}>{label}</span>
        {typeof ev.anomaly_score === "number" && (
          <span className="tabular text-sm text-ink/60">score {ev.anomaly_score.toFixed(2)}</span>
        )}
      </div>
      {ev.detail && <p className="mt-1 text-sm text-ink/70">Causes : {ev.detail}</p>}
      <ol className="mt-3 space-y-1.5 border-l-2 border-rule pl-4 text-sm">
        {(ev.steps || []).map((s, i) => (
          <li key={i}>{s}</li>
        ))}
      </ol>
      {ev.report_id && (
        <button
          onClick={() => setOpen((o) => !o)}
          aria-expanded={open}
          className="mt-4 text-sm font-semibold text-petrol hover:underline"
        >
          {open ? "Masquer le rapport d'incident" : "Rapport d'incident (notification DORA)"}
        </button>
      )}
      {open && <ReportPanel id={ev.report_id} token={token} />}
    </li>
  );
}

// Rapport généré par le moteur, sans action humaine. Le résumé direction est
// rédigé à la demande par l'assistant LLM (profil `ai`, lecture seule).
function ReportPanel({ id, token }) {
  const [report, setReport] = useState(null);
  const [summary, setSummary] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    getReport(token, id).then(setReport, (err) => setError(err.message));
  }, [id, token]);

  const download = () => {
    const url = URL.createObjectURL(new Blob([report.markdown], { type: "text/markdown" }));
    const a = Object.assign(document.createElement("a"), { href: url, download: `${id}.md` });
    a.click();
    URL.revokeObjectURL(url);
  };

  const summarize = async () => {
    setBusy(true);
    setError(null);
    try {
      setSummary((await summarizeReport(token, id)).summary);
    } catch (err) {
      setError(err.status === 503 ? "Assistant IA indisponible (profil ai non démarré)." : err.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mt-3 space-y-3">
      {report && (
        <>
          <p className="text-sm">
            Temps de reprise :{" "}
            <span className="tabular font-semibold">
              {report.recovery_seconds !== null ? `${report.recovery_seconds} s` : "non prouvée"}
            </span>
          </p>
          <pre className="max-h-80 overflow-auto whitespace-pre-wrap rounded-xl bg-paper p-4 text-[13px] leading-relaxed">
            {report.markdown}
          </pre>
          <div className="flex flex-wrap gap-4">
            <button onClick={download} className="text-sm font-semibold text-petrol hover:underline">
              Télécharger (.md)
            </button>
            <button
              onClick={summarize}
              disabled={busy}
              className="text-sm font-semibold text-petrol hover:underline disabled:opacity-50"
            >
              {busy ? "Rédaction par l'assistant…" : "Résumé pour la direction (assistant IA)"}
            </button>
          </div>
        </>
      )}
      {summary && <p className="rounded-xl border border-rule p-4 text-sm leading-relaxed">{summary}</p>}
      <div aria-live="polite">{error && <p className="text-sm text-debit">{error}</p>}</div>
    </div>
  );
}

function Components({ services }) {
  const entries = Object.entries(services).sort(
    ([a], [b]) => (CRITICAL.includes(b) ? 1 : 0) - (CRITICAL.includes(a) ? 1 : 0),
  );
  return (
    <section aria-labelledby="components-title">
      <h2 id="components-title" className="font-semibold">
        Composants
      </h2>
      <ul className="mt-2 divide-y divide-rule">
        {entries.map(([name, up]) => (
          <li key={name} className="flex items-center justify-between gap-3 py-2 text-sm">
            <span>{COMPONENT[name] || name}</span>
            <span className={`inline-flex items-center gap-2 font-medium ${up ? "text-credit" : "text-debit"}`}>
              <span className={`h-2 w-2 rounded-full ${up ? "bg-credit" : "bg-debit"}`} aria-hidden="true" />
              {up ? "Opérationnel" : "Injoignable"}
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}

function Alerts({ alerts }) {
  return (
    <section aria-labelledby="alerts-title">
      <h2 id="alerts-title" className="font-semibold">
        Alertes
      </h2>
      {alerts.length === 0 ? (
        <p className="mt-2 text-sm text-ink/60">Aucune alerte active.</p>
      ) : (
        <ul className="mt-2 space-y-2">
          {alerts.map((a) => (
            <li key={a.name + a.since} className="text-sm">
              <span className={`font-semibold ${a.severity === "critical" ? "text-debit" : "text-warn"}`}>
                {a.summary || a.name}
              </span>
              <span className="block text-ink/60">
                {a.state === "firing" ? "Déclenchée" : "En observation"}
                {a.since ? ` depuis ${hhmmss(a.since)}` : ""}
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
