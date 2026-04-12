import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: {
          DEFAULT: "#0f0f10",
          soft: "#1c1c1f",
          muted: "#6b6b72",
        },
        canvas: {
          DEFAULT: "#fafaf7",
          card: "#ffffff",
          border: "#ececec",
        },
        accent: {
          DEFAULT: "#0f0f10",
          soft: "#f1f1ec",
        },
      },
      fontFamily: {
        sans: [
          "ui-sans-serif",
          "system-ui",
          "-apple-system",
          "Segoe UI",
          "Inter",
          "sans-serif",
        ],
        display: ["ui-serif", "Georgia", "Cambria", "serif"],
      },
      borderRadius: {
        xl: "1rem",
        "2xl": "1.25rem",
      },
      boxShadow: {
        card: "0 1px 2px rgba(15,15,16,0.04), 0 8px 24px rgba(15,15,16,0.04)",
      },
    },
  },
  plugins: [],
};

export default config;
