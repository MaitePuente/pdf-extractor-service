import pytest


def pytest_addoption(parser):
    parser.addoption(
        "--run-integration", action="store_true", default=False,
        help="Run integration tests against the extractor Docker Compose stack",
    )


def pytest_collection_modifyitems(config, items):
    if not config.getoption("--run-integration"):
        for item in items:
            if item.get_closest_marker("integration"):
                item.add_marker(pytest.mark.skip(reason="Use --run-integration with the Compose stack running"))


@pytest.fixture(autouse=True)
def isolated_cache_environment(monkeypatch, request):
    if request.node.get_closest_marker("integration"):
        return
    monkeypatch.setenv("CACHE_ENABLED", "false")
    monkeypatch.setenv("REDIS_URL", "redis://cache.test:6379/0")
    monkeypatch.setenv("CACHE_TTL_SECONDS", "60")
    monkeypatch.setenv("CACHE_TIMEOUT_SECONDS", "0.1")
