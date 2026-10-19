/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      // Palette "impression fiduciaire" : papier, encre, pétrole des billets.
      colors: {
        paper: "#F3F5F2",
        ink: "#1B2B28",
        rule: "#DCE2DD",
        petrol: { DEFAULT: "#0F5257", deep: "#0A3D41" },
        line: "#8CC2BA",
        credit: "#23704B",
        debit: "#A3312A",
        warn: "#8A5A00",
      },
      fontFamily: {
        // Pile système : la démo doit fonctionner hors ligne (pas de CDN de polices).
        sans: ['"Segoe UI Variable Text"', '"Segoe UI"', "system-ui", "-apple-system", "Roboto", "sans-serif"],
      },
      boxShadow: {
        card: "0 18px 40px -18px rgba(10, 61, 65, 0.55)",
      },
    },
  },
  plugins: [],
};
