# Database / Legacy Audit

작성 목적: 현재 PostgreSQL, SQLAlchemy Model, Router/Service, Frontend, HWPX, Import/Export를 비교하여 최종 Schema 정리 후보와 향후 Migration Contract의 기준을 확정한다.

## Audit 범위

- SQLAlchemy Models: `backend/app/models.py`
- Schema compatibility upgrade: `backend/app/schema_upgrade.py`
- Routers / Services / Serializers
- Frontend `backend/app/static/app.js`
- HWPX builders and engine
- Excel importer: `backend/app/importer.py`
- PostgreSQL RC database

## Schema 관리 방식

현재 Alembic은 사용하지 않는다.

- 기존 DB 호환: `upgrade_existing_schema(engine)`
- 신규/누락 구조: `Base.metadata.create_all(engine)`
- 실행 시점: App startup

따라서 향후 실제 Schema 변경은 별도 명시적 Migration 체계를 먼저 확정한 뒤 적용해야 한다. 현재 `schema_upgrade.py`는 과거 버전 호환을 위한 수동 SQL upgrade이며, 버전별 downgrade history를 제공하지 않는다.

## 실제 PostgreSQL Table 및 Row Count

검사 시점의 RC 개발 DB 기준이다.

| 영역 | Table | Rows | 판정 |
|---|---|---:|---|
| 인증 | users | 3 | ACTIVE |
| 기준정보 | meal_type_settings | 2 | ACTIVE |
| 기준정보 | menus | 939 | ACTIVE |
| 기준정보 | ingredients | 561 | ACTIVE |
| 기준정보 | ingredient_aliases | 167 | ACTIVE |
| 기준정보 | recipes | 1,750 | ACTIVE |
| 기준정보 | recipe_ingredients | 7,440 | ACTIVE |
| 식단 | meal_services | 534 | ACTIVE / HISTORY |
| 식단 Snapshot | meal_service_menus | 3,176 | REQUIRED_HISTORY |
| 식단 Snapshot | meal_service_menu_ingredients | 10,161 | REQUIRED_HISTORY |
| 운영기록 | preservation_records | 0 | ACTIVE |
| 운영기록 | meal_actuals | 0 | ACTIVE |
| 출력 | document_templates | 0 | ACTIVE |
| 출력 | document_previews | 0 | ACTIVE / TRANSIENT |
| 이관 | import_jobs | 1 | ACTIVE / TRANSIENT |
| 발주 | order_groups | 0 | ACTIVE |
| 발주 | order_items | 2 | ACTIVE / HISTORY |
| 관리 | audit_logs | 16 | ACTIVE / AUDIT |
| 관리 | backup_records | 1 | ACTIVE / AUDIT |
| 관리 | data_archives | 2 | ACTIVE / ARCHIVE |

## Model ↔ DB Schema 비교

핵심 업무 Table에 대해 SQLAlchemy `Base.metadata` Column 집합과 PostgreSQL `information_schema.columns`를 비교했다.

대상:

```text
menus
recipes
recipe_ingredients
ingredients
meal_services
meal_service_menus
meal_service_menu_ingredients
```

결과:

```text
Model-only Column: 없음
DB-only Column: 없음
```

## 관계 무결성

검사 결과:

```text
recipes_without_menu: 0
recipe_ingredients_without_recipe: 0
recipe_ingredients_without_ingredient: 0
service_menus_without_service: 0
service_menus_with_missing_menu: 0
service_menu_ingredients_without_menu: 0
```

Nullable이 허용된 `MealServiceMenu.menu_id`, `recipe_id`, `MealServiceMenuIngredient.ingredient_id`는 Snapshot/삭제 보존 정책 때문에 nullable로 유지한다.

## 업무 영역별 Canonical 구조

### 현재 기준정보

```text
Menu
 └ Recipe
    └ RecipeIngredient
       └ Ingredient
```

### 과거 식단 Snapshot

```text
MealService
 └ MealServiceMenu
    ├ menu_id → Menu (nullable, SET NULL)
    ├ recipe_id → Recipe (nullable, SET NULL)
    └ MealServiceMenuIngredient
       └ ingredient_id → Ingredient (nullable, SET NULL)
```

현재 기준정보와 과거 Snapshot을 분리하는 것이 핵심 데이터 정책이다.

## Column 사용 분류

### ACTIVE

| Table.Column | 근거 |
|---|---|
| Menu.name / canonical_name / role / active | 기준정보 CRUD, 목록, 통계 |
| Ingredient.name / stat_group / default_unit / kg_factor / active | 기준정보 CRUD, 통계, 발주 |
| Recipe.name / version / composition_key / is_default / active | Recipe CRUD, Snapshot Apply, 통계 |
| RecipeIngredient.ingredient_id / quantity_per_100 / unit / is_primary / sort_order | Recipe 편집, Recipe Apply, 통계 |
| MealService.service_date / meal_type / planned_count / service_time | 식단, 출력, 통계 |
| MealService.note | 배식 후 특이사항 및 기존 MealService note |
| MealServiceMenu.note | 식단 작성 메뉴 비고 및 조리지시서 HWPX Source of Truth |
| MealServiceMenu.is_representative / sort_order | 식단, 출력 |
| MealServiceMenuIngredient.quantity_total / quantity_per_100 / unit | 식단 Snapshot, 이력, 발주/통계 |
| OrderGroup / OrderItem columns | 발주 기능 |
| PreservationRecord / MealActual columns | 운영기록 |
| DocumentTemplate columns | HWPX Template 관리 |
| AuditLog / BackupRecord / DataArchive columns | 관리/감사/백업 |

### REQUIRED_HISTORY

| Table.Column | 근거 |
|---|---|
| MealServiceMenu.menu_name_snapshot | 메뉴명 변경 후 과거 표시 보존 |
| MealServiceMenu.recipe_name_snapshot | 당시 Recipe 표시 보존 |
| MealServiceMenu.recipe_version_snapshot | 당시 Recipe 버전 보존 |
| MealServiceMenuIngredient.ingredient_name_snapshot | 재료명 변경/삭제 후 당시 표시 보존 |
| MealServiceMenuIngredient.quantity_total | 당시 실제 전체 사용량 보존 |
| MealServiceMenuIngredient.quantity_per_100 | 당시 저장된 100인 기준량 보존 |
| MealServiceMenuIngredient.unit | 당시 단위 보존 |
| OrderGroup.ingredient_name_snapshot | 발주 당시 재료명 보존 |
| OrderItem.ingredient_name_snapshot | 발주 당시 재료명 보존 |

### LEGACY_COMPATIBILITY

| 대상 | 현황 |
|---|---|
| `schema_upgrade.py`의 과거 Schema 호환 SQL | 기존 설치 DB를 위한 startup compatibility layer |
| `MealServiceMenu.cooking_instruction` | 현재 UI/HWPX 업무 흐름에서는 폐기되었으나 Model, workspace legacy payload, admin export, HWPX fallback 코드에 참조가 남아 있음 |
| `MealServiceMenu.cooking_note` | 위와 동일 |
| `MealServiceMenuIngredient.source_row` | Import 원본행 provenance로 10,082건 데이터가 존재하며 Importer가 기록함 |
| `meal_plan_output_at`, `cooking_output_at` | 출력 완료 추적과 운영 통계/대시보드에서 사용 중이므로 단순 Legacy가 아님 |

### TRANSIENT / ACTIVE

| 대상 | 판정 |
|---|---|
| DocumentPreview | 현재 출력 Preview Flow에서 생성되는 임시 데이터. 현재 0 rows지만 Table/API는 active |
| ImportJob | XLSX Preview/Apply Flow에서 사용. 현재 1 row |
| DataArchive | 관리 화면의 Archive Flow에서 사용. 현재 2 rows |

### SAFE_TO_REMOVE

현재 조사 단계에서 즉시 `SAFE_TO_REMOVE`로 확정할 Table은 없다.

`MealServiceMenu.cooking_instruction`, `MealServiceMenu.cooking_note`는 실제 데이터가 각각 0건이지만, 다음 참조를 먼저 제거해야 한다.

- `workspace.py` legacy ServiceMenuBody 및 update assignment
- `serializers.py` payload
- `routers/admin.py` export
- `hwpx_engine.py` fallback key
- 관련 tests/import fixtures
- SQLAlchemy Model columns

그 후 별도 승인된 Cleanup Migration에서 Column DROP 대상으로 검토할 수 있다.

## UNCERTAIN

| 대상 | 이유 | 다음 확인 |
|---|---|---|
| `MealServiceMenuIngredient.source_row` | Import 원본 행 정보를 10,082건 보유하며 현재 Importer가 기록하지만 운영 화면에는 직접 표시하지 않음 | 원본 복원/감사 요구사항 확인 후 유지 또는 archive 정책 결정 |
| `MealService.note`의 기존 식단 메모 의미 | 최근에는 배식 후 특이사항으로 재사용하지만 과거 MealService 일반 메모와 의미가 겹칠 수 있음 | 사용자 업무 정의 확인 후 별도 Column 분리 여부 결정 |
| `document_previews` 정리 주기 | 현재 Table은 active지만 RC DB row는 0 | 만료 Preview cleanup 스케줄/운영 정책 확인 |

UNCERTAIN 대상은 삭제하지 않는다.

## 조리지시서 개편 반영

현재 조리지시서 출력 Source of Truth는 다음이다.

```text
MealServiceMenu.note
```

기존 메뉴별 조리지시/주의·비고 Column은 현재 입력 UI와 HWPX 출력에서 제거되었지만, 호환 코드가 남아 있어 Phase B에서 코드 정리 후 Column 삭제 여부를 별도 승인받아야 한다.

## 기존 Importer 조사

현재 Importer는 `backend/app/importer.py`의 `MigrationImporter`이며 XLSX만 지원한다.

필수 Sheet:

```text
01_배식설정
02_메뉴기준정보
03_재료기준정보
04_재료별칭_선택
05_메뉴별재료_기준
06_식단이력_이관
07_식단재료_이관
```

현재 샘플 원본 Workbook에는 안내/코드 Sheet도 추가로 존재하지만 Importer는 위 필수 Sheet를 중심으로 동작한다.

지원 동작:

- Preview: Sheet 존재/행 수 확인
- Apply: `replace` 또는 `merge`
- Menu/Ingredient: source_code 우선, 이름 fallback
- Recipe: Ingredient composition 기준 그룹화 및 version 생성
- MealService: date + meal_type 기준
- Snapshot: menu note, name/version, ingredient quantity 및 원본행 기록
- AuditLog: Import 완료 기록

현재 Importer의 `replace`는 업무 데이터를 지우는 동작이므로 Preview/Backup/명시적 확인이 필수다.

## Phase A 결론

```text
Model ↔ PostgreSQL 핵심 Schema: 일치
FK 관계 무결성: 정상
SAFE_TO_REMOVE Table: 없음
SAFE_TO_REMOVE 확정 Column: 없음
UNCERTAIN 삭제: 없음
```

## Phase B 승인 후 Cleanup 결과

사용자 승인 후 `MealServiceMenu.cooking_instruction` 및 `MealServiceMenu.cooking_note` 참조를 제거하고, custom startup migration을 적용했다.

```text
meal_service_menus.cooking_instruction: DROP 완료
meal_service_menus.cooking_note: DROP 완료
```

두 Column의 기존 데이터는 각각 0건이었다. `MealServiceMenu.note`가 식단 작성 메뉴 비고 및 조리지시서 출력의 단일 Source of Truth다.

`source_row`와 모든 Snapshot Column은 유지했다. `source_row`는 10,082건의 Import provenance 데이터가 있어 UNCERTAIN/호환 데이터로 보존한다.

현재 핵심 DB Schema와 Model을 다시 비교했으며 Model-only/DB-only Column은 없다.
