# Sourcebook Worker

Public worked example: https://sourcebook-eazyhood.bmhennessy.chatgpt.site

Sites deployment of Sourcebook's document-to-action review. The original Python
application remains a separate local build. This Worker serves the same example,
document limits, exact-citation checks and Nebius request contract.

```sh
npm install
npm test
npm run build
npm run validate
```

Node.js 24 is used for local tests, including SQLite quota checks. The deployed
Worker has no package imports: the build embeds its code and public assets in
`dist/server/index.js`.

The initial public site has no Nebius key and serves only the labelled worked
example. A key alone never enables inference. Live requests also require an
explicit enable flag, the exact origin, a daily limit from 1 to 20, and the D1
counter. Every attempted call reserves quota before contacting the provider;
failed calls count too. Review available credits before enabling live mode.

Store `NEBIUS_API_KEY` only as a backend secret. The `.env.example` contains no
credentials. Source documents, result text and user identities are not persisted;
D1 stores only a UTC day and the number of inference attempts.

The original UI is preserved. Deployment changes add public-demo wording, a
favicon, a file-read operation lock and optional read-only WebMCP access to the
current visible review. Live WebMCP testing has not been performed.
