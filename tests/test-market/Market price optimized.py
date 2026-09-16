"""Consulta fresca ao Spansh: um pedido quando o ID da estação é conhecido.

Não guarda preços nem datas em cache. O ID por omissão foi confirmado na API
para Poisson Orbital / Kappa. Para outra estação, omitir station_id.
"""

from time import perf_counter

import requests


BASE_URL = "https://spansh.co.uk/api"


def same_station(record, station_name, system_name):
    return (
        str(record.get("name", "")).casefold() == station_name.casefold()
        and str(record.get("system_name", "")).casefold() == system_name.casefold()
    )


def get_commodity_price_spansh(station_name, system_name, commodity_name,
                              station_id=None):
    started = perf_counter()
    request_count = 0
    with requests.Session() as session:
        session.headers.update({
            "User-Agent": "RhinoSurfaceMapper/1.0",
            "Accept": "application/json",
        })

        def request(method, path, **kwargs):
            nonlocal request_count
            request_count += 1
            response = session.request(method, BASE_URL + path, timeout=20, **kwargs)
            response.raise_for_status()
            return response.json()

        def detail(identifier):
            record = request("GET", f"/station/{int(identifier)}").get("record")
            if not isinstance(record, dict):
                raise ValueError("Resposta sem o objeto 'record' da estação.")
            return record

        record = None
        if station_id is not None:
            try:
                record = detail(station_id)
            except requests.HTTPError as exc:
                if exc.response.status_code != 404:
                    raise
            if record is not None and not same_station(record, station_name, system_name):
                record = None

        if record is None:
            search = request("POST", "/stations/search", json={
                "filters": {
                    "name": {"value": station_name},
                    "system_name": {"value": system_name},
                },
                "size": 100,
            })
            matches = [item for item in search.get("results", [])
                       if same_station(item, station_name, system_name)]
            if len(matches) != 1:
                raise ValueError("A pesquisa não identificou uma única estação exata.")
            station_id = matches[0]["id"]
            # O mercado da pesquisa pode estar mais antigo: obter sempre o detalhe.
            record = detail(station_id)
            if not same_station(record, station_name, system_name):
                raise ValueError("O ID devolvido não corresponde à estação pedida.")

        market = record.get("market")
        if not isinstance(market, list):
            raise ValueError("A resposta não contém uma lista de mercado.")
        item = next((item for item in market
                     if item.get("commodity", "").casefold() == commodity_name.casefold()), None)
        if item is None:
            raise ValueError(f"A commodity '{commodity_name}' não foi encontrada no mercado.")

    return {
        "station_id": str(station_id),
        "station_name": record["name"],
        "system_name": record["system_name"],
        "updated_at": record.get("updated_at"),
        "market_updated_at": record.get("market_updated_at"),
        "commodity": item["commodity"],
        **{key: item.get(key) for key in ("buy_price", "sell_price", "demand", "supply")},
        "requests": request_count,
        "elapsed_seconds": perf_counter() - started,
    }


def print_price(result):
    def number(key):
        value = result[key]
        return "Sem dados" if value is None else f"{value:,}"

    print(f"\n--- MERCADO: {result['station_name'].upper()} ({result['system_name'].upper()}) ---")
    print(f"Atualizado a: {result['updated_at'] or 'Desconhecido'}")
    print(f"Mercado atualizado a: {result['market_updated_at'] or 'Desconhecido'}\n")
    print(f"Commodity: {result['commodity'].upper()}")
    print(f"  Você COMPRA à estação por: {number('buy_price')} CR")
    print(f"  Você VENDE à estação por:  {number('sell_price')} CR")
    print(f"  Procura da estação: {number('demand')}")
    print(f"  Stock da estação: {number('supply')}\n")
    print(f"ID: {result['station_id']} | Pedidos: {result['requests']} | Tempo: {result['elapsed_seconds']:.3f} s")


if __name__ == "__main__":
    try:
        print_price(get_commodity_price_spansh(
            "Poisson Orbital", "Kappa", "Iridium", station_id="3229734912"
        ))
    except (requests.RequestException, ValueError, KeyError) as exc:
        print(f"Erro ao consultar o mercado: {exc}")
        raise SystemExit(1)
