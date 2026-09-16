"""Atualiza e mostra os valores globais dos 37 produtos no INARA."""

import json
import hashlib
import os
import re
import shutil
import subprocess
import tempfile
import unicodedata
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path

import requests


CACHE_FILENAME = "inara_commodities_cache.json"
INARA_COMMODITIES_URL = "https://inara.cz/elite/commodities-list/"
INARA_HOME_URL = "https://inara.cz/"
REQUEST_TIMEOUT_SECONDS = 25
HEADLESS_TIMEOUT_SECONDS = 60

SURFACE_COMMODITIES = [
    "Helium",
    "Helium-3",
    "Tritium",
    "Water",
    "Iridium",
    "Platinum",
    "Palladium",
    "Gold",
    "Osmium",
    "Silver",
    "Samarium",
    "Tantalum",
    "Thorium",
    "Uranium",
    "Titanium",
    "Lithium",
    "Copper",
    "Thortveitite",
    "Periclase Dunite",
    "Monazite",
    "Rhodplumsite",
    "Diamond",
    "Alexandrite",
    "Sapphire",
    "Ruby",
    "Grandidierite",
    "Serendibite",
    "Bastnäsite",
    "Low Temperature Diamonds",
    "Quartz Pyroxenite",
    "Deuterium",
    "Magnesite",
    "Olivine",
    "Jadeite",
    "Uraninite",
    "Haematite",
    "Methanol Crystals",
]

COMMODITY_ALIASES = {
    "Bastnasite": "Bastnäsite",
    "Methanol Monohydrate Crystals": "Methanol Crystals",
}


class InaraTableParser(HTMLParser):
    """Extrai as linhas e células das tabelas HTML do INARA."""

    def __init__(self):
        super().__init__()
        self.in_row = False
        self.in_cell = False
        self.current_cell = []
        self.current_row = []
        self.rows = []

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()

        if tag == "tr":
            self.in_row = True
            self.current_row = []
        elif tag in ("td", "th") and self.in_row:
            self.in_cell = True
            self.current_cell = []

    def handle_endtag(self, tag):
        tag = tag.lower()

        if tag in ("td", "th") and self.in_cell:
            text = " ".join(" ".join(self.current_cell).split())
            self.current_row.append(text)
            self.current_cell = []
            self.in_cell = False
        elif tag == "tr" and self.in_row:
            if self.current_row:
                self.rows.append(self.current_row)
            self.current_row = []
            self.in_row = False

    def handle_data(self, data):
        if self.in_cell:
            self.current_cell.append(data)


def normalize_name(value):
    if value is None:
        return ""

    text = unicodedata.normalize("NFKD", str(value))
    text = "".join(
        ch for ch in text
        if not unicodedata.combining(ch)
    )

    return "".join(
        ch.casefold()
        for ch in text
        if ch.isalnum()
    )


def build_wanted_map():
    wanted = {
        normalize_name(product): product
        for product in SURFACE_COMMODITIES
    }

    for alias, canonical in COMMODITY_ALIASES.items():
        wanted[normalize_name(alias)] = canonical

    return wanted


def canonical_commodity_name(raw_name, wanted_by_key):
    return wanted_by_key.get(normalize_name(raw_name))


def parse_credit_value(text):
    """Converte textos como '134,148 Cr' para int 134148."""
    if not text:
        return None

    match = re.search(r"(-?[0-9][0-9\s,.'’]*)", text)

    if not match:
        return None

    digits = re.sub(r"[^0-9-]", "", match.group(1))

    if digits in ("", "-"):
        return None

    try:
        value = int(digits)
    except ValueError:
        return None

    return value if value >= 0 else None


def cache_path():
    return Path(__file__).resolve().parent / CACHE_FILENAME


def format_number(value):
    return f"{value:,}".replace(",", " ")


def extract_inara_summary(html_text):
    parser = InaraTableParser()
    parser.feed(html_text)

    summary = {}
    wanted_by_key = build_wanted_map()

    for row in parser.rows:
        if len(row) < 5:
            continue

        canonical = canonical_commodity_name(row[0], wanted_by_key)
        if canonical is None:
            continue

        average = parse_credit_value(row[1])
        maximum = parse_credit_value(row[4])
        if average is None or maximum is None:
            continue

        summary[normalize_name(canonical)] = {
            "name": canonical,
            "average": average,
            "maximum": maximum,
        }

    missing = [
        product for product in SURFACE_COMMODITIES
        if normalize_name(product) not in summary
    ]
    if missing:
        raise ValueError(
            f"A página não forneceu valores válidos para {len(missing)} produto(s): "
            + ", ".join(missing)
        )

    if len(summary) != len(SURFACE_COMMODITIES):
        raise ValueError(
            f"Foram reconhecidos {len(summary)} produtos; eram esperados "
            f"{len(SURFACE_COMMODITIES)}."
        )

    return summary


def make_payload(summary):
    return {
        "source": "INARA",
        "source_url": INARA_COMMODITIES_URL,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "notes": (
            "Valores Avg sell e Max sell obtidos da lista geral de commodities do INARA. "
            "Methanol Crystals corresponde a Methanol Monohydrate Crystals no INARA."
        ),
        "commodities": {
            product: {
                "avg_sell": summary[normalize_name(product)]["average"],
                "max_sell": summary[normalize_name(product)]["maximum"],
            }
            for product in SURFACE_COMMODITIES
        },
    }


def write_cache_atomically(payload):
    path = cache_path()
    temporary_path = path.with_name(path.name + ".tmp")

    try:
        with temporary_path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(temporary_path, path)
    except Exception:
        try:
            temporary_path.unlink()
        except FileNotFoundError:
            pass
        raise


def load_existing_cache():
    path = cache_path()
    if not path.exists():
        return None

    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
        print(f"Não foi possível ler o JSON existente: {exc}")
        return None


def cache_sha256():
    path = cache_path()
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def find_headless_browser():
    candidates = (
        Path(os.environ.get("PROGRAMFILES", ""))
        / "Google/Chrome/Application/chrome.exe",
        Path(os.environ.get("PROGRAMFILES(X86)", ""))
        / "Microsoft/Edge/Application/msedge.exe",
        Path(os.environ.get("PROGRAMFILES", ""))
        / "Microsoft/Edge/Application/msedge.exe",
        Path(os.environ.get("LOCALAPPDATA", ""))
        / "Microsoft/Edge/Application/msedge.exe",
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def browser_page_diagnostics(html_text):
    title_match = re.search(
        r"<title[^>]*>(.*?)</title>", html_text, re.IGNORECASE | re.DOTALL
    )
    title = " ".join(title_match.group(1).split()) if title_match else "(não encontrado)"
    lower_html = html_text[:200_000].casefold()
    challenge_markers = (
        "captcha",
        "challenge-platform",
        "cf-chl-",
        "just a moment",
        "verify you are human",
        "checking your browser",
        "enable javascript and cookies",
        "service unavailable",
    )
    return title, any(marker in lower_html for marker in challenge_markers)


def fetch_with_headless_browser():
    browser_path = find_headless_browser()
    if browser_path is None:
        raise RuntimeError("Não foi encontrado Edge ou Chrome instalado.")

    temporary_profile = Path(tempfile.mkdtemp(prefix="inara-headless-"))
    command = [
        str(browser_path),
        "--headless=new",
        "--disable-gpu",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-background-networking",
        f"--user-data-dir={temporary_profile}",
        "--virtual-time-budget=15000",
        "--dump-dom",
        INARA_COMMODITIES_URL,
    ]

    try:
        result = subprocess.run(
            command,
            capture_output=True,
            timeout=HEADLESS_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            f"o navegador excedeu o timeout de {HEADLESS_TIMEOUT_SECONDS} segundos"
        ) from exc
    finally:
        shutil.rmtree(temporary_profile, ignore_errors=True)

    html_text = result.stdout.decode("utf-8", errors="replace")
    stderr_text = result.stderr.decode("utf-8", errors="replace").strip()
    title, has_challenge = browser_page_diagnostics(html_text)
    has_commodity_content = bool(
        re.search(r"(?i)<table\b|\bhelium\b|\bplatinum\b|commodit", html_text)
    )

    print(f"Navegador: {browser_path.name}")
    print(f"Executável: {browser_path}")
    print(f"Código de saída: {result.returncode}")
    print(f"HTML recebido: {len(result.stdout)} bytes")
    print(f"Título: {title}")
    print(f"Sinais de challenge/erro/proteção: {'SIM' if has_challenge else 'NÃO'}")
    print(f"Sinais de lista de commodities: {'SIM' if has_commodity_content else 'NÃO'}")
    if stderr_text:
        print(f"stderr do navegador: {stderr_text[:500]}")

    if result.returncode != 0:
        raise RuntimeError(
            f"o navegador terminou com código de saída {result.returncode}"
        )
    if not html_text:
        raise RuntimeError("o navegador não devolveu HTML")
    if has_challenge:
        raise RuntimeError("a página parece conter um challenge ou erro de proteção")
    if not has_commodity_content:
        raise RuntimeError("o HTML não parece conter a lista de commodities")

    return html_text


def print_existing_cache(data):
    if data is None:
        print("Não existe JSON anterior para mostrar.")
        return

    print(f"Última atualização existente: {data.get('updated_at', 'desconhecida')}")
    commodities = data.get("commodities")
    if not isinstance(commodities, dict):
        print("Os dados existentes não têm uma secção 'commodities' válida.")
        return

    print("Dados atualmente guardados:")
    print(f"{'Produto':<28} {'Média':>12} {'Máximo':>12}")
    print("-" * 56)
    for product in SURFACE_COMMODITIES:
        values = commodities.get(product)
        if isinstance(values, dict):
            average = values.get("avg_sell")
            maximum = values.get("max_sell")
            if average is not None and maximum is not None:
                print(
                    f"{product:<28} {format_number(average):>12} "
                    f"{format_number(maximum):>12}"
                )


def print_summary(summary, updated_at):
    print("\nAtualização bem-sucedida. Valores globais INARA:")
    print(f"{'Produto':<28} {'Média':>12} {'Máximo':>12}")
    print("-" * 56)
    for product in SURFACE_COMMODITIES:
        values = summary[normalize_name(product)]
        print(
            f"{product:<28} {format_number(values['average']):>12} "
            f"{format_number(values['maximum']):>12}"
        )
    print(f"\nJSON atualizado em: {updated_at}")


def browser_headers():
    return {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/140.0.0.0 Safari/537.36"
        ),
        "Accept": (
            "text/html,application/xhtml+xml,application/xml;"
            "q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8"
        ),
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
    }


def print_response_diagnostics(response, session):
    print(
        f"Pedido: {response.url}\n"
        f"  HTTP: {response.status_code}\n"
        f"  Tamanho: {len(response.content)} bytes\n"
        f"  Cookies da sessão: {session.cookies.get_dict()}"
    )


def looks_like_challenge(response):
    if "html" not in response.headers.get("Content-Type", "").lower():
        return False

    text = response.text[:200_000].casefold()
    markers = (
        "captcha",
        "challenge-platform",
        "cf-chl-",
        "just a moment",
        "verify you are human",
        "checking your browser",
        "enable javascript and cookies",
    )
    return any(marker in text for marker in markers)


def main():
    print("Experiência controlada: navegador real em modo headless")
    print(f"Lista de commodities: {INARA_COMMODITIES_URL}")
    print(f"SURFACE_COMMODITIES: {len(SURFACE_COMMODITIES)}")
    existing_cache = load_existing_cache()
    initial_cache_sha256 = cache_sha256()
    print(f"SHA-256 da cache antes: {initial_cache_sha256}")

    try:
        html_text = fetch_with_headless_browser()
        summary = extract_inara_summary(html_text)
        if len(summary) != len(SURFACE_COMMODITIES):
            raise ValueError(
                f"Validação incompleta: encontrados {len(summary)} produtos; "
                f"eram esperados exatamente {len(SURFACE_COMMODITIES)}."
            )
        print(
            f"Validação concluída: {len(summary)} produtos encontrados; "
            "todos têm Avg sell e Max sell válidos."
        )
        payload = make_payload(summary)
        write_cache_atomically(payload)
        final_cache_sha256 = cache_sha256()
        print(f"SHA-256 da cache depois: {final_cache_sha256}")
        print_summary(summary, payload["updated_at"])
    except RuntimeError as exc:
        print(f"FALHA navegador/HTML: {exc}")
        print_existing_cache(existing_cache)
        print(f"SHA-256 da cache depois: {cache_sha256()}")
        print("JSON NÃO ALTERADO")
    except (
        ValueError,
        TypeError,
        AttributeError,
        json.JSONDecodeError,
    ) as exc:
        print(f"FALHA de parsing/validação: {exc}")
        print_existing_cache(existing_cache)
        print(f"SHA-256 da cache depois: {cache_sha256()}")
        print("JSON NÃO ALTERADO")
    except OSError as exc:
        print(f"FALHA ao escrever o JSON: {exc}")
        print_existing_cache(existing_cache)
        print(f"SHA-256 da cache depois: {cache_sha256()}")
        print("JSON NÃO ALTERADO")


if __name__ == "__main__":
    main()
