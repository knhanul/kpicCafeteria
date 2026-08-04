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
    if "recipes" not in inspector.get_table_names():
        return
    dialect = engine.dialect.name
    with engine.begin() as connection:
        if dialect == "postgresql":
            connection.execute(text("ALTER TABLE recipes DROP CONSTRAINT IF EXISTS recipes_menu_id_key"))
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
