/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: ["Inter", "system-ui", "sans-serif"],
        mono: ["\"IBM Plex Mono\"", "ui-monospace", "monospace"],
      },
      colors: {
        ink: "#12161C",
        slate: {
          muted: "#5B6472",
        },
        surface: "#F4F6F9",
        border: "#E2E6EC",
        brand: {
          DEFAULT: "#0E6E5B",
          tint: "#E4F4EF",
          dark: "#0A5548",
        },
        amber: {
          DEFAULT: "#B4770A",
          tint: "#FDF1DD",
        },
        danger: {
          DEFAULT: "#B3261E",
          tint: "#FCE8E6",
        },
        neutral2: {
          DEFAULT: "#3E5C76",
          tint: "#E7EDF3",
        },
      },
      boxShadow: {
        card: "0 1px 2px rgba(18, 22, 28, 0.06), 0 1px 1px rgba(18, 22, 28, 0.04)",
      },
      keyframes: {
        stamp: {
          "0%": { transform: "scale(1)" },
          "40%": { transform: "scale(0.94)" },
          "100%": { transform: "scale(1)" },
        },
        "fade-in": {
          "0%": { opacity: 0, transform: "translateY(4px)" },
          "100%": { opacity: 1, transform: "translateY(0)" },
        },
      },
      animation: {
        stamp: "stamp 220ms ease-out",
        "fade-in": "fade-in 180ms ease-out",
      },
    },
  },
  plugins: [],
};
