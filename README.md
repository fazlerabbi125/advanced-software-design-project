## BFS Gym API

Copy `.env.example` to `.env.docker`, replace the placeholder secrets, then run:

```powershell
docker compose --env-file .env.docker up --build
```

The `migrate` service applies the current schema before the API starts. After creating a new migration, run it with:

```powershell
docker compose --env-file .env.docker run --rm migrate
```

Swagger is available at `http://localhost:8000/docs` and pgAdmin at `http://localhost:5050`.

The cache Redis instance is exposed on port `6379`, is bounded by `CACHE_REDIS_MAXMEMORY`, and uses LRU eviction without persistence. The Celery broker/result Redis instance is exposed on port `6380`, uses AOF with one-second fsync, and rejects writes rather than evicting queued work.

Dependencies are declared in `pyproject.toml` and locked in `uv.lock`. Run `uv run ruff format --check .` and `uv run ruff check .` before committing changes.

## Membership tiers

- Basic: Gym Floor access.
- Standard: Basic benefits plus class and pool booking.
- Premium: Standard benefits plus refreshments, personal training, training plans, and VIP sauna, massage, and cold-plunge access.
