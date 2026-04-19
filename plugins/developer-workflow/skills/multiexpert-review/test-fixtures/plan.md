---
type: plan
slug: smoke-test-plan-fixture
---

# Plan: Add caching layer to user profile API

## Goal

Introduce a Redis-backed cache for the `GET /api/users/:id` endpoint to reduce database load during peak hours. Target: 80% cache hit rate, p99 latency under 50ms.

## Approach

1. Add Redis client dependency (Lettuce) to the user-service module.
2. Wrap the existing `UserRepository.findById` call with a cache-aside pattern in a new `CachedUserRepository` decorator.
3. TTL: 5 minutes. Invalidation: on `POST /api/users/:id` update.
4. Metrics: Micrometer counters for cache-hit / cache-miss, gauge for Redis connection pool usage.

## Affected modules

- `user-service/src/main/kotlin/com/example/user/repository/` — new `CachedUserRepository.kt`, wire via Spring config
- `user-service/build.gradle.kts` — add `io.lettuce:lettuce-core`
- `user-service/src/main/resources/application.yml` — Redis connection config
- `deployment/helm/user-service/values.yaml` — Redis sidecar declaration

## Risks

- Cache coherence on multi-instance deployments — covered by TTL, no pub/sub invalidation.
- Redis outage degrades latency but must not break reads — fallback to DB if Redis unreachable.

## Open questions

- Should we use Redis AUTH / TLS? (Depends on deployment env — ask infra team.)
