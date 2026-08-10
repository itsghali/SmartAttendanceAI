import logging

import pytest

from tests.conftest import register_and_verify


async def _login_with_device(client, email: str, device_identifier: str):
    resp = await client.post(
        "/auth/login",
        json={
            "email": email,
            "password": "Password123",
            "device_identifier": device_identifier,
            "device_name": f"device-{device_identifier}",
            "platform": "web",
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


@pytest.mark.asyncio
async def test_revoke_own_device_also_revokes_its_refresh_token(client, caplog, unique_email):
    caplog.set_level(logging.INFO, logger="app.email")
    await register_and_verify(client, caplog, unique_email)
    tokens = await _login_with_device(client, unique_email, "device-1")
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}

    devices = (await client.get("/devices", headers=headers)).json()
    assert len(devices) == 1
    device_id = devices[0]["id"]

    revoke = await client.delete(f"/devices/{device_id}", headers=headers)
    assert revoke.status_code == 204

    devices_after = (await client.get("/devices", headers=headers)).json()
    assert devices_after == []

    refresh_after_revoke = await client.post(
        "/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )
    assert refresh_after_revoke.status_code == 401


@pytest.mark.asyncio
async def test_list_and_revoke_own_sessions(client, caplog, unique_email):
    caplog.set_level(logging.INFO, logger="app.email")
    await register_and_verify(client, caplog, unique_email)
    first = await _login_with_device(client, unique_email, "device-a")
    second = await _login_with_device(client, unique_email, "device-b")
    headers = {"Authorization": f"Bearer {second['access_token']}"}

    sessions = (await client.get("/sessions", headers=headers)).json()
    assert len(sessions) == 2

    revoke_all = await client.delete("/sessions", headers=headers)
    assert revoke_all.status_code == 204

    for tokens in (first, second):
        resp = await client.post(
            "/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
        )
        assert resp.status_code == 401


@pytest.mark.asyncio
async def test_cannot_revoke_someone_elses_device(client, caplog, unique_email):
    caplog.set_level(logging.INFO, logger="app.email")
    await register_and_verify(client, caplog, unique_email)
    victim_tokens = await _login_with_device(client, unique_email, "victim-device")

    attacker_email = f"attacker-{unique_email}"
    await register_and_verify(client, caplog, attacker_email)
    attacker_tokens = await _login_with_device(client, attacker_email, "attacker-device")
    attacker_headers = {"Authorization": f"Bearer {attacker_tokens['access_token']}"}

    victim_headers = {"Authorization": f"Bearer {victim_tokens['access_token']}"}
    victim_device_id = (await client.get("/devices", headers=victim_headers)).json()[0]["id"]

    resp = await client.delete(f"/devices/{victim_device_id}", headers=attacker_headers)
    assert resp.status_code == 404
