# Sourcebook

A local workspace for reviewing commitments in notes and briefs. It extracts proposed tasks using an NVIDIA model on Nebius, then checks every quotation against the original document and line before displaying it. Click a quotation to inspect its context; mark reviewed items and export the result as JSON.

## Run

Python 3.11 or later; no packages to install. Run these commands from this folder:

```powershell
python app.py
```

Open <http://127.0.0.1:8766>. The labelled worked example requires no account and makes **no AI request**.

To enable actual inference, set `NEBIUS_API_KEY` in this process environment using your normal secret-management method, then restart the server. Do not paste a key into chat, the browser, source files or a public repository. Optional environment variables:

| Variable | Default |
|---|---|
| `NEBIUS_MODEL` | `nvidia/nemotron-3-super-120b-a12b` |
| `NEBIUS_BASE_URL` | `https://api.tokenfactory.us-central1.nebius.com/v1` |

Use a model/region available to your account. The server restricts destinations to HTTPS Nebius subdomains on the standard HTTPS port and requires an `nvidia/` model for this build. Provider redirects are rejected, so the key and document payload cannot be forwarded to a redirected destination. No `.env` file is loaded automatically. The status indicator checks whether a key is configured; a successful real request is still needed to establish account/model access.

The optional `.env.example` documents variable names; copying it does not configure the server. Supply variables through your shell or secret manager. If port 8766 is occupied, use `python app.py --port 8767`. Stop the process with Ctrl+C.

## What works

- Add multiple UTF-8 `.txt` / `.md` files or paste text; maximum 10 documents, 80,000 characters total.
- Numbered source lines are sent to Nebius's chat-completions API only after **Review with Nebius**.
- Unknown documents, wrong line numbers and fabricated quotations are excluded.
- At most 30 proposed actions are processed; additional entries are reported as rejected. Whitespace-only quotations are rejected.
- Owners and dates absent from the cited words become “not stated”. Relative dates stay literal.
- An empty result, provider error or missing key is shown honestly, without replacement with an example.
- No documents or results are persisted by the server. An explicit export downloads them to your computer.

The browser loses its in-memory workspace when reloaded. Nebius receives the documents when inference is requested; “local app” does not mean inference happens on-device.

## Tests and verification

```powershell
python -m unittest -v
node --check static/app.js
```

28 tests passed in the 3 October 2026 revision. Tests cover quotation rejection, attribution, limits, provider request construction, redirect rejection, bounded provider output, token-usage filtering, HTTP assets, CSRF, missing credentials and evaluation provenance. Provider transport is a test double: **this revision has not verified a live Nebius response**. The earlier browser checks covered the worked example, source inspection, and horizontal overflow at mobile/tablet widths; captures remain in `screenshots/`. The visual interface was not changed in this revision.

The model contract is always a JSON object: `{"actions":[]}` when there are no commitments. A bare array is invalid. This matches the API's JSON-object response mode and the application validator.

## Reproducible model evaluation

`fixtures/evaluation.json` contains ten **hand-authored synthetic** cases: explicit English and Spanish commitments, absent commitments, negation/hypotheticals, an instruction-injection example, a relative date, unspecified individual ownership, conflicting documents, CRLF line numbering and Unicode quotations. The expected source anchors are evaluation annotations, not model responses.

Prepare an offline report without a key or network request:

```powershell
python evaluate.py --prepare --output evaluation/preparation.json
```

It records fixture, prompt, application and evaluator hashes; `response_count` is zero and `metrics` is null. Choose a new output filename if one already exists. The prepared report bundled with this revision is `evaluation/preparation-2026-10-03.json`.

After the account, NVIDIA model and regional endpoint have been configured, explicitly request a measured run:

```powershell
python evaluate.py --run --output evaluation/run-2026-10-03.json
```

This makes **one Nebius request per case**, using the same request and validation functions as the app, and may consume account credits. It sends only the synthetic fixture documents. No requests are made without `--run`; no `.env` file is read. Existing reports are never overwritten. Keep failed runs as well as successful runs when comparing revisions.

A live report retains parsed model responses, rejected counts, accepted actions, case errors, observed latency and provider-reported token counts. Metrics are calculated only when the real provider path returns at least one parsed response. An injected test transport produces `mode: "test-double"` with `metrics: null`. If every provider request fails, metrics also remain null.

| Measurement | Meaning and limit |
|---|---|
| Validated case rate | Cases returning a valid actions object divided by the entire suite; failures remain in the denominator. |
| Citation/shape acceptance | Proposed actions passing the application's source-location and structure checks; null when no actions were proposed. It is not semantic accuracy. |
| Expected anchor recall | Annotated source anchors present in accepted quotations, divided by all expected anchors in the suite. Duplicate actions cannot inflate the matched-anchor count. |
| Unmatched accepted actions | Accepted actions whose quotations contain none of that case's expected anchors. Requires review; not automatically a false positive. |
| Empty response rate | Valid answered no-commitment cases returning an empty actions list. The number of answered cases is included. |
| Latency and token usage | Measurements from parsed provider responses; missing token counters remain null. No price or throughput estimate is inferred. |

Every action includes blank fields for a later human review of interpretation and owner/date attribution. `semantic_accuracy` remains null: exact quotations do not prove that a task is supported. Ten fixtures are a development check, not evidence of general accuracy, prompt-injection resistance or production readiness. No model scores have been filled in for this revision.

## Design and boundaries

The interface keeps source material next to proposed actions and uses quiet editorial typography. Controls are native HTML with labels, focus indicators and reduced-motion support. It follows the supplied document-review preferences without cursor effects.

This is a single-user local MVP, not a hosted service. It has no authentication, PDF/OCR ingestion, background job queue or multi-user storage. Exact-source verification proves a quotation's location, **not** that a proposed task correctly interprets it. Human review remains necessary. The model cannot send email, run tools or execute document instructions.

## Technical references

- [Nebius API authentication and chat completions](https://docs.tokenfactory.nebius.com/api-reference/introduction)
- [NVIDIA model / regional endpoint example](https://nebius.com/services/token-factory/nemotron)
- [Competition submission requirements](https://nebiusglobalaihackathon.devpost.com/rules)

## Project status and license

Built with OpenAI Codex assistance for the Nebius × NVIDIA hackathon. The source and local tests are available under the MIT license. The worked example is synthetic; live provider evaluation and the competition submission are still pending. No external user study or measured model score is claimed.
