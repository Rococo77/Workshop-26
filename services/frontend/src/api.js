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
  "transaction expired": "Le délai de validation est dépassé : le virement a été annulé.",
  "transaction cancelled": "Ce virement a déjà été annulé.",
  "transaction face_mismatch": "Ce virement a été refusé après plusieurs échecs de reconnaissance.",
  "transaction settled": "Ce virement a déjà été validé.",
  "face verification not configured": "La validation par visage n'est pas configurée pour ce compte. Contactez le support.",
};

// Validation faciale : l'API renvoie `detail: { code, attempts_left? }`.
const FACE_CODES = {
  face_not_enrolled: "Activez d'abord la validation par visage.",
  already_enrolled: "Votre visage est déjà enregistré.",
  face_reenrollment_required: "Votre visage doit être réenregistré. Contactez le support.",
  face_mismatch: "Le visage ne correspond pas à celui enregistré.",
  spoof: "Photo refusée : prenez-vous en direct, pas une photo ou un écran.",
  no_face: "Aucun visage détecté. Placez votre visage bien en face, dans la lumière.",
  multiple_faces: "Plusieurs visages détectés. Vous devez être seul sur la photo.",
  invalid_image: "Image illisible. Reprenez la photo.",
  image_too_large: "Image trop lourde. Reprenez la photo.",
  face_locked: "Trop d'échecs de reconnaissance. Réessayez dans 15 minutes.",
  face_unavailable: "La reconnaissance faciale est momentanément indisponible. Réessayez.",
  // Auto-inscription (POST /api/auth/register).
  username_taken: "Cet identifiant est déjà utilisé.",
  invalid_username: "Identifiant invalide (3 à 32 caractères : lettres, chiffres, points, underscore).",
  weak_password: "Mot de passe trop court (10 caractères minimum).",
};

export class ApiError extends Error {
  constructor(message, status, { code = null, attemptsLeft = null } = {}) {
    super(message);
    this.status = status;
    this.code = code;
    this.attemptsLeft = attemptsLeft;
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
    const code = typeof data.detail?.code === "string" ? data.detail.code : null;
    if (code) {
      throw new ApiError(FACE_CODES[code] || MESSAGES[res.status] || "Opération refusée.", res.status, {
        code,
        attemptsLeft: data.detail.attempts_left ?? null,
      });
    }
    const detail = typeof data.detail === "string" ? data.detail : null;
    throw new ApiError(DETAILS[detail] || MESSAGES[res.status] || "Opération refusée.", res.status);
  }
  return data;
}

// Mot de passe seul : pour un client, renvoie { status: "face_required",
// pending_token, role } (pas un token d'accès) -> voir loginFace().
export function login(username, password) {
  return request("/auth/login", { method: "POST", body: { username, password } }).catch((e) => {
    if (e.status === 401) throw new ApiError("Identifiant ou mot de passe incorrect.", 401);
    throw e;
  });
}

// Second facteur : visage, avec le `pending_token` renvoyé par login().
export const loginFace = (pendingToken, image) =>
  request("/api/auth/login/face", { token: pendingToken, method: "POST", body: { image } });

// Auto-inscription : identifiant + mot de passe + visage en un seul appel.
export const register = (username, password, image) =>
  request("/api/auth/register", { method: "POST", body: { username, password, image } });

export const getAccounts = (token) => request("/api/accounts/me", { token });

export const getTransactions = (token) => request("/api/transactions?limit=30", { token });

export const createTransaction = (token, payload) =>
  request("/api/transactions", { token, method: "POST", body: payload });

// Photos en base64 BRUT : le préfixe `data:image/...;base64,` déclenche
// plusieurs règles OWASP CRS du WAF (data scheme, XSS, RCE).
export const confirmTransaction = (token, id, image) =>
  request(`/api/transactions/${id}/confirm`, { token, method: "POST", body: { image } });

export const cancelTransaction = (token, id) =>
  request(`/api/transactions/${id}/cancel`, { token, method: "POST" });

export const getFaceEnrollment = (token) => request("/api/face/enrollment", { token });

export const enrollFace = (token, image) =>
  request("/api/face/enrollment", { token, method: "POST", body: { image } });

// Public : ok / perturbé, pour la pastille de l'espace client.
export const getStatus = () => request("/supervision/status");

// Réservé aux rôles operator et admin (vue détaillée de la supervision).
export const getOverview = (token) => request("/supervision/overview", { token });
