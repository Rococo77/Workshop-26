import { formatDate, formatEur } from "../format.js";

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
                </div>
                <span
                  className={`tabular shrink-0 font-semibold ${t.outgoing ? "text-debit" : "text-credit"}`}
                >
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
