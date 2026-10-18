// Client HTTP minimal. Toutes les routes sont relatives (même origine que le
// WAF) : /auth, /api, /supervision. Aucune URL de service interne exposée.

export async function login(username, password) {
  const res = await fetch("/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
  if (!res.ok) throw new Error("Authentification refusée");
  return res.json();
}

export async function getAccounts(token) {
  const res = await fetch("/api/accounts/me", {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new Error("Comptes indisponibles");
  return res.json();
}

export async function createTransaction(token, payload) {
  const res = await fetch("/api/transactions", {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
    body: JSON.stringify(payload),
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body.detail || "Transaction refusée");
  return body;
}

export async function getOverview() {
  const res = await fetch("/supervision/overview");
  if (!res.ok) throw new Error("Supervision indisponible");
  return res.json();
}
