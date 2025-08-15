# scripts/seed_expense_categories.py
# СИДЕР (idempotent): пишет 8 топ-категорий и подкатегории.
# Ожидаем схему expense_categories: key, parent_id, icon, color, name_i18n(JSONB), is_active, created_at, updated_at.
# Апсерт по key. Повторный запуск обновляет icon/color/name_i18n.

import os
import sys
from typing import Dict

from sqlalchemy import create_engine, MetaData, Table, select
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

DATA = [
    {
        "key": "food_drinks",
        "icon": "🍽️",
        "color": "#F97316",
        "name_i18n": {"ru": "Еда и напитки", "en": "Food & Drinks", "es": "Comida y bebidas"},
        "children": [
            {"key": "groceries", "icon": "🛒", "name_i18n": {"ru": "Продукты", "en": "Groceries", "es": "Supermercado"}},
            {"key": "cafes_restaurants", "icon": "🍔", "name_i18n": {"ru": "Кафе и рестораны", "en": "Cafes & Restaurants", "es": "Cafés y restaurantes"}},
            {"key": "food_delivery", "icon": "🚚", "name_i18n": {"ru": "Доставка еды", "en": "Food Delivery", "es": "Entrega de comida"}},
            {"key": "coffee_tea", "icon": "☕", "name_i18n": {"ru": "Кофе и чай", "en": "Coffee & Tea", "es": "Café y té"}},
            {"key": "bars_clubs", "icon": "🪩", "name_i18n": {"ru": "Бары и клубы", "en": "Bars & Clubs", "es": "Bares y clubes"}},
            {"key": "alcohol", "icon": "🍻", "name_i18n": {"ru": "Алкоголь", "en": "Alcohol", "es": "Alcohol"}},
            {"key": "snacks_sweets", "icon": "🍫", "name_i18n": {"ru": "Снэки и сладости", "en": "Snacks & Sweets", "es": "Aperitivos y dulces"}},
            {"key": "tips", "icon": "💸", "name_i18n": {"ru": "Чаевые", "en": "Tips", "es": "Propinas"}},
        ],
    },
    {
        "key": "transport",
        "icon": "🚗",
        "color": "#3B82F6",
        "name_i18n": {"ru": "Транспорт", "en": "Transport", "es": "Transporte"},
        "children": [
            {"key": "public_transport", "icon": "🚌", "name_i18n": {"ru": "Общественный транспорт", "en": "Public Transport", "es": "Transporte público"}},
            {"key": "taxi", "icon": "🚕", "name_i18n": {"ru": "Такси", "en": "Taxi", "es": "Taxi"}},
            {"key": "fuel", "icon": "⛽", "name_i18n": {"ru": "Топливо", "en": "Fuel", "es": "Combustible"}},
            {"key": "parking", "icon": "🅿️", "name_i18n": {"ru": "Парковка", "en": "Parking", "es": "Estacionamiento"}},
            {"key": "maintenance_repair", "icon": "🔧", "name_i18n": {"ru": "ТО и ремонт", "en": "Maintenance & Repair", "es": "Mantenimiento y reparación"}},
            {"key": "carsharing", "icon": "🚘", "name_i18n": {"ru": "Каршеринг", "en": "Carsharing", "es": "Coche compartido"}},
            {"key": "fines", "icon": "🚨", "name_i18n": {"ru": "Штрафы", "en": "Fines", "es": "Multas"}},
        ],
    },
    {
        "key": "housing_utilities",
        "icon": "🏠",
        "color": "#10B981",
        "name_i18n": {"ru": "Жильё и коммуналка", "en": "Housing & Utilities", "es": "Hogar y servicios"},
        "children": [
            {"key": "rent_mortgage", "icon": "🔑", "name_i18n": {"ru": "Аренда/ипотека", "en": "Rent/Mortgage", "es": "Alquiler/hipoteca"}},
            {"key": "utilities", "icon": "💡", "name_i18n": {"ru": "Коммунальные услуги", "en": "Utilities", "es": "Servicios públicos"}},
            {"key": "home_internet", "icon": "🌐", "name_i18n": {"ru": "Домашний интернет", "en": "Home Internet", "es": "Internet en casa"}},
            {"key": "furniture_appliances", "icon": "🛋️", "name_i18n": {"ru": "Мебель и техника", "en": "Furniture & Appliances", "es": "Muebles y electrodomésticos"}},
            {"key": "renovation_materials", "icon": "🛠️", "name_i18n": {"ru": "Ремонт и материалы", "en": "Renovation & Materials", "es": "Reformas y materiales"}},
            {"key": "cleaning", "icon": "🧹", "name_i18n": {"ru": "Уборка и клининг", "en": "Cleaning", "es": "Limpieza"}},
        ],
    },
    {
        "key": "entertainment_subscriptions",
        "icon": "🎬",
        "color": "#A855F7",
        "name_i18n": {"ru": "Развлечения и подписки", "en": "Entertainment & Subscriptions", "es": "Entretenimiento y suscripciones"},
        "children": [
            {"key": "cinema_theatre", "icon": "🎭", "name_i18n": {"ru": "Кино и театр", "en": "Cinema & Theatre", "es": "Cine y teatro"}},
            {"key": "video_music_subs", "icon": "📺", "name_i18n": {"ru": "Подписки (видео/музыка)", "en": "Video/Music Subscriptions", "es": "Suscripciones (video/música)"}},
            {"key": "games", "icon": "🎮", "name_i18n": {"ru": "Игры", "en": "Games", "es": "Videojuegos"}},
            {"key": "concerts_events", "icon": "🎟️", "name_i18n": {"ru": "Концерты и мероприятия", "en": "Concerts & Events", "es": "Conciertos y eventos"}},
            {"key": "books_audiobooks", "icon": "📚", "name_i18n": {"ru": "Книги и аудиокниги", "en": "Books & Audiobooks", "es": "Libros y audiolibros"}},
            {"key": "museums_exhibitions", "icon": "🖼️", "name_i18n": {"ru": "Музеи и выставки", "en": "Museums & Exhibitions", "es": "Museos y exposiciones"}},
        ],
    },
    {
        "key": "health_fitness",
        "icon": "🩺",
        "color": "#EF4444",
        "name_i18n": {"ru": "Здоровье и спорт", "en": "Health & Fitness", "es": "Salud y fitness"},
        "children": [
            {"key": "medicine", "icon": "💊", "name_i18n": {"ru": "Лекарства", "en": "Medicines", "es": "Medicamentos"}},
            {"key": "doctor_clinics", "icon": "🏥", "name_i18n": {"ru": "Врач и клиники", "en": "Doctor & Clinics", "es": "Médico y clínicas"}},
            {"key": "dentist", "icon": "🦷", "name_i18n": {"ru": "Стоматолог", "en": "Dentist", "es": "Dentista"}},
            {"key": "health_insurance", "icon": "🛡️", "name_i18n": {"ru": "Страховка здоровья", "en": "Health Insurance", "es": "Seguro de salud"}},
            {"key": "gym_membership", "icon": "🏋️", "name_i18n": {"ru": "Фитнес-абонемент", "en": "Gym Membership", "es": "Membresía de gimnasio"}},
            {"key": "sports_equipment", "icon": "🥊", "name_i18n": {"ru": "Спортинвентарь", "en": "Sports Equipment", "es": "Equipo deportivo"}},
        ],
    },
    {
        "key": "travel",
        "icon": "✈️",
        "color": "#06B6D4",
        "name_i18n": {"ru": "Путешествия", "en": "Travel", "es": "Viajes"},
        "children": [
            {"key": "flights", "icon": "✈️", "name_i18n": {"ru": "Авиабилеты", "en": "Flights", "es": "Vuelos"}},
            {"key": "train_bus", "icon": "🚆", "name_i18n": {"ru": "Поезд/автобус", "en": "Train/Bus", "es": "Tren/autobús"}},
            {"key": "hotel", "icon": "🏨", "name_i18n": {"ru": "Отель", "en": "Hotel", "es": "Hotel"}},
            {"key": "car_rental", "icon": "🚗", "name_i18n": {"ru": "Аренда авто", "en": "Car Rental", "es": "Alquiler de coche"}},
            {"key": "travel_insurance", "icon": "🧳", "name_i18n": {"ru": "Страховка в поездке", "en": "Travel Insurance", "es": "Seguro de viaje"}},
            {"key": "transfers", "icon": "🚐", "name_i18n": {"ru": "Трансферы", "en": "Transfers", "es": "Traslados"}},
        ],
    },
    {
        "key": "shopping_household",
        "icon": "🛍️",
        "color": "#F59E0B",
        "name_i18n": {"ru": "Покупки и быт", "en": "Shopping & Household", "es": "Compras y hogar"},
        "children": [
            {"key": "clothes_shoes", "icon": "👟", "name_i18n": {"ru": "Одежда и обувь", "en": "Clothes & Shoes", "es": "Ropa y calzado"}},
            {"key": "electronics", "icon": "💻", "name_i18n": {"ru": "Электроника", "en": "Electronics", "es": "Electrónica"}},
            {"key": "home_goods", "icon": "🧴", "name_i18n": {"ru": "Товары для дома", "en": "Home Goods", "es": "Artículos para el hogar"}},
            {"key": "stationery_print", "icon": "✏️", "name_i18n": {"ru": "Канцтовары и печать", "en": "Stationery & Print", "es": "Papelería e impresión"}},
            {"key": "gifts", "icon": "🎁", "name_i18n": {"ru": "Подарки", "en": "Gifts", "es": "Regalos"}},
            {"key": "marketplaces", "icon": "📦", "name_i18n": {"ru": "Маркетплейсы", "en": "Marketplaces", "es": "Marketplaces"}},
        ],
    },
    {
        "key": "finance_services",
        "icon": "🏦",
        "color": "#64748B",
        "name_i18n": {"ru": "Финансы и услуги", "en": "Finance & Services", "es": "Finanzas y servicios"},
        "children": [
            {"key": "bank_fees", "icon": "💳", "name_i18n": {"ru": "Банковские комиссии", "en": "Bank Fees", "es": "Comisiones bancarias"}},
            {"key": "account_maintenance", "icon": "🧾", "name_i18n": {"ru": "Обслуживание счёта", "en": "Account Maintenance", "es": "Mantenimiento de cuenta"}},
            {"key": "transfers_exchange", "icon": "🔁", "name_i18n": {"ru": "Переводы и конвертация", "en": "Transfers & FX", "es": "Transferencias y cambio"}},
            {"key": "taxes", "icon": "💰", "name_i18n": {"ru": "Налоги", "en": "Taxes", "es": "Impuestos"}},
            {"key": "duties_fees", "icon": "🏛️", "name_i18n": {"ru": "Пошлины/госплатежи", "en": "Duties & Gov. Fees", "es": "Tasas y pagos gubernamentales"}},
            {"key": "insurances", "icon": "🛡️", "name_i18n": {"ru": "Страховки", "en": "Insurances", "es": "Seguros"}},
        ],
    },
]


def upsert(engine: Engine, table: Table, row: dict, parent_id: int | None) -> int:
    with engine.begin() as conn:
        existing = conn.execute(select(table.c.id).where(table.c.key == row["key"])).fetchone()
        values = {
            "key": row["key"],
            "parent_id": parent_id,
            "icon": row.get("icon"),
            "color": row.get("color"),
            "name_i18n": row["name_i18n"],
            "is_active": True,
        }
        if existing:
            conn.execute(table.update().where(table.c.id == existing[0]).values(**values))
            return int(existing[0])
        res = conn.execute(table.insert().values(**values).returning(table.c.id))
        return int(res.scalar_one())


def main():
    url = os.getenv("DATABASE_URL")
    if not url:
        print("export DATABASE_URL=postgresql+psycopg2://user:pass@host:5432/db && python scripts/seed_expense_categories.py")
        sys.exit(2)
    engine = create_engine(url)
    meta = MetaData()
    try:
        ec = Table("expense_categories", meta, autoload_with=engine)
    except SQLAlchemyError as e:
        print("[ERROR] Нет таблицы expense_categories или не та схема:", e)
        sys.exit(2)

    # Сначала топы, потом дети
    top_ids: Dict[str, int] = {}
    for top in DATA:
        top_ids[top["key"]] = upsert(engine, ec, top, None)
    for top in DATA:
        pid = top_ids[top["key"]]
        for child in top["children"]:
            upsert(engine, ec, child, pid)

    print("OK: посеяны 8 топ-категорий и подкатегории.")

if __name__ == "__main__":
    main()
