import { useState } from "react";
import { cancelTransaction, confirmTransaction, createTransaction } from "../api.js";
import { formatEur, normalizeAmount } from "../format.js";
import FaceCapture from "./FaceCapture.jsx";

const time = new Intl.DateTimeFormat("fr-FR", { hour: "2-digit", minute: "2-digit" });

export default function TransferForm({ token, account, recentIbans, onSent, onFailure, onEnrollmentRequired }) {
  const [iban, setIban] = useState("");
  const [amount, setAmount] = useState("");
  const [sending, setSending] = useState(false);
  const [receipt, setReceipt] = useState(null);
  const [error, setError] = useState(null);
  // Virement créé côté API, en attente de la photo de confirmation.
  const [pending, setPending] = useState(null);

  const value = Number(normalizeAmount(amount));
  const valid = iban.trim().length >= 4 && value > 0;

  const submit = async (e) => {
    e.preventDefault();
    if (!account || !valid) return;
    setSending(true);
    setReceipt(null);
    setError(null);
    try {
      const dst = iban.trim().toUpperCase();
      const tx = await createTransaction(token, {
        src_account: account.id,
        dst_iban: dst,
        amount: normalizeAmount(amount),
      });
      if (tx.status === "pending") {
        setPending({ ...tx, iban: dst, attempt: 0 });
      } else {
        setReceipt({ ...tx, iban: dst });
        setAmount("");
      }
      onSent();
    } catch (err) {
      if (err.code === "face_not_enrolled") onEnrollmentRequired();
      setError(err.message);
      if (!err.code) onFailure(err);
    } finally {
      setSending(false);
    }
  };

  const confirm = async (image) => {
    setSending(true);
    setError(null);
    try {
      const tx = await confirmTransaction(token, pending.id, image);
      setReceipt({ ...tx, iban: pending.iban });
      setPending(null);
      setAmount("");
      onSent();
    } catch (err) {
      if (err.attemptsLeft === 0 || err.status === 409) {
        // Virement clos côté API (essais épuisés, expiré...) : retour au formulaire.
        setPending(null);
        setError(err.attemptsLeft === 0 ? "Virement refusé : votre visage n'a pas été reconnu." : err.message);
        onSent();
      } else {
        const left = err.attemptsLeft != null ? ` Essais restants : ${err.attemptsLeft}.` : "";
        setError(err.message + left);
        setPending((p) => ({ ...p, attempt: p.attempt + 1 }));
      }
      if (!err.code) onFailure(err);
    } finally {
      setSending(false);
    }
  };

  const cancel = async () => {
    const id = pending.id;
    setPending(null);
    setError(null);
    try {
      await cancelTransaction(token, id);
    } catch {
      // Sans annulation explicite, le virement expire de lui-même.
    }
    onSent();
  };

  if (pending) {
    return (
      <section aria-labelledby="confirm-title" className="rounded-2xl border border-rule bg-white p-6">
        <h2 id="confirm-title" className="text-lg font-semibold">
          Confirmez avec votre visage
        </h2>
        <p className="mt-2 text-sm text-ink/70">
          Virement de <span className="font-semibold text-ink">{formatEur(pending.amount)}</span> vers{" "}
          <span className="tabular">{pending.iban}</span>. À valider avant {time.format(new Date(pending.expires_at))}.
        </p>
        <div className="mt-5">
          <FaceCapture
            key={pending.attempt}
            busy={sending}
            submitLabel={`Valider ${formatEur(pending.amount)}`}
            onSubmit={confirm}
            onCancel={cancel}
          />
        </div>
        <div aria-live="polite">
          {error && <p className="mt-4 rounded-xl bg-debit/10 px-4 py-3 text-sm text-debit">{error}</p>}
        </div>
      </section>
    );
  }

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
          {sending ? "Envoi en cours…" : valid ? `Continuer avec ${formatEur(value)}` : "Continuer"}
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
