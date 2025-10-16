# src/routers/friends.py
from fastapi import APIRouter, Depends, HTTPException, Body, Query
from sqlalchemy.orm import Session
from sqlalchemy import or_, and_
from typing import List, Optional, Dict
from datetime import datetime
import secrets

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

# Для общих групп
from src.models.group_member import GroupMember
from src.models.group import Group

# >>> добавлено: используем общий логгер событий и константу типа
from src.services.events import log_event, FRIENDSHIP_CREATED

router = APIRouter(tags=["Друзья"])


# =========================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# =========================

def _pair_min_max(a: int, b: int) -> (int, int):
    return (a, b) if a < b else (b, a)


def _hidden_for_viewer(link: Friend, viewer_id: int) -> bool:
    """Вернуть персональный флаг hidden для конкретного пользователя."""
    if viewer_id == link.user_min:
        return bool(link.hidden_by_min)
    if viewer_id == link.user_max:
        return bool(link.hidden_by_max)
    # Если вдруг передали неучастника (не должно случиться)
    return False


def _other_id(link: Friend, viewer_id: int) -> int:
    """Вернуть id 'второй стороны' дружбы относительно viewer_id."""
    return link.user_max if viewer_id == link.user_min else link.user_min


def _filter_by_viewer_and_hidden(db: Session, viewer_id: int, show_hidden: Optional[bool]):
    """
    Построить базовый запрос дружб пользователя с фильтром по персональному hidden.
    show_hidden:
      - True  -> оставить только скрытых именно для viewer_id
      - False -> оставить только НЕ скрытых для viewer_id
      - None  -> не фильтровать по hidden
    """
    base = db.query(Friend).filter(or_(Friend.user_min == viewer_id, Friend.user_max == viewer_id))
    if show_hidden is None:
        return base

    # Персональный фильтр hidden-by-<side>
    return base.filter(or_(
        and_(Friend.user_min == viewer_id, Friend.hidden_by_min == show_hidden),
        and_(Friend.user_max == viewer_id, Friend.hidden_by_max == show_hidden),
    ))


def _build_friend_out_list(
    links: List[Friend],
    profiles_map: Dict[int, User],
    owner: User,
) -> List[FriendOut]:
    """
    Сконструировать FriendOut[]: user -> профиль друга, friend -> профиль владельца списка.
    hidden -> персональный флаг скрытия для владельца списка.
    """
    result: List[FriendOut] = []
    for link in links:
        other = profiles_map.get(_other_id(link, owner.id))
        if not other:
            # Профиль мог не подтянуться, пропустим строку чтобы не ломать фронт
            continue
        result.append(
            FriendOut(
                id=link.id,
                user_id=owner.id,           # Владелец списка (Я)
                friend_id=other.id,         # Друг
                created_at=link.created_at,
                updated_at=link.updated_at,
                hidden=_hidden_for_viewer(link, owner.id),
                user=UserOut.from_orm(other),   # ДРУГ
                friend=UserOut.from_orm(owner), # Владелец/текущий пользователь
            )
        )
    return result


# =========================
# ЭНДПОИНТЫ
# =========================

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
    Формат фронта: в поле 'user' лежит профиль ДРУГА.
    """
    base = _filter_by_viewer_and_hidden(db, current_user.id, show_hidden)
    total = base.count()

    links = (
        base.order_by(Friend.created_at.desc())
        .offset(offset).limit(limit)
        .all()
    )

    friend_ids = [_other_id(l, current_user.id) for l in links]
    profiles = db.query(User).filter(User.id.in_(friend_ids)).all() if friend_ids else []
    profiles_map = {u.id: u for u in profiles}

    return {"total": total, "friends": _build_friend_out_list(links, profiles_map, current_user)}


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

    umin, umax = _pair_min_max(from_user_id, to_user_id)
    link = db.query(Friend).filter(Friend.user_min == umin, Friend.user_max == umax).first()

    now = datetime.utcnow()
    created_now = False
    if not link:
        # Создаём одну строку на пару
        link = Friend(
            user_min=umin, user_max=umax,
            hidden_by_min=False, hidden_by_max=False,
            created_at=now, updated_at=now,
            # Legacy-зеркало (необязательно, но полезно на переходный период):
            user_id=umin, friend_id=umax, hidden=False,
        )
        db.add(link)
        db.commit()
        created_now = True

        # >>> изменено: пишем современное событие дружбы через общий логгер (идемпотентно)
        log_event(
            db,
            type=FRIENDSHIP_CREATED,
            actor_id=from_user_id,
            target_user_id=to_user_id,
            idempotency_key=f"friendship_created:{umin}:{umax}",
        )
        db.commit()
    else:
        # Уже дружим: снимем скрытие для обоих (на случай, если кто-то скрывал ранее)
        if link.hidden_by_min or link.hidden_by_max:
            link.hidden_by_min = False
            link.hidden_by_max = False
            link.hidden = False  # legacy: ведём как "не скрыт"
            link.updated_at = now
            db.commit()
        # События о повторном принятии инвайта не пишем, чтобы не спамить.

    # Учёт использования инвайта (как было)
    usage = db.query(InviteUsage).filter_by(user_id=to_user_id).first()
    if not usage:
        db.add(InviteUsage(invite_id=invite.id, user_id=to_user_id))
        inviter = db.query(User).filter_by(id=from_user_id).first()
        if inviter:
            inviter.invited_friends_count += 1
            db.commit()
        db.add(Event(actor_id=from_user_id, target_user_id=to_user_id,
                     type="invite_registered", data={"invite_id": invite.id}))
        db.add(Event(actor_id=to_user_id, target_user_id=from_user_id,
                     type="invite_registered", data={"invite_id": invite.id}))
        db.commit()

    return {"success": True, "created": created_now}


@router.post("/{friend_id}/hide", response_model=dict)
def hide_friend(
    friend_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_telegram_user)
):
    umin, umax = _pair_min_max(current_user.id, friend_id)
    link = db.query(Friend).filter(Friend.user_min == umin, Friend.user_max == umax).first()
    if not link:
        raise HTTPException(404, detail="Friend not found")

    now = datetime.utcnow()
    if current_user.id == link.user_min:
        link.hidden_by_min = True
    else:
        link.hidden_by_max = True
    # Legacy: общий hidden ведём как "скрыт кем-то" (для старого кода вне этого роутера)
    link.hidden = bool(link.hidden_by_min or link.hidden_by_max)
    link.updated_at = now
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
    umin, umax = _pair_min_max(current_user.id, friend_id)
    link = db.query(Friend).filter(Friend.user_min == umin, Friend.user_max == umax).first()
    if not link:
        raise HTTPException(404, detail="Friend not found")

    now = datetime.utcnow()
    if current_user.id == link.user_min:
        link.hidden_by_min = False
    else:
        link.hidden_by_max = False

    link.hidden = bool(link.hidden_by_min or link.hidden_by_max)  # legacy
    link.updated_at = now
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
    В поле 'user' — найденный ДРУГ (как ждёт фронт).
    Персональный фильтр hidden учитывается.
    """
    base = _filter_by_viewer_and_hidden(db, current_user.id, show_hidden)
    links = base.all()
    friend_ids = [_other_id(l, current_user.id) for l in links]
    if not friend_ids:
        return {"total": 0, "friends": []}

    sq = db.query(User).filter(
        User.id.in_(friend_ids),
        (User.username.ilike(f"%{query}%") |
         User.first_name.ilike(f"%{query}%") |
         User.last_name.ilike(f"%{query}%"))
    )

    total = sq.count()
    users = (
        sq.order_by(User.first_name.asc(), User.last_name.asc(), User.username.asc())
        .offset(offset).limit(limit)
        .all()
    )

    # Сопоставим user_id -> link, чтобы получить hidden и даты
    links_map = {_other_id(l, current_user.id): l for l in links}
    profiles_map = {u.id: u for u in users}

    result = []
    for uid, profile in profiles_map.items():
        link = links_map.get(uid)
        if not link:
            continue
        result.append(
            FriendOut(
                id=link.id,
                user_id=current_user.id,       # Я — владелец списка
                friend_id=uid,                 # Найденный друг
                created_at=link.created_at,
                updated_at=link.updated_at,
                hidden=_hidden_for_viewer(link, current_user.id),
                user=UserOut.from_orm(profile),          # ДРУГ
                friend=UserOut.from_orm(current_user),   # МЫ
            )
        )
    return {"total": total, "friends": result}


@router.get("/{friend_id}", response_model=FriendOut)
def get_friend_detail(
    friend_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_telegram_user),
):
    """
    Детали ДРУГА (строгая проверка, что friend_id — действительно ваш друг).
    """
    umin, umax = _pair_min_max(current_user.id, friend_id)
    link = db.query(Friend).filter(Friend.user_min == umin, Friend.user_max == umax).first()
    if not link:
        raise HTTPException(404, detail="Friend not found")

    contact = db.query(User).filter_by(id=friend_id).first()
    if not contact:
        raise HTTPException(404, detail="User not found")

    return FriendOut(
        id=link.id,
        user_id=current_user.id,      # Я
        friend_id=friend_id,          # Друг
        created_at=link.created_at,
        updated_at=link.updated_at,
        hidden=_hidden_for_viewer(link, current_user.id),
        user=UserOut.from_orm(contact),        # ДРУГ
        friend=UserOut.from_orm(current_user), # МЫ
    )


@router.get("/{friend_id}/common-groups", response_model=List[str])
def get_common_group_names(
    friend_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_telegram_user),
):
    """
    Названия общих групп. Работает и для НЕ-друзей (по user_id).
    """
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
    base = db.query(Friend).filter(or_(Friend.user_min == user_id, Friend.user_max == user_id))

    total = base.count()
    links = (
        base.order_by(Friend.created_at.desc())
        .offset(offset).limit(limit)
        .all()
    )

    ids = {_other_id(l, user_id) for l in links} | {user_id}
    profiles = db.query(User).filter(User.id.in_(ids)).all() if ids else []
    profiles_map = {u.id: u for u in profiles}
    owner = profiles_map.get(user_id)

    result = []
    for link in links:
        contact = profiles_map.get(_other_id(link, user_id))
        if not contact or not owner:
            continue
        result.append(
            FriendOut(
                id=link.id,
                user_id=owner.id,         # Владелец списка
                friend_id=contact.id,     # Его друг
                created_at=link.created_at,
                updated_at=link.updated_at,
                hidden=_hidden_for_viewer(link, user_id),
                user=UserOut.from_orm(contact),  # ДРУГ
                friend=UserOut.from_orm(owner),  # Владелец списка
            )
        )

    return {"total": total, "friends": result}


@router.get("/user/{user_id}", response_model=UserOut)
def get_user_profile_public(
    user_id: int,
    db: Session = Depends(get_db),
    _current_user: User = Depends(get_current_telegram_user),
):
    """
    Публичный профиль по user_id (минимум данных).
    НЕ требует отношения дружбы.
    """
    user = db.query(User).filter_by(id=user_id).first()
    if not user:
        raise HTTPException(404, detail="User not found")
    return UserOut.from_orm(user)
