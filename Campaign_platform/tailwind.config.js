/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],

  theme: {
    colors: {
      transparent: "transparent",
      current: "currentColor",

      // Cogentix Branding
      cogentix: {
        navy: {
          DEFAULT: '#123056',
          50: '#f0f4f8',
          100: '#d9e2ec',
          200: '#bcccdc',
          300: '#9fb3c8',
          400: '#829ab1',
          500: '#627d98',
          600: '#486581',
          700: '#334e68',
          800: '#243b53',
          900: '#123056',
          950: '#0a1929',
        },
        orange: {
          DEFAULT: '#ff7a59',
          50: '#fff5f2',
          100: '#ffe8e1',
          200: '#ffd5c7',
          300: '#ffb8a0',
          400: '#ff9575',
          500: '#ff7a59',
          600: '#e85c3a',
          700: '#c44425',
          800: '#a13820',
          900: '#84321f',
          950: '#48160b',
        },
        green: {
          DEFAULT: '#10b981',
          50: '#ecfdf5',
          100: '#d1fae5',
          200: '#a7f3d0',
          300: '#6ee7b7',
          400: '#34d399',
          500: '#10b981',
          600: '#059669',
          700: '#047857',
          800: '#065f46',
          900: '#064e3b',
        },
      },

      background: {
        DEFAULT: '#f8fafc',
        secondary: '#f1f5f9',
        tertiary: '#e2e8f0',
      },

      text: {
        primary: '#111827',
        secondary: '#4b5563',
        muted: '#6b7280',
        light: '#9ca3af',
      },
    },

    fontFamily: {
      sans: [
        'Inter',
        '-apple-system',
        'BlinkMacSystemFont',
        'Segoe UI',
        'Roboto',
        'Oxygen',
        'Ubuntu',
        'Cantarell',
        'sans-serif',
      ],
    },

    fontSize: {
      xs: ["0.75rem", { lineHeight: "1rem" }],
      sm: ["0.875rem", { lineHeight: "1.25rem" }],
      base: ["1rem", { lineHeight: "1.5rem" }],
      lg: ["1.125rem", { lineHeight: "1.75rem" }],
      xl: ["1.25rem", { lineHeight: "1.75rem" }],
      "2xl": ["1.5rem", { lineHeight: "2rem" }],
      "3xl": ["1.875rem", { lineHeight: "2.25rem" }],
      "4xl": ["2.25rem", { lineHeight: "2.5rem" }],
    },

    spacing: {
      18: "4.5rem",
      22: "5.5rem",
      72: "18rem",
      84: "21rem",
      96: "24rem",
    },

    boxShadow: {
      card: "0 1px 3px 0 rgb(0 0 0 / 0.1), 0 1px 2px -1px rgb(0 0 0 / 0.1)",
      "card-hover": "0 10px 15px -3px rgb(0 0 0 / 0.1), 0 4px 6px -4px rgb(0 0 0 / 0.1)",
      sidebar: "4px 0 6px -1px rgb(0 0 0 / 0.1)",
      topbar: "0 1px 3px 0 rgb(0 0 0 / 0.1)",
      dropdown: "0 10px 25px -5px rgb(0 0 0 / 0.1), 0 8px 10px -6px rgb(0 0 0 / 0.1)",
      button: "0 1px 2px 0 rgb(0 0 0 / 0.05)",
      "button-hover": "0 4px 6px -1px rgb(0 0 0 / 0.1), 0 2px 4px -2px rgb(0 0 0 / 0.1)",
    },

    borderRadius: {
      xl: "0.75rem",
      "2xl": "1rem",
      "3xl": "1.5rem",
    },

    animation: {
      "fade-in": "fadeIn 0.2s ease-out",
      "slide-down": "slideDown 0.2s ease-out",
      "slide-up": "slideUp 0.2s ease-out",
    },

    keyframes: {
      fadeIn: {
        "0%": { opacity: "0" },
        "100%": { opacity: "1" },
      },
      slideDown: {
        "0%": { opacity: "0", transform: "translateY(-10px)" },
        "100%": { opacity: "1", transform: "translateY(0)" },
      },
      slideUp: {
        "0%": { opacity: "0", transform: "translateY(10px)" },
        "100%": { opacity: "1", transform: "translateY(0)" },
      },
    },
  },

  plugins: [],
};
