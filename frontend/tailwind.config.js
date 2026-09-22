/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      colors: {
        ink: "#090b10",
        panel: "#11151d",
        elevated: "#171c26",
        line: "#28313e",
        accent: "#7289da",
        mint: "#57d9a3",
      },
      boxShadow: {
        panel: "0 18px 50px rgba(0, 0, 0, .24)",
      },
    },
  },
  plugins: [],
};
