"""Production INARA HTML acquisition using an installed Edge or Chrome."""

import re
import shutil
import subprocess
import tempfile
from pathlib import Path
import os

from elite_dangerous.market import SURFACE_COMMODITIES, parse_inara_summaries


INARA_URL = "https://inara.cz/elite/commodities-list/"
INARA_TIMEOUT_SECONDS = 60


def _browser() -> Path | None:
    candidates = (
        Path(os.environ.get("PROGRAMFILES", "")) / "Google/Chrome/Application/chrome.exe",
        Path(os.environ.get("PROGRAMFILES(X86)", "")) / "Microsoft/Edge/Application/msedge.exe",
        Path(os.environ.get("PROGRAMFILES", "")) / "Microsoft/Edge/Application/msedge.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft/Edge/Application/msedge.exe",
    )
    return next((path for path in candidates if path.is_file()), None)


def fetch_inara_summary():
    """Fetch and fully validate the Surface Mining INARA summary."""
    browser = _browser()
    if browser is None:
        raise RuntimeError("No installed Edge or Chrome browser was found.")
    profile = Path(tempfile.mkdtemp(prefix="rsm-inara-"))
    try:
        result = subprocess.run([
            str(browser), "--headless=new", "--disable-gpu", "--no-first-run",
            "--no-default-browser-check", "--disable-background-networking",
            f"--user-data-dir={profile}", "--virtual-time-budget=15000",
            "--dump-dom", INARA_URL,
        ], capture_output=True, timeout=INARA_TIMEOUT_SECONDS, check=False)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("INARA browser request timed out.") from exc
    finally:
        shutil.rmtree(profile, ignore_errors=True)
    html = result.stdout.decode("utf-8", errors="replace")
    lower = html[:200_000].casefold()
    if result.returncode != 0 or not html or any(marker in lower for marker in ("captcha", "challenge-platform", "just a moment", "verify you are human")):
        raise RuntimeError("INARA returned an unusable page.")
    if not re.search(r"(?i)<table\b|\bhelium\b|\bplatinum\b|commodit", html):
        raise RuntimeError("INARA page contains no commodity data.")
    parsed = parse_inara_summaries(html, tuple(SURFACE_COMMODITIES))
    if not parsed.is_complete or parsed.issues:
        raise RuntimeError("INARA returned incomplete commodity data.")
    return parsed
