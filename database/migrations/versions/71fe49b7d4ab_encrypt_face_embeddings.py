"""encrypt face embeddings at rest

Revision ID: 71fe49b7d4ab
Revises: a49a07557a55
Create Date: 2026-08-10 17:45:00.000000

"""
import sys
from pathlib import Path
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '71fe49b7d4ab'
down_revision: Union[str, None] = 'a49a07557a55'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Same in-process import technique face_service.py/attendance_service.py
# already use for cross-package imports — reuses the real encryption code
# (app.core.crypto) rather than re-implementing Fernet logic in a migration,
# so this migration and the running app can never disagree on the format.
_BACKEND_DIR = Path(__file__).resolve().parents[3] / "backend"
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))


def upgrade() -> None:
    # New failure-reason enum value for a decrypt-failure at verify time
    # (see FaceProfileCorruptedError in face_service.py). Safe to add
    # unconditionally — IF NOT EXISTS makes this idempotent.
    op.execute("ALTER TYPE faceverificationfailurereason ADD VALUE IF NOT EXISTS 'PROFILE_CORRUPTED'")

    # No schema change for face_profiles — the `embedding` column is JSON
    # both before and after (a JSON column can hold a plain string, not just
    # an array); this is a pure data migration. Deliberately part of the
    # same migration run as the code deploy that starts reading `.embedding`
    # as ciphertext (see PLAN.md item 5's "deploy-ordering hazard" finding)
    # — running this after the code deploy would break every enrolled
    # employee's verification until it completes.
    from app.core.crypto import encrypt_embedding  # noqa: E402

    connection = op.get_bind()
    rows = connection.execute(sa.text("SELECT id, embedding FROM face_profiles")).fetchall()
    for row_id, embedding in rows:
        # psycopg2 decodes a JSON array column straight into a Python list.
        # An already-encrypted row (a re-run, or a fresh DB with none yet)
        # decodes to a str instead — skip those so this migration is safe
        # to run more than once.
        if not isinstance(embedding, list):
            continue
        token = encrypt_embedding(embedding)
        connection.execute(
            sa.text("UPDATE face_profiles SET embedding = to_jsonb(CAST(:token AS text)) WHERE id = :id"),
            {"token": token, "id": row_id},
        )


def downgrade() -> None:
    # Deliberately not reversible: decrypting back to plaintext on downgrade
    # would mean a rollback silently re-exposes biometric data in plaintext,
    # a worse outcome than a blocked downgrade. Rolling back this migration
    # requires a manual, explicit decision, not an automatic one.
    raise RuntimeError(
        "This migration is intentionally not downgradable — decrypting "
        "biometric data back to plaintext must be a deliberate, manual "
        "operation, not an automatic rollback."
    )
