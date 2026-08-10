import logging
from types import SimpleNamespace

import pytest

from app.config.settings import get_settings
from app.services import face_service
from tests.conftest import login, promote_to_role, register_and_verify

FAKE_JPEG = b"\xff\xd8\xff\xe0not a real jpeg but content-type is what matters here"


@pytest.fixture(autouse=True)
def _face_verification_enabled(monkeypatch):
    # Default flipped to False once face verification started gating check-in
    # (see attendance_service.py) — this module's own tests exercise the
    # standalone enroll/verify endpoints directly, so they opt back in here.
    monkeypatch.setattr(get_settings(), "face_verification_enabled", True)


def _photo(name: str = "a.jpg", content_type: str = "image/jpeg"):
    return (name, FAKE_JPEG, content_type)


def _embedding(seed: float, dim: int = 4) -> list[float]:
    raw = [seed + i for i in range(dim)]
    norm = sum(v * v for v in raw) ** 0.5
    return [v / norm for v in raw]


async def _make_role(client, db_session, caplog, email: str, role_name: str) -> str:
    caplog.set_level(logging.INFO, logger="app.email")
    await register_and_verify(client, caplog, email)
    await promote_to_role(db_session, email, role_name)
    return await login(client, email)


async def _make_hr_manager(client, db_session, caplog, email: str) -> str:
    return await _make_role(client, db_session, caplog, email, "hr_manager")


async def _onboard_employee(client, hr_headers, email: str) -> dict:
    payload = {
        "email": email,
        "full_name": "Face Test Employee",
        "password": "TempPass123",
        "hire_date": "2026-01-15",
    }
    resp = await client.post("/employees", json=payload, headers=hr_headers)
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _setup_employee(client, db_session, caplog, unique_email):
    """HR onboards an employee, returns (hr_headers, employee_headers, employee_id)."""
    hr_access = await _make_hr_manager(client, db_session, caplog, unique_email)
    hr_headers = {"Authorization": f"Bearer {hr_access}"}
    hire_email = f"hire-{unique_email}"
    employee = await _onboard_employee(client, hr_headers, hire_email)
    employee_access = await login(client, hire_email, password="TempPass123")
    employee_headers = {"Authorization": f"Bearer {employee_access}"}
    return hr_headers, employee_headers, employee["id"]


def _mock_analyze(monkeypatch, result=None, exc=None):
    def fake(image_bytes: bytes):
        if exc is not None:
            raise exc
        return result

    monkeypatch.setattr(face_service.face_pipeline, "analyze", fake)


@pytest.mark.asyncio
async def test_enroll_success_single_photo(client, db_session, caplog, unique_email, monkeypatch):
    hr_headers, _, employee_id = await _setup_employee(client, db_session, caplog, unique_email)
    _mock_analyze(monkeypatch, result=SimpleNamespace(embedding=_embedding(1.0), liveness=0.9))

    resp = await client.post(
        f"/face/enroll/{employee_id}", files=[("photos", _photo())], headers=hr_headers
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["photos_accepted"] == 1
    assert body["photos_rejected"] == []
    assert body["embedding_dimension"] == 4


@pytest.mark.asyncio
async def test_enroll_averages_multiple_photos(client, db_session, caplog, unique_email, monkeypatch):
    hr_headers, _, employee_id = await _setup_employee(client, db_session, caplog, unique_email)
    seeds = iter([1.0, 2.0, 3.0])

    def fake(image_bytes: bytes):
        return SimpleNamespace(embedding=_embedding(next(seeds)), liveness=0.9)

    monkeypatch.setattr(face_service.face_pipeline, "analyze", fake)

    resp = await client.post(
        f"/face/enroll/{employee_id}",
        files=[("photos", _photo("a.jpg")), ("photos", _photo("b.jpg")), ("photos", _photo("c.jpg"))],
        headers=hr_headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["photos_accepted"] == 3


@pytest.mark.asyncio
async def test_enroll_partial_rejection_still_succeeds(
    client, db_session, caplog, unique_email, monkeypatch
):
    hr_headers, _, employee_id = await _setup_employee(client, db_session, caplog, unique_email)
    calls = iter(
        [
            SimpleNamespace(embedding=_embedding(1.0), liveness=0.9),
            face_service.PipelineNoFaceError("no face"),
        ]
    )

    def fake(image_bytes: bytes):
        outcome = next(calls)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(face_service.face_pipeline, "analyze", fake)

    resp = await client.post(
        f"/face/enroll/{employee_id}",
        files=[("photos", _photo("a.jpg")), ("photos", _photo("b.jpg"))],
        headers=hr_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["photos_accepted"] == 1
    assert body["photos_rejected"] == [{"index": 1, "reason": "no_face"}]


@pytest.mark.asyncio
async def test_enroll_zero_valid_photos_fails(client, db_session, caplog, unique_email, monkeypatch):
    hr_headers, _, employee_id = await _setup_employee(client, db_session, caplog, unique_email)
    _mock_analyze(monkeypatch, exc=face_service.PipelineNoFaceError("no face"))

    resp = await client.post(
        f"/face/enroll/{employee_id}", files=[("photos", _photo())], headers=hr_headers
    )
    assert resp.status_code == 400, resp.text


@pytest.mark.asyncio
async def test_enroll_requires_hr_permission(client, db_session, caplog, unique_email, monkeypatch):
    _, employee_headers, employee_id = await _setup_employee(client, db_session, caplog, unique_email)
    _mock_analyze(monkeypatch, result=SimpleNamespace(embedding=_embedding(1.0), liveness=0.9))

    resp = await client.post(
        f"/face/enroll/{employee_id}", files=[("photos", _photo())], headers=employee_headers
    )
    assert resp.status_code == 403, resp.text


@pytest.mark.asyncio
async def test_reenroll_replaces_embedding(client, db_session, caplog, unique_email, monkeypatch):
    hr_headers, employee_headers, employee_id = await _setup_employee(
        client, db_session, caplog, unique_email
    )
    _mock_analyze(monkeypatch, result=SimpleNamespace(embedding=_embedding(1.0), liveness=0.9))
    resp = await client.post(
        f"/face/enroll/{employee_id}", files=[("photos", _photo())], headers=hr_headers
    )
    assert resp.status_code == 200, resp.text

    # Re-enroll with a different embedding, then verify a probe matching the
    # NEW embedding passes — proves the old one was replaced, not appended to.
    _mock_analyze(monkeypatch, result=SimpleNamespace(embedding=_embedding(5.0), liveness=0.9))
    resp = await client.post(
        f"/face/enroll/{employee_id}", files=[("photos", _photo())], headers=hr_headers
    )
    assert resp.status_code == 200, resp.text

    _mock_analyze(monkeypatch, result=SimpleNamespace(embedding=_embedding(5.0), liveness=0.9))
    resp = await client.post(
        "/face/verify", files=[("photo", _photo())], headers=employee_headers
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["verified"] is True


@pytest.mark.asyncio
async def test_verify_match_passes(client, db_session, caplog, unique_email, monkeypatch):
    hr_headers, employee_headers, employee_id = await _setup_employee(
        client, db_session, caplog, unique_email
    )
    _mock_analyze(monkeypatch, result=SimpleNamespace(embedding=_embedding(1.0), liveness=0.9))
    await client.post(f"/face/enroll/{employee_id}", files=[("photos", _photo())], headers=hr_headers)

    resp = await client.post("/face/verify", files=[("photo", _photo())], headers=employee_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["verified"] is True
    assert body["reason"] is None


@pytest.mark.asyncio
async def test_verify_mismatch_returns_verified_false(
    client, db_session, caplog, unique_email, monkeypatch
):
    hr_headers, employee_headers, employee_id = await _setup_employee(
        client, db_session, caplog, unique_email
    )
    _mock_analyze(monkeypatch, result=SimpleNamespace(embedding=_embedding(1.0), liveness=0.9))
    await client.post(f"/face/enroll/{employee_id}", files=[("photos", _photo())], headers=hr_headers)

    # Orthogonal embedding -> cosine similarity 0 -> mismatch, not an error.
    _mock_analyze(monkeypatch, result=SimpleNamespace(embedding=[0.0, 1.0, 0.0, 0.0], liveness=0.9))
    resp = await client.post("/face/verify", files=[("photo", _photo())], headers=employee_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["verified"] is False
    assert body["reason"] == "low_similarity"


@pytest.mark.asyncio
async def test_verify_not_enrolled_returns_404(
    client, db_session, caplog, unique_email, monkeypatch
):
    _, employee_headers, _ = await _setup_employee(client, db_session, caplog, unique_email)
    resp = await client.post("/face/verify", files=[("photo", _photo())], headers=employee_headers)
    assert resp.status_code == 404, resp.text


@pytest.mark.asyncio
async def test_verify_no_face_returns_400(client, db_session, caplog, unique_email, monkeypatch):
    hr_headers, employee_headers, employee_id = await _setup_employee(
        client, db_session, caplog, unique_email
    )
    _mock_analyze(monkeypatch, result=SimpleNamespace(embedding=_embedding(1.0), liveness=0.9))
    await client.post(f"/face/enroll/{employee_id}", files=[("photos", _photo())], headers=hr_headers)

    _mock_analyze(monkeypatch, exc=face_service.PipelineNoFaceError("no face"))
    resp = await client.post("/face/verify", files=[("photo", _photo())], headers=employee_headers)
    assert resp.status_code == 400, resp.text


@pytest.mark.asyncio
async def test_verify_multiple_faces_returns_400(
    client, db_session, caplog, unique_email, monkeypatch
):
    hr_headers, employee_headers, employee_id = await _setup_employee(
        client, db_session, caplog, unique_email
    )
    _mock_analyze(monkeypatch, result=SimpleNamespace(embedding=_embedding(1.0), liveness=0.9))
    await client.post(f"/face/enroll/{employee_id}", files=[("photos", _photo())], headers=hr_headers)

    _mock_analyze(monkeypatch, exc=face_service.PipelineMultiFaceError("2 faces"))
    resp = await client.post("/face/verify", files=[("photo", _photo())], headers=employee_headers)
    assert resp.status_code == 400, resp.text


@pytest.mark.asyncio
async def test_verify_invalid_content_type_returns_400(
    client, db_session, caplog, unique_email
):
    _, employee_headers, _ = await _setup_employee(client, db_session, caplog, unique_email)
    resp = await client.post(
        "/face/verify",
        files=[("photo", ("a.gif", FAKE_JPEG, "image/gif"))],
        headers=employee_headers,
    )
    assert resp.status_code == 400, resp.text


@pytest.mark.asyncio
async def test_verify_liveness_failure_short_circuits_before_similarity(
    client, db_session, caplog, unique_email, monkeypatch
):
    """Embedding is an exact match, but liveness fails — must still reject,
    proving liveness gates before similarity is even compared (see PLAN.md
    test diagram: liveness must not be an afterthought behind matching)."""
    hr_headers, employee_headers, employee_id = await _setup_employee(
        client, db_session, caplog, unique_email
    )
    embedding = _embedding(1.0)
    _mock_analyze(monkeypatch, result=SimpleNamespace(embedding=embedding, liveness=0.9))
    await client.post(f"/face/enroll/{employee_id}", files=[("photos", _photo())], headers=hr_headers)

    _mock_analyze(monkeypatch, result=SimpleNamespace(embedding=embedding, liveness=0.0))
    resp = await client.post("/face/verify", files=[("photo", _photo())], headers=employee_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["verified"] is False
    assert body["reason"] == "liveness_failed"


@pytest.mark.asyncio
async def test_verify_model_unavailable_returns_503(
    client, db_session, caplog, unique_email, monkeypatch
):
    hr_headers, employee_headers, employee_id = await _setup_employee(
        client, db_session, caplog, unique_email
    )
    _mock_analyze(monkeypatch, result=SimpleNamespace(embedding=_embedding(1.0), liveness=0.9))
    await client.post(f"/face/enroll/{employee_id}", files=[("photos", _photo())], headers=hr_headers)

    _mock_analyze(monkeypatch, exc=face_service.PipelineModelUnavailableError("model down"))
    resp = await client.post("/face/verify", files=[("photo", _photo())], headers=employee_headers)
    assert resp.status_code == 503, resp.text


@pytest.mark.asyncio
async def test_verify_disabled_returns_503(client, db_session, caplog, unique_email, monkeypatch):
    from app.config.settings import get_settings

    _, employee_headers, _ = await _setup_employee(client, db_session, caplog, unique_email)
    settings = get_settings()
    monkeypatch.setattr(settings, "face_verification_enabled", False)
    resp = await client.post("/face/verify", files=[("photo", _photo())], headers=employee_headers)
    assert resp.status_code == 503, resp.text


@pytest.mark.asyncio
async def test_status_self_and_hr(client, db_session, caplog, unique_email, monkeypatch):
    hr_headers, employee_headers, employee_id = await _setup_employee(
        client, db_session, caplog, unique_email
    )

    resp = await client.get("/face/status", headers=employee_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["enrolled"] is False

    _mock_analyze(monkeypatch, result=SimpleNamespace(embedding=_embedding(1.0), liveness=0.9))
    await client.post(f"/face/enroll/{employee_id}", files=[("photos", _photo())], headers=hr_headers)

    resp = await client.get("/face/status", headers=employee_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["enrolled"] is True
    assert body["photo_count"] == 1

    resp = await client.get(f"/face/status/{employee_id}", headers=hr_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["enrolled"] is True
