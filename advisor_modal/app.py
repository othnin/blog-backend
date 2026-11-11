"""The thales advisor's production brain: Ollama + phi4-mini on Modal.

The advisor in src/thales/advisor/ talks to whatever answers at
OLLAMA_BASE_URL. In local dev that is a laptop Ollama on
http://localhost:11434; in production it is this app. The URL is the only
wiring -- no backend code changes are involved in either case.

What this app does:

- runs Ollama with phi4-mini on an L4 GPU (a T4 pool is the fallback),
  keeping the model weights on a Modal Volume (downloaded once, not per
  deploy),
- exposes Ollama's HTTP API behind a token-gated reverse proxy: only
  requests whose path starts with /<ADVISOR_TOKEN>/ reach the model, and
  everything else gets an ordinary 404. Ollama itself has no authentication
  anywhere, so the token is the only thing between the public URL and
  strangers spending GPU time on it,
- scales to zero: fifteen minutes after the last request the container
  sleeps and stops billing. The first request after a quiet stretch pays
  a cold start (container boot + weights into VRAM + a warmup generation
  that absorbs one-time GPU costs -- roughly 150 s all told, which can
  outlast both the advisor's 90 s timeout and Modal's edge limit, so that
  one question degrades to the offline advisor and the retry lands on a
  warm brain); questions during an active session answer in 1-3 s.

One-time setup and deploys are documented in advisor_modal/README.md.
"""

import os
import secrets
import subprocess
import time

import modal

MODEL = "phi4-mini"
OLLAMA_PORT = 11434  # Ollama, loopback only -- the proxy is its sole client
PROXY_PORT = 8000  # the token-gated proxy Modal exposes to the internet

image = (
    modal.Image.debian_slim(python_version="3.11")
    # zstd is needed by Ollama's install script to unpack its tarball.
    .apt_install("curl", "zstd")
    .run_commands("curl -fsSL https://ollama.com/install.sh | sh")
    .pip_install("fastapi", "httpx")
    .env(
        {
            # Loopback: only the proxy inside this container talks to Ollama.
            "OLLAMA_HOST": f"127.0.0.1:{OLLAMA_PORT}",
            # Weights live on the mounted Modal Volume, not in the image.
            "OLLAMA_MODELS": "/models",
            # Keep the weights in VRAM for the container's whole life; the
            # container itself sleeps after scaledown_window.
            "OLLAMA_KEEP_ALIVE": "-1",
        }
    )
)

volume = modal.Volume.from_name("thales-advisor-models", create_if_missing=True)

app = modal.App("thales-advisor", image=image)


def _start_ollama(timeout: int = 180) -> None:
    """Start `ollama serve` and block until it answers /api/version."""
    import httpx

    subprocess.Popen(["ollama", "serve"])
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            httpx.get(f"http://127.0.0.1:{OLLAMA_PORT}/api/version", timeout=5)
            return
        except httpx.TransportError:
            # Not up yet. Ollama binds its port before it is ready to
            # answer (GPU discovery happens first), so a probe that
            # connects and then times out still means "starting" -- the
            # whole TransportError family counts as "keep waiting".
            time.sleep(1)
    raise RuntimeError("ollama serve did not come up")


def _ensure_model() -> None:
    """Pull the model if the volume does not carry it, then warm the GPU."""
    import httpx

    # `ollama show` validates that the model is loadable (manifest and
    # blobs), unlike `ollama list`, which only reads the manifest.
    show = subprocess.run(["ollama", "show", MODEL], capture_output=True)
    if show.returncode != 0:
        subprocess.run(["ollama", "rm", MODEL], capture_output=True)
        subprocess.run(["ollama", "pull", MODEL], check=True)
        volume.commit()

    # Warm the brain before serving. Loading the weights alone (an empty
    # prompt) is not enough: measured on an L4, the first real compute
    # after a bare load pays ~55 s of one-time costs (kernel setup,
    # CUDA-graph capture, GPU clock ramp) and the next requests still pay
    # ~11 s each. One real generation with a medium prompt absorbs those,
    # so the first learner question after a cold start is fast. The
    # OLLAMA_KEEP_ALIVE=-1 env var keeps the weights resident afterwards.
    # Warmup failure is non-fatal: the app still comes up, and the first
    # request would then pay these costs instead -- slow but correct.
    try:
        warmup = httpx.post(
            f"http://127.0.0.1:{OLLAMA_PORT}/api/generate",
            json={
                "model": MODEL,
                "prompt": (
                    "You are a helpful assistant in a research laboratory. "
                    "Write one short paragraph summarizing why careful "
                    "laboratory notebooks matter, mentioning dated entries, "
                    "repeated measurements, and honest records of failures. "
                    "Keep it under sixty words and then stop."
                ),
                "stream": False,
                "keep_alive": -1,
                "options": {"num_predict": 64},
            },
            timeout=300,
        )
        warmup.raise_for_status()
        seconds = warmup.json().get("total_duration", 0) / 1e9
        print(f"advisor: warmup generation took {seconds:.1f}s", flush=True)
    except (httpx.HTTPError, ValueError) as exc:
        print(f"advisor: warmup skipped ({exc!r})", flush=True)


@app.function(volumes={"/models": volume})
def pull_model(model_name: str = MODEL) -> None:
    """Fill the volume with a model (CPU only, no GPU billed).

    Run once before the first deploy so the web endpoint's first cold start
    never has to download weights:

        modal run advisor_modal/app.py::pull_model --model-name phi4-mini

    Also the way to add a model for a future ADVISOR_MODEL swap.
    """
    _start_ollama()
    subprocess.run(["ollama", "pull", model_name], check=True)
    volume.commit()


@app.function(
    # L4 preferred (24 GB VRAM, plentiful capacity); T4 as a fallback pool.
    # A single GPU type is fine too, but the list keeps one scarce pool from
    # queueing learner questions behind "acquiring capacity" messages.
    gpu=["L4", "T4"],
    # Sleep (and stop billing) 15 min after the last request. Long enough
    # that a learner pondering between questions keeps the warm brain;
    # each wake-up costs at most ~$0.20 of idle L4 time.
    scaledown_window=900,
    volumes={"/models": volume},
    secrets=[modal.Secret.from_name("thales-advisor-token")],
)
@modal.concurrent(max_inputs=100)
@modal.asgi_app()
def advisor():
    """The brain itself: a token-gated reverse proxy over local Ollama."""
    import httpx
    from fastapi import FastAPI, Request
    from fastapi.responses import Response

    _start_ollama()
    print("advisor: ollama is up", flush=True)
    _ensure_model()
    print("advisor: model warm, serving", flush=True)

    token = os.environ["ADVISOR_TOKEN"]

    web = FastAPI(docs_url=None, openapi_url=None, redoc_url=None)
    client = httpx.AsyncClient(
        base_url=f"http://127.0.0.1:{OLLAMA_PORT}",
        timeout=600.0,  # generation can be slow; Ollama has no per-request cap
    )

    def token_ok(candidate: str) -> bool:
        # compare_digest raises on non-ASCII input, and URLs can carry it.
        try:
            return secrets.compare_digest(candidate, token)
        except TypeError:
            return False

    @web.api_route("/{path:path}", methods=["GET", "POST"])
    async def proxy(request: Request, path: str) -> Response:
        # Only /<token>/... reaches Ollama; anything else -- including a
        # wrong token -- is an ordinary 404, indistinguishable from a miss.
        prefix, _, rest = path.partition("/")
        if not rest or not token_ok(prefix):
            return Response(status_code=404)
        upstream = await client.request(
            request.method,
            f"/{rest}",
            params=request.query_params,
            content=await request.body(),
            headers={
                "Content-Type": request.headers.get(
                    "content-type", "application/json"
                )
            },
        )
        return Response(
            content=upstream.content,
            status_code=upstream.status_code,
            headers={
                "Content-Type": upstream.headers.get(
                    "content-type", "application/json"
                )
            },
        )

    return web
