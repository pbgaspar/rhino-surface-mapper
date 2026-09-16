"""Executar e introduzir o sistema e a mercadoria (nome em inglês no Spansh).

Requer requests (pip install requests).
"""

import sys
from time import perf_counter

import requests


BASE_URL = "https://spansh.co.uk/api"


def get_json(session, method, path, **kwargs):
    response = session.request(method, BASE_URL + path, timeout=25, **kwargs)
    response.raise_for_status()
    return response.json()


def find_system(session, name):
    page = 0
    seen = set()
    while True:
        data = get_json(session, "POST", "/systems/search", json={
            "filters": {"name": {"value": name}}, "size": 100, "page": page,
        })
        results = data.get("results", [])
        for item in results:
            if item.get("name", "").casefold() == name.casefold():
                return item["id64"]
        ids = {str(item["id64"]) for item in results}
        if not results:
            return None
        if ids.issubset(seen):
            raise ValueError("A API repetiu a página da pesquisa; pesquisa incompleta.")
        seen.update(ids)
        if len(seen) >= data["count"]:
            return None
        page += 1


def collect_stations(record):
    """Inclui estações do sistema e de corpos, sem duplicar market_id."""
    stations = {}

    def visit(node):
        for station in node.get("stations", []):
            identifier = station.get("market_id")
            if identifier is not None:
                stations[str(identifier)] = station
        for body in node.get("bodies", []):
            visit(body)

    visit(record)
    return stations


def landing_pad(record):
    for field, label in (("large_pads", "L (grande)"),
                         ("medium_pads", "M (média)"),
                         ("small_pads", "S (pequena)")):
        if field == "large_pads" and record.get("has_large_pad") is True:
            return label
        if (record.get(field) or 0) > 0:
            return label
    return "Desconhecida"


def commodity_row(record, commodity):
    market = record.get("market")
    if not isinstance(market, list):
        raise ValueError("Sem dados de mercado no detalhe da estação")
    for item in market:
        if item.get("commodity", "").casefold() != commodity.strip().casefold():
            continue
        demand = item.get("demand")
        if demand is None:
            raise ValueError(f"Procura de {commodity} desconhecida")
        if demand <= 0:
            return None
        return {
            "name": record["name"], "price": item.get("sell_price"),
            "demand": demand, "pad": landing_pad(record),
            "market_updated_at": record.get("market_updated_at") or "Desconhecido",
            "updated_at": record.get("updated_at") or "Desconhecido",
        }
    return None


def query_system(name, commodity, progress=print):
    rows, errors = [], []
    with requests.Session() as session:
        session.headers.update({"User-Agent": "RhinoSurfaceMapper/1.0", "Accept": "application/json"})
        identifier = find_system(session, name)
        if identifier is None:
            raise ValueError(f"Sistema '{name}' não encontrado por nome exato.")
        system = get_json(session, "GET", f"/system/{identifier}")["record"]
        if system.get("name", "").casefold() != name.casefold():
            raise ValueError("O sistema devolvido não corresponde ao nome pedido.")
        stations = collect_stations(system)
        # A lista do sistema anuncia os mercados; não filtrar por procura aqui,
        # porque só o detalhe fornece os preços e a procura mais recentes.
        candidates = [(key, station) for key, station in stations.items()
                      if station.get("has_market") is True or "Market" in station.get("services", [])]
        progress(f"{len(stations)} estações registadas; a verificar {len(candidates)} possíveis mercados...")
        for index, (key, station) in enumerate(candidates, 1):
            progress(f"  [{index}/{len(candidates)}] {station['name']}")
            try:
                record = get_json(session, "GET", f"/station/{int(key)}")["record"]
                if record.get("system_name", "").casefold() != name.casefold():
                    errors.append(f"{station['name']}: já não está neste sistema.")
                    continue
                if record.get("has_market") is False:
                    continue
                row = commodity_row(record, commodity)
                if row:
                    rows.append(row)
            except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
                errors.append(f"{station['name']}: {exc}")
    rows.sort(key=lambda row: (row["price"] if row["price"] is not None else -1,
                               row["demand"]), reverse=True)
    return rows, errors


def print_results(name, commodity, rows, errors):
    print(f"\n--- {commodity.upper()}: {name.upper()} ---")
    print("Preço: quanto recebes por unidade ao vender à estação. Plataforma: tamanho máximo.\n")
    if rows:
        headers = ["Estação", "Venda (CR/t)", "Procura (t)", "Plataforma", "Atualização do mercado (UTC)"]
        cells = [[row["name"], f"{row['price']:,}" if row["price"] is not None else "Sem dados",
                  f"{row['demand']:,}", row["pad"], row["market_updated_at"]] for row in rows]
        widths = [max(len(line[i]) for line in [headers] + cells) for i in range(len(headers))]
        for line in [headers] + cells:
            print(" | ".join(value.ljust(width) for value, width in zip(line, widths)))
        print("\nAtualização geral da estação (UTC):")
        for row in rows:
            print(f"  {row['name']}: {row['updated_at']}")
    else:
        print(f"Não foi encontrada procura positiva de {commodity} nas estações verificadas.")
    if errors:
        print("\nResultado parcial — não foi possível confirmar estas estações:")
        for error in errors:
            print(f"  {error}")
    print(f"\n{len(rows)} estações com procura de {commodity}; {len(errors)} verificações incompletas.")


def main():
    name = " ".join(sys.argv[1:]).strip() if len(sys.argv) > 1 else input("Nome do sistema: ").strip()
    if not name:
        print("Introduz um nome de sistema.")
        return 1
    commodity = input("Nome da mercadoria (em inglês, por exemplo Iridium): ").strip()
    if not commodity:
        print("Introduz um nome de mercadoria.")
        return 1
    started = perf_counter()
    try:
        rows, errors = query_system(name, commodity)
        print_results(name, commodity, rows, errors)
        print(f"Tempo total: {perf_counter() - started:.2f} s")
        return 2 if errors else 0
    except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
        print(f"Erro ao consultar o sistema: {exc}")
        return 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (KeyboardInterrupt, EOFError):
        print("\nConsulta cancelada.")
        raise SystemExit(130)
