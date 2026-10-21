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

When a VIP room is full, the member is put on that room's waiting list and the 409 response tells them their position. Places that free up go to the front of the list first, so nobody can jump the queue; a member who does not come back within 30 minutes loses their place. Members can check their position with `GET /api/v1/access/waitlist/{zone}` and leave with `DELETE /api/v1/access/waitlist/{zone}`.

## Face-recognition door scanners

Face matching happens on the scanner, not in this API. When a scanner recognises a member it calls `POST /api/v1/access/device-check-in` with `{"member_id": 3}` and its secret key in the `X-Device-Key` header. Each key is mapped to the zone its door opens in `SCANNER_DEVICE_KEYS`, for example `SCANNER_DEVICE_KEYS='{"a-long-random-key": "vip_sauna"}'`. The usual entry rules apply, and the entry is logged with `source: face_recognition`.

## Staff and manager accounts

Members register through the API. Create a staff or manager account, or change an existing user's role, with:

```powershell
docker compose --env-file .env.docker exec api python -m app.scripts.create_user --email staff@bfs-gym.local --password "a-long-password" --role staff
```

## Booking eligibility (Chain of Responsibility)

`BookingService.create` loads the current membership, plan and requested week's bookings,
then passes a `BookingContext` through the handlers in
`app/modules/bookings/eligibility.py`. Every handler forwards to its successor even when
it fails. Rejections return HTTP 422 with a `detail` array of `{code, message}` entries.
Invalid request data (including a missing timezone) retains the normal validation response.

The chain checks future start time, active membership covering the session, plan entitlement,
booking window, weekly limit, and another confirmed booking at the same instant. Missing
membership is reported once; checks needing an unknown plan are not evaluated. Limits are
stored on `membership_plans`: Basic 2 days / 3 bookings, Standard 3 / 5, Premium 7 / 10.
Run `alembic upgrade head` before using the change. Custom plans default to Basic limits;
set their database values explicitly as needed. There is not yet a manager configuration API.
Windows are rolling 24-hour days, inclusive at the boundary. Weeks and membership dates use
UTC; weekly counts use the requested session's Monday–Sunday week, excluding cancellations.

A user-row lock covers membership lookup, eligibility checks and insertion. This prevents
parallel requests by the same member from exceeding the weekly limit. Cancelling and
rebooking an identical slot reuses the cancelled row because the existing unique constraint
also covers cancelled rows. The API request shape is unchanged.

To add a rule, implement `EligibilityRule.check` and register the class in `DEFAULT_RULES`.
Keep database reads and writes in the service; handlers consume the loaded context.

### Remaining report requirements

The current model has only confirmed/cancelled bookings, a resource name/type and a start
time. This implementation does **not** claim full report compliance:

- Full interval conflicts need authoritative session end times. Replace `SameStartRule`
  when those exist and load bookings overlapping the interval, including the previous week.
- Shared capacity and unit allocation need a timetable/session record and station/lane
  inventory. Check and allocate under a session-row lock in the booking transaction;
  the user-row lock does not protect capacity between different members.
- Equipment daily caps need equipment types and equipment bookings (currently unsupported).
- Suspension needs persisted suspension dates or an agreed no-show history mechanism.
- Once checked-in/no-show statuses exist, include them in the weekly count. Reuse the chain
  for waitlist acceptance when the session-based waitlist/offer workflow is implemented.

These are integration tasks, not rules silently marked as passing. No facilities subsystem,
Observer notifications, or membership State implementation is added here.

### Booking tests

```sh
uv run python -m unittest discover -s tests -v
uv run ruff check .
uv run ruff format --check .
```

The unit/API tests need no running services. Five service tests run only when
`BFS_TEST_DATABASE_URL` points to an explicitly chosen disposable PostgreSQL database:

```sh
BFS_TEST_DATABASE_URL='postgresql+asyncpg://test_user:test_password@127.0.0.1:5432/bfs_test' \
  uv run python -m unittest discover -s tests -v
```

Service tests create and remove a uniquely named schema. They never read the application's
configured database URL. Use the project's locked Python/dependency versions for reproduction.
