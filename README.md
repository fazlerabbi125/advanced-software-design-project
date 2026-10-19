## BFS Gym API

### Local development

Use your local PostgreSQL instance and pgAdmin. Create a PostgreSQL database and role matching `.env`, then copy `.env.example` to `.env` and replace the placeholder secrets.

```powershell
uv sync --all-groups
docker compose -f compose.local.yml --env-file .env up -d
uv run --env-file .env alembic upgrade head
uv run --env-file .env -m app.main or uv run --env-file .env fastapi dev app/main.py
```

Start the optional local worker in another terminal:

```powershell
uv run --env-file .env celery --app=app.queue.celery_app:celery_app worker --pool=solo --loglevel=INFO --queues=bfs_gym
```

### Complete Docker setup

Copy `.env.docker.example` to `.env.docker`, replace the placeholder secrets, then run:

```powershell
docker compose --env-file .env.docker up --build
```

The `migrate` service applies the current schema before the API starts. After creating a new migration, run it with:

```powershell
docker compose --env-file .env.docker run --rm migrate
```

Swagger is available at `http://localhost:8000/docs` and pgAdmin at `http://localhost:5050` in the complete Docker setup.

The cache Redis instance is exposed on port `6379`, is bounded by `CACHE_REDIS_MAXMEMORY`, and uses LRU eviction without persistence. The Celery broker/result Redis instance is exposed on port `6380`, uses AOF with one-second fsync, and rejects writes rather than evicting queued work.

Dependencies are declared in `pyproject.toml` and locked in `uv.lock`. Run `uv run ruff format --check .` and `uv run ruff check .` before committing changes.

## Membership tiers

- Basic: Gym Floor access.
- Standard: Basic benefits plus class and pool booking.
- Premium: Standard benefits plus refreshments, personal training, training plans, and VIP sauna, massage, and cold-plunge access.

## Membership prices

Plans are priced in cent and last 30 days: Basic EUR 30, Standard EUR 45, Premium EUR 70. List them with `GET /api/v1/memberships/plans` and buy one with `POST /api/v1/memberships/purchase` (payments use the mock gateway, which approves every charge).

## VIP rooms and occupancy

Each VIP room (sauna, massage, cold plunge) holds at most `VIP_ROOM_CAPACITY` people at once (default 8); a check-in to a full room returns 409. A visit counts towards a zone for a fixed time (sauna 30 min, massage 60, cold plunge 15, gym floor 180), after which the member is counted out automatically; checking out earlier frees the place straight away. Staff and managers can see the live counts with `GET /api/v1/access/occupancy`.

## Renewing and cancelling

A membership is active, expired (past its end date) or cancelled, and what members can do depends on that state:

- `POST /api/v1/memberships/me/renew` renews on the same plan and charges again. An active membership gets another period added after its current end date; an expired one starts again from today; a cancelled one cannot be renewed (buy a new plan instead).
- `POST /api/v1/memberships/me/cancel` cancels an active membership. Access stops straight away and there is no refund.

## Staff and manager accounts

Members register through the API. Create a staff or manager account, or change an existing user's role, with:

```powershell
docker compose --env-file .env.docker exec api python -m app.scripts.create_user --email staff@bfs-gym.local --password "a-long-password" --role staff
```
