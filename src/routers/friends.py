from fastapi import APIRouter, Depends, HTTPException, Body, Query
from sqlalchemy.orm import Session
from typing import List, Optional, Union
from src.db import get_db
from src.models.user import User
from src.models.friend import Friend
from src.models.friend_invite import FriendInvite
from src.models.invite_usage import InviteUsage
from src.models.event import Event
from src.schemas.friend import FriendOut, FriendCreate
from src.schemas.friend_invite import FriendInviteOut
from src.schemas.invite_usage import InviteUsageOut
from src.schemas.user import UserOut
from src.utils.telegram_dep import get_current_telegram_user
import secrets
from datetime import datetime

router = APIRouter(tags=["Друзья"])  # ← Только tags, prefix убран

@router.get("/", response_model=Union[List[FriendOut], dict])
def get_friends(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_telegram_user),
    show_hidden: Optional[bool] = False,
    offset: int = Query(0, ge=0),
    limit: Optional[int] = Query(None, gt=0)
):
    """
    Получить список друзей текущего пользователя.
    - Если не указаны offset/limit — возвращает весь список (старое поведение).
    - Если указаны — возвращает {"total": ..., "friends": [...]} (новое поведение для фронта с пагинацией).
    """
    query = db.query(Friend).filter(Friend.user_id == current_user.id)
    if show_hidden is not None:
        query = query.filter(Friend.hidden == show_hidden)
    total = query.count()

    if limit is not None:
        friends = query.offset(offset).limit(limit).all()
    else:
        friends = query.all()

    result = []
    for friend in friends:
        friend_profile = db.query(User).filter(User.id == friend.friend_id).first()
        result.append(
            FriendOut(
                id=friend.id,
                user_id=friend.user_id,
                friend_id=friend.friend_id,
                created_at=friend.created_at,
                updated_at=friend.updated_at,
                hidden=friend.hidden,
                user=UserOut.from_orm(friend_profile),
                friend=UserOut.from_orm(current_user)
            )
        )

    if limit is not None:
        return {"total": total, "friends": result}
    else:
        return result

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
    exists = db.query(Friend).filter(
        Friend.user_id == from_user_id,
        Friend.friend_id == to_user_id
    ).first()
    if not exists:
        now = datetime.utcnow()
        db.add(Friend(user_id=from_user_id, friend_id=to_user_id, hidden=False, created_at=now, updated_at=now))
        db.add(Friend(user_id=to_user_id, friend_id=from_user_id, hidden=False, created_at=now, updated_at=now))
        db.commit()
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
    usage = db.query(InviteUsage).filter_by(user_id=to_user_id).first()
    if not usage:
        db.add(InviteUsage(invite_id=invite.id, user_id=to_user_id))
        inviter = db.query(User).filter_by(id=from_user_id).first()
        if inviter:
            inviter.invited_friends_count += 1
            db.commit()
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
