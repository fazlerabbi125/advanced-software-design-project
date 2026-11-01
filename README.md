# BFS Gym API

BFS Gym is a gym membership and facility-access management API. The gym offers a gym floor, swimming pool, fitness classes, personal training sessions, and VIP wellness rooms (sauna, massage, and cold plunge).

This repository is a proof-of-concept monolithic REST API. It demonstrates object-oriented analysis and design, domain business rules, architectural patterns, and automated testing. It is not a complete production gym-management system.

## Gym Background

BFS Gym serves three tiers of members:

- **Standard members** access the gym floor and can book fitness classes.
- **Premium members** additionally access the swimming pool, personal training, and the VIP wellness suites.
- Entry-door scanners perform face matching and send a trusted template ID plus confidence score to the API; the API validates access rules.

The business rules include membership plans with configurable booking windows and weekly limits, VIP room capacity enforcement with automatic waiting lists, booking eligibility checks before any reservation is accepted, and automated notifications when significant events occur.

## User Roles

| Role | What they can do |
|---|---|
| **Member** | Register, purchase/renew/cancel membership, book eligible activities, check in to sessions, receive in-app notifications |
| **Staff** | Everything a member can do, plus manually check in a member and view live zone occupancy |
| **Manager** | Everything staff can do, plus create and configure membership plans and view business reports |
| **Biometric scanner** | A trusted hardware device (identified by a secret device key) that submits check-in requests after a face-match |

## Implemented Features

- JWT authentication (access + refresh tokens) with member, staff, and manager roles.
- Membership plans (Basic, Standard, Premium) with entitlement-based access control.
- Stripe Checkout gateway (sandbox mode), pending memberships, and a verified, idempotent webhook that activates a membership only after payment succeeds.
- Booking creation, listing, cancellation, and eligibility feedback (active membership, plan entitlement, booking window, weekly limit, same-start conflict checks).
- VIP occupancy tracking, automatic waiting lists, and visit expiry using Redis sorted sets.
- Scanner/device check-in with indexed template lookup, confidence validation, denied-scan auditing, configurable device keys, and zone-specific access policies.
- Member biometric photo upload with local image-quality and single-face validation.
- Durable in-app notifications, Redis Pub/Sub delivery, and authenticated SSE streaming.

## Design Patterns Used

The patterns below are intentional parts of the application design, rather than
names applied to every framework feature. The role names use the course/GoF
terminology. A class can play more than one practical role, but each mapping below
identifies the important collaboration in the code.

### Strategy — choose an access rule without changing the check-in workflow

**Intent:** encapsulate interchangeable behaviours behind one interface. This keeps
`AccessService` from growing a large `if`/`elif` block for every type of gym zone.

- **Strategy:** `AccessPolicy` in `app/modules/access/policies.py` defines the
  common `check(...)` operation.
- **ConcreteStrategy:** `GymFloorPolicy` and `VipAreaPolicy` implement the rule for
  their respective zone types.
- **Context:** `AccessService` in `app/modules/access/access_service.py` selects the
  policy for the requested `AccessZone` and delegates the access decision to it.
- **Collaboration:** `build_policies(...)` assembles the zone-to-strategy mapping.
  Adding a new access rule means implementing `AccessPolicy` and registering it,
  instead of rewriting the check-in operation.

### Chain of Responsibility — run a sequence of independent checks

**Intent:** pass one request through a chain of handlers. Each handler owns one
rule, then forwards the request to its successor. This project deliberately collects
all booking failures instead of stopping at the first one.

- **Handler:** `EligibilityRule` in `app/modules/bookings/eligibility.py` provides
  `handle(...)`, a `check(...)` hook, and the successor link.
- **ConcreteHandler:** rules such as `ActiveMembershipRule`, `EntitlementRule`,
  `BookingWindowRule`, and `WeeklyLimitRule` each check one eligibility condition.
- **Client:** `BookingService` builds a `BookingContext` and sends it to the first
  handler returned by `build_eligibility_chain(...)`.
- **Outcome:** a member can see, for example, both an unavailable plan entitlement
  and a weekly-limit problem in one response.

The biometric-photo validator uses the same pattern for a different problem:
`PhotoValidationHandler` is the **Handler** and `ImageTypeHandler`,
`ReadabilityHandler`, `ImageQualityHandler`, and `SingleFaceHandler` are the
**ConcreteHandlers**. `PhotoValidator` creates the chain and is its **Client**.
The ordered checks reject an unsuitable upload before later checks need to process it.

### Factory Method — centralise payment-gateway creation

**Intent:** let client code depend on a product interface instead of directly
constructing a provider-specific object.

- **Product:** the abstract `PaymentGateway` in
  `app/modules/memberships/payment_gateway.py`.
- **ConcreteProduct:** `StripeCheckoutGateway`, which implements Stripe Checkout.
- **Creator / factory method:** `PaymentGatewayFactory.create(settings)` chooses and
  creates the configured gateway.
- **Client:** application startup calls the factory once and membership services use
  the returned `PaymentGateway` contract.

This acts as a dependency firewall: adding another provider changes the factory and
adds a new concrete product, rather than changing each service that takes payment.

### Observer — record and publish membership and booking events

**Intent:** let an event source notify interested work without tightly coupling the
source to the delivery mechanism.

- **Subject-like event sources:** booking, membership, and payment services create
  `NotificationEvent` values when their domain action succeeds.
- **Observer / ConcreteObserver:** `NotificationObserver.observe(...)` in
  `app/modules/notifications/service.py` records the event as a durable
  `Notification` in the current database transaction.
- **Notification delivery collaborator:** after a successful commit,
  `NotificationPublisher` publishes the saved notifications on a user-specific
  Redis channel; `NotificationFeed` exposes them to the member through SSE.

This is an application-specific publish/subscribe adaptation of Observer. Unlike a
textbook `Subject` that keeps an in-memory observer list, events are made durable
first and live delivery happens only after the transaction succeeds. That avoids
notifying a member about a change that is later rolled back.

### State — make membership actions depend on lifecycle state

**Intent:** represent state-specific behaviour in separate objects instead of
spreading status checks throughout a service.

- **State:** `MembershipState` in `app/modules/memberships/states.py` defines the
  operations that vary by state: `cancel(...)` and `renewal_terms(...)`.
- **ConcreteState:** `ActiveState`, `ExpiredState`, `PendingState`, and
  `CancelledState` implement the allowed behaviour for each lifecycle state.
- **Context / client:** `MembershipService` asks `state_of(membership, today)` for
  the current state and delegates the requested action to it.

For example, an active membership can be cancelled or renewed, while a pending
membership rejects both actions. The state object is selected from the persisted
membership status when needed, rather than stored as a long-lived object on the ORM
model.

### Builder — assemble a complete booking snapshot step by step

**Intent:** construct a complex object in clear steps, then return it only when it
is complete.

- **Builder:** `BookingContextBuilder` in `app/modules/bookings/builder.py` loads
  the timetable session, membership, weekly bookings, no-show status, and equipment
  usage through fluent `with_...` methods.
- **Product:** immutable `BookingContext`, the data required by the booking
  eligibility chain.
- **Director / client:** `BookingService._build_context(...)` chooses the build
  steps, then calls `build()` before running the eligibility handlers.

The builder keeps data-gathering details out of the booking operation and prevents a
partially populated context from reaching the business rules.

### Interceptor — apply cross-cutting CORS handling in the request pipeline

**Intent:** allow a framework to run an out-of-band service at defined processing
points without changing every endpoint. Here the cross-cutting concern is browser
cross-origin policy, not gym business logic.

- **Concrete Framework:** FastAPI/Starlette provides the HTTP request-processing
  pipeline.
- **Dispatcher:** the framework's middleware stack calls registered middleware for
  each request and response.
- **ConcreteInterceptor:** FastAPI's `CORSMiddleware` handles CORS preflight
  requests and adds CORS headers for origins allowed by its configuration.
- **Application:** `app/main.py` registers the interceptor with
  `app.add_middleware(...)`; debug mode and production mode supply different CORS
  settings.

This is a framework-provided Interceptor use, rather than a custom BFS Gym
interceptor hierarchy. It keeps the endpoint handlers focused on API operations
instead of repeating CORS policy logic.

### Decorator — wrap the HTTP application with CORS behaviour

**Intent:** attach a responsibility to an object by wrapping it, instead of changing
the wrapped object's implementation. The wrapper keeps the same interface and
delegates the work it does not own to the wrapped component.

- **Component / ConcreteComponent:** the FastAPI application is the inner ASGI
  application that receives HTTP requests.
- **Decorator / ConcreteDecorator:** FastAPI's `CORSMiddleware` wraps that
  application when `app.add_middleware(...)` is called in `app/main.py`.
- **Collaboration:** the middleware receives the same ASGI call shape as the
  application, handles CORS preflight requests, adds allowed-origin headers, and
  delegates normal request processing to the application it wraps.

The same middleware therefore has two useful views: structurally it is a Decorator
around the application, while operationally it is an Interceptor at the HTTP request
processing point. Python `@...` syntax is also used in the codebase, but those
language-level decorators are separate from this GoF Decorator collaboration.


## Architecture

The project follows a **modular monolithic MVC/REST architecture**:

- **Models** (`app/models/`) — SQLAlchemy ORM models define the database schema.
- **Services** (`app/modules/*/service.py`, `app/modules/*/*_service.py`) — contain all business logic; routers never query the database directly.
- **Routers/Controllers** (`app/modules/*/endpoints/v1.py`) — FastAPI route handlers that validate requests, call services, and return responses.

### Data Models & Entity Relationships

The relational domain model is built on SQLAlchemy 2.0 with strict foreign key constraints, cascading policies, and uniqueness rules:

```mermaid
erDiagram
    USER ||--o| MEMBER_PROFILE : "has profile (1:1)"
    USER ||--o{ REFRESH_TOKEN : "issues (1:N)"
    USER ||--o{ MEMBERSHIP : "purchases (1:N)"
    USER ||--o{ BOOKING : "reserves (1:N)"
    USER ||--o{ WAITLIST_ENTRY : "queues for (1:N)"
    USER ||--o{ ACCESS_LOG : "records (1:N)"
    USER ||--o{ NOTIFICATION : "receives (1:N)"

    MEMBERSHIP_PLAN ||--|{ PLAN_ENTITLEMENT : "defines (1:N)"
    MEMBERSHIP_PLAN ||--o{ MEMBERSHIP : "specifies (1:N)"

    TIMETABLE_SESSION ||--o{ BOOKING : "allocates (1:N)"
    TIMETABLE_SESSION ||--o{ WAITLIST_ENTRY : "queues for (1:N)"

    USER {
        uuid id PK
        string email UK
        string password_hash
        enum role "member | staff | manager"
        boolean is_active
    }
    MEMBER_PROFILE {
        int id PK
        uuid user_id FK,UK "1:1 unique"
        string name
        string phone "optional"
        date date_of_birth
        string biometric_image_key UK
        string biometric_content_type
        timestamp biometric_uploaded_at
        uuid biometric_template_id UK
    }
    MEMBERSHIP_PLAN {
        int id PK
        string name UK
        int price_minor
        string currency
        int duration_days
        int booking_window_days
        int weekly_booking_limit
        boolean is_active
    }
    PLAN_ENTITLEMENT {
        int id PK
        int plan_id FK
        enum entitlement "gym_floor | class | pool | vip_area | etc"
    }
    MEMBERSHIP {
        int id PK
        uuid user_id FK
        int plan_id FK
        enum status "active | expired | pending | cancelled"
        date starts_on
        date ends_on
        string payment_reference UK
    }
    TIMETABLE_SESSION {
        int id PK
        string resource_name
        enum resource_type "class | pool | personal_training | equipment"
        timestamp starts_at
        timestamp ends_at
        int capacity
        int allocated_count
        int station_count
    }
    BOOKING {
        int id PK
        uuid user_id FK
        int timetable_session_id FK "optional"
        string resource_name
        enum resource_type "class | pool | personal_training | equipment"
        timestamp starts_at
        timestamp ends_at "optional"
        enum status "confirmed | cancelled | checked_in | no_show"
    }
    WAITLIST_ENTRY {
        int id PK
        int session_id FK
        uuid user_id FK
        enum status "waiting | offered | accepted | expired"
        timestamp offered_at
    }
    ACCESS_LOG {
        int id PK
        uuid member_id FK
        enum event "check_in | check_out | manual_check_in"
        string zone
        timestamp occurred_at
        string source
    }
    DENIED_ACCESS_ATTEMPT {
        int id PK
        uuid biometric_template_id
        string scanner_key_fingerprint
        enum zone
        float confidence
        enum reason
        timestamp occurred_at
    }
    REFRESH_TOKEN {
        int id PK
        uuid user_id FK
        string jti UK
        string family_id
        timestamp expires_at
        timestamp revoked_at
    }
    NOTIFICATION {
        int id PK
        uuid user_id FK
        enum event_type
        json payload
        boolean is_read
        timestamp read_at
        timestamp created_at
    }
```

#### Key Relationships and Integrity Constraints

| Parent Model | Relationship | Child Model | Foreign Key / Constraint | Cascade / On-Delete | Description |
|---|---|---|---|---|---|
| `User` | **1 : 1 (Optional)** | `MemberProfile` | `member_profiles.user_id` (Unique) | `CASCADE` (orphan-removal in ORM) | One-to-one member name, phone, and biometric-photo reference. |
| `User` | **1 : N** | `RefreshToken` | `refresh_tokens.user_id` | `CASCADE` | Stores rotating JWT refresh tokens with family tracking and revocation. |
| `User` | **1 : N** | `Membership` | `memberships.user_id` | `CASCADE` | Tracks past, current, and renewed membership contracts per member. |
| `User` | **1 : N** | `Booking` | `bookings.user_id` | `CASCADE` | Active and historical facility reservations made by the member. |
| `User` | **1 : N** | `WaitlistEntry` | `waitlist_entries.user_id` | `CASCADE` | Tracks session waitlist positions requested by the member. |
| `User` | **1 : N** | `AccessLog` | `access_logs.member_id` | `CASCADE` | Physical-access history retained while the account exists. |
| `User` | **1 : N** | `Notification` | `notifications.user_id` | `CASCADE` | Durable in-app event history with read state. |
| `MembershipPlan` | **1 : N** | `PlanEntitlement` | `plan_entitlements.plan_id` | `CASCADE` (delete-orphan) | Defines feature privileges (e.g., VIP sauna access, pool bookings) granted by each plan tier. Unique on `(plan_id, entitlement)`. |
| `MembershipPlan` | **1 : N** | `Membership` | `memberships.plan_id` | `RESTRICT` | Associates purchased memberships with their parent plan rules (pricing, booking window, weekly limits). |
| `TimetableSession` | **1 : N** | `Booking` | `bookings.timetable_session_id` | `RESTRICT` | Links member bookings to scheduled classes, pool slots, personal training blocks, or equipment slots. |
| `TimetableSession` | **1 : N** | `WaitlistEntry` | `waitlist_entries.session_id` | `RESTRICT` | Queue of members waiting for spots on full timetable sessions. Unique on `(session_id, user_id)`. |

## Why No External Cloud AI for Door Scanners

The biometric scanner feature uses scanner-owned matching (mocked for this project), with no external API key. The API accepts only a trusted device key, template ID, and confidence score; it performs one indexed profile lookup, applies business rules, and logs denied scans without retaining the raw device key.

Biometric enrolment uploads are checked locally before storage. The API accepts only `image/png`,
`image/jpeg`, and `image/jpg`, verifies the matching PNG/JPEG bytes, requires at least 300×300 pixels,
rejects unsuitable brightness or blur, and requires exactly one visible frontal face using OpenCV's
bundled Haar cascade. It is separate from scanner-owned recognition and needs no Pydantic AI or
external API key.

### Test biometric scanner check-in

1. Set `SCANNER_DEVICE_KEYS='{"test-sauna-key":"vip_sauna"}'` and optionally set
   `BIOMETRIC_MIN_CONFIDENCE=0.80` in `.env`, then restart the API.
2. Register and log in as a member, upload an enrolment image, and copy the returned `template_id`.
   The bundled Postman collection saves it as `{{biometricTemplateId}}` automatically.
3. Send `POST /api/v1/access/device-check-in` with `X-Device-Key: test-sauna-key` and:

   ```json
   {"template_id":"<returned UUID>","confidence":0.92}
   ```

   A valid member with the required entitlement receives `201`. Unknown template IDs and confidence
   below the threshold receive specific `403` responses; a full VIP area returns `409`. Each rejection
   is recorded in `denied_access_attempts` with a hashed device-key fingerprint.

## Why No Celery

Celery was originally added as a notification queue placeholder, but it is not needed:

- **Stripe webhooks** are signature-verified synchronously inside the FastAPI endpoint — no background queue is needed. A verified paid Checkout event atomically records its event ID and activates the matching pending membership.
- **In-app notifications** are delivered via Redis Pub/Sub + Server-Sent Events (SSE) — this is instant push delivery; a queue would only add latency.
- **Periodic background jobs** (waitlist expiry, no-show detection) are handled by APScheduler, which runs inside the FastAPI process with no extra Docker service or infrastructure.

Removing Celery simplifies the stack from three services (API + Celery worker + queue-Redis) to one (API), while the Redis container that already exists for VIP occupancy is reused for Pub/Sub.

## Local Development

Copy `.env.example` to `.env` and replace placeholder values. You will need a Stripe test account — get a test secret key from [https://dashboard.stripe.com/test/apikeys](https://dashboard.stripe.com/test/apikeys).

Start a local PostgreSQL instance (or use any existing one) and a local Redis container:

```powershell
uv sync --all-groups
docker compose -f compose.local.yml --env-file .env up -d
uv run --env-file .env alembic upgrade head
uv run --env-file .env fastapi dev app/main.py
```

Check the local Redis container is running:

```powershell
docker compose -f compose.local.yml --env-file .env ps
```

## Full Docker Setup

Copy `.env.docker.example` to `.env.docker` and replace placeholder secrets, then start the full stack:

```powershell
docker compose --env-file .env.docker up --build
```

The `migrate` service applies the schema before the API starts. Swagger is available at `http://localhost:8000/docs`; pgAdmin at `http://localhost:5050`.

### Enable Stripe webhook forwarding

For the full Docker stack, start the Stripe CLI sidecar:

```powershell
docker compose --env-file .env.docker --profile stripe up -d --build
docker compose --env-file .env.docker --profile stripe logs -f stripe-listener
```

After it starts, copy the `whsec_...` signing secret from the `stripe-listener` container logs into `STRIPE_WEBHOOK_SECRET` in `.env.docker`, then recreate the API container so it receives the new environment value:

```powershell
docker compose --env-file .env.docker up -d --force-recreate api
```

The webhook verifies the Stripe signature, ignores duplicate event IDs, and activates only the matching pending membership after a paid Checkout event. It also handles delayed-payment success and failure events when those methods are enabled in the Stripe account.

### Test Stripe Checkout from Swagger or Postman

1. In the Stripe Dashboard **test mode**, enable **Cards** and the Apple Pay and Google Pay
   wallets under **Settings → Payment methods**. The API intentionally does not send
   `payment_method_types`: Stripe Checkout dynamically displays the enabled, eligible methods.
   Apple Pay and Google Pay are card wallets, not valid separate API method names.
2. Start the Stripe listener above and copy its current `whsec_...` value into
   `STRIPE_WEBHOOK_SECRET`; restart the API after changing it.
3. Ensure an active membership plan exists. In Swagger (`/docs`) sign in as a manager, create a
   plan with `POST /api/v1/memberships/plans`, then register/sign in as a member. In Postman, use
   the **Stripe Checkout** folder after setting `planId` and logging in; the collection saves the
   returned `checkoutUrl`.
4. Call `POST /api/v1/memberships/purchase` with `{"plan_id": <planId>}` and the member access
   token. Swagger/Postman returns a pending membership and `checkout_url`; open that URL in a
   browser. Complete a card test payment with Stripe's `4242 4242 4242 4242` test card, any future
   expiry date, and any CVC.
5. Watch the listener/API logs, then call `GET /api/v1/memberships/me`: the pending membership
   becomes `active` only after the verified webhook is received. Repeating the webhook is safe.

Apple Pay and Google Pay must be tested in the returned Checkout page on an eligible device and
browser with a configured wallet; neither Swagger nor Postman can display or force those buttons.
Stripe chooses whether to show them based on the account, customer device, browser, currency, and
regional eligibility. See Stripe's [dynamic payment-method documentation](https://docs.stripe.com/payments/existing-customers?platform=web&ui=stripe-hosted).

The normal test suite validates the Checkout request shape without network access. To run the
optional real sandbox-session test (it creates a session only, no charge), use a test key and:

```powershell
$env:BFS_STRIPE_INTEGRATION_TEST = "1";uv run --env-file .env python -m unittest discover -s tests -v

# Run all tests
$env:BFS_STRIPE_INTEGRATION_TEST = "1";uv run --env-file .env python -m unittest tests.test_payment_gateway -v
```

```bash
BFS_STRIPE_INTEGRATION_TEST=1 uv run --env-file .env python -m unittest tests.test_payment_gateway -v
```

For the host-run API workflow (`compose.local.yml`), use the local sidecar instead. It forwards to the API through Docker Desktop's `host.docker.internal` hostname:

```powershell
docker compose -f compose.local.yml --env-file .env --profile stripe up -d
docker compose -f compose.local.yml --env-file .env --profile stripe logs -f stripe-listener
```

Copy the displayed `whsec_...` value into `.env` and restart the host-run FastAPI process.

### Test in-app notifications from Swagger, Postman, or curl

Redis must be running (`cache-redis` from either Compose file) before testing notifications.

1. Register and log in as a member. In Swagger, click **Authorize** and enter only the access token; Swagger adds the `Bearer` prefix.
2. In a second terminal, keep the authenticated stream open with curl:

   ```powershell
   curl.exe -N -H "Authorization: Bearer <access token>" http://localhost:8000/api/v1/notifications/stream
   ```

   Swagger documents the endpoint but does not continuously render an SSE stream. In Postman, create a
   `GET /api/v1/notifications/stream` request with `Authorization: Bearer {{accessToken}}` and use its
   streaming response view. Do not put a JWT in the URL.
3. In Swagger or Postman, create/cancel a booking, accept a waitlist offer, cancel/renew membership, or
   complete a Stripe Checkout payment. The stream returns `event: notification` with a JSON payload and
   notification ID.
4. Copy that ID and call `PATCH /api/v1/notifications/{notification_id}/read` with the same member token.
   A different member receives `404`. Reconnect the stream to replay unread rows; clients should deduplicate
   messages by notification ID.

To apply a new migration:

```powershell
docker compose --env-file .env.docker run --rm migrate
```

## Verification

Run the unit/API tests (database integration tests are skipped unless a disposable test database
is configured):

```powershell
uv run python -m unittest discover -s tests -v
```

Run the complete test suite, including database integration tests. Add this value to an uncommitted
`.env` or `.env.test` file; use a separate database, because tests create and drop schemas:

```env
BFS_TEST_DATABASE_URL=postgresql+asyncpg://bfs_gym:your-password@localhost:5432/bfs_gym_test
```

```powershell
# Start Redis for the host-run development setup when it is not already running.
docker compose -f compose.local.yml --env-file .env up -d cache-redis

# The environment file must be passed to uv because unittest skip conditions
# read BFS_TEST_DATABASE_URL directly from the process environment.
uv run --env-file .env python -m unittest discover -s tests -v
```

The one remaining default skip is the opt-in live Stripe sandbox test. Run it only with a valid
`sk_test_...` key; it creates a Checkout Session but never charges a card:

PowerShell:

```powershell
$env:BFS_STRIPE_INTEGRATION_TEST = "1"
uv run --env-file .env python -m unittest tests.test_payment_gateway -v
```

Bash:

```bash
BFS_STRIPE_INTEGRATION_TEST=1 uv run --env-file .env python -m unittest tests.test_payment_gateway -v
```

Expected result: both payment-gateway tests pass. The sandbox test creates a Stripe test-mode Checkout
Session only; it does not complete a payment or charge a card. Dependency deprecation warnings from
`httpx` do not make this test fail.

For the full Docker stack, start its database and Redis services, then run the same test command
on the host with `BFS_TEST_DATABASE_URL` pointing at a reachable disposable test database. The
project's normal full-stack startup command is:

```powershell
docker compose --env-file .env.docker up -d --build
```

Run static checks separately:

```powershell
uv run ruff check .
uv run ruff format --check .
```

## Assignment Mapping

| Rubric Item | Evidence location |
|---|---|
| Scenario narrative | Report section 1 |
| Use-case diagrams | Report section 3, UML artefacts |
| Design-pattern roles and code mapping | [Design Patterns Used](#design-patterns-used) |
| Automated tests | `tests/` directory (Unit, Integration, and DB tests) |
| CI/CD | `.github/workflows/ci.yml` (Lint, DB Integration Tests, Metrics) |
| Metrics + refactoring | `BookingService.create` refactored (complexity 10 -> 2), Radon CI job |
| AI Chain of Responsibility (Feature A) | `docs/implementation-guide.md#optional-ai-features` *(OpenCV photo quality check)* |
