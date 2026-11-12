import pytest

from contacts_cli.api import GoogleAPI

from .fake_google import FakeGoogle


@pytest.fixture
def server():
    return FakeGoogle()


@pytest.fixture
def api(server):
    return GoogleAPI(*server.clients())


def pytest_addoption(parser):
    parser.addoption("--installed-cli", help="Absolute CLI executable for clean-wheel checks")
