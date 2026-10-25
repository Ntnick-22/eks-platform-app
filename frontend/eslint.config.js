// ESLint (flat config). Runs in CI's check job inside the build stage image: `npm run lint`.
import js from "@eslint/js";
import reactHooks from "eslint-plugin-react-hooks";
import reactRefresh from "eslint-plugin-react-refresh";
import { defineConfig, globalIgnores } from "eslint/config";
import globals from "globals";

export default defineConfig([
  globalIgnores(["dist"]), // vite build output, not source
  {
    files: ["**/*.{js,jsx}"],
    extends: [
      js.configs.recommended, // core JS mistakes: unused/undefined variables, unreachable code...
      reactHooks.configs.flat.recommended, // rules of hooks + missing useEffect dependencies
      reactRefresh.configs.vite, // keeps Vite's hot reload working (components-only exports)
    ],
    languageOptions: {
      ecmaVersion: "latest",
      globals: globals.browser, // window, document, fetch... are defined in the browser
      parserOptions: { ecmaFeatures: { jsx: true } },
    },
  },
]);
