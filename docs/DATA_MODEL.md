# 데이터 모델

## 메뉴와 다중 레시피

```text
Menu
└─ Recipe 1:N
   └─ RecipeIngredient 1:N
```

같은 메뉴라도 재료 구성이 다르면 별도의 레시피로 관리합니다.

- `Recipe.version`: 메뉴별 순차 버전
- `Recipe.name`: 사용자가 구분하는 이름
- `Recipe.composition_key`: 재료 ID 집합을 정렬해 만든 구성 키
- `Recipe.is_default`: 식단에 메뉴를 추가할 때 기본 선택
- `Recipe.active`: 미사용 처리

수량과 단위는 `composition_key`에 포함하지 않습니다. 따라서 재료가 같고 수량만 달라진 경우에는 기존 레시피를 수정합니다.

## 식단 스냅샷

```text
MealService
└─ MealServiceMenu
   ├─ menu_id
   ├─ recipe_id
   ├─ menu_name_snapshot
   ├─ recipe_name_snapshot
   ├─ recipe_version_snapshot
   └─ MealServiceMenuIngredient
```

식단에 메뉴를 추가할 때 선택한 레시피의 재료를 스냅샷으로 복사합니다. 이후 기준 레시피가 수정되어도 과거 식단의 재료는 자동 변경되지 않습니다.

## 실제 식수와 보존식

- `MealActual`: 실제 식수 결과
- `PreservationRecord`: 보존식 기록

두 정보는 독립적으로 저장합니다.
