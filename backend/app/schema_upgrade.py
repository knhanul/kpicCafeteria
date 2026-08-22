from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine


def upgrade_existing_schema(engine: Engine) -> None:
    """Small in-place compatibility upgrade for the previous full-source release.

    Fresh databases are handled by SQLAlchemy metadata. PostgreSQL deployments made
    from the previous release need the one-recipe-per-menu unique constraint removed
    before the new multi-recipe model can be used.
    """
    inspector = inspect(engine)
    dialect = engine.dialect.name

    # --- User table migration (runs even if recipes table doesn't exist yet) ---
    if "users" in inspector.get_table_names():
        user_cols = {col["name"] for col in inspector.get_columns("users")}
        user_additions_pg = {
            "role": "VARCHAR(20) DEFAULT 'user'",
            "must_change_password": "BOOLEAN DEFAULT FALSE",
            "password_changed_at": "TIMESTAMPTZ",
            "last_login_at": "TIMESTAMPTZ",
            "updated_at": "TIMESTAMPTZ",
        }
        user_additions_sqlite = {
            "role": "VARCHAR(20) DEFAULT 'user'",
            "must_change_password": "BOOLEAN DEFAULT 0",
            "password_changed_at": "DATETIME",
            "last_login_at": "DATETIME",
            "updated_at": "DATETIME",
        }
        additions = user_additions_pg if dialect == "postgresql" else user_additions_sqlite
        with engine.begin() as connection:
            for name, decl in additions.items():
                if name not in user_cols:
                    if dialect == "postgresql":
                        connection.execute(text(f"ALTER TABLE users ADD COLUMN IF NOT EXISTS {name} {decl}"))
                    else:
                        connection.execute(text(f"ALTER TABLE users ADD COLUMN {name} {decl}"))
            # Set role='admin' for existing users with no role (NULL or empty)
            if dialect == "postgresql":
                connection.execute(text("UPDATE users SET role = 'user' WHERE role IS NULL OR role = ''"))
                connection.execute(text("UPDATE users SET must_change_password = FALSE WHERE must_change_password IS NULL"))
            else:
                connection.execute(text("UPDATE users SET role = 'user' WHERE role IS NULL OR role = ''"))
                connection.execute(text("UPDATE users SET must_change_password = 0 WHERE must_change_password IS NULL"))

    if "recipes" not in inspector.get_table_names():
        return
    legacy_service_menu_columns = {
        col["name"] for col in inspector.get_columns("meal_service_menus")
    } if "meal_service_menus" in inspector.get_table_names() else set()
    with engine.begin() as connection:
        if dialect == "postgresql":
            connection.execute(text("ALTER TABLE recipes DROP CONSTRAINT IF EXISTS recipes_menu_id_key"))
            # Drop legacy unique index on recipes.menu_id (from older schema) and recreate as plain index
            connection.execute(text("DROP INDEX IF EXISTS ix_recipes_menu_id"))
            connection.execute(text("CREATE INDEX IF NOT EXISTS ix_recipes_menu_id ON recipes(menu_id)"))
            connection.execute(text("ALTER TABLE recipes ADD COLUMN IF NOT EXISTS name VARCHAR(120)"))
            connection.execute(text("ALTER TABLE recipes ADD COLUMN IF NOT EXISTS version INTEGER"))
            connection.execute(text("ALTER TABLE recipes ADD COLUMN IF NOT EXISTS composition_key VARCHAR(1000)"))
            connection.execute(text("ALTER TABLE recipes ADD COLUMN IF NOT EXISTS is_default BOOLEAN"))
            connection.execute(text("ALTER TABLE recipes ADD COLUMN IF NOT EXISTS active BOOLEAN"))
            connection.execute(text("ALTER TABLE recipes ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ"))
            connection.execute(text("UPDATE recipes SET name = COALESCE(name, '기본 레시피')"))
            connection.execute(text("UPDATE recipes SET version = COALESCE(version, 1)"))
            connection.execute(text("UPDATE recipes SET composition_key = COALESCE(NULLIF(composition_key, ''), 'LEGACY-' || id::text)"))
            connection.execute(text("UPDATE recipes SET is_default = COALESCE(is_default, TRUE)"))
            connection.execute(text("UPDATE recipes SET active = COALESCE(active, TRUE)"))
            connection.execute(text("UPDATE recipes SET created_at = COALESCE(created_at, NOW())"))
            connection.execute(text("ALTER TABLE recipes ALTER COLUMN name SET NOT NULL"))
            connection.execute(text("ALTER TABLE recipes ALTER COLUMN version SET NOT NULL"))
            connection.execute(text("ALTER TABLE recipes ALTER COLUMN composition_key SET NOT NULL"))
            connection.execute(text("ALTER TABLE recipes ALTER COLUMN is_default SET NOT NULL"))
            connection.execute(text("ALTER TABLE recipes ALTER COLUMN active SET NOT NULL"))
            connection.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_recipe_menu_version_idx ON recipes(menu_id, version)"))
            connection.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_recipe_menu_composition_idx ON recipes(menu_id, composition_key)"))
            connection.execute(text("ALTER TABLE meal_service_menus ADD COLUMN IF NOT EXISTS recipe_id INTEGER"))
            connection.execute(text("ALTER TABLE meal_service_menus ADD COLUMN IF NOT EXISTS recipe_name_snapshot VARCHAR(120)"))
            connection.execute(text("ALTER TABLE meal_service_menus ADD COLUMN IF NOT EXISTS recipe_version_snapshot INTEGER"))
            connection.execute(text("DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='fk_meal_service_menu_recipe') THEN ALTER TABLE meal_service_menus ADD CONSTRAINT fk_meal_service_menu_recipe FOREIGN KEY (recipe_id) REFERENCES recipes(id) ON DELETE SET NULL; END IF; END $$;"))
            # DocumentTemplate new columns
            dt_cols = {col["name"] for col in inspector.get_columns("document_templates")} if "document_templates" in inspector.get_table_names() else set()
            for name, decl in {
                "description": "TEXT",
                "stored_filename": "VARCHAR(255)",
                "file_size": "INTEGER",
                "checksum_sha256": "VARCHAR(64)",
                "is_valid": "BOOLEAN DEFAULT FALSE",
                "validation_message": "TEXT",
                "placeholder_summary": "JSON",
                "updated_at": "TIMESTAMPTZ DEFAULT NOW()",
                "created_by": "VARCHAR(80)",
            }.items():
                if name not in dt_cols:
                    connection.execute(text(f"ALTER TABLE document_templates ADD COLUMN IF NOT EXISTS {name} {decl}"))
            # MealTypeSetting new columns
            mts_cols = {col["name"] for col in inspector.get_columns("meal_type_settings")} if "meal_type_settings" in inspector.get_table_names() else set()
            for name, decl in {
                "sort_order": "INTEGER DEFAULT 0",
                "created_at": "TIMESTAMPTZ DEFAULT NOW()",
                "updated_at": "TIMESTAMPTZ DEFAULT NOW()",
            }.items():
                if name not in mts_cols:
                    connection.execute(text(f"ALTER TABLE meal_type_settings ADD COLUMN IF NOT EXISTS {name} {decl}"))
            # MealService concept_title
            ms_cols = {col["name"] for col in inspector.get_columns("meal_services")} if "meal_services" in inspector.get_table_names() else set()
            if "concept_title" not in ms_cols:
                connection.execute(text("ALTER TABLE meal_services ADD COLUMN IF NOT EXISTS concept_title VARCHAR(80)"))
            # Widen meal_service_menu_ingredients.source_row from VARCHAR(50) to TEXT
            if "meal_service_menu_ingredients" in inspector.get_table_names():
                msmi_cols = {col["name"]: col for col in inspector.get_columns("meal_service_menu_ingredients")}
                if "source_row" in msmi_cols:
                    connection.execute(text("ALTER TABLE meal_service_menu_ingredients ALTER COLUMN source_row TYPE TEXT"))
                connection.execute(text("CREATE INDEX IF NOT EXISTS ix_meal_service_menu_ingredients_ingredient_id ON meal_service_menu_ingredients(ingredient_id)"))
            # Legacy per-menu cooking instructions were replaced by MealServiceMenu.note.
            if "meal_service_menus" in inspector.get_table_names():
                for column in ("cooking_instruction", "cooking_note"):
                    if column in legacy_service_menu_columns:
                        connection.execute(text(f"ALTER TABLE meal_service_menus DROP COLUMN IF EXISTS {column}"))
        elif dialect == "sqlite":
            # SQLite cannot drop the legacy UNIQUE(menu_id) constraint in place.
            # Fresh test databases work normally. Existing SQLite users should export,
            # recreate the database, then re-import the migration workbook.
            columns = {column["name"] for column in inspector.get_columns("recipes")}
            additions = {
                "name": "VARCHAR(120) DEFAULT '기본 레시피'",
                "version": "INTEGER DEFAULT 1",
                "composition_key": "VARCHAR(1000) DEFAULT ''",
                "is_default": "BOOLEAN DEFAULT 1",
                "active": "BOOLEAN DEFAULT 1",
                "created_at": "DATETIME",
            }
            for name, declaration in additions.items():
                if name not in columns:
                    connection.execute(text(f"ALTER TABLE recipes ADD COLUMN {name} {declaration}"))
            service_columns = {column["name"] for column in inspector.get_columns("meal_service_menus")}
            for name, declaration in {
                "recipe_id": "INTEGER",
                "recipe_name_snapshot": "VARCHAR(120)",
                "recipe_version_snapshot": "INTEGER",
            }.items():
                if name not in service_columns:
                    connection.execute(text(f"ALTER TABLE meal_service_menus ADD COLUMN {name} {declaration}"))

            # --- DocumentTemplate new columns (SQLite) ---
            if "document_templates" in inspector.get_table_names():
                dt_columns = {column["name"] for column in inspector.get_columns("document_templates")}
                for name, declaration in {
                    "description": "TEXT",
                    "stored_filename": "VARCHAR(255)",
                    "file_size": "INTEGER",
                    "checksum_sha256": "VARCHAR(64)",
                    "is_valid": "BOOLEAN DEFAULT 0",
                    "validation_message": "TEXT",
                    "placeholder_summary": "JSON",
                    "updated_at": "DATETIME",
                    "created_by": "VARCHAR(80)",
                }.items():
                    if name not in dt_columns:
                        connection.execute(text(f"ALTER TABLE document_templates ADD COLUMN {name} {declaration}"))

            # --- MealTypeSetting new columns (SQLite) ---
            if "meal_type_settings" in inspector.get_table_names():
                mts_columns = {column["name"] for column in inspector.get_columns("meal_type_settings")}
                for name, declaration in {
                    "sort_order": "INTEGER DEFAULT 0",
                    "created_at": "DATETIME",
                    "updated_at": "DATETIME",
                }.items():
                    if name not in mts_columns:
                        connection.execute(text(f"ALTER TABLE meal_type_settings ADD COLUMN {name} {declaration}"))

            # --- MealService concept_title (SQLite) ---
            if "meal_services" in inspector.get_table_names():
                ms_columns = {column["name"] for column in inspector.get_columns("meal_services")}
                if "concept_title" not in ms_columns:
                    connection.execute(text("ALTER TABLE meal_services ADD COLUMN concept_title VARCHAR(80)"))

            # --- meal_service_menu_ingredients.ingredient_id index (SQLite) ---
            if "meal_service_menu_ingredients" in inspector.get_table_names():
                connection.execute(text("CREATE INDEX IF NOT EXISTS ix_meal_service_menu_ingredients_ingredient_id ON meal_service_menu_ingredients(ingredient_id)"))
            if "meal_service_menus" in inspector.get_table_names():
                for column in ("cooking_instruction", "cooking_note"):
                    if column in {col["name"] for col in inspector.get_columns("meal_service_menus")}:
                        connection.execute(text(f"ALTER TABLE meal_service_menus DROP COLUMN {column}"))
