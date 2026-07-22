#!/usr/bin/env python3
"""Colab launcher for the full YaoBi Agent web UI.

The script is intentionally plain Python so a Colab cell can run it directly:

    !python colab/launch_yaobi_colab.py --backend mock --ngrok-token "$NGROK_AUTHTOKEN"

It installs the project, configures one of the supported Tao/LLM providers, starts
``backend.server`` and optionally opens a public ngrok tunnel.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


REPO_URL = "https://github.com/pariskang/Yao-Bi-Agent.git"
DEFAULT_MODEL_BY_BACKEND = {
    "transformers": "CMLM/Dao1-30b-a3b",
    "poe": "Gemini-3.1-Pro",
    "minimax": "abab6.5s-chat",
    "azure": "gpt-4o-mini",
    "openai": "gpt-4o-mini",
    "anthropic": "claude-3-5-sonnet-latest",
    "http": "CMLM/Dao1-30b-a3b",
    "mock": "mock-tao",
    "disabled": "disabled",
}


def run(cmd: list[str], cwd: Path | None = None) -> None:
    print("$", " ".join(cmd), flush=True)
    subprocess.check_call(cmd, cwd=str(cwd) if cwd else None)


def ensure_repo(args: argparse.Namespace) -> Path:
    workdir = Path(args.workdir).expanduser().resolve()
    if (workdir / "pyproject.toml").exists():
        print(f"[repo] using existing checkout: {workdir}")
        return workdir
    workdir.parent.mkdir(parents=True, exist_ok=True)
    run(["git", "clone", "--depth", "1", "--branch", args.branch, args.repo_url, str(workdir)])
    return workdir


def install_project(repo: Path, with_transformers: bool) -> None:
    run([sys.executable, "-m", "pip", "install", "-U", "pip", "setuptools", "wheel"])
    extras = ".[dev]" if with_transformers else "."
    run([sys.executable, "-m", "pip", "install", "-e", extras], cwd=repo)
    run([sys.executable, "-m", "pip", "install", "-q", "pyngrok"])
    if with_transformers:
        run([sys.executable, "-m", "pip", "install", "-U", "transformers>=4.51", "accelerate", "torch"])


def configure_env(args: argparse.Namespace) -> dict[str, str]:
    env = os.environ.copy()
    env["TAO_BACKEND"] = args.backend
    env["TAO_MODEL_ID"] = args.model_id or DEFAULT_MODEL_BY_BACKEND[args.backend]
    if args.api_key:
        env["TAO_API_KEY"] = args.api_key
    if args.endpoint_url:
        env["TAO_ENDPOINT_URL"] = args.endpoint_url
    if args.azure_endpoint:
        env["AZURE_OPENAI_ENDPOINT"] = args.azure_endpoint
    if args.azure_deployment:
        env["AZURE_OPENAI_DEPLOYMENT"] = args.azure_deployment
    if args.azure_api_version:
        env["AZURE_OPENAI_API_VERSION"] = args.azure_api_version
    if args.clinician_token:
        env["YAOBI_CLINICIAN_TOKEN"] = args.clinician_token
    if args.no_preload:
        env["TAO_PRELOAD"] = "0"
    return env


def wait_health(port: int, timeout: int = 90) -> dict[str, str]:
    url = f"http://127.0.0.1:{port}/api/health"
    deadline = time.time() + timeout
    last = ""
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as resp:
                body = resp.read().decode("utf-8", errors="replace")
                print(f"[health] {body[:300]}")
                return {"url": url, "body": body}
        except (urllib.error.URLError, TimeoutError) as exc:
            last = str(exc)
            time.sleep(1)
    raise RuntimeError(f"backend did not become healthy at {url}: {last}")


def start_backend(repo: Path, args: argparse.Namespace, env: dict[str, str]) -> subprocess.Popen:
    log_path = repo / "yaobi_server.log"
    log = log_path.open("w", encoding="utf-8")
    cmd = [sys.executable, "-m", "backend.server", "--host", args.host, "--port", str(args.port)]
    if args.no_preload:
        cmd.append("--no-preload")
    print("$", " ".join(cmd), f"# logs -> {log_path}", flush=True)
    proc = subprocess.Popen(cmd, cwd=str(repo), env=env, stdout=log, stderr=subprocess.STDOUT, text=True)
    try:
        wait_health(args.port, args.health_timeout)
    except Exception:
        log.flush(); log.close()
        print("\n[backend log tail]")
        if log_path.exists():
            print("\n".join(log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-80:]))
        proc.terminate()
        raise
    return proc


def start_ngrok(args: argparse.Namespace) -> str | None:
    if args.no_ngrok:
        return None
    from pyngrok import conf, ngrok

    if args.ngrok_token:
        ngrok.set_auth_token(args.ngrok_token)
    region = args.ngrok_region or os.getenv("NGROK_REGION") or "ap"
    conf.get_default().region = region
    tunnel = ngrok.connect(args.port, bind_tls=True)
    public_url = tunnel.public_url
    Path("yaobi_public_url.txt").write_text(public_url + "\n", encoding="utf-8")
    print(f"[ngrok] public UI: {public_url}")
    return public_url


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Launch full YaoBi Agent UI in Colab with optional ngrok public URL.")
    p.add_argument("--repo-url", default=REPO_URL)
    p.add_argument("--branch", default="main")
    p.add_argument("--workdir", default="/content/Yao-Bi-Agent")
    p.add_argument("--backend", choices=sorted(DEFAULT_MODEL_BY_BACKEND), default=os.getenv("TAO_BACKEND", "mock"))
    p.add_argument("--model-id", default=os.getenv("TAO_MODEL_ID"))
    p.add_argument("--api-key", default=os.getenv("TAO_API_KEY"))
    p.add_argument("--endpoint-url", default=os.getenv("TAO_ENDPOINT_URL"))
    p.add_argument("--azure-endpoint", default=os.getenv("AZURE_OPENAI_ENDPOINT"))
    p.add_argument("--azure-deployment", default=os.getenv("AZURE_OPENAI_DEPLOYMENT"))
    p.add_argument("--azure-api-version", default=os.getenv("AZURE_OPENAI_API_VERSION", "2024-02-15-preview"))
    p.add_argument("--clinician-token", default=os.getenv("YAOBI_CLINICIAN_TOKEN"))
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--port", type=int, default=int(os.getenv("PORT", "8000")))
    p.add_argument("--no-preload", action="store_true", help="Start UI first; load model only on demand/warmup.")
    p.add_argument("--skip-install", action="store_true", help="Use already installed dependencies.")
    p.add_argument("--no-ngrok", action="store_true", help="Only print the local Colab URL.")
    p.add_argument("--ngrok-token", default=os.getenv("NGROK_AUTHTOKEN"))
    p.add_argument("--ngrok-region", default=os.getenv("NGROK_REGION", "ap"))
    p.add_argument("--health-timeout", type=int, default=90)
    return p.parse_args()


def main() -> None:
    args = parse_args()
    repo = ensure_repo(args)
    if not args.skip_install:
        install_project(repo, with_transformers=args.backend == "transformers")
    env = configure_env(args)
    proc = start_backend(repo, args, env)
    public_url = start_ngrok(args)
    local_url = f"http://127.0.0.1:{args.port}"
    print("\nYaoBi Agent is running")
    print(f"- local:  {local_url}")
    if public_url:
        print(f"- public: {public_url}")
    print(f"- backend pid: {proc.pid}")
    print(f"- provider: {env['TAO_BACKEND']} / {env['TAO_MODEL_ID']}")
    print("- clinician mode: set YAOBI_CLINICIAN_TOKEN and enter it in UI settings if publicly exposed")
    print("- logs: yaobi_server.log")


if __name__ == "__main__":
    main()
