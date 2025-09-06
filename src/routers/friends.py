# src/routers/friends.py

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

# Для общих групп и «друзей контакта»
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
    В user — профиль ДРУГА (как ожидает фронт AddGroupMembersModal).
    """
    query = db.query(Friend).filter(Friend.user_id == current_user.id)
    if show_hidden is not None:
        query = query.filter(Friend.hidden == show_hidden)

    # стабильный порядок: по дате добавления (сначала более новые)
    total = query.count()
    friends = query.order_by(Friend.created_at.desc()).offset(offset).limit(limit).all()

    friend_ids = [f.friend_id for f in friends]
    profiles = db.query(User).filter(User.id.in_(friend_ids)).all() if friend_ids else []
    profiles_map = {u.id: u for u in profiles}

    result = []
    for link in friends:
        friend_profile = profiles_map.get(link.friend_id)
        result.append(
            FriendOut(
                id=link.id,
                user_id=link.user_id,
                friend_id=link.friend_id,
                created_at=link.created_at,
                updated_at=link.updated_at,
                hidden=link.hidden,
                user=UserOut.from_orm(friend_profile) if friend_profile else None,  # ДРУГ
                friend=UserOut.from_orm(current_user),                               # МЫ
            )
        )

    return {"total": total, "friends": result}


@router.post("/invite", response_model=FriendInviteOut)
def create_invite(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_telegram_user)
):
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
    invite = db.query(FriendInvite).filter_by(token=token).first()
    if not invite:
        raise HTTPException(404, detail={"code": "invite_not_found"})
    from_user_id = invite.from_user_id
    to_user_id = current_user.id
    if from_user_id == to_user_id:
        return {"success": True}

    exists = db.query(Friend).filter(
        Friend.user_id == from_user_id,
        Friend.friend_id == to_user_id
    ).first()
    if not exists:
        now = datetime.utcnow()
        db.add(Friend(user_id=from_user_id, friend_id=to_user_id, hidden=False, created_at=now, updated_at=now))
        db.add(Friend(user_id=to_user_id, friend_id=from_user_id, hidden=False, created_at=now, updated_at=now))
        db.commit()
        db.add(Event(actor_id=from_user_id, target_user_id=to_user_id, type="friend_added", data=None))
        db.add(Event(actor_id=to_user_id, target_user_id=from_user_id, type="friend_added", data=None))
        db.commit()

    usage = db.query(InviteUsage).filter_by(user_id=to_user_id).first()
    if not usage:
        db.add(InviteUsage(invite_id=invite.id, user_id=to_user_id))
        inviter = db.query(User).filter_by(id=from_user_id).first()
        if inviter:
            inviter.invited_friends_count += 1
            db.commit()
        db.add(Event(actor_id=from_user_id, target_user_id=to_user_id, type="invite_registered", data={"invite_id": invite.id}))
        db.add(Event(actor_id=to_user_id, target_user_id=from_user_id, type="invite_registered", data={"invite_id": invite.id}))
        db.commit()

    return {"success": True}


@router.post("/{friend_id}/hide", response_model=dict)
def hide_friend(
    friend_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_telegram_user)
):
    link = db.query(Friend).filter_by(user_id=current_user.id, friend_id=friend_id).first()
    if not link:
        raise HTTPException(404, detail="Friend not found")
    link.hidden = True
    link.updated_at = datetime.utcnow()
    db.commit()
    db.add(Event(actor_id=current_user.id, target_user_id=friend_id, type="friend_hidden", data=None))
    db.commit()
    return {"success": True}


@router.post("/{friend_id}/unhide", response_model=dict)
def unhide_friend(
    friend_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_telegram_user)
):
    link = db.query(Friend).filter_by(user_id=current_user.id, friend_id=friend_id).first()
    if not link:
        raise HTTPException(404, detail="Friend not found")
    link.hidden = False
    link.updated_at = datetime.utcnow()
    db.commit()
    db.add(Event(actor_id=current_user.id, target_user_id=friend_id, type="friend_unhidden", data=None))
    db.commit()
    return {"success": True}


@router.get("/invite/{token}/stats", response_model=dict)
def invite_stats(
    token: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_telegram_user)
):
    invite = db.query(FriendInvite).filter_by(token=token, from_user_id=current_user.id).first()
    if not invite:
        raise HTTPException(404, detail={"code": "invite_not_found"})
    usages = db.query(InviteUsage).filter_by(invite_id=invite.id).all()
    uses_count = len(usages)
    return {
        "uses_count": uses_count,
        "usages": [{"user_id": u.user_id, "used_at": u.used_at} for u in usages]
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
    Поиск среди МОИХ друзей (по username/first_name/last_name).
    В user — найденный ДРУГ (как ждёт фронт).
    """
    friend_ids_q = db.query(Friend.friend_id).filter(Friend.user_id == current_user.id)
    if show_hidden is not None:
        friend_ids_q = friend_ids_q.filter(Friend.hidden == show_hidden)
    friend_ids = [row[0] for row in friend_ids_q]

    sq = db.query(User).filter(
        User.id.in_(friend_ids),
        (User.username.ilike(f"%{query}%") |
         User.first_name.ilike(f"%{query}%") |
         User.last_name.ilike(f"%{query}%"))
    )
    total = sq.count()
    users = sq.order_by(User.first_name.asc(), User.last_name.asc(), User.username.asc()).offset(offset).limit(limit).all()

    if users:
        user_ids = [u.id for u in users]
        links = db.query(Friend).filter(Friend.user_id == current_user.id, Friend.friend_id.in_(user_ids)).all()
        link_map = {l.friend_id: l for l in links}
    else:
        link_map = {}

    result = []
    for user in users:
        link = link_map.get(user.id)
        if not link:
            continue
        result.append(
            FriendOut(
                id=link.id,
                user_id=link.user_id,
                friend_id=link.friend_id,
                created_at=link.created_at,
                updated_at=link.updated_at,
                hidden=link.hidden,
                user=UserOut.from_orm(user),            # ДРУГ
                friend=UserOut.from_orm(current_user),   # МЫ
            )
        )
    return {"total": total, "friends": result}

# ===== Детали контакта и связанные данные =====

@router.get("/{friend_id}", response_model=FriendOut)
def get_friend_detail(
    friend_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_telegram_user),
):
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
        user=UserOut.from_orm(contact),        # ДРУГ
        friend=UserOut.from_orm(current_user), # МЫ
    )


@router.get("/{friend_id}/common-groups", response_model=List[str])
def get_common_group_names(
    friend_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_telegram_user),
):
    my_group_ids = db.query(GroupMember.group_id).filter(GroupMember.user_id == current_user.id).subquery()
    his_group_ids = db.query(GroupMember.group_id).filter(GroupMember.user_id == friend_id).subquery()

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
    Друзья указанного пользователя (для вкладки «Друзья контакта»).
    Контракт фронта: ДРУГ -> user, Владелец списка -> friend.
    """
    q = db.query(Friend).filter(Friend.user_id == user_id)
    total = q.count()
    links = q.order_by(Friend.created_at.desc()).offset(offset).limit(limit).all()

    ids = [l.friend_id for l in links] + [user_id]
    profiles = db.query(User).filter(User.id.in_(set(ids))).all() if ids else []
    profiles_map = {u.id: u for u in profiles}
    owner = profiles_map.get(user_id)

    result = []
    for link in links:
        contact = profiles_map.get(link.friend_id)
        if not contact or not owner:
            continue
        result.append(
            FriendOut(
                id=link.id,
                user_id=link.user_id,
                friend_id=link.friend_id,
                created_at=link.created_at,
                updated_at=link.updated_at,
                hidden=link.hidden,
                user=UserOut.from_orm(contact),  # ДРУГ
                friend=UserOut.from_orm(owner),  # Владелец списка
            )
        )

    return {"total": total, "friends": result}
