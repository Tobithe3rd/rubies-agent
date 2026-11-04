import next from "eslint-config-next";

const generated = [
  ".next/**",
  "node_modules/**",
  "next-env.d.ts",
  // Vendored sources are copied in as-is.
  "components/ai-elements/**",
  "components/ui/**",
];

const storageGuard = [
  {
    name: "localStorage",
    message: "Only core/storage/chat-id-store.ts may touch browser storage.",
  },
  {
    name: "sessionStorage",
    message: "Only core/storage/chat-id-store.ts may touch browser storage.",
  },
  {
    name: "indexedDB",
    message: "Only core/storage/chat-id-store.ts may touch browser storage.",
  },
];

const storageProperties = [
  {
    object: "window",
    property: "localStorage",
    message: "Only core/storage/chat-id-store.ts may touch browser storage.",
  },
  {
    object: "window",
    property: "sessionStorage",
    message: "Only core/storage/chat-id-store.ts may touch browser storage.",
  },
  {
    object: "window",
    property: "indexedDB",
    message: "Only core/storage/chat-id-store.ts may touch browser storage.",
  },
  {
    object: "document",
    property: "cookie",
    message: "Only core/storage/chat-id-store.ts may touch browser storage.",
  },
];

const config = [
  ...next,
  {
    ignores: generated,
  },
  {
    files: ["**/*.{js,mjs,cjs,ts,tsx}"],
    rules: {
      "max-lines": [
        "error",
        { max: 250, skipBlankLines: true, skipComments: true },
      ],
      "no-restricted-globals": ["error", ...storageGuard],
      "no-restricted-properties": ["error", ...storageProperties],
    },
  },
  {
    files: ["features/chat/**/*.{ts,tsx}"],
    rules: {
      "no-restricted-imports": [
        "error",
        {
          patterns: [
            {
              group: ["@/features/panel", "@/features/panel/**", "**/features/panel/**"],
              message: "features/chat must not import features/panel.",
            },
          ],
        },
      ],
    },
  },
  {
    files: ["features/panel/**/*.{ts,tsx}"],
    rules: {
      "no-restricted-imports": [
        "error",
        {
          patterns: [
            {
              group: ["@/features/chat", "@/features/chat/**", "**/features/chat/**"],
              message: "features/panel must not import features/chat.",
            },
          ],
        },
      ],
    },
  },
  {
    files: ["core/**/*.{ts,tsx}"],
    rules: {
      "no-restricted-imports": [
        "error",
        {
          patterns: [
            {
              group: [
                "@/features/**",
                "@/app/**",
                "@/components/**",
                "**/features/**",
                "**/app/**",
                "**/components/**",
              ],
              message: "core must stay free of React features and app code.",
            },
          ],
        },
      ],
    },
  },
  {
    files: ["core/storage/chat-id-store.ts"],
    rules: {
      "no-restricted-globals": "off",
      "no-restricted-properties": "off",
    },
  },
];

export default config;
