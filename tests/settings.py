"""Test-only settings for importing routers; overridden dependencies never connect to them."""

TEST_ENVIRONMENT = {
    "POSTGRES_HOST": "127.0.0.1",
    "POSTGRES_DB": "unused",
    "POSTGRES_USER": "unused",
    "POSTGRES_PASSWORD": "unused",
    "CACHE_REDIS_URL": "redis://127.0.0.1:1",
    "JWT_ACCESS_SECRET_KEY": "test-only-access",
    "JWT_REFRESH_SECRET_KEY": "test-refresh",
    "JWT_ISSUER": "test",
    "JWT_AUDIENCE": "test",
    "UPLOAD_ROOT": "/tmp/bfs-test-unused",
    "STRIPE_SECRET_KEY": "sk_test_unused",
    "STRIPE_WEBHOOK_SECRET": "whsec_unused",
    "STRIPE_SUCCESS_URL": "https://example.test/checkout/success",
    "STRIPE_CANCEL_URL": "https://example.test/checkout/cancel",
}
