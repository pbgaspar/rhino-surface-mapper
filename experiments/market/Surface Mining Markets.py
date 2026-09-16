"""Surface Mining Markets

Teste autónomo para o Rhino Surface Mapper.

Objetivo:
- Pedir apenas o nome do sistema.
- Consultar o Spansh usando a mesma lógica que já funcionava no
  "System Iridium market.py".
- Verificar os 21 produtos definidos para surface mining.
- Considerar apenas mercados locais com procura > MIN_DEMAND.
- Escolher os 3 produtos cujo melhor preço local é mais elevado.
- Mostrar até 3 estações por produto, ordenadas por:
    1) preço mais alto
    2) maior procura
    3) pad L > M > S apenas em empate
- Mostrar data/idade dos dados de mercado.
- Acrescentar média e máximo galácticos quando a API global estiver disponível.

Requer:
    pip install requests
"""

import sys
from collections import defaultdict
from datetime import datetime, timezone
from time import perf_counter
import unicodedata

import requests


# ============================================================
# CONFIGURAÇÃO
# ============================================================

SPANSH_BASE_URL = "https://spansh.co.uk/api"
GLOBAL_BASE_URL = "https://api.eddata.dev/v2"

MIN_DEMAND = 100          # nesta fase: procura tem de ser > 100 t
TOP_PRODUCTS = 3
TOP_STATIONS = 3

# 13 novos produtos introduzidos com Surface Mining + 8 minerais
# de alto valor que podem fazer parte do conjunto que queremos vigiar.
# Total: 21.
#
# A comparação é normalizada, portanto "Bastnäsite" também casa com
# "Bastnasite" se a API usar a forma sem acento.
SURFACE_COMMODITIES = [
    "Alexandrite",
    "Bastnäsite",
    "Deuterium",
    "Diamond",
    "Grandidierite",
    "Helium",
    "Helium-3",
    "Iridium",
    "Jadeite",
    "Magnesite",
    "Monazite",
    "Olivine",
    "Osmium",
    "Periclase Dunite",
    "Platinum",
    "Quartz Pyroxenite",
    "Rhodplumsite",
    "Ruby",
    "Sapphire",
    "Serendibite",
    "Thortveitite",
]


# ============================================================
# FUNÇÕES DE APOIO
# ============================================================

def get_json(session, method, path, base_url=SPANSH_BASE_URL, **kwargs):
    response = session.request(
        method,
        base_url + path,
        timeout=25,
        **kwargs,
    )
    response.raise_for_status()
    return response.json()


def normalize_name(value):
    """Compara nomes ignorando maiúsculas, acentos, espaços e pontuação."""
    if value is None:
        return ""

    text = unicodedata.normalize("NFKD", str(value))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return "".join(ch.casefold() for ch in text if ch.isalnum())


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
    """Idade aproximada dos dados, em formato curto."""
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

    days = hours // 24
    return f"{days}d"


# ============================================================
# SPANSH — PESQUISA DO SISTEMA
# ============================================================

def find_system(session, name):
    """
    Mantém a lógica que já funcionava no teste anterior:
    POST /systems/search com filtro pelo nome e confirmação exata.
    """
    page = 0
    seen = set()

    while True:
        data = get_json(
            session,
            "POST",
            "/systems/search",
            json={
                "filters": {
                    "name": {
                        "value": name,
                    }
                },
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
    """
    Inclui estações diretamente no sistema e estações dos corpos,
    sem duplicar market_id.
    """
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
    """Maior plataforma disponível: L, M, S ou ?."""
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
    """Só serve para desempatar preço e procura."""
    return {
        "L": 3,
        "M": 2,
        "S": 1,
        "?": 0,
    }.get(pad, 0)


# ============================================================
# LEITURA DOS 21 PRODUTOS EM CADA ESTAÇÃO
# ============================================================

def station_surface_rows(record, wanted_by_key, min_demand):
    """
    Lê o mercado de UMA estação uma única vez e devolve todos os
    produtos de surface mining que tenham:
        sell_price > 0
        demand > min_demand

    Importante:
    - mercado ausente => erro/incompleto
    - produto ausente ou demand <= limite => não entra nos resultados
    """
    market = record.get("market")

    if not isinstance(market, list):
        raise ValueError("Sem dados de mercado no detalhe da estação")

    pad = landing_pad(record)
    market_updated_at = record.get("market_updated_at") or "Desconhecido"
    updated_at = record.get("updated_at") or "Desconhecido"

    rows = []

    for item in market:
        raw_name = item.get("commodity", "")
        key = normalize_name(raw_name)

        canonical_name = wanted_by_key.get(key)
        if canonical_name is None:
            continue

        demand = item.get("demand")
        sell_price = item.get("sell_price")

        try:
            demand = int(demand)
        except (TypeError, ValueError):
            # Não assumimos procura zero se a procura é desconhecida.
            continue

        try:
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


def query_system_surface_markets(
    name,
    min_demand=MIN_DEMAND,
    progress=print,
):
    """
    Consulta cada estação candidata UMA vez e, nessa resposta,
    procura os 21 produtos.
    """
    results = defaultdict(list)
    errors = []

    wanted_by_key = {
        normalize_name(name): name
        for name in SURFACE_COMMODITIES
    }

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

        candidates = [
            (key, station)
            for key, station in stations.items()
            if (
                station.get("has_market") is True
                or "Market" in station.get("services", [])
            )
        ]

        progress(
            f"{len(stations)} estações registadas; "
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

                if record.get("has_market") is False:
                    continue

                rows = station_surface_rows(
                    record,
                    wanted_by_key,
                    min_demand,
                )

                for row in rows:
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

    # Em cada produto:
    # 1.º preço, 2.º procura, 3.º pad apenas em empate.
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
# MÉDIA E MÁXIMO GALÁCTICOS
# ============================================================

def query_galaxy_summary():
    """
    Obtém o relatório global de mercadorias.

    Esta parte é deliberadamente independente do Spansh:
    se falhar, a pesquisa local continua a funcionar.

    O endpoint global usado atualmente exclui Fleet Carriers.
    """
    with requests.Session() as session:
        session.headers.update(
            {
                "User-Agent": "RhinoSurfaceMapper/1.0",
                "Accept": "application/json",
            }
        )

        data = get_json(
            session,
            "GET",
            "/commodities",
            base_url=GLOBAL_BASE_URL,
        )

    if not isinstance(data, list):
        raise ValueError(
            "Formato inesperado na resposta das estatísticas galácticas."
        )

    summary = {}

    for item in data:
        name = item.get("commodityName")
        if not name:
            continue

        summary[normalize_name(name)] = {
            "name": name,
            "average": item.get("avgSellPrice"),
            "maximum": item.get("maxSellPrice"),
            "total_demand": item.get("totalDemand"),
        }

    return summary


def galaxy_stats(product, summary):
    return summary.get(
        normalize_name(product),
        {
            "average": None,
            "maximum": None,
            "total_demand": None,
        },
    )


# ============================================================
# ESCOLHA DOS 3 PRODUTOS
# ============================================================

def select_top_products(results, limit=TOP_PRODUCTS):
    """
    Escolhe os produtos pelo melhor preço local possível.

    Se dois produtos tiverem o mesmo melhor preço:
      - maior procura nessa melhor estação
      - depois maior pad
    """
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


# ============================================================
# APRESENTAÇÃO
# ============================================================

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
        f"SURFACE MINING — {system_name.upper()} "
        f"| PROCURA LOCAL > {format_number(min_demand)} t"
    )
    print("=" * 112)

    if not selected:
        print()
        print(
            "Não foram encontrados produtos da lista de surface mining "
            f"com procura superior a {format_number(min_demand)} t."
        )

    for number, info in enumerate(selected, 1):
        product = info["product"]
        stats = galaxy_stats(product, galaxy_summary)

        print()
        print(f"{number}. {product.upper()}")

        if stats.get("average") is not None or stats.get("maximum") is not None:
            print(
                "   Galáxia (sem Fleet Carriers) — "
                f"Média: {format_number(stats.get('average'))} Cr/t"
                f" | Máximo: {format_number(stats.get('maximum'))} Cr/t"
            )
        else:
            print(
                "   Galáxia — média/máximo não disponíveis."
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


# ============================================================
# MAIN
# ============================================================

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
        exact_name, local_results, errors = query_system_surface_markets(
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

    # A consulta global é complementar.
    # Se falhar, não invalida os dados locais.
    try:
        galaxy_summary = query_galaxy_summary()
    except (
        requests.RequestException,
        ValueError,
        KeyError,
        TypeError,
    ) as exc:
        print()
        print(
            "Aviso: não foi possível obter a média/máximo galácticos: "
            f"{exc}"
        )
        galaxy_summary = {}

    selected = select_top_products(local_results)

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
        raise SystemExit(main())
    except (KeyboardInterrupt, EOFError):
        print("\nConsulta cancelada.")
        raise SystemExit(130)
