# 구내식당 HWPX 반복 페이지 템플릿 v2

이 템플릿은 **문서 전체 플레이스홀더 치환**이 아니라 **1페이지 Page Block 복제 + 복제본 내부(Local Scope) 치환**을 전제로 합니다.

## 공통 규칙

1. `Contents/section0.xml`에서 다음 XML 주석 사이의 최상위 콘텐츠를 한 페이지 템플릿으로 취급합니다.

```xml
<!-- CAFETERIA_REPEAT_PAGE_START ... -->
... page block ...
<!-- CAFETERIA_REPEAT_PAGE_END -->
```

2. 원본 템플릿의 플레이스홀더 이름은 페이지 번호를 포함하지 않습니다. 같은 Page Block을 여러 번 복제하여 동일한 로컬 플레이스홀더를 재사용합니다.
3. 처리 순서는 반드시 `clone -> bind inside clone -> append`입니다. 문서 전체에 `replaceAll()`을 수행하면 안 됩니다.
4. 두 번째 복제 페이지부터는 복제한 Page Block의 **첫 번째 최상위 `hp:p`에 `pageBreak="1"`**을 적용하는 방식을 우선 사용합니다. 별도 빈 페이지 나눔 문단을 추가하지 않는 것이 좋습니다.
5. 복제 후 HWPX의 표/개체 ID 및 셀 주소 참조 무결성을 검사합니다.

## 식단표

- 페이지 용량: **2주**
- 로컬 슬롯: `W1`, `W2`
- 페이지 수: `ceil(출력 주 수 / 2)`
- 마지막 페이지가 홀수 주로 끝나면 `W2`는 빈 값으로 바인딩합니다.
- 기존 플레이스홀더 예: `{{W1_D1_DATE}}`, `{{W1_D1_LUNCH_MENU}}`, `{{W2_D5_DINNER_MENU}}`

## 조리지시서

- 페이지 용량: **1일 / 중식+석식**
- 페이지 수: 선택한 출력 일자 수
- 한 페이지 안의 중식/석식 플레이스홀더만 사용합니다.
- 메뉴/식재료 슬롯은 현재 템플릿의 `LUNCH_*`, `DINNER_*`를 로컬 슬롯으로 사용합니다.

## 보존식 기록지

- 페이지 용량: **3식**
- 로컬 슬롯: `B1`, `B2`, `B3`
- 페이지 수: `ceil(출력 식사 수 / 3)`
- 마지막 페이지의 남는 슬롯은 빈 값으로 바인딩합니다.

## 금지 패턴

```text
PAGE1_DATE, PAGE2_DATE, PAGE3_DATE ...
P1_W1_D1, P2_W1_D1 ...
```

페이지 수만큼 플레이스홀더를 늘리지 않습니다.

## 권장 생성 알고리즘

```text
load template
  -> locate repeat page block
  -> split DTO into page-sized chunks
  -> for each chunk:
       clone page block
       bind placeholders only inside the clone
       clear unused local slots
       if cloneIndex > 0: set first top-level hp:p pageBreak=1
       append clone
  -> remove original unbound template block
  -> validate no unexpected {{...}} remains
  -> save HWPX
```
