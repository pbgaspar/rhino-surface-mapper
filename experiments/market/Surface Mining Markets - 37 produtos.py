"""Surface Mining Markets — 37 produtos + INARA

Consulta os mercados do sistema indicado no Spansh e usa a página geral
de commodities do INARA para obter Avg sell e Max sell galácticos.

Requer:
    pip install requests
"""

import re
import sys
import unicodedata
from collections import defaultdict
from datetime import datetime, timezone
from html.parser import HTMLParser
from time import perf_counter

import requests


SPANSH_BASE_URL = "https://spansh.co.uk/api"
INARA_COMMODITIES_URL = "https://inara.cz/elite/commodities-list/"

MIN_DEMAND = 100
TOP_PRODUCTS = 3
TOP_STATIONS = 3

# Estações com nome exatamente XXX-XXX são excluídas antes de pedir
# o detalhe do mercado.
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

# Alguns nomes podem aparecer de forma diferente nas fontes.
# O nome à direita é o nosso nome canónico.
COMMODITY_ALIASES = {
    "Bastnasite": "Bastnäsite",
    "Methanol Monohydrate Crystals": "Methanol Crystals",
}


def get_json(session, method, path, base_url=SPANSH_BASE_URL, **kwargs):
    response = session.request(method, base_url + path, timeout=25, **kwargs)
    response.raise_for_status()
    return response.json()


def normalize_name(value):
    """Normaliza nomes para comparação entre Spansh/INARA/lista interna."""
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
    """
    Primeiro tenta igualdade normalizada.
    Se o INARA acrescentar um glifo/ícone ao nome, aceita também
    correspondência por início/fim inequívoco.
    """
    key = normalize_name(raw_name)

    if key in wanted_by_key:
        return wanted_by_key[key]

    matches = []
    for wanted_key, canonical in wanted_by_key.items():
        if key.startswith(wanted_key) or key.endswith(wanted_key):
            matches.append(canonical)

    matches = list(dict.fromkeys(matches))

    if len(matches) == 1:
        return matches[0]

    return None


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
    return bool(
        EXCLUDED_STATION_RE.fullmatch(
            str(station_name or "").strip()
        )
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

        if demand <= min_demand:
            continue

        if sell_price <= 0:
            continue

        rows.append(
            {
                "commodity": canonical_name,
                "station": record.get(
                    "name",
                    "Desconhecida",
                ),
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
                "User-Agent": (
                    "Mozilla/5.0 "
                    "(Windows NT 10.0; Win64; x64) "
                    "RhinoSurfaceMapper/1.0"
                ),
                "Accept": "application/json",
            }
        )

        identifier = find_system(
            session,
            name,
        )

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

        exact_system_name = system.get(
            "name",
            name,
        )

        stations = collect_stations(system)

        candidates = []

        for key, station in stations.items():
            station_name = station.get("name", "")

            if station_is_excluded(station_name):
                continue

            if (
                station.get("has_market") is True
                or "Market" in station.get("services", [])
            ):
                candidates.append((key, station))

        excluded_count = sum(
            1
            for station in stations.values()
            if station_is_excluded(
                station.get("name", "")
            )
        )

        progress(
            f"{len(stations)} estações registadas; "
            f"{excluded_count} excluídas por formato XXX-XXX; "
            f"a verificar {len(candidates)} possíveis mercados..."
        )

        for index, (key, station) in enumerate(
            candidates,
            1,
        ):
            station_name = station.get(
                "name",
                key,
            )

            progress(
                f"  [{index}/{len(candidates)}] "
                f"{station_name}"
            )

            try:
                record = get_json(
                    session,
                    "GET",
                    f"/station/{int(key)}",
                )["record"]

                if (
                    record.get(
                        "system_name",
                        "",
                    ).casefold()
                    != name.casefold()
                ):
                    errors.append(
                        f"{station_name}: "
                        "já não está neste sistema."
                    )
                    continue

                if station_is_excluded(
                    record.get("name", "")
                ):
                    continue

                if record.get("has_market") is False:
                    continue

                rows = station_product_rows(
                    record,
                    wanted_by_key,
                    min_demand,
                )

                for row in rows:
                    results[
                        row["commodity"]
                    ].append(row)

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

    return (
        exact_system_name,
        dict(results),
        errors,
    )


# ============================================================
# INARA — Avg sell / Max sell
# ============================================================

class InaraTableParser(HTMLParser):
    """Extrai texto das linhas/células das tabelas HTML."""

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
            text = " ".join(
                " ".join(self.current_cell).split()
            )
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
    """
    '134,148 Cr' -> 134148
    '0 Cr'       -> 0
    """
    if not text:
        return None

    match = re.search(
        r"(-?[0-9][0-9\s,.'’]*)",
        text,
    )

    if not match:
        return None

    digits = re.sub(
        r"[^0-9-]",
        "",
        match.group(1),
    )

    if digits in ("", "-"):
        return None

    try:
        return int(digits)
    except ValueError:
        return None


def query_inara_summary():
    """
    Faz UMA consulta à lista geral de commodities do INARA.

    Colunas esperadas:
      Commodity | Avg sell | Avg buy | Avg profit |
      Max sell  | Min buy | Max profit

    Se o layout mudar, esta função falha de forma controlada e
    a consulta local Spansh continua.
    """
    wanted_by_key = build_wanted_map()

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/152.0 Safari/537.36"
        ),
        "Accept": (
            "text/html,application/xhtml+xml,"
            "application/xml;q=0.9,*/*;q=0.8"
        ),
        "Accept-Language": "en-US,en;q=0.9",
    }

    response = requests.get(
        INARA_COMMODITIES_URL,
        headers=headers,
        timeout=25,
    )
    response.raise_for_status()

    parser = InaraTableParser()
    parser.feed(response.text)

    summary = {}

    for row in parser.rows:
        if len(row) < 5:
            continue

        canonical = canonical_commodity_name(
            row[0],
            wanted_by_key,
        )

        if canonical is None:
            continue

        avg_sell = parse_credit_value(row[1])
        max_sell = parse_credit_value(row[4])

        if avg_sell is None and max_sell is None:
            continue

        summary[normalize_name(canonical)] = {
            "name": canonical,
            "average": avg_sell,
            "maximum": max_sell,
            "source": "INARA",
        }

    if not summary:
        raise ValueError(
            "Não consegui extrair Avg sell / Max sell da página do INARA."
        )

    return summary


def galaxy_stats(
    product,
    summary,
):
    return summary.get(
        normalize_name(product),
        {
            "average": None,
            "maximum": None,
            "source": None,
        },
    )


# ============================================================
# SELEÇÃO / APRESENTAÇÃO
# ============================================================

def select_top_products(
    results,
    limit=TOP_PRODUCTS,
):
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
                "best_pad_rank": pad_rank(
                    best["pad"]
                ),
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
    galaxy_summary,
    errors,
    min_demand,
    elapsed,
):
    print()
    print("=" * 112)
    print(
        f"MINERAÇÃO — {system_name.upper()} "
        f"| 37 PRODUTOS "
        f"| PROCURA LOCAL > "
        f"{format_number(min_demand)} t"
    )
    print("=" * 112)

    if not selected:
        print()
        print(
            "Não foram encontrados produtos da lista com procura "
            f"superior a {format_number(min_demand)} t."
        )

    for number, info in enumerate(
        selected,
        1,
    ):
        product = info["product"]
        stats = galaxy_stats(
            product,
            galaxy_summary,
        )

        print()
        print(
            f"{number}. "
            f"{product.upper()}"
        )

        if (
            stats.get("average") is not None
            or stats.get("maximum") is not None
        ):
            print(
                "   INARA — "
                f"Média galáctica: "
                f"{format_number(stats.get('average'))} Cr/t"
                f" | Máximo galáctico: "
                f"{format_number(stats.get('maximum'))} Cr/t"
            )
        else:
            print(
                "   INARA — "
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
                    format_number(
                        row["price"]
                    ),
                    format_number(
                        row["demand"]
                    ),
                    row["pad"],
                    str(
                        row[
                            "market_updated_at"
                        ]
                    ),
                    data_age(
                        row[
                            "market_updated_at"
                        ]
                    ),
                ]
            )

        widths = [
            max(
                len(headers[i]),
                max(
                    (
                        len(str(row[i]))
                        for row in rows
                    ),
                    default=0,
                ),
            )
            for i in range(
                len(headers)
            )
        ]

        prefix = "   "

        print(
            prefix
            + " | ".join(
                headers[i].ljust(
                    widths[i]
                )
                for i in range(
                    len(headers)
                )
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
                    str(row[i]).ljust(
                        widths[i]
                    )
                    for i in range(
                        len(row)
                    )
                )
            )

    if errors:
        print()
        print("-" * 112)
        print(
            "Resultado parcial — "
            "não foi possível confirmar estas estações:"
        )

        for error in errors:
            print(
                f"  {error}"
            )

    print()
    print(
        f"{len(selected)} produtos apresentados; "
        f"{len(errors)} verificações incompletas."
    )
    print(
        f"Tempo total: {elapsed:.2f} s"
    )


def main():
    system_name = (
        " ".join(sys.argv[1:]).strip()
        if len(sys.argv) > 1
        else input(
            "Nome do sistema: "
        ).strip()
    )

    if not system_name:
        print(
            "Introduz um nome de sistema."
        )
        return 1

    started = perf_counter()

    try:
        (
            exact_name,
            local_results,
            errors,
        ) = query_system_markets(
            system_name,
            min_demand=MIN_DEMAND,
        )

    except (
        requests.RequestException,
        ValueError,
        KeyError,
        TypeError,
    ) as exc:
        print(
            f"Erro ao consultar o sistema: {exc}"
        )
        return 1

    # Consulta complementar ao INARA.
    # Se falhar, os resultados locais continuam válidos.
    try:
        galaxy_summary = query_inara_summary()

    except (
        requests.RequestException,
        ValueError,
        KeyError,
        TypeError,
    ) as exc:
        print()
        print(
            "Aviso: não foi possível obter "
            "a média/máximo do INARA: "
            f"{exc}"
        )
        galaxy_summary = {}

    selected = select_top_products(
        local_results
    )

    print_results(
        exact_name,
        selected,
        galaxy_summary,
        errors,
        MIN_DEMAND,
        perf_counter() - started,
    )

    return 2 if errors else 0


if __name__ == "__main__":
    try:
        raise SystemExit(
            main()
        )

    except (
        KeyboardInterrupt,
        EOFError,
    ):
        print(
            "\nConsulta cancelada."
        )
        raise SystemExit(130)
