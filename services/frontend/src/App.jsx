import { useCallback, useEffect, useMemo, useState } from "react";
import { getAccounts, getFaceEnrollment, getTransactions, login, loginFace, register } from "./api.js";
import AccountCard from "./components/AccountCard.jsx";
import ConsentModal from "./components/ConsentModal.jsx";
import FaceCapture from "./components/FaceCapture.jsx";
import FaceEnrollment from "./components/FaceEnrollment.jsx";
import Guilloche from "./components/Guilloche.jsx";
import History from "./components/History.jsx";
import PoseCapture, { POSES } from "./components/PoseCapture.jsx";
import TransferForm from "./components/TransferForm.jsx";
import { StatusBanner, StatusPill, useServiceStatus } from "./components/ServiceStatus.jsx";
import Supervision, { saveSupervisionToken } from "./Supervision.jsx";

// Erreurs révélatrices d'un incident (réseau, rate-limit, indisponibilité).
const INCIDENT_STATUSES = new Set([0, 429, 502, 503, 504]);

export default function App() {
  return window.location.pathname === "/supervision" ? <Supervision /> : <ClientApp />;
}

function ClientApp() {
  const [session, setSession] = useState(null);
  const [mode, setMode] = useState(window.location.pathname === "/register" ? "register" : "login");

  const goTo = (next) => {
    setMode(next);
    window.history.replaceState(null, "", next === "register" ? "/register" : "/");
  };

  if (session) return <Banking session={session} onLogout={() => setSession(null)} />;
  return mode === "register" ? (
    <Register onRegistered={setSession} onGoToLogin={() => goTo("login")} />
  ) : (
    <Login onLogin={setSession} onGoToRegister={() => goTo("register")} />
  );
}

function Wordmark({ className = "" }) {
  return <span className={`text-xl font-bold tracking-tight ${className}`}>Alpha</span>;
}

// Habillage commun aux écrans de connexion/inscription (bandeau + formulaire).
function AuthShell({ title, subtitle, children, footer }) {
  return (
    <div className="grid min-h-screen lg:grid-cols-[1.1fr_1fr]">
      <aside className="relative hidden overflow-hidden bg-petrol p-12 text-white lg:flex lg:flex-col">
        <Guilloche className="absolute inset-0 h-full w-full text-line/30" />
        <Wordmark className="relative text-2xl" />
        <div className="relative mt-auto max-w-md">
          <p className="text-[2.5rem] font-semibold leading-[1.1] tracking-tight">
            Envoyez de l&apos;argent en quelques secondes.
          </p>
          <p className="mt-4 text-white/75">
            Consultez votre solde, virez vers n&apos;importe quel IBAN de la plateforme et suivez chaque
            opération.
          </p>
        </div>
      </aside>

      <main className="flex flex-col px-6 py-10 sm:px-12">
        <Wordmark className="text-petrol lg:hidden" />
        <div className="m-auto w-full max-w-sm">
          <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
          {subtitle && <p className="mt-2 text-sm text-ink/70">{subtitle}</p>}
          <div className="mt-8">{children}</div>
          {footer}
        </div>
        <p className="mx-auto mt-10 max-w-sm text-center text-[13px] text-ink/50">
          Plateforme de paiement fictive du démonstrateur Resilience-Alpha. Aucun argent réel.
        </p>
      </main>
    </div>
  );
}

function Login({ onLogin, onGoToRegister }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  // null = étape mot de passe ; sinon second facteur (jeton intermédiaire).
  const [face, setFace] = useState(null);

  const submitPassword = async (e) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const res = await login(username.trim(), password);
      if (res.pending_token) {
        setFace({ token: res.pending_token, attempt: 0 });
        return;
      }
      if (res.role !== "customer") {
        // operator / admin : pas de comptes bancaires, leur espace est la supervision.
        saveSupervisionToken(res.access_token);
        window.location.assign("/supervision");
        return;
      }
      onLogin({ token: res.access_token, username: username.trim() });
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  const submitFace = async (image) => {
    setBusy(true);
    setError(null);
    try {
      const res = await loginFace(face.token, image);
      onLogin({ token: res.access_token, username: username.trim() });
    } catch (err) {
      setError(err.message);
      setFace((f) => ({ ...f, attempt: f.attempt + 1 }));
    } finally {
      setBusy(false);
    }
  };

  if (face) {
    return (
      <AuthShell
        title="Confirmez avec votre visage"
        subtitle="Dernière étape : une photo de votre visage pour finaliser la connexion."
      >
        <FaceCapture
          key={face.attempt}
          busy={busy}
          submitLabel="Se connecter"
          onSubmit={submitFace}
          onCancel={() => setFace(null)}
        />
        <div aria-live="polite">
          {error && <p className="mt-4 rounded-xl bg-debit/10 px-4 py-3 text-sm text-debit">{error}</p>}
        </div>
      </AuthShell>
    );
  }

  return (
    <AuthShell
      title="Connexion à votre espace"
      footer={
        <p className="mt-6 text-center text-sm text-ink/70">
          Pas encore de compte ?{" "}
          <button type="button" onClick={onGoToRegister} className="font-medium text-petrol hover:underline">
            Créer un compte
          </button>
        </p>
      }
    >
      <form onSubmit={submitPassword} className="space-y-5">
        <div>
          <label htmlFor="username" className="block text-sm font-medium">
            Identifiant
          </label>
          <input
            id="username"
            className="field"
            autoComplete="username"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            required
          />
        </div>
        <div>
          <label htmlFor="password" className="block text-sm font-medium">
            Mot de passe
          </label>
          <input
            id="password"
            type="password"
            className="field"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
          />
        </div>
        <button
          disabled={busy}
          className="w-full rounded-xl bg-petrol px-4 py-3 font-semibold text-white hover:bg-petrol-deep disabled:opacity-50"
        >
          {busy ? "Connexion…" : "Se connecter"}
        </button>
        <div aria-live="polite">
          {error && <p className="rounded-xl bg-debit/10 px-4 py-3 text-sm text-debit">{error}</p>}
        </div>
      </form>
    </AuthShell>
  );
}

function Register({ onRegistered, onGoToLogin }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  // credentials -> consent (pop-up) -> photos (pool de 5 poses).
  const [stage, setStage] = useState("credentials");
  const [images, setImages] = useState({});
  const [step, setStep] = useState(0);
  const [retryKey, setRetryKey] = useState(0);

  const submitCredentials = (e) => {
    e.preventDefault();
    setError(null);
    if (password !== confirm) {
      setError("Les mots de passe ne correspondent pas.");
      return;
    }
    setStage("consent");
  };

  const resetToCredentials = () => {
    setStage("credentials");
    setImages({});
    setStep(0);
  };

  const submitAll = async (allImages) => {
    setBusy(true);
    setError(null);
    try {
      const res = await register(username.trim(), password, true, allImages);
      onRegistered({ token: res.access_token, username: username.trim() });
    } catch (err) {
      setError(err.message);
      if (err.pose) {
        // Une seule pose en cause : on ne refait que celle-là, les 4 autres
        // photos déjà acceptées sont conservées.
        const idx = POSES.findIndex((p) => p.key === err.pose);
        setStep(idx >= 0 ? idx : 0);
        setRetryKey((n) => n + 1);
      } else {
        // Erreur non liée à une pose (identifiant pris...) : retour au formulaire.
        resetToCredentials();
      }
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

  if (stage === "photos") {
    return (
      <AuthShell
        title="Activez la validation par visage"
        subtitle="Dernière étape : 5 photos sous différents angles protégeront votre compte (mot de passe + visage)."
      >
        <PoseCapture
          step={step}
          retryKey={retryKey}
          busy={busy}
          onPhoto={onPhoto}
          onCancel={resetToCredentials}
        />
        <div aria-live="polite">
          {error && <p className="mt-4 rounded-xl bg-debit/10 px-4 py-3 text-sm text-debit">{error}</p>}
        </div>
      </AuthShell>
    );
  }

  return (
    <>
      <AuthShell
        title="Créer un compte"
        footer={
          <p className="mt-6 text-center text-sm text-ink/70">
            Déjà un compte ?{" "}
            <button type="button" onClick={onGoToLogin} className="font-medium text-petrol hover:underline">
              Se connecter
            </button>
          </p>
        }
      >
        <form onSubmit={submitCredentials} className="space-y-5">
          <div>
            <label htmlFor="new-username" className="block text-sm font-medium">
              Identifiant
            </label>
            <input
              id="new-username"
              className="field"
              autoComplete="username"
              minLength={3}
              maxLength={32}
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              required
            />
          </div>
          <div>
            <label htmlFor="new-password" className="block text-sm font-medium">
              Mot de passe
            </label>
            <input
              id="new-password"
              type="password"
              className="field"
              autoComplete="new-password"
              minLength={10}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
          </div>
          <div>
            <label htmlFor="confirm-password" className="block text-sm font-medium">
              Confirmez le mot de passe
            </label>
            <input
              id="confirm-password"
              type="password"
              className="field"
              autoComplete="new-password"
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
              required
            />
          </div>
          <button className="w-full rounded-xl bg-petrol px-4 py-3 font-semibold text-white hover:bg-petrol-deep">
            Continuer
          </button>
          <div aria-live="polite">
            {error && <p className="rounded-xl bg-debit/10 px-4 py-3 text-sm text-debit">{error}</p>}
          </div>
        </form>
      </AuthShell>
      {stage === "consent" && (
        <ConsentModal onAccept={() => setStage("photos")} onDecline={() => setStage("credentials")} />
      )}
    </>
  );
}

function Banking({ session, onLogout }) {
  const { token, username } = session;
  const [accounts, setAccounts] = useState(null);
  const [transactions, setTransactions] = useState(null);
  const [lastFailureAt, setLastFailureAt] = useState(0);
  // null = inconnu : on affiche le formulaire, l'API redemande l'enrôlement si besoin.
  const [faceEnrolled, setFaceEnrolled] = useState(null);
  const status = useServiceStatus(lastFailureAt);

  const onFailure = useCallback(
    (err) => {
      if (err.status === 401) onLogout();
      else if (INCIDENT_STATUSES.has(err.status)) setLastFailureAt(Date.now());
    },
    [onLogout],
  );

  const refresh = useCallback(async () => {
    try {
      const [acc, txs] = await Promise.all([getAccounts(token), getTransactions(token)]);
      setAccounts(acc);
      setTransactions(txs);
    } catch (err) {
      onFailure(err); // on garde les dernières données connues à l'écran
    }
  }, [token, onFailure]);

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, 5000);
    return () => clearInterval(id);
  }, [refresh]);

  useEffect(() => {
    getFaceEnrollment(token)
      .then((f) => setFaceEnrolled(!f.required || f.enrolled))
      .catch(onFailure);
  }, [token, onFailure]);

  const account = accounts?.[0];
  const recentIbans = useMemo(() => {
    const seen = new Set();
    for (const t of transactions || []) {
      if (t.outgoing && !t.is_canary && t.status === "settled") seen.add(t.dst_iban);
    }
    return [...seen].slice(0, 3);
  }, [transactions]);

  return (
    <div className="min-h-screen">
      <header className="border-b border-rule bg-white">
        <div className="mx-auto flex max-w-5xl flex-wrap items-center gap-x-6 gap-y-2 px-4 py-4">
          <Wordmark className="text-petrol" />
          <StatusPill state={status} />
          <div className="ml-auto flex items-center gap-4 text-sm">
            <span className="capitalize text-ink/75">{username}</span>
            <button onClick={onLogout} className="font-medium text-petrol hover:underline">
              Se déconnecter
            </button>
          </div>
        </div>
      </header>
      <StatusBanner state={status} />

      <main className="mx-auto grid max-w-5xl gap-8 px-4 py-8 lg:grid-cols-[1fr_380px] lg:gap-12">
        <div className="space-y-10">
          <AccountCard account={account} holder={username} />
          <div className="hidden lg:block">
            <History transactions={transactions} />
          </div>
        </div>
        <div className="space-y-10">
          {faceEnrolled === false ? (
            <FaceEnrollment token={token} onEnrolled={() => setFaceEnrolled(true)} onFailure={onFailure} />
          ) : (
            <TransferForm
              token={token}
              account={account}
              recentIbans={recentIbans}
              onSent={refresh}
              onFailure={onFailure}
              onEnrollmentRequired={() => setFaceEnrolled(false)}
            />
          )}
          <div className="lg:hidden">
            <History transactions={transactions} />
          </div>
        </div>
      </main>
    </div>
  );
}
