# Data Migration Guide

## 목적

원본 Excel/CSV/문서 자료를 DB에 직접 넣지 않고 다음 절차로 표준 XLSX Migration Data로 만든다.

```text
원본 자료
→ 구조 분석
→ 정규화
→ Validation
→ Canonical XLSX Preview
→ 사람 검토
→ Import Apply
```

현재 Importer는 `backend/app/importer.py`의 `MigrationImporter`이며 XLSX를 입력으로 받는다.

## 표준 Sheet

Importer가 요구하는 필수 Sheet는 다음과 같다.

```text
01_배식설정
02_메뉴기준정보
03_재료기준정보
04_재료별칭_선택
05_메뉴별재료_기준
06_식단이력_이관
07_식단재료_이관
```

Workbook에는 `00_안내`, `08_검증요약`, `99_코드목록` 같은 설명/검증 Sheet를 추가할 수 있지만, 필수 업무 Sheet와 혼동하지 않는다.

## Sheet Contract

### 01_배식설정

| Column | 필수 | 의미 |
|---|---|---|
| 배식유형 | Y | 중식/석식 또는 LUNCH/DINNER |
| 기본계획식수 | N | 기본 계획 식수 |
| 기본배식시간 | N | HH:MM |
| 사용여부 | N | Y/N |
| 설명 | N | 설명 |

### 02_메뉴기준정보

| Column | 필수 | 의미 |
|---|---|---|
| 메뉴ID | 권장 | 사람이 관리하는 안정적인 `menu_key` |
| 메뉴명 | Y | 메뉴 표시명 |
| 통계집계메뉴명 | N | `Menu.canonical_name` |
| 메뉴역할 | N | 현재 허용 역할 |
| 사용여부 | N | Y/N |
| 검토상태 | N | 검토 상태 |

### 03_재료기준정보

| Column | 필수 | 의미 |
|---|---|---|
| 재료ID | 권장 | 사람이 관리하는 안정적인 `ingredient_key` |
| 표준재료명 | Y | 표준 Ingredient 이름 |
| 통계분석군 | N | 통계분석군 |
| 기본단위 | N | kg, g, L 등 |
| kg환산계수 | N | 명시적으로 확인된 경우만 |
| 분석제외 | N | Y/N |
| 사용여부 | N | Y/N |
| 검토상태 | N | 검토 상태 |

### 04_재료별칭_선택

| Column | 필수 | 의미 |
|---|---|---|
| 원재료별칭 | Y | 원본에서 확인된 별칭 |
| 재료ID | Y | `ingredient_key` |
| 표준재료명 | N | 사람 확인용 |
| 출처 | N | 별칭 출처 |

이름이 비슷하다는 이유만으로 별칭을 만들거나 Ingredient를 병합하지 않는다.

### 05_메뉴별재료_기준

한 행은 하나의 RecipeIngredient 후보이다.

| Column | 필수 | 의미 |
|---|---|---|
| 메뉴ID | Y | `menu_key` |
| 메뉴명 | N | 검토용 표시값 |
| 레시피명 | N(선택 열) | `Recipe.name`. 비어 있거나 열이 없으면 `기본 레시피 vN` |
| 재료ID | Y | `ingredient_key` |
| 표준재료명 | N | 검토용 표시값 |
| 100인기준수량 | N | `RecipeIngredient.quantity_per_100` |
| 단위 | N | 명시된 단위 |
| 원본행 | N | 원본 provenance |
| 원본비고 | N | 원본 설명 |
| 검토상태 | N | 검토 상태 |

같은 메뉴 안에서 재료 ID 구성이 같은 행 묶음은 하나의 `composition_key` 후보가 된다. 블록은 `재료순서`가 다시 작아지거나 `레시피명`이 바뀌면 새로 시작한다.

`레시피명` 규칙:

- 같은 메뉴ID 안에서 레시피명과 재료 구성은 1:1이다. 같은 이름이 다른 구성에 쓰이거나(`DUPLICATE_RECIPE_NAME`), 다른 이름이 같은 구성을 가지면(`RECIPE_NAME_SAME_COMPOSITION`) Preview 오류로 반영하지 않는다. 같은 이름·같은 구성의 반복 블록은 하나의 레시피로 합친다.
- 병합(merge) 재가져오기에서 구성이 같은 기존 레시피가 있으면 파일의 레시피명으로 이름을 갱신한다(새 레시피를 만들지 않음). 이미 저장된 식단의 레시피명 Snapshot은 이번 파일로 다시 연결된 식단 메뉴만 갱신된다.

### 06_식단이력_이관

| Column | 필수 | 의미 |
|---|---|---|
| 일자 | Y | MealService 날짜 |
| 배식유형 | Y | LUNCH/DINNER 또는 중식/석식 |
| 계획식수 | N | `MealService.planned_count` |
| 배식시간 | N | 서비스 시간 |
| 메뉴순서 | Y | `sort_order` |
| 메뉴ID | 권장 | `menu_key` |
| 메뉴명 | Y | 당시 메뉴 Snapshot |
| 레시피명 | N(선택 열) | 그날 사용한 레시피. 같은 메뉴ID의 `05.레시피명`과 정확히 일치해야 함 |
| 메인메뉴여부 | N(선택 열) | `MealServiceMenu.is_representative` (메인 메뉴, `Y`/`N`) |
| 메뉴비고 | N | `MealServiceMenu.note` |

같은 날짜와 배식유형은 하나의 MealService로 묶는다.

`레시피명`(선택 열)이 있으면 해당 식단 메뉴를 같은 메뉴ID의 그 레시피에 연결하고 레시피명 Snapshot을 저장한다. `07`의 그날 재료 구성이 레시피와 달라도 연결하며, `07` 재료는 실제 기록대로 보존한다. 빈 값이거나 열이 없으면 기존 방식(`07` 재료 구성이 정확히 같은 레시피, 없으면 메뉴의 기본 레시피)으로 연결한다. 같은 메뉴ID의 `05`에 없는 이름은 시트명·행번호와 함께 Preview 오류(`UNKNOWN_RECIPE_NAME`)가 되고, 반영 시에도 기존 데이터를 지우기 전에 거부한다.

`메인메뉴여부`(선택 열, `Y`/`N`)는 `MealServiceMenu.is_representative`(화면 표기: 메인 메뉴)에 저장된다.

- 열이 있으면 파일 값을 그대로 반영한다. 명시된 `N`도 기존 값을 덮어쓰며, 재가져오기(병합)에서 이전에 `Y`였던 행이 `N`이면 해제된다. 병합 시 파일에 포함된 식단(일자×배식유형)은 파일의 지정이 기준이므로, 파일에 없는 기존 메뉴의 오래된 메인 표시도 해제된다.
- 한 식단(일자×배식유형)에서 `Y`는 최대 1건이다. 모든 행이 `N`인 식단은 메인 메뉴 없이 저장된다.
- `Y`/`N` 이외의 값(빈 값 포함), 같은 식단의 `Y` 복수 지정, 같은 메뉴 행의 상충 값은 Preview에서 시트명·엑셀 행번호와 함께 오류로 표시되며 반영하지 않는다(임의로 고르지 않음).
- 열이 없는 기존 파일은 그대로 이관된다. 이 경우에만 이번 이관에서 새로 만든 메뉴 중 메뉴역할이 `주찬`이고 메뉴순서가 가장 빠른 메뉴를 자동으로 메인 메뉴로 지정한다(병합 시 이미 메인 메뉴가 있는 식단은 그대로 둔다).
- 메인 메뉴 지정을 맞추려고 메뉴역할을 바꾸지 않는다. 일품밥류(비빔밥·볶음밥 등)의 메인 지정은 `메인메뉴여부` 열로만 표현된다.

### 07_식단재료_이관

| Column | 필수 | 의미 |
|---|---|---|
| 일자 | Y | MealService 날짜 |
| 배식유형 | Y | 식사 유형 |
| 메뉴순서 | Y | 식단 메뉴 순서 |
| 메뉴ID | 권장 | `menu_key` |
| 메뉴명 | Y | 당시 메뉴명 |
| 재료순서 | Y | Snapshot 순서 |
| 재료ID | 권장 | 확인된 `ingredient_key` |
| 표준재료명 | Y | 당시 재료명 Snapshot |
| 원본재료명 | N | 원본 표시명 |
| 수량 | N | 당시 `quantity_total` |
| 단위 | N | 당시 단위 |
| 원본비고 | N | 당시 재료 비고 |
| 원본행 | N | provenance |

`재료ID`가 없으면 이름으로 자동 연결하지 않는다. 해당 행을 Review/Error로 남긴다.

## 표준 Key

```text
menu_key       원본에서 관리하는 메뉴 식별자
ingredient_key  원본에서 관리하는 재료 식별자
recipe_key      필요 시 원본 Recipe 식별자
service_key    일자 + 배식유형
```

DB Primary Key를 원본 파일에서 직접 관리하지 않는다. Importer가 DB ID를 생성/조회한다.

## 정규화 규칙

자동 처리 가능:

- 앞뒤 공백 제거
- 연속 공백 정리
- `LUNCH`/`중식`, `DINNER`/`석식` 변환
- 명확한 Excel 날짜 Serial 변환
- 명시된 Unit의 대소문자 정리

Review 필요:

- 메뉴명 오타/약칭
- Ingredient 통합 여부
- 단위 추정
- 비정상 수량
- 메뉴/Recipe 동일성 판단
- 중식/석식이 불명확한 행

## 수량 규칙

현재 기준 Recipe의 수량은 100인 기준이다.

```text
RecipeIngredient.quantity_per_100
```

과거 식단 Snapshot은 다음을 별도로 저장한다.

```text
quantity_total
quantity_per_100
unit
```

원본에 전체 수량과 계획 식수가 모두 명시된 신규 Migration Data의 경우 준비 단계에서 다음 계산을 할 수 있다.

```text
quantity_per_100 = quantity_total * 100 / planned_count
```

단, 계산값임을 Validation Report에 기록한다. 현재 DB에 이미 저장된 Snapshot의 null 값을 사후 보정하는 용도로 사용하지 않는다.

`quantity_per_100` 또는 Unit을 알 수 없으면 임의로 계산/추정하지 않고 Review 또는 Error로 남긴다.

## Snapshot 규칙

현재 Menu/Ingredient/Recipe 기준정보와 당시 Snapshot을 혼동하지 않는다.

```text
Menu.name                         현재 이름
MealServiceMenu.menu_name_snapshot 당시 이름

Recipe.name                       현재 Recipe 이름
MealServiceMenu.recipe_name_snapshot 당시 Recipe 이름

Ingredient.name                   현재 재료명
MealServiceMenuIngredient.ingredient_name_snapshot 당시 재료명
```

## Duplicate / Merge 정책

- Menu: `메뉴ID` 우선, 없으면 동일 이름은 Preview에서 확인
- Ingredient: `재료ID` 우선, 이름만으로 자동 병합 금지
- Recipe: 동일 메뉴의 재료 구성은 `composition_key`로 확인
- MealService: `일자 + 배식유형`
- MealServiceMenu: 동일 Service 안의 `menu_key + 메뉴순서`
- Snapshot Ingredient: `service_menu + 재료순서 + 당시 재료 식별정보`

## Import Workflow

1. 원본 파일을 복사본으로 보존한다.
2. Sheet/Column 의미를 분석한다.
3. `menu_key`, `ingredient_key`, `service_key`를 정한다.
4. Canonical Sheet로 변환한다.
5. ERROR와 WARNING을 분리한다.
6. 사람이 Review 항목을 확인한다.
7. `/api/setup/import/preview`로 Preview한다.
8. Summary와 오류를 확인한다.
9. Backup을 생성한다.
10. `replace` 또는 `merge`를 명시적으로 선택한다.
11. `/api/setup/import/apply`를 실행한다.
12. Import 후 Count/FK/핵심 화면을 검증한다.

기본은 Preview이며, 업로드만으로 DB가 변경되어서는 안 된다.

## ERROR / WARNING

ERROR 예:

- 필수 Sheet 없음
- 필수 날짜 없음
- 알 수 없는 배식유형
- 필수 메뉴/재료 Key 없음
- 숫자 수량 파싱 실패
- 확인되지 않은 Ingredient ID
- service_key 충돌

WARNING 예:

- Recipe 이름 없음
- quantity_per_100 계산값
- 단위 혼재
- 기존 이름과 유사하지만 동일성 미확정
- 과거 Snapshot의 일부 정보 부족

## Quality Report

각 Migration마다 다음을 보고한다.

```text
메뉴 수
재료 수
별칭 수
Recipe 재료 행 수
MealService 수
MealServiceMenu 수
Snapshot 재료 행 수
중복 후보
미매칭 메뉴
미매칭 재료
단위 불명
수량 불명
100인 환산 계산 행
Review 필요 행
```

## 변경된 Legacy 필드

다음 필드는 현재 최종 Schema에 없으며 Migration Contract에도 포함하지 않는다.

```text
MealServiceMenu.cooking_instruction
MealServiceMenu.cooking_note
```

조리지시서의 메뉴 비고는 `MealServiceMenu.note`를 사용한다.
배식 후 특이사항은 `MealService.note`를 사용한다.
