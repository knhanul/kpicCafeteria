"""Tests for the order management (발주 관리) API."""
from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db import Base
from app.models import (
    Ingredient,
    MealService,
    MealServiceMenu,
    MealServiceMenuIngredient,
    MealTypeSetting,
    Menu,
    OrderItem,
    User,
)
from app.routers.orders import (
    BulkUpdateBody,
    OrderGroupBody,
    OrderItemBody,
    OrderItemsSaveBody,
    bulk_update_items,
    create_order_group,
    list_orders,
    save_order_items,
)
from app.schema_upgrade import upgrade_existing_schema


def make_db() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    upgrade_existing_schema(engine)
    return Session(engine, expire_on_commit=False)


def make_user(db: Session) -> User:
    user = User(username="tester", password_hash="x", display_name="Tester", active=True)
    db.add(user)
    db.flush()
    return user


def make_meal_type(db: Session, code="LUNCH", name="중식") -> MealTypeSetting:
    setting = MealTypeSetting(code=code, name=name, default_planned_count=100, active=True)
    db.add(setting)
    db.flush()
    return setting


def make_ingredient(db: Session, name="대파", unit="kg") -> Ingredient:
    ing = Ingredient(name=name, stat_group="채소", default_unit=unit, active=True)
    db.add(ing)
    db.flush()
    return ing


def make_service(db: Session, service_date: date, planned_count=100) -> MealService:
    svc = MealService(service_date=service_date, meal_type="LUNCH", planned_count=planned_count)
    db.add(svc)
    db.flush()
    return svc


def make_menu(db: Session, name="육개장") -> Menu:
    menu = Menu(name=name, canonical_name=name, role="주찬", active=True)
    db.add(menu)
    db.flush()
    return menu


def add_ingredient_to_service(
    db: Session,
    service: MealService,
    menu: Menu,
    ingredient: Ingredient,
    quantity_total: float,
    unit: str = "kg",
) -> None:
    sm = MealServiceMenu(
        meal_service_id=service.id,
        menu_id=menu.id,
        menu_name_snapshot=menu.name,
        sort_order=1,
    )
    db.add(sm)
    db.flush()
    db.add(
        MealServiceMenuIngredient(
            meal_service_menu_id=sm.id,
            ingredient_id=ingredient.id,
            ingredient_name_snapshot=ingredient.name,
            quantity_total=quantity_total,
            quantity_per_100=quantity_total * 100 / service.planned_count,
            unit=unit,
        )
    )
    db.flush()


def test_list_orders_aggregates_same_date_same_ingredient():
    db = make_db()
    user = make_user(db)
    make_meal_type(db)
    ing = make_ingredient(db)
    menu1 = make_menu(db, "육개장")
    menu2 = make_menu(db, "잡채")
    svc = make_service(db, date(2025, 1, 1))
    add_ingredient_to_service(db, svc, menu1, ing, 8.0)
    add_ingredient_to_service(db, svc, menu2, ing, 4.0)

    result = list_orders(date(2025, 1, 1), date(2025, 1, 3), db, user)
    assert len(result["items"]) == 1
    item = result["items"][0]
    assert item["ingredient_name"] == "대파"
    assert item["required_quantity"] == 12.0
    assert item["required_unit"] == "kg"
    assert item["order_quantity"] == 12.0  # default = required
    assert item["status"] == "pending"
    assert item["in_plan"] is True
    assert len(item["menus"]) == 2
    assert {m["menu_name"] for m in item["menus"]} == {"육개장", "잡채"}
    assert all(m["service_date"] == "2025-01-01" for m in item["menus"])
    assert all(m["meal_type"] == "LUNCH" for m in item["menus"])
    assert all(m["meal_type_name"] == "중식" for m in item["menus"])


def test_list_orders_mixed_id_and_name_keys_do_not_crash():
    """ingredient-linked rows (int key) and name-keyed rows (str key) must sort together."""
    db = make_db()
    user = make_user(db)
    make_meal_type(db)
    ing = make_ingredient(db)
    menu = make_menu(db)
    svc = make_service(db, date(2025, 1, 1))
    sm = MealServiceMenu(
        meal_service_id=svc.id,
        menu_id=menu.id,
        menu_name_snapshot=menu.name,
        sort_order=1,
    )
    db.add(sm)
    db.flush()
    # ingredient-linked row
    db.add(
        MealServiceMenuIngredient(
            meal_service_menu_id=sm.id,
            ingredient_id=ing.id,
            ingredient_name_snapshot=ing.name,
            quantity_total=5.0,
            unit="kg",
        )
    )
    # name-keyed row (ingredient deleted -> ingredient_id is NULL)
    db.add(
        MealServiceMenuIngredient(
            meal_service_menu_id=sm.id,
            ingredient_id=None,
            ingredient_name_snapshot="삭제된재료",
            quantity_total=3.0,
            unit="kg",
        )
    )
    db.flush()

    result = list_orders(date(2025, 1, 1), date(2025, 1, 3), db, user)
    assert len(result["items"]) == 2
    names = sorted(i["ingredient_name"] for i in result["items"])
    assert names == ["대파", "삭제된재료"]


def test_list_orders_separate_rows_per_date():
    db = make_db()
    user = make_user(db)
    ing = make_ingredient(db)
    menu = make_menu(db)
    svc1 = make_service(db, date(2025, 1, 1))
    svc2 = make_service(db, date(2025, 1, 3))
    add_ingredient_to_service(db, svc1, menu, ing, 10.0)
    add_ingredient_to_service(db, svc2, menu, ing, 7.0)

    result = list_orders(date(2025, 1, 1), date(2025, 1, 3), db, user)
    assert len(result["items"]) == 2
    quantities = sorted(i["required_quantity"] for i in result["items"])
    assert quantities == [7.0, 10.0]
    # Default order date = day before service date
    by_date = {i["service_date"]: i for i in result["items"]}
    assert by_date["2025-01-01"]["order_date"] == "2024-12-31"
    assert by_date["2025-01-01"]["delivery_date"] == "2025-01-01"


def test_save_order_items_upserts_and_preserves_user_input():
    db = make_db()
    user = make_user(db)
    ing = make_ingredient(db)
    menu = make_menu(db)
    svc = make_service(db, date(2025, 1, 1))
    add_ingredient_to_service(db, svc, menu, ing, 12.0)

    # User edits order quantity/date/status
    save_order_items(
        OrderItemsSaveBody(
            items=[
                OrderItemBody(
                    service_date=date(2025, 1, 1),
                    ingredient_id=ing.id,
                    ingredient_name="대파",
                    required_quantity=12.0,
                    required_unit="kg",
                    order_quantity=15.0,
                    order_unit="kg",
                    order_date=date(2025, 1, 1),
                    delivery_date=date(2025, 1, 2),
                    status="ordered",
                )
            ]
        ),
        db,
        user,
    )
    stored = db.query(OrderItem).one()
    assert stored.order_quantity == 15.0
    assert stored.status == "ordered"

    # Plan changes required quantity; user fields must be preserved
    add_ingredient_to_service(db, svc, menu, ing, 3.0)  # now 15.0 required
    result = list_orders(date(2025, 1, 1), date(2025, 1, 3), db, user)
    item = result["items"][0]
    assert item["required_quantity"] == 15.0
    assert item["order_quantity"] == 15.0
    assert item["status"] == "ordered"
    assert item["order_date"] == "2025-01-01"


def test_stored_item_outside_plan_is_kept():
    db = make_db()
    user = make_user(db)
    ing = make_ingredient(db)
    menu = make_menu(db)
    svc = make_service(db, date(2025, 1, 1))
    add_ingredient_to_service(db, svc, menu, ing, 12.0)

    save_order_items(
        OrderItemsSaveBody(
            items=[
                OrderItemBody(
                    service_date=date(2025, 1, 1),
                    ingredient_id=ing.id,
                    ingredient_name="대파",
                    required_quantity=12.0,
                    required_unit="kg",
                    order_quantity=15.0,
                    order_unit="kg",
                    order_date=date(2025, 1, 1),
                    delivery_date=date(2025, 1, 2),
                    status="ordered",
                )
            ]
        ),
        db,
        user,
    )
    # Remove the ingredient from the meal plan
    db.query(MealServiceMenuIngredient).delete()
    db.commit()

    result = list_orders(date(2025, 1, 1), date(2025, 1, 3), db, user)
    assert len(result["items"]) == 1
    item = result["items"][0]
    assert item["in_plan"] is False
    assert item["order_quantity"] == 15.0
    assert item["status"] == "ordered"


def test_create_order_group_links_rows_and_marks_ordered():
    db = make_db()
    user = make_user(db)
    ing = make_ingredient(db)
    menu = make_menu(db)
    svc1 = make_service(db, date(2025, 1, 1))
    svc2 = make_service(db, date(2025, 1, 3))
    add_ingredient_to_service(db, svc1, menu, ing, 10.0)
    add_ingredient_to_service(db, svc2, menu, ing, 7.0)

    # Persist rows first (as the UI does on save)
    save_order_items(
        OrderItemsSaveBody(
            items=[
                OrderItemBody(
                    service_date=date(2025, 1, 1), ingredient_id=ing.id, ingredient_name="대파",
                    required_quantity=10.0, required_unit="kg", order_quantity=10.0, order_unit="kg",
                    order_date=date(2024, 12, 31), delivery_date=date(2025, 1, 1), status="pending",
                ),
                OrderItemBody(
                    service_date=date(2025, 1, 3), ingredient_id=ing.id, ingredient_name="대파",
                    required_quantity=7.0, required_unit="kg", order_quantity=7.0, order_unit="kg",
                    order_date=date(2025, 1, 2), delivery_date=date(2025, 1, 3), status="pending",
                ),
            ]
        ),
        db,
        user,
    )

    result = create_order_group(
        OrderGroupBody(
            items=[
                OrderItemBody(
                    service_date=date(2025, 1, 1), ingredient_id=ing.id, ingredient_name="대파",
                    required_quantity=10.0, required_unit="kg", order_quantity=10.0, order_unit="kg",
                    order_date=date(2024, 12, 31), delivery_date=date(2025, 1, 1), status="pending",
                ),
                OrderItemBody(
                    service_date=date(2025, 1, 3), ingredient_id=ing.id, ingredient_name="대파",
                    required_quantity=7.0, required_unit="kg", order_quantity=7.0, order_unit="kg",
                    order_date=date(2025, 1, 2), delivery_date=date(2025, 1, 3), status="pending",
                ),
            ],
            order_quantity=18.0,
            order_unit="kg",
            order_date=date(2024, 12, 31),
            delivery_date=date(2025, 1, 1),
        ),
        db,
        user,
    )
    assert result["ok"] is True

    rows = db.query(OrderItem).all()
    assert len(rows) == 2
    assert all(r.order_group_id == result["group_id"] for r in rows)
    assert all(r.status == "ordered" for r in rows)
    assert all(r.order_date == date(2024, 12, 31) for r in rows)


def test_bulk_update_status_and_dates():
    db = make_db()
    user = make_user(db)
    ing1 = make_ingredient(db, "대파")
    ing2 = make_ingredient(db, "양파")
    menu = make_menu(db)
    svc = make_service(db, date(2025, 1, 1))
    add_ingredient_to_service(db, svc, menu, ing1, 5.0)
    add_ingredient_to_service(db, svc, menu, ing2, 3.0)

    save_order_items(
        OrderItemsSaveBody(
            items=[
                OrderItemBody(
                    service_date=date(2025, 1, 1), ingredient_id=ing1.id, ingredient_name="대파",
                    required_quantity=5.0, required_unit="kg", order_quantity=5.0, order_unit="kg",
                    order_date=date(2024, 12, 31), delivery_date=date(2025, 1, 1), status="pending",
                ),
                OrderItemBody(
                    service_date=date(2025, 1, 1), ingredient_id=ing2.id, ingredient_name="양파",
                    required_quantity=3.0, required_unit="kg", order_quantity=3.0, order_unit="kg",
                    order_date=date(2024, 12, 31), delivery_date=date(2025, 1, 1), status="pending",
                ),
            ]
        ),
        db,
        user,
    )

    result = bulk_update_items(
        BulkUpdateBody(
            items=[
                OrderItemBody(
                    service_date=date(2025, 1, 1), ingredient_id=ing1.id, ingredient_name="대파",
                    required_quantity=5.0, required_unit="kg", order_quantity=5.0, order_unit="kg",
                    order_date=date(2024, 12, 31), delivery_date=date(2025, 1, 1), status="pending",
                ),
                OrderItemBody(
                    service_date=date(2025, 1, 1), ingredient_id=ing2.id, ingredient_name="양파",
                    required_quantity=3.0, required_unit="kg", order_quantity=3.0, order_unit="kg",
                    order_date=date(2024, 12, 31), delivery_date=date(2025, 1, 1), status="pending",
                ),
            ],
            order_date=date(2025, 1, 2),
            status="skipped",
        ),
        db,
        user,
    )
    assert result["updated"] == 2
    rows = db.query(OrderItem).all()
    assert all(r.status == "skipped" for r in rows)
    assert all(r.order_date == date(2025, 1, 2) for r in rows)
