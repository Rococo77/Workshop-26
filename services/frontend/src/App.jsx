import React, { useState } from "react";
import { login } from "./api.js";
import PaymentPanel from "./components/PaymentPanel.jsx";
import SupervisionPanel from "./components/SupervisionPanel.jsx";

export default function App() {
  const [token, setToken] = useState(null);
  const [role, setRole] = useState(null);
  const [username, setUsername] = useState("alice");
  const [password, setPassword] = useState("");
  const [error, setError] = useState(null);

  const submit = async (e) => {
    e.preventDefault();
    setError(null);
    try {
      const res = await login(username, password);
      setToken(res.access_token);
      setRole(res.role);
    } catch (e) {
      setError(e.message);
    }
  };

  return (
    <div className="min-h-screen px-4 py-6 max-w-6xl mx-auto">
      <header className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold">PROJECT RESILIENCE-ALPHA</h1>
          <p className="text-slate-400 text-sm">Plateforme de paiement fictive — cyber-résilience et reprise autonome</p>
        </div>
        {token && (
          <button onClick={() => { setToken(null); setRole(null); }}
                  className="text-sm text-slate-400 hover:text-slate-200">
            {username} ({role}) · déconnexion
          </button>
        )}
      </header>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-1">
          {!token ? (
            <form onSubmit={submit} className="rounded-lg bg-slate-900 border border-slate-700 p-4 space-y-3">
              <h2 className="font-semibold">Connexion</h2>
              <input className="w-full bg-slate-800 rounded px-3 py-2 text-sm"
                     value={username} onChange={(e) => setUsername(e.target.value)} placeholder="utilisateur" />
              <input type="password" className="w-full bg-slate-800 rounded px-3 py-2 text-sm"
                     value={password} onChange={(e) => setPassword(e.target.value)} placeholder="mot de passe" />
              <button className="w-full bg-emerald-600 hover:bg-emerald-500 rounded px-3 py-2 text-sm font-semibold">
                Se connecter
              </button>
              {error && <div className="text-red-400 text-sm">{error}</div>}
            </form>
          ) : (
            <PaymentPanel token={token} />
          )}
        </div>

        <div className="lg:col-span-2">
          <h2 className="font-semibold mb-3">Supervision & reprise autonome</h2>
          <SupervisionPanel />
        </div>
      </div>
    </div>
  );
}
