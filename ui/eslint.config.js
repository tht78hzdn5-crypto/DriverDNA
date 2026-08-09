// Correctness-only, matching the Python side's ruff config (pyproject.toml
// [tool.ruff]): no style/formatting rules, just the classes of bug a human
// reviewer skims past — unused vars, undefined refs, and the two React
// hook mistakes (stale closures, conditional hooks) the render-parity
// crawler structurally cannot see since it only checks rendered numbers.
import js from "@eslint/js";
import reactHooks from "eslint-plugin-react-hooks";
import reactRefresh from "eslint-plugin-react-refresh";
import globals from "globals";

export default [
  {
    ignores: ["dist", "../src/driverdna/ui/static"],
  },
  {
    files: ["src/**/*.{js,jsx}"],
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: "module",
      parserOptions: { ecmaFeatures: { jsx: true } },
      globals: globals.browser,
    },
    plugins: {
      "react-hooks": reactHooks,
      "react-refresh": reactRefresh,
    },
    rules: {
      ...js.configs.recommended.rules,
      // Only the two long-established hook rules (stale closures, hooks
      // called conditionally) — eslint-plugin-react-hooks 7's "recommended"
      // set pulls in ~14 more React-Compiler-readiness rules (set-state-
      // in-effect, purity, immutability, ...) that are opinionated
      // architectural guidance, not the "this is a bug" class this gate is
      // scoped to, matching the Python side's correctness-only ruff config.
      "react-hooks/rules-of-hooks": "error",
      "react-hooks/exhaustive-deps": "warn",
      "react-refresh/only-export-components": "warn",
    },
  },
  {
    files: ["public/sw.js"],
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: "script",
      globals: globals.serviceworker,
    },
    rules: js.configs.recommended.rules,
  },
  {
    files: ["vite.config.js", "eslint.config.js"],
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: "module",
      globals: globals.node,
    },
    rules: js.configs.recommended.rules,
  },
];
