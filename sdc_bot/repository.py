"""SQLite persistence and a serial, transactional unit of work.

Only internal, constant table/column identifiers reach the query helpers. Values are
always bound parameters. The process lock covers reads as well as writes so another
coroutine cannot accidentally commit part of an in-progress transaction.
"""

import asyncio
import fcntl
import json
from contextlib import asynccontextmanager
from importlib.resources import files
from pathlib import Path

import aiosqlite


class UnitOfWork:
    def __init__(self, connection: aiosqlite.Connection):
        self.connection = connection

    async def one(self, table: str, **where) -> dict | None:
        rows = await self.all(table, **where)
        return rows[0] if rows else None

    async def all(self, table: str, **where) -> list[dict]:
        clause = " AND ".join(f"{key} IS ?" for key in where)
        query = f"SELECT * FROM {table}" + (f" WHERE {clause}" if clause else "")
        async with self.connection.execute(query, tuple(where.values())) as cursor:
            return [dict(row) for row in await cursor.fetchall()]

    async def insert(self, table: str, **values) -> int:
        columns = ", ".join(values)
        placeholders = ", ".join("?" for _ in values)
        async with self.connection.execute(
            f"INSERT INTO {table} ({columns}) VALUES ({placeholders})", tuple(values.values())
        ) as cursor:
            return cursor.lastrowid

    async def update(self, table: str, where: dict, **values) -> int:
        assignments = ", ".join(f"{key} = ?" for key in values)
        clause = " AND ".join(f"{key} IS ?" for key in where)
        async with self.connection.execute(
            f"UPDATE {table} SET {assignments} WHERE {clause}",
            (*values.values(), *where.values()),
        ) as cursor:
            return cursor.rowcount

    async def delete(self, table: str, **where) -> int:
        if not where:
            raise ValueError("Refusing to delete without a condition")
        clause = " AND ".join(f"{key} IS ?" for key in where)
        async with self.connection.execute(
            f"DELETE FROM {table} WHERE {clause}", tuple(where.values())
        ) as cursor:
            return cursor.rowcount

    async def enqueue(
        self,
        *,
        guild_id: int,
        key: str,
        kind: str,
        entity_id: int,
        channel_id: int,
        payload: dict,
        now: str,
    ) -> int:
        existing = await self.one("deliveries", delivery_key=key)
        values = dict(channel_id=channel_id, payload_json=json.dumps(payload), updated_at=now)
        if existing:
            if existing["channel_id"] != channel_id:
                # Message IDs are scoped to the original channel.
                values["message_ids"] = "[]"
            state = existing["state"]
            await self.update(
                "deliveries",
                {"id": existing["id"]},
                **values,
                version=existing["version"] + 1,
                state=state if state in ("sending", "ambiguous") else "pending",
                next_attempt_at=None,
                attempts=0,
                error=existing["error"] if state == "ambiguous" else None,
            )
            return existing["id"]
        return await self.insert(
            "deliveries",
            guild_id=guild_id,
            delivery_key=key,
            kind=kind,
            entity_id=entity_id,
            **values,
        )


class Repository:
    def __init__(self, path: str):
        self.path = str(Path(path).expanduser().resolve()) if path != ":memory:" else path
        self.connection: aiosqlite.Connection | None = None
        self.lock = asyncio.Lock()
        self._lock_file = None

    async def open(self):
        if self.connection is not None:
            raise RuntimeError("Repository is already open")
        if self.path != ":memory:":
            Path(self.path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
            self._lock_file = open(self.path + ".lock", "a")
            try:
                fcntl.flock(self._lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                self._lock_file.close()
                self._lock_file = None
                raise RuntimeError(
                    "Another bot process is using this database. Stop it first."
                ) from exc
        try:
            self.connection = await aiosqlite.connect(self.path, isolation_level=None)
            self.connection.row_factory = aiosqlite.Row
            await self.connection.execute("PRAGMA foreign_keys=ON")
            await self.connection.execute("PRAGMA journal_mode=WAL")
            await self.connection.execute("PRAGMA busy_timeout=5000")
            await self._migrate()
        except BaseException:
            await self.close()
            raise

    async def _migrate(self):
        await self.connection.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY)"
        )
        async with self.connection.execute("SELECT version FROM schema_migrations") as cursor:
            applied = {row[0] for row in await cursor.fetchall()}
        migrations = sorted(files("sdc_bot").joinpath("migrations").iterdir(), key=lambda p: p.name)
        for migration in migrations:
            if not migration.name.endswith(".sql"):
                continue
            version = int(migration.name.split("_")[0])
            if version not in applied:
                try:
                    await self.connection.executescript(
                        "BEGIN IMMEDIATE;\n"
                        + migration.read_text()
                        + f"\nINSERT INTO schema_migrations VALUES ({version});\nCOMMIT;"
                    )
                except BaseException:
                    await self.connection.rollback()
                    raise

    @asynccontextmanager
    async def transaction(self):
        if self.connection is None:
            raise RuntimeError("Repository is not open")
        async with self.lock:
            await self.connection.execute("BEGIN IMMEDIATE")
            try:
                yield UnitOfWork(self.connection)
                await self.connection.commit()
            except BaseException:
                await self.connection.rollback()
                raise

    async def close(self):
        if self.connection:
            await self.connection.close()
            self.connection = None
        if self._lock_file:
            fcntl.flock(self._lock_file, fcntl.LOCK_UN)
            self._lock_file.close()
            self._lock_file = None
