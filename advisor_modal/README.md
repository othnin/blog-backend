# The advisor's production brain (Modal)

`app.py` deploys the lab's literature-advisor model runtime — Ollama with
**phi4-mini** on an L4 GPU (with T4 as a fallback pool) — as a scale-to-zero
Modal app. The backend's advisor (`src/thales/advisor/`) calls it through
`OLLAMA_BASE_URL`; that single variable is the whole wiring, on the Django
side and here.

Why Modal and not another always-on Ollama service: the lab gets a handful
of questions a day, so paying ~$35–40/month of resident RAM on Railway made
no sense. Here the brain sleeps when idle, wakes on a question, and Modal's
included monthly credits comfortably cover lab-sized traffic.

## One-time setup

```bash
pipx install modal                      # or: pip install modal
modal token new                        # browser login, once

# The token gates the public URL (Ollama itself has no authentication).
# Save the printed token — it must also go into the backend's URL variable.
TOKEN=$(openssl rand -hex 16) && echo "TOKEN=$TOKEN"
modal secret create thales-advisor-token ADVISOR_TOKEN=$TOKEN

# Fill the model volume once (CPU only, nothing is billed for GPU here).
modal run advisor_modal/app.py::pull_model --model-name phi4-mini

# Deploy. The output prints the app's URL.
modal deploy advisor_modal/app.py
```

The brain's base URL is the printed URL **plus the token as a path prefix**,
e.g. `https://<workspace>--<label>.modal.run/<token>` — requests to any other
path get an ordinary 404.

## Wiring the backend

On the deploying host (Railway → blog-backend → Variables):

```
OLLAMA_BASE_URL=https://<workspace>--<label>.modal.run/<token>
OLLAMA_TIMEOUT=90
```

`OLLAMA_TIMEOUT=90` is recommended with this brain: a cold start can run
~150 s (see below), which the advisor treats as unreachable — one degraded
question, then a retry lands warm. Local development keeps its defaults
(`http://localhost:11434`, 60 s) — nothing to set.

Nothing in this folder ships in the backend's Docker image (the Dockerfile
copies only `./src`), and `railway.toml`'s watch patterns do not include it,
so changing the brain never redeploys the backend.

## Cost model

- An L4 is billed **only while a container is alive** ($0.000222/s ≈
  $0.80/hr): the request itself plus a 15-minute tail
  (`scaledown_window`), so an active session stays warm and overnight the
  bill is zero. Each wake-up costs at most ~$0.20 of idle tail.
- A typical question is a few seconds of L4 time. Even an hour of classroom
  use every school day stays inside Modal's included monthly credits.
- Weights are stored once on a Modal Volume (`thales-advisor-models`), not
  re-downloaded on cold starts.

## Behaviour to expect

- **Warm questions are the norm:** inside a session (or within 15 minutes
  of the last question) the brain answers in **1–3 s** — roughly 600
  tokens/s prompt processing, ~80 tokens/s generation on the L4.
- **Cold start:** the first question after a quiet stretch wakes the
  container, which boots, loads the weights, and runs a warmup generation
  that absorbs the L4's one-time costs (kernel setup, CUDA-graph capture,
  clock ramp — measured at ~100 s after a bare load). All told this can
  exceed ~150 s, which outlasts both the advisor's 90 s timeout and
  Modal's edge limit — so **that one question degrades to the offline
  advisor** (the question is refunded, nothing burns), and asking again
  seconds later lands on the fully warm brain. The warmup is what makes
  the *second* question sub-second instead of another ~55 s.
- **Failures are graceful by design:** if the brain is unreachable, the
  advisor returns 503 and the desk silently answers from its offline
  keyword advisor; since a failed query does not consume a question, the
  learner can simply ask again.
- **Logs:** `modal app logs thales-advisor` (or the Modal dashboard). The
  app prints its startup milestones (`advisor: ollama is up`, `advisor:
  warmup generation took ...s`, `advisor: model warm, serving`), and
  Ollama's own log lines land there too. The backend log signature for an
  unreachable brain is `OLLAMA_UNREACHABLE` plus a 503 on
  `/api/thales/advisor/chat/` — that means the URL/token is wrong or
  Modal is down, not that anything in Django is broken. Note that
  `modal app stop thales-advisor` does not merely sleep the container — it
  disables the deployment entirely (the URL then answers
  `invalid function call`); redeploy with `modal deploy` to bring it back.

## Swapping the model

Pull the new model onto the volume, then point the backend at it:

```bash
modal run advisor_modal/app.py::pull_model --model-name <model>
```

and set `ADVISOR_MODEL=<model>` on the backend (it overrides
`src/thales/advisor/config.json`). Match the GPU size to the model — phi4-mini
fits an L4 (or T4) with room to spare.

## Developing this app

`modal serve advisor_modal/app.py` runs it ephemerally with live reload and
a temporary URL — useful for trying changes without a deploy. The deploy
target is whatever `modal.App("thales-advisor", ...)` is named; renaming it
changes the URL and requires updating the backend variable.
