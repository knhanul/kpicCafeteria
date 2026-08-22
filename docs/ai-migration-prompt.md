# AI Migration Prompt

아래 Prompt를 원본 Excel/CSV/문서와 함께 사용한다. 이 Prompt는 원본을 DB에 직접 반영하지 않고, 프로젝트의 Canonical Migration Data와 Validation Report를 만드는 것을 목표로 한다.

## Prompt

```text
당신은 구내식당 데이터 Migration 분석 담당자다.

첨부한 원본 자료를 분석하여 kpicCafeteria의 Canonical Migration Contract에 맞는 표준 Migration Data를 생성하라. DB에 직접 접속하거나 DB를 변경하지 말고, Preview 가능한 파일과 Validation Report만 생성하라.

반드시 다음 순서를 따른다.

1. 원본 파일 유형과 파일 구조를 파악한다.
2. Sheet, 표, Header, 행 의미를 설명한다.
3. 날짜와 중식/석식을 식별한다.
4. 메뉴, 재료, Recipe, 식단, Snapshot 후보를 추출한다.
5. menu_key, ingredient_key, recipe_key, service_key를 정한다.
6. 앞뒤 공백, 명백한 날짜 형식, 명백한 Unit 표기만 정규화한다.
7. 메뉴명/재료명이 유사하다는 이유로 자동 병합하지 않는다.
8. ingredient_id 또는 ingredient_key를 알 수 없는 행은 이름으로 자동 연결하지 말고 Review/Error로 남긴다.
9. Recipe 수량은 quantity_per_100을 사용한다.
10. 과거 식단은 quantity_total, quantity_per_100, unit을 별도 값으로 보존한다.
11. quantity_per_100이 원본에 없으면 임의 계산하지 않는다. 전체 수량과 계획 식수가 모두 명시된 경우에만 계산 후보로 표시하고 계산값임을 Report에 기록한다.
12. 단위가 불명확하면 임의로 kg/g/L/ml을 지정하지 않는다.
13. 중식/석식이 불명확하면 임의 분류하지 않는다.
14. 현재 기준정보와 과거 Snapshot을 구분한다.
15. 삭제된 Legacy 필드인 MealServiceMenu.cooking_instruction, MealServiceMenu.cooking_note를 생성하지 않는다.
16. 조리지시서 메뉴 비고는 MealServiceMenu.note 후보로 만들고, 배식 후 특이사항은 MealService.note 후보로 구분한다.
17. ERROR와 WARNING을 분리한다.
18. 사람이 검토해야 하는 모든 행을 Review 목록으로 만든다.
19. 실제 DB Apply는 수행하지 않는다.

Canonical XLSX Sheet:
- 01_배식설정
- 02_메뉴기준정보
- 03_재료기준정보
- 04_재료별칭_선택
- 05_메뉴별재료_기준
- 06_식단이력_이관
- 07_식단재료_이관

핵심 Field:
- Menu: 메뉴ID, 메뉴명, 통계집계메뉴명, 메뉴역할, 사용여부
- Ingredient: 재료ID, 표준재료명, 통계분석군, 기본단위, kg환산계수, 분석제외, 사용여부
- RecipeIngredient: 메뉴ID, 레시피명, 재료ID, 100인기준수량, 단위, 재료순서
- MealService: 일자, 배식유형, 계획식수, 배식시간
- MealServiceMenu: 메뉴ID, 메뉴명, 메뉴순서, 메뉴비고
- Snapshot Ingredient: 재료ID, 표준재료명, 수량, 100인기준수량, 단위, 재료순서, 원본행

허용 배식유형:
- 중식 → LUNCH
- 석식 → DINNER
- LUNCH → LUNCH
- DINNER → DINNER

Output:
A. 원본 구조 분석
B. Canonical Migration Data
C. Validation Report
D. ERROR 목록
E. WARNING 목록
F. Review 필요 목록
G. 중복 후보 목록
H. 수량/단위 변환 내역
I. Snapshot 보존 내역
J. Import 전 사람이 확인해야 할 질문

확실하지 않은 값은 빈 값 또는 Review로 남기고, 0/기본 단위/임의 이름으로 대체하지 마라.
``` 

## AI 작업 후 검토

AI가 생성한 결과는 다음 순서로 사람이 검토한다.

```text
원본과 Canonical 행 대조
→ ERROR/WARNING 확인
→ Key 중복 확인
→ 날짜/식사구분 확인
→ 메뉴/재료 연결 확인
→ 수량/단위 확인
→ Snapshot 값 확인
→ Import Preview
→ Backup
→ 명시적 Apply
```

Schema나 Importer가 바뀌면 이 Prompt와 `data-migration-guide.md`를 함께 갱신한다.
