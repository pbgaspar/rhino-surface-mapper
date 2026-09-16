"""Compara três consultas reais de cada versão, sem cache de mercado."""

import contextlib
import importlib.util
import io
import statistics
from pathlib import Path
from time import perf_counter
from unittest.mock import patch

import requests


def load(filename, name):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(filename))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    original = load("Market price test.py", "original")
    optimized = load("Market price optimized.py", "optimized")
    durations = {"original": [], "optimized": []}
    real_request = requests.Session.request
    for iteration in range(3):
        outputs = {}
        # Alternar a ordem para reduzir a vantagem sistemática da segunda consulta.
        order = ("original", "optimized") if iteration % 2 == 0 else ("optimized", "original")
        for mode in order:
            calls = []

            def counted(session, method, url, **kwargs):
                calls.append((method, url))
                return real_request(session, method, url, **kwargs)

            output = io.StringIO()
            started = perf_counter()
            with patch.object(requests.Session, "request", counted), contextlib.redirect_stdout(output):
                if mode == "original":
                    original.get_commodity_price_spansh("Poisson Orbital", "Kappa", "Iridium")
                else:
                    result = optimized.get_commodity_price_spansh(
                        "Poisson Orbital", "Kappa", "Iridium", "3229734912")
                    optimized.print_price(result)
            elapsed = perf_counter() - started
            assert len(calls) == (2 if mode == "original" else 1), calls
            durations[mode].append(elapsed)
            outputs[mode] = [line.strip() for line in output.getvalue().splitlines() if line.strip()]
            print(f"Consulta {iteration + 1}: {mode}: {len(calls)} pedidos, {elapsed:.3f} s")
        assert any(line.startswith("Commodity:") for line in outputs["original"]), outputs
        assert all(line in outputs["optimized"] for line in outputs["original"]), outputs
        print("  Preços, procura, stock e updated_at iguais.")
    for mode, values in durations.items():
        print(f"Mediana {mode}: {statistics.median(values):.3f} s")

    # Verificar também o caminho genérico, sem ID conhecido.
    resolved = optimized.get_commodity_price_spansh("Poisson Orbital", "Kappa", "Iridium")
    assert resolved["station_id"] == "3229734912" and resolved["requests"] == 2
    print("Pesquisa sem ID: estação correta, seguida de pedido ao detalhe.")
    optimized.print_price(resolved)


if __name__ == "__main__":
    main()
