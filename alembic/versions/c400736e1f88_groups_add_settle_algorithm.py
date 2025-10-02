"""groups: add settle_algorithm

<описание: добавляет колонку settle_algorithm с типом ENUM('greedy','pairs') + индекс>
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# --- ВАЖНО ---
# 1) Оставь значение `revision` из сгенерированного файла Alembic.
# 2) Убедись, что `down_revision` равен "cfc0e43a79e4".
revision: str = 'c400736e1f88'
down_revision: Union[str, None] = "cfc0e43a79e4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None
# --- /ВАЖНО ---

# Вспомогательные инспекторы (как в твоих миграциях)
def _col_names(bind, table: str) -> set[str]:
    insp = sa.inspect(bind)
    return {c["name"] for c in insp.get_columns(table)}

def _index_names(bind, table: str) -> set[str]:
    insp = sa.inspect(bind)
    return {ix["name"] for ix in insp.get_indexes(table)}


def upgrade() -> None:
    bind = op.get_bind()

    # 1) Создаём тип ENUM (безопасно, если уже есть — checkfirst=True)
    settle_enum = sa.Enum("greedy", "pairs", name="settle_algorithm")
    settle_enum.create(bind, checkfirst=True)

    # 2) Добавляем колонку, если её ещё нет
    cols = _col_names(bind, "groups")
    if "settle_algorithm" not in cols:
        op.add_column(
            "groups",
            sa.Column(
                "settle_algorithm",
                settle_enum,
                nullable=False,
                server_default=sa.text("'greedy'"),  # дефолт для существующих строк
                comment="Алгоритм взаимозачёта: greedy|pairs",
            ),
        )

    # 3) Индекс на колонку (для фильтров/сортировок)
    ix_names = _index_names(bind, "groups")
    if "ix_groups_settle_algorithm" not in ix_names:
        op.create_index(
            "ix_groups_settle_algorithm",
            "groups",
            ["settle_algorithm"],
            unique=False,
        )


def downgrade() -> None:
    bind = op.get_bind()

    # 1) Удаляем индекс, если есть
    ix_names = _index_names(bind, "groups")
    if "ix_groups_settle_algorithm" in ix_names:
        op.drop_index("ix_groups_settle_algorithm", table_name="groups")

    # 2) Удаляем колонку, если есть
    cols = _col_names(bind, "groups")
    if "settle_algorithm" in cols:
        op.drop_column("groups", "settle_algorithm")

    # 3) Дропаем тип ENUM (после удаления колонки)
    settle_enum = sa.Enum("greedy", "pairs", name="settle_algorithm")
    settle_enum.drop(bind, checkfirst=True)
