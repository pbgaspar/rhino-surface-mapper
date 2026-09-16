"""Surface Mining Markets — Spansh local + cache INARA

- Mercados do sistema: Spansh
- Média/máximo galácticos: cache local obtida do INARA
- 37 produtos
- Procura local > 100 t
- Máximo 3 produtos e 3 estações por produto
- Exclui estações com nome exatamente XXX-XXX

Colocar este ficheiro e "inara_commodities_cache.json" na mesma pasta.

Requer:
    pip install requests
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unicodedata
from collections import defaultdict
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from time import perf_counter

import requests


SPANSH_BASE_URL = "https://spansh.co.uk/api"
CACHE_FILENAME = "inara_commodities_cache.json"
INARA_COMMODITIES_URL = "https://inara.cz/elite/commodities-list/"
INARA_CACHE_MAX_AGE_SECONDS = 3600
HEADLESS_TIMEOUT_SECONDS = 60

MIN_DEMAND = 100
TOP_PRODUCTS = 3
TOP_STATIONS = 3

EXCLUDED_STATION_RE = re.compile(r"^[A-Za-z0-9]{3}-[A-Za-z0-9]{3}$")

SURFACE_COMMODITIES = [
    'Helium',
    'Helium-3',
    'Tritium',
    'Water',
    'Iridium',
    'Platinum',
    'Palladium',
    'Gold',
    'Osmium',
    'Silver',
    'Samarium',
    'Tantalum',
    'Thorium',
    'Uranium',
    'Titanium',
    'Lithium',
    'Copper',
    'Thortveitite',
    'Periclase Dunite',
    'Monazite',
    'Rhodplumsite',
    'Diamond',
    'Alexandrite',
    'Sapphire',
    'Ruby',
    'Grandidierite',
    'Serendibite',
    'Bastnäsite',
    'Low Temperature Diamonds',
    'Quartz Pyroxenite',
    'Deuterium',
    'Magnesite',
    'Olivine',
    'Jadeite',
    'Uraninite',
    'Haematite',
    'Methanol Crystals',
]

COMMODITY_ALIASES = {
    "Bastnasite": "Bastnäsite",
    "Methanol Monohydrate Crystals": "Methanol Crystals",
}


def get_json(session, method, path, **kwargs):
    response = session.request(
        method,
        SPANSH_BASE_URL + path,
        timeout=25,
        **kwargs,
    )
    response.raise_for_status()
    return response.json()


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


def format_number(value):
    if value is None:
        return "—"

    try:
        return f"{int(round(float(value))):,}".replace(",", " ")
    except (TypeError, ValueError):
        return str(value)


def parse_utc(value):
    if not value:
        return None

    try:
        text = str(value).strip()

        if text.endswith("Z"):
            text = text[:-1] + "+00:00"

        dt = datetime.fromisoformat(text)

        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)

        return dt.astimezone(timezone.utc)

    except (TypeError, ValueError):
        return None


def data_age(value):
    dt = parse_utc(value)

    if dt is None:
        return "?"

    seconds = max(
        0,
        int((datetime.now(timezone.utc) - dt).total_seconds()),
    )

    if seconds < 60:
        return f"{seconds}s"

    minutes = seconds // 60

    if minutes < 60:
        return f"{minutes}m"

    hours = minutes // 60

    if hours < 48:
        return f"{hours}h"

    return f"{hours // 24}d"


def station_is_excluded(station_name):
    normalized_name = str(station_name or "").strip()

    return bool(
        EXCLUDED_STATION_RE.fullmatch(
            normalized_name
        )
        or len(normalized_name) == 4
    )


# ============================================================
# SPANSH
# ============================================================

def find_system(session, name):
    page = 0
    seen = set()

    while True:
        data = get_json(
            session,
            "POST",
            "/systems/search",
            json={
                "filters": {"name": {"value": name}},
                "size": 100,
                "page": page,
            },
        )

        results = data.get("results", [])

        for item in results:
            if item.get("name", "").casefold() == name.casefold():
                return item["id64"]

        ids = {
            str(item["id64"])
            for item in results
            if item.get("id64") is not None
        }

        if not results:
            return None

        if ids.issubset(seen):
            raise ValueError(
                "A API repetiu a página da pesquisa; pesquisa incompleta."
            )

        seen.update(ids)

        if len(seen) >= data.get("count", len(seen)):
            return None

        page += 1


def collect_stations(record):
    stations = {}

    def visit(node):
        if not isinstance(node, dict):
            return

        for station in node.get("stations", []):
            identifier = station.get("market_id")

            if identifier is not None:
                stations[str(identifier)] = station

        for body in node.get("bodies", []):
            visit(body)

    visit(record)
    return stations


def landing_pad(record):
    for field, label in (
        ("large_pads", "L"),
        ("medium_pads", "M"),
        ("small_pads", "S"),
    ):
        if field == "large_pads" and record.get("has_large_pad") is True:
            return label

        try:
            if (record.get(field) or 0) > 0:
                return label
        except TypeError:
            pass

    return "?"


def pad_rank(pad):
    return {
        "L": 3,
        "M": 2,
        "S": 1,
        "?": 0,
    }.get(pad, 0)


def station_product_rows(record, wanted_by_key, min_demand):
    market = record.get("market")

    if not isinstance(market, list):
        raise ValueError(
            "Sem dados de mercado no detalhe da estação"
        )

    pad = landing_pad(record)
    market_updated_at = (
        record.get("market_updated_at")
        or "Desconhecido"
    )
    updated_at = (
        record.get("updated_at")
        or "Desconhecido"
    )

    rows = []

    for item in market:
        canonical_name = canonical_commodity_name(
            item.get("commodity", ""),
            wanted_by_key,
        )

        if canonical_name is None:
            continue

        demand = item.get("demand")
        sell_price = item.get("sell_price")

        try:
            demand = int(demand)
            sell_price = int(sell_price)
        except (TypeError, ValueError):
            continue

        if demand <= min_demand or sell_price <= 0:
            continue

        rows.append(
            {
                "commodity": canonical_name,
                "station": record.get("name", "Desconhecida"),
                "price": sell_price,
                "demand": demand,
                "pad": pad,
                "market_updated_at": market_updated_at,
                "updated_at": updated_at,
            }
        )

    return rows


def query_system_markets(
    name,
    min_demand=MIN_DEMAND,
    progress=print,
):
    results = defaultdict(list)
    errors = []
    wanted_by_key = build_wanted_map()

    with requests.Session() as session:
        session.headers.update(
            {
                "User-Agent": "RhinoSurfaceMapper/1.0",
                "Accept": "application/json",
            }
        )

        identifier = find_system(session, name)

        if identifier is None:
            raise ValueError(
                f"Sistema '{name}' não encontrado por nome exato."
            )

        system = get_json(
            session,
            "GET",
            f"/system/{identifier}",
        )["record"]

        if system.get("name", "").casefold() != name.casefold():
            raise ValueError(
                "O sistema devolvido não corresponde ao nome pedido."
            )

        exact_system_name = system.get("name", name)
        stations = collect_stations(system)

        candidates = []
        carrier_excluded_count = 0
        squadron_carrier_excluded_count = 0

        for key, station in stations.items():
            station_name = station.get("name", "")

            if station_is_excluded(station_name):
                normalized_name = str(station_name or "").strip()

                if EXCLUDED_STATION_RE.fullmatch(normalized_name):
                    carrier_excluded_count += 1
                elif len(normalized_name) == 4:
                    squadron_carrier_excluded_count += 1

                continue

            if (
                station.get("has_market") is True
                or "Market" in station.get("services", [])
            ):
                candidates.append((key, station))

        progress(
            f"{len(stations)} estações registadas; "
            f"{carrier_excluded_count} Carriers + "
            f"{squadron_carrier_excluded_count} Squadron Carriers excluídos; "
            f"a verificar {len(candidates)} possíveis mercados..."
        )

        for index, (key, station) in enumerate(candidates, 1):
            station_name = station.get("name", key)

            progress(
                f"  [{index}/{len(candidates)}] {station_name}"
            )

            try:
                record = get_json(
                    session,
                    "GET",
                    f"/station/{int(key)}",
                )["record"]

                if record.get("system_name", "").casefold() != name.casefold():
                    errors.append(
                        f"{station_name}: já não está neste sistema."
                    )
                    continue

                if station_is_excluded(record.get("name", "")):
                    continue

                if record.get("has_market") is False:
                    continue

                for row in station_product_rows(
                    record,
                    wanted_by_key,
                    min_demand,
                ):
                    results[row["commodity"]].append(row)

            except (
                requests.RequestException,
                ValueError,
                KeyError,
                TypeError,
            ) as exc:
                errors.append(
                    f"{station_name}: {exc}"
                )

    for rows in results.values():
        rows.sort(
            key=lambda row: (
                row["price"],
                row["demand"],
                pad_rank(row["pad"]),
            ),
            reverse=True,
        )

    return exact_system_name, dict(results), errors


# ============================================================
# CACHE INARA
# ============================================================

class InaraTableParser(HTMLParser):
    """Extrai as linhas/células de tabelas HTML do INARA."""

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
        return int(digits)
    except ValueError:
        return None


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

    return any(marker in lower_html for marker in challenge_markers)


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
    has_commodity_content = bool(
        re.search(r"(?i)<table\b|\bhelium\b|\bplatinum\b|commodit", html_text)
    )

    if result.returncode != 0:
        raise RuntimeError(
            f"o navegador terminou com código de saída {result.returncode}"
        )

    if not html_text:
        raise RuntimeError("o navegador não devolveu HTML")

    if browser_page_diagnostics(html_text):
        raise RuntimeError("a página parece conter um challenge ou erro de proteção")

    if not has_commodity_content:
        raise RuntimeError("o HTML não parece conter a lista de commodities")

    return html_text


def cache_path():
    return Path(__file__).resolve().parent / CACHE_FILENAME


def cache_age_seconds(value):
    dt = parse_utc(value)

    if dt is None:
        return None

    return max(0, int((datetime.now(timezone.utc) - dt).total_seconds()))


def load_inara_cache():
    path = cache_path()

    if not path.exists():
        raise FileNotFoundError(
            f"Ficheiro de cache não encontrado: {path.name}"
        )

    with path.open("r", encoding="utf-8") as fh:
        data = json.load(fh)

    commodities = data.get("commodities")

    if not isinstance(commodities, dict):
        raise ValueError(
            "O ficheiro de cache INARA não tem uma secção 'commodities' válida."
        )

    summary = {}
    wanted_by_key = build_wanted_map()

    for raw_name, values in commodities.items():
        canonical = canonical_commodity_name(
            raw_name,
            wanted_by_key,
        )

        if canonical is None or not isinstance(values, dict):
            continue

        summary[normalize_name(canonical)] = {
            "name": canonical,
            "average": values.get("avg_sell"),
            "maximum": values.get("max_sell"),
        }

    if not summary:
        raise ValueError(
            "O ficheiro de cache INARA não contém valores reconhecidos."
        )

    return {
        "summary": summary,
        "updated_at": data.get("updated_at"),
        "source": data.get("source", "INARA"),
        "source_url": data.get("source_url"),
        "path": str(path),
    }


def _extract_inara_summary(html_text):
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

        avg_sell = parse_credit_value(row[1])
        max_sell = parse_credit_value(row[4])

        if avg_sell is None or max_sell is None:
            continue

        summary[normalize_name(canonical)] = {
            "name": canonical,
            "average": avg_sell,
            "maximum": max_sell,
            "source": "INARA",
        }

    if len(summary) != len(SURFACE_COMMODITIES):
        raise ValueError(
            f"Foram reconhecidos {len(summary)} produtos; eram esperados "
            f"exatamente {len(SURFACE_COMMODITIES)}."
        )

    return summary


def refresh_inara_cache_if_needed():
    try:
        cache_info = load_inara_cache()
    except (FileNotFoundError, OSError, ValueError, json.JSONDecodeError):
        cache_info = None

    age = cache_age_seconds(cache_info.get("updated_at") if cache_info else None) if cache_info else None

    if age is not None and age < INARA_CACHE_MAX_AGE_SECONDS:
        return cache_info

    print("INARA: a atualizar valores globais...")
    temporary_path = cache_path().with_name(cache_path().name + ".tmp")

    try:
        summary = _extract_inara_summary(fetch_with_headless_browser())

        payload = {
            "source": "INARA",
            "source_url": INARA_COMMODITIES_URL,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "notes": (
                "Valores Avg sell e Max sell obtidos da lista geral de commodities do INARA. "
                "Methanol Crystals corresponde a Methanol Monohydrate Crystals no INARA."
            ),
            "commodities": {
                commodity: {
                    "avg_sell": summary[normalize_name(commodity)]["average"],
                    "max_sell": summary[normalize_name(commodity)]["maximum"],
                }
                for commodity in SURFACE_COMMODITIES
            },
        }

        with temporary_path.open("w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
        os.replace(temporary_path, cache_path())

        print("INARA: cache atualizada (37/37 produtos).")
        return load_inara_cache()

    except Exception:
        try:
            temporary_path.unlink()
        except (FileNotFoundError, OSError):
            pass

        print("INARA: atualização indisponível; a usar a última cache válida.")
        if cache_info is not None:
            return cache_info
        return {
            "summary": {},
            "updated_at": None,
            "source": "INARA",
            "source_url": INARA_COMMODITIES_URL,
            "path": str(cache_path()),
        }


def galaxy_stats(product, cache_info):
    summary = cache_info.get("summary", {})

    return summary.get(
        normalize_name(product),
        {
            "average": None,
            "maximum": None,
        },
    )


def cache_label(cache_info):
    updated = cache_info.get("updated_at")

    if not updated:
        return "INARA (cache local)"

    try:
        dt = datetime.fromisoformat(updated)
        age_seconds = cache_age_seconds(updated)

        if age_seconds is None:
            return f"INARA (cache {updated})"

        age_hours, remaining_seconds = divmod(age_seconds, 3600)
        age_minutes = remaining_seconds // 60
        age_text = f"{age_hours}h{age_minutes:02d}m"

        if age_seconds < 3 * 3600:
            color = "\033[32m"
        elif age_seconds < 6 * 3600:
            color = "\033[33m"
        else:
            color = "\033[31m"

        interior = (
            f"cache {dt.strftime('%d/%m/%Y %H:%M')}"
            f" — {age_text}"
        )
        return f"INARA ({color}{interior}\033[0m)"
    except (TypeError, ValueError):
        return f"INARA (cache {updated})"


# ============================================================
# SELEÇÃO / APRESENTAÇÃO
# ============================================================

def select_top_products(results, limit=TOP_PRODUCTS):
    ranked = []

    for product, rows in results.items():
        if not rows:
            continue

        best = rows[0]

        ranked.append(
            {
                "product": product,
                "best_price": best["price"],
                "best_demand": best["demand"],
                "best_pad_rank": pad_rank(best["pad"]),
                "stations": rows,
            }
        )

    ranked.sort(
        key=lambda item: (
            item["best_price"],
            item["best_demand"],
            item["best_pad_rank"],
        ),
        reverse=True,
    )

    return ranked[:limit]


def print_results(
    system_name,
    selected,
    cache_info,
    errors,
    min_demand,
    elapsed,
):
    print()
    print("=" * 112)
    print(
        f"MINERAÇÃO — {system_name.upper()} "
        f"| 37 PRODUTOS "
        f"| PROCURA LOCAL > {format_number(min_demand)} t"
    )
    print("=" * 112)

    if not selected:
        print()
        print(
            "Não foram encontrados produtos da lista com procura "
            f"superior a {format_number(min_demand)} t."
        )

    source_label = cache_label(cache_info)

    for number, info in enumerate(selected, 1):
        product = info["product"]
        stats = galaxy_stats(product, cache_info)

        print()
        print(f"{number}. {product.upper()}")

        if (
            stats.get("average") is not None
            or stats.get("maximum") is not None
        ):
            print(
                f"   {source_label} — "
                f"Média galáctica: {format_number(stats.get('average'))} Cr/t"
                f" | Máximo galáctico: {format_number(stats.get('maximum'))} Cr/t"
            )
        else:
            print(
                f"   {source_label} — "
                "média/máximo não disponíveis."
            )

        print()

        headers = [
            "Estação",
            "Preço (Cr/t)",
            "Procura (t)",
            "Pad",
            "Mercado UTC",
            "Idade",
        ]

        rows = []

        for row in info["stations"][:TOP_STATIONS]:
            rows.append(
                [
                    row["station"],
                    format_number(row["price"]),
                    format_number(row["demand"]),
                    row["pad"],
                    str(row["market_updated_at"]),
                    data_age(row["market_updated_at"]),
                ]
            )

        widths = [
            max(
                len(headers[i]),
                max(
                    (len(str(row[i])) for row in rows),
                    default=0,
                ),
            )
            for i in range(len(headers))
        ]

        prefix = "   "

        print(
            prefix
            + " | ".join(
                headers[i].ljust(widths[i])
                for i in range(len(headers))
            )
        )

        print(
            prefix
            + "-+-".join(
                "-" * width
                for width in widths
            )
        )

        for row in rows:
            print(
                prefix
                + " | ".join(
                    str(row[i]).ljust(widths[i])
                    for i in range(len(row))
                )
            )

    if errors:
        print()
        print("-" * 112)
        print(
            "Resultado parcial — não foi possível confirmar estas estações:"
        )

        for error in errors:
            print(f"  {error}")

    print()
    print(
        f"{len(selected)} produtos apresentados; "
        f"{len(errors)} verificações incompletas."
    )
    print(f"Tempo total: {elapsed:.2f} s")


def main():
    system_name = (
        " ".join(sys.argv[1:]).strip()
        if len(sys.argv) > 1
        else input("Nome do sistema: ").strip()
    )

    if not system_name:
        print("Introduz um nome de sistema.")
        return 1

    started = perf_counter()

    try:
        exact_name, local_results, errors = query_system_markets(
            system_name,
            min_demand=MIN_DEMAND,
        )
    except (
        requests.RequestException,
        ValueError,
        KeyError,
        TypeError,
    ) as exc:
        print(f"Erro ao consultar o sistema: {exc}")
        return 1

    try:
        inara_cache = refresh_inara_cache_if_needed()

        if inara_cache is None:
            raise FileNotFoundError("Cache INARA não disponível.")
    except (
        OSError,
        ValueError,
        json.JSONDecodeError,
    ) as exc:
        print()
        print(
            "Aviso: não foi possível carregar a cache INARA: "
            f"{exc}"
        )
        inara_cache = {
            "summary": {},
            "updated_at": None,
            "source": "INARA",
        }

    selected = select_top_products(local_results)

    print_results(
        exact_name,
        selected,
        inara_cache,
        errors,
        MIN_DEMAND,
        perf_counter() - started,
    )

    return 2 if errors else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (KeyboardInterrupt, EOFError):
        print("\nConsulta cancelada.")
        raise SystemExit(130)
