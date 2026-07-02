import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}"
  ],
  theme: {
    extend: {
      colors: {
        ink: "#050816",
        aurora: "#53f2ff",
        ember: "#ff7a18",
        neon: "#9fff8c",
        panel: "#0b1225"
      },
      boxShadow: {
        glow: "0 0 0 1px rgba(83,242,255,0.18), 0 18px 60px rgba(8,15,40,0.45)",
        ember: "0 0 0 1px rgba(255,122,24,0.25), 0 18px 60px rgba(255,122,24,0.15)"
      },
      backgroundImage: {
        grid: "linear-gradient(rgba(255,255,255,0.05) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,0.05) 1px, transparent 1px)"
      }
    }
  },
  plugins: []
};

export default config;
