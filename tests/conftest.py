from datetime import UTC, datetime

import pytest

from sdc_bot.models import Actor
from sdc_bot.repository import Repository
from sdc_bot.services import Services


class Clock:
    def __init__(self):
        self.now = datetime(2026, 10, 26, 14, 0, tzinfo=UTC)

    def __call__(self):
        return self.now


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def admin():
    return Actor(100, 1, manage_guild=True, channel_id=400)


@pytest.fixture
def board():
    return Actor(100, 2, frozenset({200}), channel_id=400)


@pytest.fixture
def member():
    return Actor(100, 3, channel_id=500)


@pytest.fixture
async def repo(tmp_path):
    repo = Repository(str(tmp_path / "test.sqlite3"))
    await repo.open()
    yield repo
    await repo.close()


@pytest.fixture
async def services(repo, clock, admin, board):
    services = Services(repo, clock)
    await services.setup(admin, 200, 400)
    await services.save_project(
        board, name="Alpha", channel_id=500, contact_id=2, milestone="Prototype"
    )
    await services.save_project(board, name="Beta", channel_id=501)
    return services
