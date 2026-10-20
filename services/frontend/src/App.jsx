import { useCallback, useEffect, useMemo, useState } from "react";
import { getAccounts, getTransactions, login } from "./api.js";
import AccountCard from "./components/AccountCard.jsx";
import Guilloche from "./components/Guilloche.jsx";
import History from "./components/History.jsx";
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
  return session ? (
    <Banking session={session} onLogout={() => setSession(null)} />
  ) : (
    <Login onLogin={setSession} />
  );
}

function Wordmark({ className = "" }) {
  return <span className={`text-xl font-bold tracking-tight ${className}`}>Alpha</span>;
}

function Login({ onLogin }) {
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
      if (res.role !== "customer") {
        // operator / admin : pas de comptes bancaires, leur espace est la supervision.
        saveSupervisionToken(res.access_token);
        window.location.assign("/supervision");
        return;
      }
      onLogin({ token: res.access_token, username: username.trim() });
    } catch (err) {
      setError(err.message);
      setPending(false);
    }
  };

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
          <h1 className="text-2xl font-semibold tracking-tight">Connexion à votre espace</h1>
          <form onSubmit={submit} className="mt-8 space-y-5">
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
              disabled={pending}
              className="w-full rounded-xl bg-petrol px-4 py-3 font-semibold text-white hover:bg-petrol-deep disabled:opacity-50"
            >
              {pending ? "Connexion…" : "Se connecter"}
            </button>
            <div aria-live="polite">
              {error && <p className="rounded-xl bg-debit/10 px-4 py-3 text-sm text-debit">{error}</p>}
            </div>
          </form>
        </div>
        <p className="mx-auto mt-10 max-w-sm text-center text-[13px] text-ink/50">
          Plateforme de paiement fictive du démonstrateur Resilience-Alpha. Aucun argent réel.
        </p>
      </main>
    </div>
  );
}

function Banking({ session, onLogout }) {
  const { token, username } = session;
  const [accounts, setAccounts] = useState(null);
  const [transactions, setTransactions] = useState(null);
  const [lastFailureAt, setLastFailureAt] = useState(0);
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

  const account = accounts?.[0];
  const recentIbans = useMemo(() => {
    const seen = new Set();
    for (const t of transactions || []) {
      if (t.outgoing && !t.is_canary) seen.add(t.dst_iban);
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
          <TransferForm
            token={token}
            account={account}
            recentIbans={recentIbans}
            onSent={refresh}
            onFailure={onFailure}
          />
          <div className="lg:hidden">
            <History transactions={transactions} />
          </div>
        </div>
      </main>
    </div>
  );
}
