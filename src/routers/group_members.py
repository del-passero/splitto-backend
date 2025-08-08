# src/routers/group_members.py
# РОУТЕР УЧАСТНИКОВ ГРУППЫ
# -----------------------------------------------------------------------------
# Что делаем в этом файле:
#  1) Сохраняем старую логику (bulk-добавление друзей, пагинация в / и /group/{group_id}).
#  2) Авторизация через Telegram WebApp (get_current_telegram_user) во всех ручках.
#  3) Правила доступа:
#     • Добавлять участников может ЛЮБОЙ УЧАСТНИК группы (не только владелец).
#     • Удалять участников может ТОЛЬКО ВЛАДЕЛЕЦ группы.
#     • НОВОЕ: «Выйти из группы» может любой участник, но с проверкой:
#        – владелец НЕ может выйти;
#        – у пользователя не должно быть ни одной НЕудалённой транзакции в этой группе
#          (created_by / paid_by / transfer_from / shares.user_id);
#        – группа должна быть активной (не archived/deleted).
#  4) Блокируем мутации для архивных/удалённых групп.
#  5) Просмотр состава группы — только участникам этой группы.
#  6) Не даём удалить владельца (защита от случайной поломки группы).
#  7) Пагинация:
#     • / — поддерживает offset/limit (оставляем).
#     • /group/{group_id} — поддерживает offset/limit (оставляем).
#
# ВАЖНО: модель Group получила поля deleted_at/status (архив/soft-delete) — миграции сделаем позже.
# До миграций код не запускаем.

from typing import List, Optional, Union

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from src.db import get_db
from src.models.friend import Friend
from src.models.group import Group, GroupStatus
from src.models.group_member import GroupMember
from src.models.transaction import Transaction              # NEW: для проверки «есть транзакции?»
from src.models.transaction_share import TransactionShare   # NEW: для проверки участия в shares
from src.models.user import User

from src.schemas.group_member import GroupMemberCreate, GroupMemberOut
from src.schemas.user import UserOut

# Авторизация: текущий пользователь из Telegram WebApp
from src.utils.telegram_dep import get_current_telegram_user


# Общие гарды/хелперы по группам
from src.utils.groups import (
    require_membership,         # проверка «пользователь — участник группы»
    require_owner,              # проверка «пользователь — владелец группы»
    guard_mutation_for_member,  # членство + группа active (не archived/deleted)
    ensure_group_active,        # группа не archived/deleted
)

router = APIRouter()


def add_mutual_friends_for_group(db: Session, group_id: int):
    """
    Для всех участников группы создать двусторонние связи Friend (bulk-оптимизация!).
    Как это работает:
      1) Сначала собираем все user_id участников группы одним запросом.
      2) Затем вытаскиваем уже существующие связи среди них в виде множества пар (user_id, friend_id).
      3) Генерируем недостающие пары без вложенных SELECT’ов и bulk-вставляем их.
    Почему двусторонние? Потому что дружба в модели симметричная: (A,B) и (B,A).
    """
    # Получаем все user_id участников группы
    member_ids = [m[0] for m in db.query(GroupMember.user_id).filter(GroupMember.group_id == group_id).all()]
    if not member_ids:
        return

    # Bulk fetch: все существующие friend-связи в группе (user_id, friend_id)
    existing_links = db.query(Friend.user_id, Friend.friend_id).filter(
        Friend.user_id.in_(member_ids),
        Friend.friend_id.in_(member_ids)
    ).all()
    existing_set = set(existing_links)

    # Сформируем все возможные уникальные пары (без повторов)
    to_create = []
    for i in range(len(member_ids)):
        for j in range(i + 1, len(member_ids)):
            a, b = member_ids[i], member_ids[j]
            # Если связи нет — добавляем двусторонне
            if (a, b) not in existing_set:
                to_create.append(Friend(user_id=a, friend_id=b))
            if (b, a) not in existing_set:
                to_create.append(Friend(user_id=b, friend_id=a))

    if to_create:
        db.bulk_save_objects(to_create)
        db.commit()


@router.post("/", response_model=GroupMemberOut)
def add_group_member(
    member: GroupMemberCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_telegram_user),
):
    """
    Добавить нового участника в группу.

    ПРАВИЛА ДОСТУПА:
      • Эту операцию может выполнять ЛЮБОЙ УЧАСТНИК группы (не только владелец).
      • Группа должна быть активной (не archived и не soft-deleted).

    ВАЛИДАЦИИ:
      • Пользователь, которого добавляем, должен существовать в таблице users.
      • Нельзя добавить участника второй раз.

    ПОСЛЕ ДОБАВЛЕНИЯ:
      • Автоматически добавляем всем участникам группы друг друга в друзья (bulk).
    """
    # 1) Гард: текущий пользователь — участник группы, и группа активна
    group = guard_mutation_for_member(db, member.group_id, current_user.id)

    # 2) Пользователь, которого добавляем, существует?
    user_to_add = db.query(User).filter(User.id == member.user_id).first()
    if not user_to_add:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    # 3) Уже состоит в группе?
    exists = db.query(GroupMember).filter(
        GroupMember.group_id == member.group_id,
        GroupMember.user_id == member.user_id
    ).first()
    if exists:
        raise HTTPException(status_code=400, detail="Пользователь уже в группе")

    # 4) Добавляем в группу
    db_member = GroupMember(group_id=member.group_id, user_id=member.user_id)
    db.add(db_member)
    db.commit()
    db.refresh(db_member)

    # 5) Bulk добавление друзей
    add_mutual_friends_for_group(db, member.group_id)

    return db_member


@router.get("/", response_model=Union[List[GroupMemberOut], dict])
def get_group_members(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_telegram_user),  # просто требуем авторизацию
    offset: int = Query(0, ge=0),
    limit: Optional[int] = Query(None, gt=0)
):
    """
    Получить список всех записей GroupMember (админ/техн. эндпоинт).
    ПАГИНАЦИЯ:
      • Если передан limit — возвращаем {"total": ..., "items": [...]}
      • Если limit не передан — возвращаем массив без total.
    """
    query = db.query(GroupMember).options(joinedload(GroupMember.user))
    total = query.count()
    if limit is not None:
        members = query.offset(offset).limit(limit).all()
    else:
        members = query.all()

    items = [GroupMemberOut.from_orm(m) for m in members]
    if limit is not None:
        return {"total": total, "items": items}
    else:
        return items


@router.get("/group/{group_id}", response_model=Union[List[dict], dict])
def get_members_for_group(
    group_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_telegram_user),
    offset: int = Query(0, ge=0),
    limit: Optional[int] = Query(None, gt=0)
):
    """
    Получить участников конкретной группы (bulk join на User!).

    ДОСТУП:
      • Видеть состав группы может только её участник.

    ПАГИНАЦИЯ:
      • Если передан limit — вернётся {"total": ..., "items": [...]}
      • Если limit не передан — вернётся массив без total.
    """
    # 1) Проверяем, что текущий пользователь — участник группы (и группа не soft-deleted)
    require_membership(db, group_id, current_user.id)

    # 2) Основной запрос
    query = (
        db.query(GroupMember, User)
        .join(User, GroupMember.user_id == User.id)
        .filter(GroupMember.group_id == group_id)
        .options()  # здесь join уже есть; joinedload не нужен
    )

    total = query.count()
    if limit is not None:
        memberships = query.offset(offset).limit(limit).all()
    else:
        memberships = query.all()

    # Полностью сериализуем user через UserOut (как в твоём коде)
    items = [
        {
            "id": gm.id,
            "group_id": gm.group_id,
            "user": UserOut.from_orm(u).dict()
        }
        for gm, u in memberships
    ]

    if limit is not None:
        return {"total": total, "items": items}
    else:
        return items


@router.delete("/{member_id}", status_code=204)
def delete_group_member(
    member_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_telegram_user),
):
    """
    Удалить участника из группы.

    ПРАВИЛА:
      • Удалять может ТОЛЬКО ВЛАДЕЛЕЦ группы.
      • Группа должна быть активной (не archived/deleted).
      • Нельзя удалить владельца (защита от поломки группы).
    """
    # 1) Находим запись членства
    member = db.query(GroupMember).filter(GroupMember.id == member_id).first()
    if not member:
        raise HTTPException(status_code=404, detail="Участник группы не найден")

    # 2) Группа существует и не soft-deleted
    group = db.query(Group).filter(Group.id == member.group_id, Group.deleted_at.is_(None)).first()
    if not group:
        raise HTTPException(status_code=404, detail="Группа не найдена")

    # 3) Проверка, что текущий пользователь — владелец группы
    require_owner(db, group.id, current_user.id)

    # 4) Группа должна быть активной (не archived/deleted)
    ensure_group_active(group)

    # 5) Нельзя удалить владельца группы
    if member.user_id == group.owner_id:
        raise HTTPException(status_code=409, detail="Нельзя удалить владельца группы")

    # 6) Удаляем запись членства
    db.delete(member)
    db.commit()
    return


# -----------------------------------------------------------------------------
# НОВОЕ: Выйти из группы (self-leave)
# -----------------------------------------------------------------------------
@router.post("/group/{group_id}/leave", status_code=204)
def leave_group(
    group_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_telegram_user),
):
    """
    Выйти из группы (удалить СЕБЯ из участников).

    Правила:
      • Выйти может только участник группы (очевидно).
      • Владелец НЕ может выйти из группы.
      • Группа должна быть активной (не archived/deleted).
      • У пользователя не должно быть НИ ОДНОЙ НЕудалённой транзакции в этой группе, где он:
           – автор (created_by), или
           – платил (paid_by), или
           – источник перевода (transfer_from), или
           – присутствует в долях (transaction_shares.user_id).
        (Транзакции с is_deleted = true игнорируются.)
    """
    # 1) Проверяем членство и получаем группу
    member = db.query(GroupMember).filter(
        GroupMember.group_id == group_id,
        GroupMember.user_id == current_user.id
    ).first()
    if not member:
        raise HTTPException(status_code=403, detail="Вы не являетесь участником группы")

    group = db.query(Group).filter(Group.id == group_id, Group.deleted_at.is_(None)).first()
    if not group:
        raise HTTPException(status_code=404, detail="Группа не найдена")

    # 2) Владелец не может выйти
    if group.owner_id == current_user.id:
        raise HTTPException(status_code=409, detail="Владелец не может выйти из группы")

    # 3) Группа должна быть активной (не archived/deleted)
    ensure_group_active(group)

    # 4) Проверка на НЕудалённые транзакции, где пользователь фигурирует любым образом
    has_tx = (
        db.query(func.count())
        .select_from(Transaction)
        .outerjoin(
            TransactionShare,
            TransactionShare.transaction_id == Transaction.id
        )
        .filter(
            Transaction.group_id == group_id,
            Transaction.is_deleted.is_(False),
            (
                (Transaction.created_by == current_user.id) |
                (Transaction.paid_by == current_user.id) |
                (Transaction.transfer_from == current_user.id) |
                (TransactionShare.user_id == current_user.id)
            )
        )
        .scalar()
        or 0
    )
    if has_tx > 0:
        raise HTTPException(status_code=409, detail="Нельзя выйти: есть не удалённые транзакции с вашим участием")

    # 5) Удаляем запись членства (self-leave)
    db.delete(member)
    db.commit()
    return
