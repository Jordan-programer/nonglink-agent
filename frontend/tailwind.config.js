/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./src/**/*.{js,ts,jsx,tsx,mdx}",
    "./frontend/src/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  darkMode: ["selector", '[data-theme="dark"]'],
  theme: {
    extend: {
      colors: {
        bg: "var(--color-bg)",
        sidebar: "var(--color-sidebar)",
        "sidebar-hover": "var(--color-sidebar-hover)",
        "sidebar-active": "var(--color-sidebar-active)",
        surface: "var(--color-surface)",
        "user-block": "var(--color-user-block)",
        text: "var(--color-text)",
        "text-secondary": "var(--color-text-secondary)",
        border: "var(--color-border)",
        accent: "var(--color-accent)",
        "accent-hover": "var(--color-accent-hover)",
        success: "var(--color-success)",
        error: "var(--color-error)",
      },
      fontFamily: {
        sans: ["var(--font-sans)", "Instrument Sans", "system-ui", "-apple-system", "sans-serif"],
        serif: ["var(--font-serif)", "Newsreader", "Georgia", "serif"],
        stencil: ["var(--font-stencil)", "Big Shoulders Stencil Display", "Impact", "sans-serif"],
      },
      borderRadius: {
        textbox: "24px",
        user: "16px",
        btn: "10px",
        item: "8px",
        talao: "4px",
      },
      boxShadow: {
        soft: "var(--shadow-soft)",
        menu: "var(--shadow-menu)",
      },
    },
  },
  plugins: [],
};
