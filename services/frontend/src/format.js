const eur = new Intl.NumberFormat("fr-FR", { style: "currency", currency: "EUR" });
const when = new Intl.DateTimeFormat("fr-FR", {
  day: "numeric",
  month: "short",
  hour: "2-digit",
  minute: "2-digit",
});

export const formatEur = (value) => eur.format(Number(value) || 0);
export const formatDate = (iso) => when.format(new Date(iso));

// "10,50" (saisie française) -> "10.50" (format attendu par l'API).
export const normalizeAmount = (raw) => raw.replace(/\s/g, "").replace(",", ".");
