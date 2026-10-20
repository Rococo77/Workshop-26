import { useState } from "react";
import { createTransaction } from "../api.js";
import { formatEur, normalizeAmount } from "../format.js";

export default function TransferForm({ token, account, recentIbans, onSent, onFailure }) {
  const [iban, setIban] = useState("");
  const [amount, setAmount] = useState("");
  const [sending, setSending] = useState(false);
  const [receipt, setReceipt] = useState(null);
  const [error, setError] = useState(null);

  const value = Number(normalizeAmount(amount));
  const valid = iban.trim().length >= 4 && value > 0;

  const submit = async (e) => {
    e.preventDefault();
    if (!account || !valid) return;
    setSending(true);
    setReceipt(null);
    setError(null);
    try {
      const tx = await createTransaction(token, {
        src_account: account.id,
        dst_iban: iban.trim().toUpperCase(),
        amount: normalizeAmount(amount),
      });
      setReceipt({ ...tx, iban: iban.trim().toUpperCase() });
      setAmount("");
      onSent();
    } catch (err) {
      setError(err.message);
      onFailure(err);
    } finally {
      setSending(false);
    }
  };

  return (
    <section aria-labelledby="transfer-title" className="rounded-2xl bg-white border border-rule p-6">
      <h2 id="transfer-title" className="text-lg font-semibold">
        Envoyer de l&apos;argent
      </h2>

      <form onSubmit={submit} className="mt-5 space-y-4">
        <div>
          <label htmlFor="iban" className="block text-sm font-medium">
            IBAN du bénéficiaire
          </label>
          <input
            id="iban"
            className="field tabular uppercase"
            placeholder="FR76-FAKE-0002"
            autoComplete="off"
            value={iban}
            onChange={(e) => setIban(e.target.value)}
          />
          {recentIbans.length > 0 && (
            <div className="mt-2 flex flex-wrap gap-2" aria-label="Bénéficiaires récents">
              {recentIbans.map((r) => (
                <button
                  key={r}
                  type="button"
                  onClick={() => setIban(r)}
                  className="tabular rounded-full border border-rule px-3 py-1 text-[13px] text-ink/80 hover:border-petrol hover:text-petrol"
                >
                  {r}
                </button>
              ))}
            </div>
          )}
        </div>

        <div>
          <label htmlFor="amount" className="block text-sm font-medium">
            Montant
          </label>
          <div className="relative">
            <input
              id="amount"
              inputMode="decimal"
              className="field tabular pr-10"
              placeholder="0,00"
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
            />
            <span className="pointer-events-none absolute right-4 top-1/2 mt-[3px] -translate-y-1/2 text-ink/50">
              €
            </span>
          </div>
        </div>

        <button
          disabled={!valid || sending}
          className="w-full rounded-xl bg-petrol px-4 py-3 font-semibold text-white hover:bg-petrol-deep disabled:cursor-not-allowed disabled:opacity-40"
        >
          {sending ? "Envoi en cours…" : valid ? `Envoyer ${formatEur(value)}` : "Envoyer"}
        </button>
      </form>

      <div aria-live="polite">
        {receipt && (
          <p className="mt-4 rounded-xl bg-credit/10 px-4 py-3 text-sm text-credit">
            Virement de {formatEur(receipt.amount)} envoyé à{" "}
            <span className="tabular">{receipt.iban}</span>.
            <br />
            Référence <span className="tabular">{receipt.reference}</span>
          </p>
        )}
        {error && <p className="mt-4 rounded-xl bg-debit/10 px-4 py-3 text-sm text-debit">{error}</p>}
      </div>
    </section>
  );
}
