import Guilloche from "./Guilloche.jsx";
import { formatEur } from "../format.js";

// Le compte présenté comme une carte : solde, IBAN, titulaire.
export default function AccountCard({ account, holder }) {
  return (
    <section
      aria-label="Compte courant"
      className="relative overflow-hidden rounded-[22px] bg-petrol text-white shadow-card aspect-[1.586] max-w-md w-full p-6 sm:p-7 flex flex-col"
    >
      <Guilloche className="absolute inset-0 h-full w-full text-line/25" />
      <div className="relative flex items-start justify-between">
        <span className="text-[15px] font-semibold">Compte courant</span>
        <span className="text-[13px] text-white/70">EUR</span>
      </div>

      <div className="relative mt-auto">
        <p className="text-[13px] text-white/70">Solde disponible</p>
        <p className="tabular text-[clamp(2rem,7vw,2.75rem)] font-semibold leading-tight tracking-tight">
          {account ? formatEur(account.balance) : "…"}
        </p>
      </div>

      <div className="relative mt-5 flex items-end justify-between gap-4 text-[14px]">
        <span className="tabular tracking-[0.08em]">{account?.iban_fake ?? "—"}</span>
        <span className="capitalize text-white/85">{holder}</span>
      </div>
    </section>
  );
}
