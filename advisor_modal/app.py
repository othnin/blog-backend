"""The thales advisor's production brain: Ollama + phi4-mini on Modal.

The advisor in src/thales/advisor/ talks to whatever answers at
OLLAMA_BASE_URL. In local dev that is a laptop Ollama on
http://localhost:11434; in production it is this app. The URL is the only
wiring -- no backend code changes are involved in either case.

What this app does:

- runs Ollama with phi4-mini on a T4 GPU, keeping the model weights on a
  Modal Volume (downloaded once, not per deploy),
- exposes Ollama's HTTP API behind a token-gated reverse proxy: only
  requests whose path starts with /<ADVISOR_TOKEN>/ reach the model, and
  everything else gets an ordinary 404. Ollama itself has no authentication
  anywhere, so the token is the only thing between the public URL and
  strangers spending GPU time on it,
- scales to zero: five minutes after the last request the container sleeps
  and stops billing. The first request after a quiet stretch pays a cold
  start (container boot + weights into VRAM, roughly 20-30 s); requests
  during an active session are warm and fast.

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
        except httpx.ConnectError:
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

    # An empty prompt is accepted by /api/generate and forces the weights
    # into VRAM, so the first real request pays only generation time. The
    # OLLAMA_KEEP_ALIVE=-1 env var keeps them resident afterwards.
    httpx.post(
        f"http://127.0.0.1:{OLLAMA_PORT}/api/generate",
        json={"model": MODEL, "prompt": "", "keep_alive": -1},
        timeout=300,
    )


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
    gpu="T4",  # 16 GB VRAM; phi4-mini's ~2.5 GB q4 fits with room to spare
    scaledown_window=300,  # sleep (and stop billing) 5 min after the last request
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
    _ensure_model()

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
