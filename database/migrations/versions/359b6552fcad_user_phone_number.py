"""user phone number

Revision ID: 359b6552fcad
Revises: 71fe49b7d4ab
Create Date: 2026-08-12 13:35:55.220037

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '359b6552fcad'
down_revision: Union[str, None] = '71fe49b7d4ab'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('users', sa.Column('phone_number', sa.String(length=50), nullable=True))


def downgrade() -> None:
    op.drop_column('users', 'phone_number')
