import logging

import pytest

from tests.conftest import register_and_verify


@pytest.mark.asyncio
async def test_login_rate_limited_after_threshold(client, caplog, unique_email):
    caplog.set_level(logging.INFO, logger="app.email")
    await register_and_verify(client, caplog, unique_email)

    responses = []
    for _ in range(11):
        resp = await client.post(
            "/auth/login", json={"email": unique_email, "password": "WrongPassword1"}
        )
        responses.append(resp.status_code)

    assert responses[:10] == [401] * 10
    assert responses[10] == 429
