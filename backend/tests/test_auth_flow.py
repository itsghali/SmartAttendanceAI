import logging
from types import SimpleNamespace

import pytest

from tests.conftest import extract_otp, login, register_and_verify as _register_and_verify

_extract_otp = extract_otp


@pytest.mark.asyncio
async def test_register_creates_verified_user(client, unique_email):
    # No email step — self-registered accounts are usable immediately,
    # same as HR-onboarded accounts.
    resp = await client.post(
        "/auth/register",
        json={"email": unique_email, "password": "Password123", "full_name": "Jane Doe"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["email"] == unique_email
    assert body["is_verified"] is True
    assert body["role"] == "employee"


@pytest.mark.asyncio
async def test_register_duplicate_email_rejected(client, unique_email):
    payload = {"email": unique_email, "password": "Password123", "full_name": "Jane Doe"}
    first = await client.post("/auth/register", json=payload)
    assert first.status_code == 201
    second = await client.post("/auth/register", json=payload)
    assert second.status_code == 409


@pytest.mark.asyncio
async def test_register_with_phone_number_is_persisted(client, unique_email):
    resp = await client.post(
        "/auth/register",
        json={
            "email": unique_email,
            "password": "Password123",
            "full_name": "Jane Doe",
            "phone_number": "+15551234567",
        },
    )
    assert resp.status_code == 201
    assert resp.json()["phone_number"] == "+15551234567"


@pytest.mark.asyncio
async def test_register_privileged_role_rejected_when_signup_code_not_configured(
    client, unique_email, monkeypatch
):
    # ADMIN_SIGNUP_CODE unset (default) — privileged self-signup must fail
    # closed, not silently fall back to "employee".
    monkeypatch.setattr(
        "app.services.auth_service.get_settings",
        lambda: SimpleNamespace(admin_signup_code=None),
    )
    resp = await client.post(
        "/auth/register",
        json={
            "email": unique_email,
            "password": "Password123",
            "full_name": "Jane Doe",
            "role": "admin",
            "setup_code": "anything",
        },
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_register_privileged_role_wrong_setup_code_rejected(
    client, unique_email, monkeypatch
):
    monkeypatch.setattr(
        "app.services.auth_service.get_settings",
        lambda: SimpleNamespace(admin_signup_code="correct-code"),
    )
    resp = await client.post(
        "/auth/register",
        json={
            "email": unique_email,
            "password": "Password123",
            "full_name": "Jane Doe",
            "role": "super_admin",
            "setup_code": "wrong-code",
        },
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_register_privileged_role_correct_setup_code_succeeds(
    client, unique_email, monkeypatch
):
    monkeypatch.setattr(
        "app.services.auth_service.get_settings",
        lambda: SimpleNamespace(admin_signup_code="correct-code"),
    )
    resp = await client.post(
        "/auth/register",
        json={
            "email": unique_email,
            "password": "Password123",
            "full_name": "Jane Doe",
            "phone_number": "+15551234567",
            "role": "hr_manager",
            "setup_code": "correct-code",
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["role"] == "hr_manager"
    assert body["phone_number"] == "+15551234567"


@pytest.mark.asyncio
async def test_register_rejects_role_outside_allowed_set(client, unique_email):
    resp = await client.post(
        "/auth/register",
        json={
            "email": unique_email,
            "password": "Password123",
            "full_name": "Jane Doe",
            "role": "supervisor",
            "setup_code": "whatever",
        },
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_register_rejects_weak_password(client, unique_email):
    resp = await client.post(
        "/auth/register",
        json={"email": unique_email, "password": "short", "full_name": "Jane Doe"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_login_succeeds_immediately_after_register(client, unique_email):
    await client.post(
        "/auth/register",
        json={"email": unique_email, "password": "Password123", "full_name": "Jane Doe"},
    )
    resp = await client.post(
        "/auth/login", json={"email": unique_email, "password": "Password123"}
    )
    assert resp.status_code == 200, resp.text


@pytest.mark.asyncio
async def test_login_success_issues_tokens_and_registers_device(client, caplog, unique_email):
    await _register_and_verify(client, caplog, unique_email)
    resp = await client.post(
        "/auth/login",
        json={
            "email": unique_email,
            "password": "Password123",
            "device_identifier": "device-abc",
            "device_name": "Pixel 8",
            "platform": "android",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["access_token"]
    assert body["refresh_token"]
    assert body["token_type"] == "bearer"

    me = await client.get("/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"})
    assert me.status_code == 200
    assert me.json()["email"] == unique_email

    devices = await client.get(
        "/devices", headers={"Authorization": f"Bearer {body['access_token']}"}
    )
    assert devices.status_code == 200
    assert len(devices.json()) == 1
    assert devices.json()[0]["device_name"] == "Pixel 8"


@pytest.mark.asyncio
async def test_login_wrong_password_rejected(client, caplog, unique_email):
    await _register_and_verify(client, caplog, unique_email)
    resp = await client.post(
        "/auth/login", json={"email": unique_email, "password": "WrongPassword1"}
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_me_requires_bearer_token(client):
    resp = await client.get("/auth/me")
    assert resp.status_code in (401, 403)


@pytest.mark.asyncio
async def test_refresh_rotates_token_and_old_one_stops_working(client, caplog, unique_email):
    await _register_and_verify(client, caplog, unique_email)
    login = await client.post(
        "/auth/login", json={"email": unique_email, "password": "Password123"}
    )
    old_refresh = login.json()["refresh_token"]

    refreshed = await client.post("/auth/refresh", json={"refresh_token": old_refresh})
    assert refreshed.status_code == 200
    new_refresh = refreshed.json()["refresh_token"]
    assert new_refresh != old_refresh

    reuse_old = await client.post("/auth/refresh", json={"refresh_token": old_refresh})
    assert reuse_old.status_code == 401

    # Replaying an already-rotated (revoked) refresh token is a theft/replay
    # signal, not an ordinary error — AuthService.refresh() now kills every
    # session for the user when this happens, so the otherwise-still-valid
    # new_refresh from the legitimate rotation above is invalidated too.
    # This is intentional (see backend audit P1 #3): the alternative is
    # letting a stolen token's replay pass silently while only the attacker's
    # own reuse attempt gets rejected.
    reuse_new = await client.post("/auth/refresh", json={"refresh_token": new_refresh})
    assert reuse_new.status_code == 401


@pytest.mark.asyncio
async def test_refresh_reuse_of_revoked_token_kills_whole_session_family(
    client, caplog, unique_email
):
    await _register_and_verify(client, caplog, unique_email)
    login = await client.post(
        "/auth/login", json={"email": unique_email, "password": "Password123"}
    )
    first_refresh = login.json()["refresh_token"]

    rotated = await client.post("/auth/refresh", json={"refresh_token": first_refresh})
    assert rotated.status_code == 200
    second_refresh = rotated.json()["refresh_token"]

    # Simulates an attacker replaying a stolen (and since-rotated) token.
    replay = await client.post("/auth/refresh", json={"refresh_token": first_refresh})
    assert replay.status_code == 401

    # The legitimate device's own still-valid token is also dead now — the
    # whole family was killed, not just the replayed one.
    legitimate_followup = await client.post(
        "/auth/refresh", json={"refresh_token": second_refresh}
    )
    assert legitimate_followup.status_code == 401


@pytest.mark.asyncio
async def test_logout_revokes_refresh_token(client, caplog, unique_email):
    await _register_and_verify(client, caplog, unique_email)
    login = await client.post(
        "/auth/login", json={"email": unique_email, "password": "Password123"}
    )
    refresh_token = login.json()["refresh_token"]

    logout = await client.post("/auth/logout", json={"refresh_token": refresh_token})
    assert logout.status_code == 204

    reuse = await client.post("/auth/refresh", json={"refresh_token": refresh_token})
    assert reuse.status_code == 401


@pytest.mark.asyncio
async def test_forgot_password_reset_flow(client, caplog, unique_email):
    await _register_and_verify(client, caplog, unique_email)

    caplog.clear()
    caplog.set_level(logging.INFO, logger="app.email")
    forgot = await client.post("/auth/forgot-password", json={"email": unique_email})
    assert forgot.status_code == 204
    code = _extract_otp(caplog)

    reset = await client.post(
        "/auth/reset-password",
        json={"email": unique_email, "code": code, "new_password": "NewPassword456"},
    )
    assert reset.status_code == 204

    old_login = await client.post(
        "/auth/login", json={"email": unique_email, "password": "Password123"}
    )
    assert old_login.status_code == 401

    new_login = await client.post(
        "/auth/login", json={"email": unique_email, "password": "NewPassword456"}
    )
    assert new_login.status_code == 200


@pytest.mark.asyncio
async def test_forgot_password_unknown_email_does_not_leak(client):
    resp = await client.post(
        "/auth/forgot-password", json={"email": "nobody@example.com"}
    )
    assert resp.status_code == 204


@pytest.mark.asyncio
async def test_change_password_success_revokes_other_sessions(client, caplog, unique_email):
    await _register_and_verify(client, caplog, unique_email)
    login = await client.post(
        "/auth/login", json={"email": unique_email, "password": "Password123"}
    )
    access_token = login.json()["access_token"]
    refresh_token = login.json()["refresh_token"]
    headers = {"Authorization": f"Bearer {access_token}"}

    changed = await client.patch(
        "/auth/change-password",
        json={"current_password": "Password123", "new_password": "BrandNewPass789"},
        headers=headers,
    )
    assert changed.status_code == 204

    old_refresh_reuse = await client.post(
        "/auth/refresh", json={"refresh_token": refresh_token}
    )
    assert old_refresh_reuse.status_code == 401

    old_password_login = await client.post(
        "/auth/login", json={"email": unique_email, "password": "Password123"}
    )
    assert old_password_login.status_code == 401

    new_password_login = await client.post(
        "/auth/login", json={"email": unique_email, "password": "BrandNewPass789"}
    )
    assert new_password_login.status_code == 200


@pytest.mark.asyncio
async def test_change_password_wrong_current_password_rejected(client, caplog, unique_email):
    await _register_and_verify(client, caplog, unique_email)
    login = await client.post(
        "/auth/login", json={"email": unique_email, "password": "Password123"}
    )
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    resp = await client.patch(
        "/auth/change-password",
        json={"current_password": "WrongPassword1", "new_password": "BrandNewPass789"},
        headers=headers,
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_workforce_intelligence_notice_starts_unacknowledged(
    client, caplog, unique_email
):
    await _register_and_verify(client, caplog, unique_email)
    access = await login(client, unique_email)
    resp = await client.get("/auth/me", headers={"Authorization": f"Bearer {access}"})
    assert resp.status_code == 200
    assert resp.json()["workforce_intelligence_notice_acknowledged_at"] is None


@pytest.mark.asyncio
async def test_acknowledge_workforce_intelligence_notice_sets_timestamp(
    client, caplog, unique_email
):
    await _register_and_verify(client, caplog, unique_email)
    access = await login(client, unique_email)
    headers = {"Authorization": f"Bearer {access}"}

    resp = await client.post(
        "/auth/acknowledge-workforce-intelligence-notice", headers=headers
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["workforce_intelligence_notice_acknowledged_at"] is not None

    me = await client.get("/auth/me", headers=headers)
    assert me.json()["workforce_intelligence_notice_acknowledged_at"] is not None


@pytest.mark.asyncio
async def test_acknowledge_workforce_intelligence_notice_is_idempotent(
    client, caplog, unique_email
):
    await _register_and_verify(client, caplog, unique_email)
    access = await login(client, unique_email)
    headers = {"Authorization": f"Bearer {access}"}

    first = await client.post(
        "/auth/acknowledge-workforce-intelligence-notice", headers=headers
    )
    second = await client.post(
        "/auth/acknowledge-workforce-intelligence-notice", headers=headers
    )
    assert first.status_code == 200
    assert second.status_code == 200
    # The second call must not overwrite the first real timestamp with a
    # later one (see UserRepository.acknowledge_workforce_intelligence_notice).
    assert (
        first.json()["workforce_intelligence_notice_acknowledged_at"]
        == second.json()["workforce_intelligence_notice_acknowledged_at"]
    )
