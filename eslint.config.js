// Lint rules for the web interface (npm run lint)
import js from "@eslint/js";
import globals from "globals";

export default [
  { ignores: ["ghostscribe/static/vendor/**"] },
  js.configs.recommended,
  {
    files: ["ghostscribe/static/**/*.js"],
    languageOptions: {
      ecmaVersion: "latest",
      sourceType: "module",
      globals: { ...globals.browser, marked: "readonly", DOMPurify: "readonly" }, // vendor/*.js
    },
    rules: {
      eqeqeq: "error",
      "no-var": "error",
      "prefer-const": "error",
      "no-unused-vars": ["error", { caughtErrors: "none" }],
    },
  },
  {
    files: ["eslint.config.js"],
    languageOptions: { sourceType: "module", globals: globals.node },
  },
];
