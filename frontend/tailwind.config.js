/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        brand: {
          50: "#eef5ff",
          100: "#d8e7ff",
          200: "#b8d3ff",
          300: "#87b5ff",
          400: "#4f8cff",
          500: "#2866ff",
          600: "#1247f0",
          700: "#0d36c2",
          800: "#10329b",
          900: "#132f7b",
        },
      },
      keyframes: {
        "fade-in": {
          "0%": { opacity: "0", transform: "translateY(4px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
      },
      animation: {
        "fade-in": "fade-in 0.25s ease-out both",
      },
    },
  },
  plugins: [
    require('@tailwindcss/typography'),
  ],
};
