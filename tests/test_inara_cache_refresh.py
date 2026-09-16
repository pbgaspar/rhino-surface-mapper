import importlib.util
from pathlib import Path


def load_module():
    script_path = (
        Path(__file__).resolve().parents[1]
        / "tests"
        / "test-market"
        / "Surface Mining Markets - cache INARA.py"
    )
    spec = importlib.util.spec_from_file_location(
        "inara_cache_script",
        script_path,
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_inara_cache_refresh_contract_and_product_count():
    module = load_module()

    assert len(module.SURFACE_COMMODITIES) == 37
    assert hasattr(module, "cache_age_seconds")
    assert hasattr(module, "refresh_inara_cache_if_needed")
