import React, { useEffect, useState } from "react";
import { getAccounts, createTransaction } from "../api.js";

// Parcours métier : visualiser ses comptes et initier une transaction.
// Sert à matérialiser l'état du service AVANT / PENDANT / APRÈS l'incident.
export default function PaymentPanel({ token }) {
  const [accounts, setAccounts] = useState([]);
  const [dst, setDst] = useState("");
  const [amount, setAmount] = useState("10.00");
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);

  const refresh = async () => {
    try {
      setAccounts(await getAccounts(token));
      setError(null);
    } catch (e) {
      setError(e.message);
    }
  };

  useEffect(() => { refresh(); }, []);

  const submit = async (e) => {
    e.preventDefault();
    setResult(null);
    setError(null);
    try {
      const src = accounts[0]?.id;
      const tx = await createTransaction(token, {
        src_account: src,
        dst_account: Number(dst),
        amount,
      });
      setResult(`Transaction ${tx.reference} : ${tx.status} (${tx.amount} €)`);
      refresh();
    } catch (e) {
      setError(e.message);
    }
  };

  return (
    <div className="rounded-lg bg-slate-900 border border-slate-700 p-4 space-y-3">
      <h2 className="font-semibold">Espace paiement</h2>
      <div className="space-y-1">
        {accounts.map((a) => (
          <div key={a.id} className="flex justify-between text-sm">
            <span className="font-mono">#{a.id} {a.iban_fake}</span>
            <span className="text-emerald-400">{a.balance} {a.currency}</span>
          </div>
        ))}
      </div>
      <form onSubmit={submit} className="space-y-2">
        <input
          className="w-full bg-slate-800 rounded px-3 py-2 text-sm"
          placeholder="Compte destinataire (id)"
          value={dst}
          onChange={(e) => setDst(e.target.value)}
          required
        />
        <input
          className="w-full bg-slate-800 rounded px-3 py-2 text-sm"
          placeholder="Montant"
          value={amount}
          onChange={(e) => setAmount(e.target.value)}
          required
        />
        <button className="w-full bg-sky-600 hover:bg-sky-500 rounded px-3 py-2 text-sm font-semibold">
          Initier la transaction
        </button>
      </form>
      {result && <div className="text-emerald-400 text-sm">{result}</div>}
      {error && <div className="text-red-400 text-sm">{error}</div>}
    </div>
  );
}
