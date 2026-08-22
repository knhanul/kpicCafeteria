# Final Database Schema

이 문서는 현재 승인된 운영 기준 데이터 모델을 설명한다. 현재 DB는 Alembic이 아니라 `schema_upgrade.py`의 startup compatibility upgrade와 `Base.metadata.create_all()`을 사용한다.

## 핵심 원칙

```text
현재 기준정보             과거 식단 Snapshot
Menu                      MealServiceMenu.menu_name_snapshot
Recipe                    recipe_name_snapshot
RecipeIngredient          recipe_version_snapshot
Ingredient                MealServiceMenuIngredient.*_snapshot
```

현재 기준정보 변경은 과거 Snapshot을 변경하지 않는다.

## Table 목록

### 인증/관리

- `users`: 로그인, 권한, 비밀번호 상태
- `audit_logs`: 관리자 작업 Audit
- `backup_records`: 백업 이력
- `data_archives`: Excel 아카이브 이력

### 기준정보

- `menus`: 메뉴명, 통계 집계명, 역할, 활성 상태
- `recipes`: 메뉴별 Recipe 이름, version, composition_key, 기본/활성 상태
- `recipe_ingredients`: 현재 Recipe의 재료, 100인 수량, 단위, 주재료, 순서
- `ingredients`: 표준재료명, 통계분석군, 기본단위, kg 환산계수, 활성 상태
- `ingredient_aliases`: 재료 별칭
- `meal_type_settings`: 중식/석식 기본값

### 식단/Snapshot

- `meal_services`: 날짜, 식사구분, 계획식수, 서비스시간, 식단 메모, 출력 완료시각
- `meal_service_menus`: 식단의 메뉴와 당시 메뉴/Recipe Snapshot
- `meal_service_menu_ingredients`: 당시 재료명, 전체수량, 100인수량, 단위, 원본 provenance

### 운영

- `preservation_records`: 보존식 기록
- `meal_actuals`: 실제 식수 및 실제 식수 메모

### 출력/이관

- `document_templates`: HWPX Template 메타데이터
- `document_previews`: 만료 가능한 출력 Preview
- `import_jobs`: XLSX Import Preview/Apply 작업

### 발주

- `order_groups`: 재료별 발주 Group
- `order_items`: 날짜별 재료 발주 Item

## 관계도

```text
Menu
 └─< Recipe
      └─< RecipeIngredient >─ Ingredient

MealService
 └─< MealServiceMenu
      ├── Menu (menu_id, nullable, SET NULL)
      ├── Recipe (recipe_id, nullable, SET NULL)
      └─< MealServiceMenuIngredient
            └── Ingredient (ingredient_id, nullable, SET NULL)

MealService ── 0..1 PreservationRecord
MealService ── 0..1 MealActual
```

## Snapshot 정책

`MealServiceMenu`는 당시 표시값을 보존한다.

```text
menu_name_snapshot
recipe_name_snapshot
recipe_version_snapshot
note
```

`MealServiceMenuIngredient`는 당시 사용값을 보존한다.

```text
ingredient_name_snapshot
ingredient_id
quantity_total
quantity_per_100
unit
sort_order
source_note
source_row
```

`ingredient_id`와 `quantity_per_100`가 null일 수 있는 과거 데이터는 임의 보정하지 않는다.

## 조리지시서 정책

현재 조리지시서의 메뉴 관련 Source of Truth는 다음이다.

```text
MealServiceMenu.note
```

배식 후 특이사항은 다음에 저장한다.

```text
MealService.note
```

메뉴별 Legacy Column은 제거되었다.

```text
meal_service_menus.cooking_instruction  제거
meal_service_menus.cooking_note         제거
```

## 삭제/유지 결과

### 삭제된 Legacy 구조

- `MealServiceMenu.cooking_instruction`
- `MealServiceMenu.cooking_note`

두 Column은 실제 데이터가 0건이었고, 최근 업무 흐름에서 사용되지 않았다. Model, Serializer, Workspace legacy update, Admin export, HWPX fallback 참조도 함께 제거했다.

### 유지한 구조

- `source_row`: Import 원본행 provenance 10,082건
- 모든 Snapshot 이름/수량/단위 Column
- `meal_plan_output_at`, `cooking_output_at`: 출력 완료 추적 및 운영 통계 사용
- `ImportJob`, `DocumentPreview`, `DataArchive`: 현재 Preview/Import/Archive 업무 흐름 사용

## Schema 검증

Phase B Cleanup 적용 후 핵심 Table을 PostgreSQL과 Model 사이에서 재비교한다.

```text
Model-only Column: 없음
DB-only Column: 없음
FK Orphan: 없음
```

## 변경 적용 방식

Cleanup은 `backend/app/schema_upgrade.py`의 idempotent startup SQL로 적용되었다.

```sql
ALTER TABLE meal_service_menus
  DROP COLUMN IF EXISTS cooking_instruction;

ALTER TABLE meal_service_menus
  DROP COLUMN IF EXISTS cooking_note;
```

실제 적용 전 RC DB Backup을 생성했고, App 재기동 후 Column 부재와 전체 Test 통과를 확인한다.
