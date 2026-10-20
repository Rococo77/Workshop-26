import { formatDate, formatEur } from "../format.js";

const REJECTED = {
  expired: "Expiré",
  cancelled: "Annulé",
  face_mismatch: "Refusé, visage non reconnu",
  insufficient_funds: "Refusé, solde insuffisant",
};

function statusLabel(t) {
  if (t.status === "pending") return "En attente de validation";
  if (t.status === "rejected") return REJECTED[t.reject_reason] || "Refusé";
  return null;
}

export default function History({ transactions }) {
  return (
    <section aria-labelledby="history-title">
      <h2 id="history-title" className="text-lg font-semibold">
        Opérations récentes
      </h2>

      {transactions === null && <p className="mt-4 text-ink/60">Chargement de l&apos;historique…</p>}
      {transactions?.length === 0 && (
        <p className="mt-4 text-ink/60">
          Aucune opération pour l&apos;instant. Votre premier virement apparaîtra ici.
        </p>
      )}

      {transactions?.length > 0 && (
        <ul className="mt-3 divide-y divide-rule">
          {transactions.map((t) => {
            const counterpart = t.outgoing ? t.dst_iban : t.src_iban;
            const label = statusLabel(t);
            const amountTone =
              t.status === "rejected"
                ? "text-ink/40 line-through"
                : t.status === "pending"
                  ? "text-ink/50"
                  : t.outgoing
                    ? "text-debit"
                    : "text-credit";
            return (
              <li key={t.id} className="flex items-center justify-between gap-4 py-3.5">
                <div className="min-w-0">
                  <p className="truncate font-medium">
                    {t.is_canary
                      ? "Contrôle automatique du service"
                      : t.outgoing
                        ? `Virement vers ${counterpart}`
                        : `Virement reçu de ${counterpart}`}
                  </p>
                  <p className="text-[13px] text-ink/55">
                    {formatDate(t.created_at)}, réf. <span className="tabular">{t.reference}</span>
                  </p>
                  {label && (
                    <p className={`text-[13px] font-medium ${t.status === "pending" ? "text-warn" : "text-debit"}`}>
                      {label}
                    </p>
                  )}
                </div>
                <span className={`tabular shrink-0 font-semibold ${amountTone}`}>
                  {t.outgoing ? "−" : "+"}
                  {formatEur(t.amount)}
                </span>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
