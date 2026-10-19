// Client HTTP minimal. Toutes les routes sont relatives (même origine que le
// WAF) : /auth, /api, /supervision. Aucune URL de service interne exposée.

// Message affiché au client selon la réponse : pendant une attaque, le WAF
// renvoie 429/403 et l'API 503 ; le client doit comprendre quoi faire.
const MESSAGES = {
  401: "Votre session a expiré. Reconnectez-vous.",
  403: "Requête bloquée par le filtrage de sécurité.",
  429: "Trop de demandes en ce moment. Réessayez dans quelques secondes.",
  503: "Le service de paiement est momentanément indisponible. Réessayez dans un instant.",
};

const DETAILS = {
  "insufficient funds": "Solde insuffisant pour ce virement.",
  "destination account not found": "Aucun compte ne correspond à cet IBAN.",
  "source and destination must differ": "Vous ne pouvez pas vous virer de l'argent sur le même compte.",
  "amount must be positive": "Le montant doit être supérieur à zéro.",
  "invalid amount": "Montant invalide.",
};

export class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

async function request(path, { token, method = "GET", body } = {}) {
  let res;
  try {
    res = await fetch(path, {
      method,
      headers: {
        ...(body ? { "Content-Type": "application/json" } : {}),
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: body ? JSON.stringify(body) : undefined,
    });
  } catch {
    throw new ApiError("Connexion au service impossible. Vérifiez le réseau.", 0);
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail = typeof data.detail === "string" ? data.detail : null;
    throw new ApiError(DETAILS[detail] || MESSAGES[res.status] || "Opération refusée.", res.status);
  }
  return data;
}

export function login(username, password) {
  return request("/auth/login", { method: "POST", body: { username, password } }).catch((e) => {
    if (e.status === 401) throw new ApiError("Identifiant ou mot de passe incorrect.", 401);
    throw e;
  });
}

export const getAccounts = (token) => request("/api/accounts/me", { token });

export const getTransactions = (token) => request("/api/transactions?limit=30", { token });

export const createTransaction = (token, payload) =>
  request("/api/transactions", { token, method: "POST", body: payload });

export const getOverview = () => request("/supervision/overview");
