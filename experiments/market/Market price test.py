import requests


BASE_URL = "https://spansh.co.uk/api"
USER_AGENT = "RhinoSurfaceMapper/1.0"


def find_market_items(value):
    """
    Procura recursivamente uma lista de itens de mercado
    dentro da resposta JSON do Spansh.
    """

    if isinstance(value, list):
        if value and all(
            isinstance(item, dict)
            and "commodity" in item
            for item in value
        ):
            return value

        for item in value:
            result = find_market_items(item)

            if result:
                return result

    elif isinstance(value, dict):
        # Caso normal: market é uma lista
        market = value.get("market")

        if isinstance(market, list):
            result = find_market_items(market)

            if result:
                return result

        # Procurar também noutras propriedades
        for key, child in value.items():
            if key == "market":
                continue

            result = find_market_items(child)

            if result:
                return result

    return []


def find_updated_at(value):
    """
    Procura recursivamente o campo updated_at.
    """

    if isinstance(value, dict):
        if value.get("updated_at"):
            return value["updated_at"]

        for child in value.values():
            result = find_updated_at(child)

            if result:
                return result

    elif isinstance(value, list):
        for child in value:
            result = find_updated_at(child)

            if result:
                return result

    return "Desconhecido"


def get_commodity_price_spansh(
    station_name: str,
    system_name: str,
    commodity_name: str
):
    """Obtém o mercado actualizado de uma estação via Spansh."""

    search_url = f"{BASE_URL}/stations/search"

    search_payload = {
        "filters": {
            "name": {
                "value": station_name
            },
            "system_name": {
                "value": system_name
            }
        },
        "size": 1
    }

    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json"
    }

    try:
        # Procurar a estação
        response = requests.post(
            search_url,
            json=search_payload,
            headers=headers,
            timeout=20
        )

        response.raise_for_status()

        results = response.json().get("results", [])

        if not results:
            print(
                f"Estação '{station_name}' no sistema "
                f"'{system_name}' não encontrada."
            )
            return

        search_station = results[0]
        market_id = search_station.get("id")

        if not market_id:
            print("A pesquisa não devolveu o ID da estação.")
            return

        # Obter os dados detalhados da estação
        station_url = f"{BASE_URL}/station/{market_id}"

        station_response = requests.get(
            station_url,
            headers=headers,
            timeout=20
        )

        station_response.raise_for_status()

        station_data = station_response.json()

        # Obter timestamp e lista do mercado
        updated_at = find_updated_at(station_data)
        market_list = find_market_items(station_data)

        print(
            f"\n--- MERCADO: {station_name.upper()} "
            f"({system_name.upper()}) ---"
        )
        print(f"Atualizado a: {updated_at}\n")

        wanted_commodity = commodity_name.casefold()

        for item in market_list:
            item_name = item.get("commodity", "")

            if item_name.casefold() != wanted_commodity:
                continue

            # Segundo a estrutura apresentada pelo Spansh:
            # buy_price  = preço a que o comandante compra
            # sell_price = preço a que o comandante vende
            buy_price = item.get("buy_price", 0)
            sell_price = item.get("sell_price", 0)

            # Estes valores são relativos à estação
            demand = item.get("demand", 0)
            supply = item.get("supply", 0)

            print(f"Commodity: {item_name.upper()}")
            print(
                f"  Você COMPRA à estação por: "
                f"{buy_price:,} CR"
            )
            print(
                f"  Você VENDE à estação por:  "
                f"{sell_price:,} CR"
            )
            print(f"  Procura da estação: {demand:,}")
            print(f"  Stock da estação: {supply:,}\n")

            return

        print(
            f"A commodity '{commodity_name}' "
            "não foi encontrada no mercado."
        )

    except requests.exceptions.Timeout:
        print("Erro: a ligação ao Spansh excedeu o tempo limite.")

    except requests.exceptions.HTTPError as exc:
        print(f"Erro HTTP do Spansh: {exc}")

    except requests.exceptions.RequestException as exc:
        print(f"Erro na ligação à API do Spansh: {exc}")

    except ValueError as exc:
        print(f"Erro ao interpretar a resposta JSON: {exc}")


if __name__ == "__main__":
    get_commodity_price_spansh(
        "Poisson Orbital",
        "Kappa",
        "Iridium"
    )