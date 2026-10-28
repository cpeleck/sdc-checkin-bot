"""Durable Discord outbox. Network I/O never runs inside a database transaction."""

import asyncio
import json
import logging
from datetime import timedelta
from typing import Protocol

from .models import instant, stamp, utc_now
from .repository import Repository

log = logging.getLogger(__name__)


class TransientDelivery(Exception):
    """Definitely not delivered; safe to retry."""


class PermanentDelivery(Exception):
    """Configuration or permissions must be repaired before retrying."""


class AmbiguousDelivery(Exception):
    """A create-message operation may have succeeded; a human must check."""


class Transport(Protocol):
    async def publish(self, delivery: dict, checkpoint) -> list[int]: ...


class Dispatcher:
    def __init__(
        self,
        repository: Repository,
        transport: Transport,
        clock=utc_now,
        guild_id: int | None = None,
    ):
        self.repository = repository
        self.transport = transport
        self.clock = clock
        self.guild_id = guild_id
        self.lock = asyncio.Lock()

    async def recover(self):
        async with self.repository.transaction() as tx:
            scope = {"guild_id": self.guild_id} if self.guild_id is not None else {}
            for row in await tx.all("deliveries", state="sending", **scope):
                await tx.update(
                    "deliveries",
                    {"id": row["id"]},
                    state="ambiguous",
                    error="Process stopped during delivery. Check Discord before /sdc retry.",
                    updated_at=stamp(self.clock()),
                )

    async def _valid(self, tx, row: dict) -> bool:
        if row["kind"] not in ("prompt", "reminder"):
            return True
        payload = json.loads(row["payload_json"])
        round_ = await tx.one("rounds", id=payload["round_id"])
        if not round_ or round_["closed_at"]:
            return False
        if row["kind"] == "reminder":
            if await tx.one("checkins", round_id=round_["id"], project_id=payload["project_id"]):
                return False
            if payload.get("automatic") and self.clock() >= instant(round_["due_at"]):
                return False
        return True

    async def flush(self, limit: int = 100):
        async with self.lock:
            for _ in range(limit):
                row = await self._claim()
                if row is None:
                    return

                async def checkpoint(ids):
                    async with self.repository.transaction() as tx:
                        current = await tx.one("deliveries", id=row["id"])
                        if current["channel_id"] == row["channel_id"]:
                            await tx.update(
                                "deliveries", {"id": row["id"]}, message_ids=json.dumps(ids)
                            )

                try:
                    ids = await self.transport.publish(row, checkpoint)
                except PermanentDelivery as exc:
                    await self._failure(row, "failed", str(exc))
                except TransientDelivery as exc:
                    await self._failure(row, "retry" if row["attempts"] < 5 else "failed", str(exc))
                except AmbiguousDelivery as exc:
                    await self._failure(row, "ambiguous", str(exc))
                except Exception:
                    # Unexpected errors can happen after a successful HTTP send, too.
                    log.exception("Unexpected failure for delivery %s", row["id"])
                    await self._failure(
                        row, "ambiguous", "Unexpected delivery error; check logs and Discord."
                    )
                else:
                    async with self.repository.transaction() as tx:
                        current = await tx.one("deliveries", id=row["id"])
                        same_channel = current["channel_id"] == row["channel_id"]
                        await tx.update(
                            "deliveries",
                            {"id": row["id"]},
                            state="sent" if current["version"] == row["version"] else "pending",
                            message_ids=json.dumps(ids) if same_channel else "[]",
                            error=None,
                            updated_at=stamp(self.clock()),
                        )

    async def _claim(self) -> dict | None:
        async with self.repository.transaction() as tx:
            scope = {"guild_id": self.guild_id} if self.guild_id is not None else {}
            for row in await tx.all("deliveries", **scope):
                if row["state"] not in ("pending", "retry"):
                    continue
                if row["next_attempt_at"] and instant(row["next_attempt_at"]) > self.clock():
                    continue
                if not await self._valid(tx, row):
                    await tx.update("deliveries", {"id": row["id"]}, state="skipped")
                    continue
                row.update(state="sending", attempts=row["attempts"] + 1)
                await tx.update(
                    "deliveries",
                    {"id": row["id"]},
                    state="sending",
                    attempts=row["attempts"],
                    updated_at=stamp(self.clock()),
                )
                return row
        return None

    async def _failure(self, row: dict, state: str, error: str):
        log.warning("Delivery %s %s: %s", row["id"], state, error)
        async with self.repository.transaction() as tx:
            await tx.update(
                "deliveries",
                {"id": row["id"]},
                state=state,
                error=error[:1000],
                next_attempt_at=stamp(
                    self.clock() + timedelta(seconds=min(300, 2 ** row["attempts"]))
                )
                if state == "retry"
                else None,
                updated_at=stamp(self.clock()),
            )
