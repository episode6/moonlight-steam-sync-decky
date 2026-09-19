// Flat config: typescript-eslint recommended + react-hooks, over src/ only.
// probes/ (the PR-0 device-probe kit, its own throwaway plugin) is ignored
// explicitly, as are build output and dependencies.
import js from "@eslint/js";
import reactHooks from "eslint-plugin-react-hooks";
import tseslint from "typescript-eslint";

export default tseslint.config(
  {
    ignores: ["dist/**", "out/**", "node_modules/**", "probes/**", "backend/**", "**/*.js"],
  },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    files: ["src/**/*.{ts,tsx}"],
    plugins: { "react-hooks": reactHooks },
    rules: {
      ...reactHooks.configs.recommended.rules,
      "@typescript-eslint/no-unused-vars": ["error", { argsIgnorePattern: "^_" }],
    },
  },
  {
    // src/lib/ is pure (spec 3.6.3): no Decky, no React, so vitest can load
    // every module there and the logic stays testable off-device.
    files: ["src/lib/**/*.ts"],
    rules: {
      "no-restricted-imports": [
        "error",
        {
          patterns: [
            {
              group: ["@decky/*", "react", "react-dom", "react/*", "react-icons", "react-icons/*"],
              message: "src/lib/ must stay pure: no @decky/* or React imports (spec 3.6.3).",
            },
          ],
        },
      ],
    },
  },
);
