"""Live end-to-end smoke test for face enrollment + verification.

Exercises the real HTTP API against a running dev server and live Postgres —
required before calling this module done (mocked unit tests alone are not
sufficient, per this project's own live-verification discipline). Test faces
are cropped at runtime from insightface's own bundled sample photo
(t1.jpg, shipped inside the `insightface` pip package for its own demos) —
no external image fetching, no fabricated identities.

`FACE_VERIFICATION_ENABLED` defaults to False (see config/settings.py) — the
enroll/verify sections below need it on regardless of what you're checking, so
start the server with it set, and pass the matching flag to this script:

    FACE_VERIFICATION_ENABLED=true uvicorn app.main:app --port 8001 > server.log 2>&1 &
    python -m scripts.smoke_test_face --base-url http://localhost:8001 \
        --log-file server.log --face-verification-enabled

Run it again WITHOUT setting the env var and WITHOUT the CLI flag to confirm
the flag-off regression guard instead (check-in still works with no selfie;
the standalone /face/enroll and /face/verify calls will correctly 503 — that
is expected, not a bug, when the flag is off).

The dev server logs OTP codes instead of emailing them when SMTP isn't
configured (see app/services/email_service.py) — this script tails that log
to grab the verification code automatically, mirroring what
backend/tests/conftest.py's extract_otp() does against pytest's caplog.
"""

from __future__ import annotations

import argparse
import base64
import re
import sys
import time
import uuid
from pathlib import Path

import cv2
import httpx
import insightface

_AI_DIR = Path(__file__).resolve().parents[2] / "ai"
sys.path.insert(0, str(_AI_DIR))
from face_recognition.pipeline import _get_app  # noqa: E402


def build_fixtures(tmp_dir: Path) -> tuple[Path, Path, Path]:
    """Crops two distinct real faces + one synthetically-degraded ("spoof
    proxy") version of the first, from insightface's own bundled group
    photo. Returns (face_a, face_b, face_a_spoof)."""
    import numpy as np

    tmp_dir.mkdir(parents=True, exist_ok=True)
    src = Path(insightface.__file__).parent / "data" / "images" / "t1.jpg"
    img = cv2.imread(str(src))
    h, w = img.shape[:2]
    app = _get_app()
    faces = sorted(app.get(img), key=lambda f: f.bbox[0])[:2]

    paths = []
    for i, face in enumerate(faces):
        x1, y1, x2, y2 = [int(v) for v in face.bbox]
        pad = 80
        crop = img[max(y1 - pad, 0) : min(y2 + pad, h), max(x1 - pad, 0) : min(x2 + pad, w)]
        path = tmp_dir / f"face_{i}.jpg"
        cv2.imwrite(str(path), crop)
        paths.append(path)

    face_a_img = cv2.imread(str(paths[0]))
    blurred = cv2.GaussianBlur(face_a_img, (5, 5), 1.5)
    fh, fw = face_a_img.shape[:2]
    yy, xx = np.mgrid[0:fh, 0:fw]
    band = (np.sin(xx * 0.9) * 15).astype(np.int16)
    spoofed = np.clip(blurred.astype(np.int16) + band[..., None], 0, 255).astype("uint8")
    spoof_path = tmp_dir / "face_0_spoof.jpg"
    cv2.imwrite(str(spoof_path), spoofed, [cv2.IMWRITE_JPEG_QUALITY, 40])

    return paths[0], paths[1], spoof_path


def extract_otp(log_text: str) -> str:
    matches = re.findall(r"verification code is (\d{6})", log_text)
    if not matches:
        raise AssertionError("no OTP code found in server log")
    return matches[-1]


def tail_new_content(log_file: Path, since_pos: int) -> tuple[str, int]:
    with open(log_file, "r", errors="ignore") as f:
        f.seek(since_pos)
        content = f.read()
        return content, f.tell()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost:8001")
    parser.add_argument("--log-file", required=True, help="dev server's stdout log file")
    parser.add_argument("--tmp-dir", default=None)
    parser.add_argument(
        "--face-verification-enabled",
        action="store_true",
        help="pass this if the dev server under test was started with FACE_VERIFICATION_ENABLED=true "
        "(changes which check-in outcomes are expected below)",
    )
    args = parser.parse_args()

    tmp_dir = Path(args.tmp_dir) if args.tmp_dir else Path.cwd() / ".smoke_face_fixtures"
    print("Building face fixtures from insightface's bundled sample photo...")
    face_a, face_b, face_a_spoof = build_fixtures(tmp_dir)
    print(f"  face_a={face_a}\n  face_b={face_b}\n  face_a_spoof={face_a_spoof}")

    log_path = Path(args.log_file)
    log_pos = log_path.stat().st_size if log_path.exists() else 0

    client = httpx.Client(base_url=args.base_url, timeout=30.0)
    unique = uuid.uuid4().hex[:12]
    hr_email = f"smoke-hr-{unique}@example.com"
    employee_email = f"smoke-emp-{unique}@example.com"
    password = "SmokeTest123"

    def register_and_verify(email: str) -> None:
        resp = client.post("/auth/register", json={
            "email": email, "password": password, "full_name": "Smoke Test User"
        })
        assert resp.status_code == 201, resp.text
        deadline = time.time() + 5
        code = None
        while time.time() < deadline:
            content, new_pos = tail_new_content(log_path, log_pos)
            try:
                code = extract_otp(content)
                break
            except AssertionError:
                time.sleep(0.2)
        assert code is not None, f"could not find OTP for {email} in server log"
        resp = client.post("/auth/verify-email", json={"email": email, "code": code})
        assert resp.status_code == 200, resp.text

    print("Registering HR user...")
    register_and_verify(hr_email)
    # No HTTP endpoint promotes a role (TODOS.md: "roles:manage has no
    # endpoint") — every existing script/test that needs an HR account hits
    # the DB directly for this one step. Real HTTP is used for everything
    # actually under test below.
    import asyncio

    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.config.settings import get_settings
    from app.models.role import Role
    from app.models.user import User

    async def promote(email: str, role_name: str) -> None:
        engine = create_async_engine(get_settings().database_url)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with session_factory() as session:
            user = (await session.execute(select(User).where(User.email == email))).scalar_one()
            role = (await session.execute(select(Role).where(Role.name == role_name))).scalar_one()
            user.role_id = role.id
            await session.commit()
        await engine.dispose()

    asyncio.run(promote(hr_email, "hr_manager"))
    print("Logging in as HR...")
    resp = client.post("/auth/login", json={"email": hr_email, "password": password})
    assert resp.status_code == 200, resp.text
    hr_headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}

    print("Onboarding employee...")
    resp = client.post(
        "/employees",
        json={
            "email": employee_email,
            "full_name": "Smoke Test Employee",
            "password": "TempPass123",
            "hire_date": "2026-01-15",
        },
        headers=hr_headers,
    )
    assert resp.status_code == 201, resp.text
    employee_id = resp.json()["id"]

    print("Registering employee's own account (separate OTP)...")
    resp = client.post("/auth/login", json={"email": employee_email, "password": "TempPass123"})
    assert resp.status_code == 200, resp.text
    employee_headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}

    failures = []

    def check(label: str, condition: bool, detail: str = "") -> None:
        status = "PASS" if condition else "FAIL"
        print(f"[{status}] {label} {detail}")
        if not condition:
            failures.append(label)

    print("\n--- Enroll with face_a ---")
    with open(face_a, "rb") as f:
        resp = client.post(
            f"/face/enroll/{employee_id}",
            files=[("photos", ("face_a.jpg", f, "image/jpeg"))],
            headers=hr_headers,
        )
    check("enroll succeeds", resp.status_code == 200, resp.text)

    print("\n--- Verify with face_a (same person) ---")
    with open(face_a, "rb") as f:
        resp = client.post(
            "/face/verify", files=[("photo", ("face_a.jpg", f, "image/jpeg"))], headers=employee_headers
        )
    body = resp.json() if resp.status_code == 200 else {}
    check("verify same-person returns 200", resp.status_code == 200, resp.text)
    check("verify same-person -> verified=true", body.get("verified") is True, str(body))

    print("\n--- Verify with face_b (different person) ---")
    with open(face_b, "rb") as f:
        resp = client.post(
            "/face/verify", files=[("photo", ("face_b.jpg", f, "image/jpeg"))], headers=employee_headers
        )
    body = resp.json() if resp.status_code == 200 else {}
    check("verify different-person returns 200", resp.status_code == 200, resp.text)
    check(
        "verify different-person -> verified=false, reason=low_similarity",
        body.get("verified") is False and body.get("reason") == "low_similarity",
        str(body),
    )

    print("\n--- Verify with face_a_spoof (synthetic degraded proxy, INFORMATIONAL) ---")
    with open(face_a_spoof, "rb") as f:
        resp = client.post(
            "/face/verify",
            files=[("photo", ("face_a_spoof.jpg", f, "image/jpeg"))],
            headers=employee_headers,
        )
    body = resp.json() if resp.status_code == 200 else {}
    print(f"    response: {resp.status_code} {body}")
    print(
        "    NOTE: this is a synthetic blur+banding proxy for a print/screen replay, not a\n"
        "    real physical spoof capture. Passive heuristic liveness (see ai/face_recognition/\n"
        "    pipeline.py) is documented as v1/interim — do not treat a 'verified=true' here as\n"
        "    proof the liveness gate is production-ready. Not counted as a hard pass/fail."
    )

    print("\n--- Kill switch: FACE_VERIFICATION_ENABLED=false ---")
    resp = client.get(f"/face/status/{employee_id}", headers=hr_headers)
    check("status endpoint reachable before disabling", resp.status_code == 200, resp.text)

    print(
        f"\n--- Check-in gate (server started with --face-verification-enabled="
        f"{args.face_verification_enabled}) ---"
    )
    OFFICE_LAT, OFFICE_LNG = 36.8065, 10.1815
    resp = client.post(
        "/geofences",
        json={"name": "Smoke Test HQ", "center_latitude": OFFICE_LAT, "center_longitude": OFFICE_LNG, "radius_meters": 100},
        headers=hr_headers,
    )
    check("geofence created", resp.status_code == 201, resp.text)

    def check_in_with(selfie_path: Path | None) -> httpx.Response:
        body = {"latitude": OFFICE_LAT, "longitude": OFFICE_LNG}
        if selfie_path is not None:
            body["selfie_base64"] = base64.b64encode(selfie_path.read_bytes()).decode()
        return client.post("/attendance/check-in", json=body, headers=employee_headers)

    def check_out() -> None:
        client.post(
            "/attendance/check-out",
            json={"latitude": OFFICE_LAT, "longitude": OFFICE_LNG},
            headers=employee_headers,
        )

    resp = check_in_with(face_a)
    check("check-in with matching selfie succeeds", resp.status_code == 201, resp.text)
    check_out()

    if args.face_verification_enabled:
        resp = check_in_with(face_b)
        check("check-in with mismatched selfie rejected (400)", resp.status_code == 400, resp.text)
        resp = check_in_with(None)
        check("check-in with no selfie rejected when enabled (400)", resp.status_code == 400, resp.text)
    else:
        resp = check_in_with(None)
        check(
            "check-in with no selfie still succeeds when flag is off (regression guard)",
            resp.status_code == 201,
            resp.text,
        )
        check_out()

    print("\n" + "=" * 60)
    if failures:
        print(f"SMOKE TEST FAILED: {len(failures)} check(s) failed: {failures}")
        sys.exit(1)
    print("SMOKE TEST PASSED")


if __name__ == "__main__":
    main()
