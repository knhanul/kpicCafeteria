# HWPX → PDF Renderer Report

## Goal

Provide a PDF preview that is generated strictly from the already-produced HWPX output.

The pipeline is kept as:

`DB → DTO/builders → HWPX generation → PDF conversion`

What is **not** used:

- DB → HTML → PDF
- DB → direct PDF generation without the generated HWPX step

## Selected approach

### Renderer abstraction

A pluggable renderer interface was added in `backend/app/hwpx_pdf_renderer.py`.

The backend now depends on a PDF renderer abstraction instead of hard-coding HTML-to-PDF logic.

### Conversion flow

The current flow is:

1. Build the document DTO from ORM-loaded `MealService` rows.
2. Generate HWPX bytes from the existing HWPX template engine.
3. Pass those HWPX bytes to the PDF renderer.
4. Return the PDF bytes to the download route.

### Implementation choice

The renderer uses **Hancom Office COM automation** on Windows:

- COM ProgID: `HWPFrame.HwpObject`
- Document open mode: `Open(..., "HWPX", ...)`
- Export mode: `SaveAs(..., "PDF", "")`

This matches the environment where HWPX output and PDF export are available through Hancom Office.

## Why this approach

- It preserves the generated HWPX layout as the source of truth.
- It avoids introducing a parallel HTML rendering pipeline.
- It keeps the API and UI unchanged.
- It is pluggable, so the renderer can be replaced later without changing the document routes.

## Failure handling

If PDF conversion fails:

- the PDF request returns an error response
- the HWPX download path still works normally
- the HWPX generation pipeline is not blocked

This means preview failure does **not** break document export.

## Validation and testing

The document generation path was validated with:

- shared HWPX engine tests
- document export tests
- PDF wiring tests that verify the backend calls the HWPX-first PDF helper

Because the live Hancom COM session is environment-sensitive under automated test execution, the PDF smoke tests were written to verify the HWPX-first wiring deterministically via monkeypatching.

## Alternatives considered

### Playwright / Chromium HTML-to-PDF

Rejected for the final pipeline because it bypasses the generated HWPX and does not reflect the actual document output source of truth.

### Direct print-to-PDF workflow

Potentially viable as a future alternative, but it still depends on Windows printer behavior and was not selected as the primary path.

### Headless server-side document conversion libraries

Not selected because they do not preserve the exact HWPX rendering stack already in use.

## Limitations

- The current renderer depends on Windows and Hancom Office.
- It is not portable to Linux or a Docker-only headless environment without a compatible Hancom runtime.
- COM-based export can be sensitive to desktop/session timing and startup conditions.
- PDF conversion remains a best-effort preview feature; HWPX download remains the guaranteed export path.

## Summary

The backend now follows the required HWPX-first pipeline and exposes a pluggable PDF renderer layer. The chosen implementation uses Hancom Office COM export on Windows, with graceful failure behavior and no impact on HWPX downloads.
