# backend/src/routers/friends.py

from fastapi import APIRouter, Depends, HTTPException, Body, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from src.db import get_db
from src.models.user import User
from src.models.friend import Friend
from src.models.friend_invite import FriendInvite
from src.models.invite_usage import InviteUsage
from src.models.event import Event
from src.schemas.friend import FriendOut
from src.schemas.friend_invite import FriendInviteOut
from src.schemas.user import UserOut
from src.utils.telegram_dep import get_current_telegram_user
import secrets
from datetime import datetime

# NEW: для общих групп
from src.models.group_member import GroupMember
from src.models.group import Group

router = APIRouter(tags=["Друзья"])

@router.get("/", response_model=dict)
def get_friends(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_telegram_user),
    show_hidden: Optional[bool] = False,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, gt=0)
):
    """
    Получить список друзей текущего пользователя (с пагинацией).
    """
    query = db.query(Friend).filter(Friend.user_id == current_user.id)
    if show_hidden is not None:
        query = query.filter(Friend.hidden == show_hidden)
    total = query.count()
    friends = query.offset(offset).limit(limit).all()

    # Bulk fetch: оптимизация!
    friend_ids = [friend.friend_id for friend in friends]
    profiles = db.query(User).filter(User.id.in_(friend_ids)).all()
    profiles_map = {u.id: u for u in profiles}

    result = []
    for friend in friends:
        friend_profile = profiles_map.get(friend.friend_id)
        result.append(
            FriendOut(
                id=friend.id,
                user_id=friend.user_id,
                friend_id=friend.friend_id,
                created_at=friend.created_at,
                updated_at=friend.updated_at,
                hidden=friend.hidden,
                user=UserOut.from_orm(current_user),
                friend=UserOut.from_orm(friend_profile) if friend_profile else None
            )
        )

    return {
        "total": total,
        "friends": result
    }


@router.post("/invite", response_model=FriendInviteOut)
def create_invite(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_telegram_user)
):
    """
    Сгенерировать бессрочную invite-ссылку для приглашения в Splitto.
    """
    token = secrets.token_urlsafe(16)
    invite = FriendInvite(from_user_id=current_user.id, token=token)
    db.add(invite)
    db.commit()
    db.refresh(invite)
    return invite

@router.post("/accept", response_model=dict)
def accept_invite(
    token: str = Body(..., embed=True),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_telegram_user)
):
    """
    Принять invite по токену. Добавляет пользователя в друзья к автору invite (если не сам себе).
    При первом заходе по invite увеличивает invited_friends_count у автора.
    """
    invite = db.query(FriendInvite).filter_by(token=token).first()
    if not invite:
        raise HTTPException(404, detail={"code": "invite_not_found"})
    from_user_id = invite.from_user_id
    to_user_id = current_user.id
    if from_user_id == to_user_id:
        return {"success": True}
    # Проверяем, не являются ли уже друзьями
    exists = db.query(Friend).filter(
        Friend.user_id == from_user_id,
        Friend.friend_id == to_user_id
    ).first()
    if not exists:
        now = datetime.utcnow()
        # Двусторонняя связь дружбы
        db.add(Friend(user_id=from_user_id, friend_id=to_user_id, hidden=False, created_at=now, updated_at=now))
        db.add(Friend(user_id=to_user_id, friend_id=from_user_id, hidden=False, created_at=now, updated_at=now))
        db.commit()
        # Логируем событие "добавлен друг"
        db.add(Event(
            actor_id=from_user_id,
            target_user_id=to_user_id,
            type="friend_added",
            data=None
        ))
        db.add(Event(
            actor_id=to_user_id,
            target_user_id=from_user_id,
            type="friend_added",
            data=None
        ))
        db.commit()
    # Отмечаем использование инвайта (и увеличиваем счетчик только при первом использовании)
    usage = db.query(InviteUsage).filter_by(user_id=to_user_id).first()
    if not usage:
        db.add(InviteUsage(invite_id=invite.id, user_id=to_user_id))
        inviter = db.query(User).filter_by(id=from_user_id).first()
        if inviter:
            inviter.invited_friends_count += 1
            db.commit()
        # Логируем событие "инвайт зарегистрирован"
        db.add(Event(
            actor_id=from_user_id,
            target_user_id=to_user_id,
            type="invite_registered",
            data={"invite_id": invite.id}
        ))
        db.add(Event(
            actor_id=to_user_id,
            target_user_id=from_user_id,
            type="invite_registered",
            data={"invite_id": invite.id}
        ))
        db.commit()
    return {"success": True}

@router.post("/{friend_id}/hide", response_model=dict)
def hide_friend(
    friend_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_telegram_user)
):
    """
    Скрыть друга из списка (hidden=True).
    """
    friend = db.query(Friend).filter_by(user_id=current_user.id, friend_id=friend_id).first()
    if not friend:
        raise HTTPException(404, detail="Friend not found")
    friend.hidden = True
    friend.updated_at = datetime.utcnow()
    db.commit()
    # Логируем событие "друг скрыт"
    db.add(Event(
        actor_id=current_user.id,
        target_user_id=friend_id,
        type="friend_hidden",
        data=None
    ))
    db.commit()
    return {"success": True}

@router.post("/{friend_id}/unhide", response_model=dict)
def unhide_friend(
    friend_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_telegram_user)
):
    """
    Восстановить друга в списке (hidden=False).
    """
    friend = db.query(Friend).filter_by(user_id=current_user.id, friend_id=friend_id).first()
    if not friend:
        raise HTTPException(404, detail="Friend not found")
    friend.hidden = False
    friend.updated_at = datetime.utcnow()
    db.commit()
    # Логируем событие "друг восстановлен"
    db.add(Event(
        actor_id=current_user.id,
        target_user_id=friend_id,
        type="friend_unhidden",
        data=None
    ))
    db.commit()
    return {"success": True}

@router.get("/invite/{token}/stats", response_model=dict)
def invite_stats(
    token: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_telegram_user)
):
    """
    Получить статистику по инвайту (сколько пользователей впервые зашли по этой ссылке,
    а также список user_id и дату входа).
    """
    invite = db.query(FriendInvite).filter_by(token=token, from_user_id=current_user.id).first()
    if not invite:
        raise HTTPException(404, detail={"code": "invite_not_found"})
    usages = db.query(InviteUsage).filter_by(invite_id=invite.id).all()
    uses_count = len(usages)
    return {
        "uses_count": uses_count,
        "usages": [
            {"user_id": u.user_id, "used_at": u.used_at}
            for u in usages
        ]
    }

@router.get("/search", response_model=dict)
def search_friends(
    query: str = Query(..., min_length=1, description="Строка для поиска по имени/username"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_telegram_user),
    show_hidden: Optional[bool] = False,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, gt=0)
):
    """
    Поиск друзей по имени, username или фамилии (с пагинацией).
    Bulk-оптимизация: загружает все Friend-связи одним запросом.
    """
    # Получаем friend_ids друзей текущего пользователя с фильтром hidden
    friend_ids_query = db.query(Friend.friend_id).filter(Friend.user_id == current_user.id)
    if show_hidden is not None:
        friend_ids_query = friend_ids_query.filter(Friend.hidden == show_hidden)
    friend_ids = [row[0] for row in friend_ids_query]

    # Поиск пользователей среди друзей (bulk)
    search_query = db.query(User).filter(
        User.id.in_(friend_ids),
        (
            User.username.ilike(f"%{query}%") |
            User.first_name.ilike(f"%{query}%") |
            User.last_name.ilike(f"%{query}%")
        )
    )
    total = search_query.count()
    users = search_query.offset(offset).limit(limit).all()

    # Bulk-оптимизация: загружаем все Friend-связи за один раз!
    # Формируем map по user_id (friend_id)
    if users:
        user_ids = [u.id for u in users]
        friend_links = db.query(Friend).filter(
            Friend.user_id == current_user.id,
            Friend.friend_id.in_(user_ids)
        ).all()
        friend_link_map = {f.friend_id: f for f in friend_links}
    else:
        friend_link_map = {}

    result = []
    for user in users:
        friend_link = friend_link_map.get(user.id)
        if not friend_link:
            continue
        result.append(
            FriendOut(
                id=friend_link.id,
                user_id=friend_link.user_id,
                friend_id=friend_link.friend_id,
                created_at=friend_link.created_at,
                updated_at=friend_link.updated_at,
                hidden=friend_link.hidden,
                user=UserOut.from_orm(current_user),
                friend=UserOut.from_orm(user)
            )
        )

    return {
        "total": total,
        "friends": result
    }

# ===================== NEW ENDPOINTS FOR CONTACT PAGE =====================

@router.get("/{friend_id}", response_model=FriendOut)
def get_friend_detail(
    friend_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_telegram_user),
):
    """
    Детали дружбы для конкретного друга текущего пользователя.
    friend_id — это ID пользователя-друга (как в hide/unhide).
    """
    link = db.query(Friend).filter_by(user_id=current_user.id, friend_id=friend_id).first()
    if not link:
        raise HTTPException(404, detail="Friend not found")
    contact = db.query(User).filter_by(id=friend_id).first()
    if not contact:
        raise HTTPException(404, detail="User not found")
    return FriendOut(
        id=link.id,
        user_id=link.user_id,
        friend_id=link.friend_id,
        created_at=link.created_at,
        updated_at=link.updated_at,
        hidden=link.hidden,
        user=UserOut.from_orm(current_user),
        friend=UserOut.from_orm(contact),
    )


@router.get("/{friend_id}/common-groups", response_model=List[str])
def get_common_group_names(
    friend_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_telegram_user),
):
    """
    Возвращает только названия общих групп (string[]).
    """
    # set of group ids, где состоит current_user
    my_group_ids = db.query(GroupMember.group_id).filter(
        GroupMember.user_id == current_user.id
    ).subquery()

    # set of group ids, где состоит friend_id (контакт)
    his_group_ids = db.query(GroupMember.group_id).filter(
        GroupMember.user_id == friend_id
    ).subquery()

    # пересечение по group_id и выбор только имён
    names = (
        db.query(Group.name)
        .join(my_group_ids, my_group_ids.c.group_id == Group.id)
        .join(his_group_ids, his_group_ids.c.group_id == Group.id)
        .order_by(Group.name.asc())
        .all()
    )
    return [row[0] for row in names]


@router.get("/of/{user_id}", response_model=dict)
def get_friends_of_user(
    user_id: int,
    db: Session = Depends(get_db),
    _current_user: User = Depends(get_current_telegram_user),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, gt=0),
):
    """
    «Контакты контакта» (Вариант A): список друзей указанного пользователя.
    Возвращаем в том же контракте { total, friends: FriendOut[] }.
    """
    q = db.query(Friend).filter(Friend.user_id == user_id)
    total = q.count()
    links = q.offset(offset).limit(limit).all()

    # bulk user profiles
    ids = [l.friend_id for l in links] + [user_id]
    profiles = db.query(User).filter(User.id.in_(set(ids))).all()
    profiles_map = {u.id: u for u in profiles}
    owner = profiles_map.get(user_id)

    result = []
    for link in links:
        contact = profiles_map.get(link.friend_id)
        if not contact or not owner:
            # пропускаем несогласованность
            continue
        result.append(
            FriendOut(
                id=link.id,
                user_id=link.user_id,          # владелец списка (contact page owner)
                friend_id=link.friend_id,      # его друг
                created_at=link.created_at,
                updated_at=link.updated_at,
                hidden=link.hidden,
                user=UserOut.from_orm(owner),
                friend=UserOut.from_orm(contact),
            )
        )

    return {"total": total, "friends": result}
