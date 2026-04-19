---
type: test-plan
slug: smoke-test-test-plan-fixture
source_spec: docs/specs/synthetic-user-profile-cache.md
---

# Test Plan: User profile caching

## Acceptance Criteria (from source spec)

- AC-1: `GET /api/users/:id` returns cached result when cache hit
- AC-2: Cache hit rate ≥80% under steady state
- AC-3: p99 latency ≤50ms for cached requests
- AC-4: Cache invalidates on `POST /api/users/:id` update
- AC-5: Redis outage: endpoint falls back to DB, returns 200 with degraded latency

## Test Cases

### TC-1: Cache hit on repeated read
**Priority:** P0

Steps:
1. Warm cache by calling `GET /api/users/42`
2. Call `GET /api/users/42` again within 5 minutes

Expected: second call returns `X-Cache: HIT` header, response time <20ms.

### TC-2: Cache miss on cold read
**Priority:** P1

Steps:
1. Flush Redis
2. Call `GET /api/users/42`

Expected: response has `X-Cache: MISS`, user data loaded from DB.

### TC-3: Cache invalidates on user update
**Priority:** P0

Steps:
1. Warm cache for user 42
2. POST user update for 42
3. GET user 42 again

Expected: response has `X-Cache: MISS` (invalidation occurred), new data reflected.

### TC-4: Redis outage fallback
**Priority:** P1

Steps:
1. Stop Redis container
2. Call `GET /api/users/42`

Expected: 200 OK, response loaded from DB, latency degraded but under 200ms.
