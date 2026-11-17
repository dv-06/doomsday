/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: "#050505",
        charcoal: "#0b0b0d",
        graphite: "#121216",
        slate: "#1b1b21",
        line: "#26262e",
        ember: "#e2571e",
        flame: "#f97316",
        sand: "#f4e7dd",
        ash: "#a9a9b8",
      },
      fontFamily: {
        display: ['"Bebas Neue"', "Impact", "system-ui", "sans-serif"],
        sans: ['"Inter"', "system-ui", "-apple-system", "Segoe UI", "sans-serif"],
        mono: ['"JetBrains Mono"', "ui-monospace", "SFMono-Regular", "monospace"],
      },
      boxShadow: {
        ember: "0 0 0 1px rgba(226,87,30,0.25), 0 18px 60px -32px rgba(226,87,30,0.55)",
        card: "0 24px 60px -40px rgba(0,0,0,0.9)",
      },
      backgroundImage: {
        "ember-glow": "radial-gradient(circle at 20% 0%, rgba(226,87,30,0.18), transparent 55%)",
        grain: "url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='120' height='120'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='2'/%3E%3C/filter%3E%3Crect width='120' height='120' filter='url(%23n)' opacity='0.035'/%3E%3C/svg%3E\")",
      },
      keyframes: {
        pulseDot: {
          "0%,100%": { opacity: "1", transform: "scale(1)" },
          "50%": { opacity: "0.35", transform: "scale(0.78)" },
        },
        rise: {
          "0%": { opacity: "0", transform: "translateY(10px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
      },
      animation: {
        "pulse-dot": "pulseDot 2.4s ease-in-out infinite",
        rise: "rise 0.45s ease-out both",
      },
    },
  },
  plugins: [],
};
