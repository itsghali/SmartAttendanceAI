# SmartAttendanceAI

Intelligent attendance management platform: GPS geofencing, facial recognition, real-time tracking, and AI fraud detection (GPS spoofing, impossible travel, buddy punching). Employees check in/out only inside authorized zones after identity verification.

**Status:** Auth+RBAC, Employee+Department, Attendance+GPS+Geofencing, and Face Enrollment+Verification modules complete on the backend (real, tested, live-verified — 121 backend tests). Face verification is now wired into check-in (`FACE_VERIFICATION_ENABLED`, off by default) — geofence match and, once enabled, a live selfie match against the employee's enrolled embedding, both required. Mobile has check-in/check-out/breaks plus a selfie-capture step (`expo-camera`) wired end-to-end to the live backend; the camera permission/capture UX itself still needs a live walkthrough on real hardware (see `TODOS.md`). Everything else — leave/remote-work, fraud models, dashboards, web UI beyond auth/geofences — is built module-by-module from here. See `DEVELOPMENT_LOG.md` and `TODOS.md`.

## Monorepo layout

| Path | Stack | Purpose |
|---|---|---|
| `backend/` | FastAPI, SQLAlchemy, PostGIS | REST API, auth, business logic |
| `web/` | Next.js (App Router), TypeScript, Tailwind | Admin/HR dashboard |
| `mobile/` | Expo, React Native, TypeScript | Employee app (check-in/out, GPS, face) |
| `ai/` | scikit-learn, XGBoost, SHAP, PyTorch/ONNX | Fraud detection, face recognition |
| `database/` | Alembic | Schema migrations, seed scripts |
| `docker/` | Docker Compose | Local dev infra (Postgres+PostGIS, Redis) |
| `docs/` | — | Architecture, API docs |
| `scripts/` | — | One-off ops/dev scripts |
| `tests/` | — | Cross-service integration/e2e tests |

Each module has its own README with setup/run/test commands.

## Quickstart

```
cd docker && docker compose up -d postgres redis
cd ../backend && py -3.11 -m venv .venv && .venv/Scripts/activate && pip install -r requirements-dev.txt && copy .env.example .env
cd ../database && alembic upgrade head
cd ../backend && python -m scripts.seed_rbac && uvicorn app.main:app --reload
cd ../web && npm install && copy .env.example .env.local && npm run dev
cd ../mobile && npm install && copy .env.example .env && npm start
```

Postgres binds host port **55432** (not the default 5432) — this machine already had something on 5432, so the compose file remaps it. Adjust `DATABASE_URL`/`alembic.ini` if you deploy elsewhere and want the default back.

## Web dashboard signup

`web/app/register` lets HR/Admin/SuperAdmin self-signup (name, email, phone, password, role — admin/hr_manager/super_admin) instead of hand-crafting accounts. It's gated: the form also asks for a **setup code**, checked server-side against `ADMIN_SIGNUP_CODE` in `backend/.env`. Unset → every privileged signup request is rejected (fail-closed), so this is safe to leave off until you actually want it. Generate one and set it before anyone needs to self-signup on web:

```bash
python -c "import secrets; print(secrets.token_urlsafe(18))"
```

Put the value in `backend/.env` as `ADMIN_SIGNUP_CODE=...` (and the deployment's env vars if not local), then share it out-of-band with whoever should be able to create HR/Admin/SuperAdmin accounts. Mobile signup (employees) never asks for this — it always defaults to the `employee` role.

## Local test accounts

> **Local dev only.** These exist in the local Docker Postgres volume, seeded by hand for manual testing. They are throwaway credentials for a database that never leaves this machine — never create accounts like these in a deployed environment, and never point this repo's `.env` at a real database while they exist.

Every account below was verified working (`HTTP 200` on `/auth/login`) at the time of writing — except `offboard@example.com`, which returns `403 {"detail":"account is deactivated"}` on purpose. If another one stops working, the local Postgres volume was probably reset — recreate it with the recipe further down.

**One per role** — use these to check RBAC (`403` vs `200`) on any endpoint:

| Email | Password | Role | State |
|---|---|---|---|
| `superadmin@example.com` | `Sadmin12345` | super_admin | Every permission |
| `admin@example.com` | `Admin12345` | admin | Org-wide admin |
| `hr@example.com` | `Hr12345678` | hr_manager | Onboards employees, manages geofences |
| `supervisor@example.com` | `Super12345` | supervisor | Supervises `onbreak@` and `closed@` |
| `auditor@example.com` | `Audit12345` | auditor | Read-only |
| `test1@example.com` | `Test12345` | employee | Clean — not checked in |

### Permissions by role

| Permission | super_admin | admin | hr_manager | supervisor | employee | auditor |
|---|:---:|:---:|:---:|:---:|:---:|:---:|
| **User Management** |
| users:read | ✓ | ✓ | ✓ | ✓ | – | ✓ |
| users:write | ✓ | ✓ | ✓ | – | – | – |
| users:delete | ✓ | ✓ | ✓ | – | – | – |
| **Device Management** |
| devices:read:own | ✓ | – | – | – | ✓ | – |
| devices:manage:own | ✓ | – | – | – | ✓ | – |
| devices:manage:all | ✓ | ✓ | – | – | – | – |
| **Session Management** |
| sessions:read:own | ✓ | – | – | – | ✓ | – |
| sessions:manage:own | ✓ | – | – | – | ✓ | – |
| sessions:manage:all | ✓ | ✓ | – | – | – | – |
| **Geofencing** |
| geofences:read | ✓ | ✓ | ✓ | – | – | ✓ |
| geofences:write | ✓ | ✓ | ✓ | – | – | – |
| geofence_events:read | ✓ | ✓ | ✓ | – | – | – |
| **Attendance** |
| attendance:record:own | ✓ | – | – | – | ✓ | – |
| attendance:read:own | ✓ | – | – | – | ✓ | – |
| attendance:read:all | ✓ | ✓ | ✓ | ✓* | – | ✓ |
| attendance:correct | ✓ | ✓ | ✓ | ✓ | – | – |
| **Audit & Compliance** |
| audit_logs:read | ✓ | ✓ | ✓ | – | – | ✓ |

**Notes:**
- `super_admin` has every permission (full superset).
- `hr_manager` identical to `admin` except missing `devices:manage:all` and `sessions:manage:all` (no device/session admin powers).
- `supervisor` has `attendance:read:all` scoped to department only (enforced at route level, not role-wide).
- `supervisor` deliberately excluded from `geofence_events:read` — kept off geofence-exit/exceptions/history screens by design.
- `auditor` is read-only; `audit_logs:read` is present but has no backend feature (no logs table/endpoint exists).

**Employees in a specific attendance state** — no setup needed, they are already in it:

| Email | Password | State |
|---|---|---|
| `casa@example.com` | `Casa12345` | Checked in at Casablanca Demo Site |
| `demo@example.com` | `Demo12345` | Checked in at Marrakech Demo Site |
| `onbreak@example.com` | `Break12345` | Checked in **and on an open break** (no `break_end_at`) |
| `closed@example.com` | `Closed12345` | Completed shift — checked in and out the same day |
| `leave@example.com` | `Leave12345` | Employee `status=on_leave`; login still works |
| `offboard@example.com` | `Offb12345` | Employee `status=terminated`, user deactivated — login returns `403` |
| `emp-livetest-1785948119@example.com` | `TempPass123` | Has a full ENTER → EXIT → RETURN event history |
| `autoexit@example.com` | `Autoex12345` | Checked in, geofence EXIT auto-started a break (`source=geofence_exit`, `break_end_at=null`) — left open, never returned |

Attendance state is per-day: `onbreak@` and `closed@` are only in that state for the date they were seeded (`2026-08-06`). Re-run the state commands below to put them back in it today.

Type credentials manually rather than relying on browser autofill — submitting the login form with empty fields returns a `401`, which reads like "wrong password" but isn't.

### Test geofences

| Name | Center (lat, lng) | Radius |
|---|---|---|
| Casablanca Demo Site | `33.5897, -7.6039` | 100 m |
| Marrakech Demo Site | `31.6286, -7.9919` | 100 m |
| Mobile Test HQ | `37.422, -122.0841` | 200 m |
| HQ Live / Live Test Site | `36.8065, 10.1815` | 100 m |

`mobile/.env` keeps the dev GPS override commented out by default. Uncomment the two override lines only when you explicitly need a fixed test location inside **Marrakech Demo Site** or **Casablanca Demo Site**. See "Dev GPS override" below.

### Dev GPS override

Some dev machines cannot provide a real GPS fix at all (Windows blocks per-app location consent for the browser; CI has no location provider). `mobile/src/services/locationService.ts` can honor `EXPO_PUBLIC_DEV_LOCATION="lat,lng"` and skip the OS entirely, but only when you also set `EXPO_PUBLIC_ALLOW_DEV_LOCATION_OVERRIDE=true`.

**This is gated on `__DEV__` and cannot run in a release build.** That gate is load-bearing: this product gates attendance on physical presence, so a location override is precisely the bypass a fraud attempt would want. `__DEV__` compiles to `false` in release builds, so the branch is unreachable in a shipped app even if the env var is set. `locationService.test.ts` asserts this directly (`SECURITY: ignores the override entirely when __DEV__ is false`). Do not replace it with a runtime-only check — env vars, headers, and settings flags all survive into production.

Keep both override lines commented out in `mobile/.env` to use real GPS.

### Recreating these accounts

If the Postgres volume is reset, the accounts above are gone. Recreate the HR account, then onboard employees through it:

```bash
BASE=http://localhost:8000
# 1. Register, then read the OTP out of the backend logs (console email backend)
curl -s -X POST $BASE/auth/register -H "Content-Type: application/json" \
  -d '{"email":"hr@example.com","password":"Hr12345678","full_name":"HR Manager"}'
docker logs docker-backend-1 2>&1 | grep "hr@example.com" | grep -o "verification code is [0-9]\{6\}" | tail -1

# 2. Verify with that code
curl -s -X POST $BASE/auth/verify-email -H "Content-Type: application/json" \
  -d '{"email":"hr@example.com","code":"<OTP>"}'

# 3. Promote to hr_manager (no API for role assignment yet — see TODOS.md)
docker exec docker-postgres-1 psql -U postgres -d smartattendance \
  -c "UPDATE users SET role_id=(SELECT id FROM roles WHERE name='hr_manager') WHERE email='hr@example.com';"

# 4. Onboard an employee (HR-created accounts are auto-verified)
TOKEN=$(curl -s -X POST $BASE/auth/login -H "Content-Type: application/json" \
  -d '{"email":"hr@example.com","password":"Hr12345678"}' | python -c "import sys,json;print(json.load(sys.stdin)['access_token'])")
curl -s -X POST $BASE/employees -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"email":"test1@example.com","full_name":"Test One","password":"Test12345","hire_date":"2026-01-15"}'

# 5. Seed demo sites and employee site assignments
cd ../backend && python -m scripts.seed_demo_sites
```

#### The role accounts

`POST /employees` takes `role_name`, so HR can mint one account per role in a loop. There is still no API for changing an existing user's role — that stays a `psql` `UPDATE` (step 3 above).

```bash
mk() {  # email full_name password role_name
  curl -s -o /dev/null -w "%{http_code} $1\n" -X POST $BASE/employees \
    -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
    -d "{\"email\":\"$1\",\"full_name\":\"$2\",\"password\":\"$3\",\"role_name\":\"$4\",\"hire_date\":\"2026-02-01\"}"
}
mk superadmin@example.com  "Root Admin"     Sadmin12345 super_admin
mk admin@example.com       "Admin User"     Admin12345  admin
mk supervisor@example.com  "Sam Supervisor" Super12345  supervisor
mk auditor@example.com     "Aud Itor"       Audit12345  auditor
mk onbreak@example.com     "Bree Cake"      Break12345  employee
mk closed@example.com      "Clo Sedshift"   Closed12345 employee
mk leave@example.com       "Lea Ver"        Leave12345  employee
mk offboard@example.com    "Off Boarded"    Offb12345   employee
mk autoexit@example.com    "Auto Exit"      Autoex12345 employee
```

#### The attendance states

Employee IDs are not the user IDs — read them from `GET /employees` first. Use the Marrakech Demo Site coordinates for `demo@example.com`; use Casablanca for `casa@example.com`.

```bash
LOGIN() { curl -s -X POST $BASE/auth/login -H "Content-Type: application/json" \
  -d "{\"email\":\"$1\",\"password\":\"$2\"}" | python -c "import sys,json;print(json.load(sys.stdin)['access_token'])"; }
AT=33.5731; LNG=-7.5898
POS="{\"latitude\":$AT,\"longitude\":$LNG,\"accuracy_meters\":10}"

# onbreak@ — checked in, break left open
T=$(LOGIN onbreak@example.com Break12345)
curl -s -X POST $BASE/attendance/check-in    -H "Authorization: Bearer $T" -H "Content-Type: application/json" -d "$POS" >/dev/null
curl -s -X POST $BASE/attendance/break/start -H "Authorization: Bearer $T" -H "Content-Type: application/json" -d "$POS"

# autoexit@ — checked in at HQ Live / Live Test Site, EXIT auto-starts a
# break (source=geofence_exit); left open on purpose, no RETURN sent
T=$(LOGIN autoexit@example.com Autoex12345)
curl -s -X POST $BASE/attendance/check-in -H "Authorization: Bearer $T" -H "Content-Type: application/json" \
  -d '{"latitude":36.8065,"longitude":10.1815,"accuracy_meters":10}' >/dev/null
for s in 1 2 3; do
  curl -s -X POST $BASE/attendance/location-ping -H "Authorization: Bearer $T" -H "Content-Type: application/json" \
    -d "{\"latitude\":36.82,\"longitude\":10.1815,\"accuracy_meters\":10,\"ping_seq\":$s}" >/dev/null
done

# closed@ — full shift, checked in and back out
T=$(LOGIN closed@example.com Closed12345)
curl -s -X POST $BASE/attendance/check-in  -H "Authorization: Bearer $T" -H "Content-Type: application/json" -d "$POS" >/dev/null
curl -s -X POST $BASE/attendance/check-out -H "Authorization: Bearer $T" -H "Content-Type: application/json" -d "$POS"

# leave@ / offboard@ — HR sets employment status (terminated also deactivates the user)
curl -s -X PATCH $BASE/employees/<leave_employee_id>/status -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" -d '{"status":"on_leave"}'
curl -s -X PATCH $BASE/employees/<offboard_employee_id>/status -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" -d '{"status":"terminated"}'

# supervisor@ — point two employees at it, so its team endpoints return rows
curl -s -X PATCH $BASE/employees/<onbreak_employee_id> -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" -d '{"supervisor_id":"<supervisor_employee_id>"}'
```

### Seeing geofence exit monitoring work

Check-in only records an `ENTER` event. `EXIT` needs 3 consecutive out-of-zone pings (60 s apart in the app, so ~3 min), which is slow to reproduce by hand. Drive it directly instead — `ping_seq` must increase, since repeats are deduped:

```bash
TOKEN=$(curl -s -X POST $BASE/auth/login -H "Content-Type: application/json" \
  -d '{"email":"test1@example.com","password":"Test12345"}' | python -c "import sys,json;print(json.load(sys.stdin)['access_token'])")
for s in 1 2 3; do
  curl -s -X POST $BASE/attendance/location-ping -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d "{\"latitude\":34.5,\"longitude\":-7.5898,\"accuracy_meters\":10,\"ping_seq\":$s}"; echo
done
```

Ping 3 returns `{"status":"exited","event_fired":"exit"}`. Reload the app to see the amber banner. Send a ping back inside the zone (`33.5731,-7.5898`) with a higher `ping_seq` to fire `RETURN`. The endpoint is rate-limited to 10 pings/minute per employee.

That same debounced `EXIT` also auto-starts a `BreakPeriod` (`source=geofence_exit`) — unlike a manual break, pings keep being processed while it's open so a `RETURN` can auto-close it; checking out while it's still open closes it too, using the checkout's own position. See `autoexit@example.com` above for a permanently-seeded example, or `TODOS.md` / `AI-CHANGELOG.md` for the design writeup.

## Why Python 3.11 for backend/ and ai/

System default is Python 3.14; PyTorch/ONNX Runtime/scikit-learn/XGBoost don't reliably ship wheels for brand-new CPython releases yet. `backend/.venv` and `ai/.venv` are pinned to 3.11 (`py -3.11 -m venv .venv`) to avoid source-build failures.

## Development process

This project builds incrementally, module by module: design → implement → test → document → validate, before moving to the next module. See `CHANGELOG.md` for versioned releases and `DEVELOPMENT_LOG.md` for the full timestamped build history.
