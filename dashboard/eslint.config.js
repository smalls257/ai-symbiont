// QG-FE-01. eslint 9.x flat config: @eslint/js recommended plus the three rules the standard
// names. The page is a classic script (no bundler), hence sourceType "script".
import js from "@eslint/js";
import globals from "globals";

export default [
  { ignores: ["node_modules/**"] },
  js.configs.recommended,
  {
    languageOptions: { sourceType: "script", globals: globals.browser },
    rules: {
      "no-unused-vars": "error",
      eqeqeq: "error",
      "no-implicit-globals": "error",
    },
  },
  { files: ["eslint.config.js"], languageOptions: { sourceType: "module", globals: globals.node } },
];
