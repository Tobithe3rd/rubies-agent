import next from "eslint-config-next";

const config = [
  ...next,
  {
    ignores: [
      ".next/**",
      "node_modules/**",
      "next-env.d.ts",
      // Vendored AI Elements sources are copied in as-is.
      "components/ai-elements/**",
    ],
  },
];

export default config;
