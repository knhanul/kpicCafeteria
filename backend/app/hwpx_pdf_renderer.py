from __future__ import annotations

import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
import sys


class HwpxPdfRenderError(RuntimeError):
    pass


class HwpxPdfRenderer(Protocol):
    def render(self, hwpx_bytes: bytes, *, source_name: str = "document.hwpx") -> bytes:
        raise NotImplementedError


@dataclass(slots=True)
class HancomComPdfRenderer:
    printer_name: str = "Hancom PDF"
    visible: bool = False
    security_module_name: str = "FilePathCheckerModule"

    def render(self, hwpx_bytes: bytes, *, source_name: str = "document.hwpx") -> bytes:
        temp_dir = Path(tempfile.mkdtemp(prefix="hwpx_pdf_"))
        try:
            hwpx_path = temp_dir / Path(source_name).name
            if hwpx_path.suffix.lower() != ".hwpx":
                hwpx_path = hwpx_path.with_suffix(".hwpx")
            pdf_path = hwpx_path.with_suffix(".pdf")
            hwpx_path.write_bytes(hwpx_bytes)

            self._convert_in_subprocess(hwpx_path, pdf_path)

            if not pdf_path.exists():
                raise HwpxPdfRenderError("PDF 파일이 생성되지 않았습니다.")
            pdf_bytes = pdf_path.read_bytes()
            if not pdf_bytes.startswith(b"%PDF"):
                raise HwpxPdfRenderError("생성 결과가 PDF 형식이 아닙니다.")
            return pdf_bytes
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def _configure_window(self, hwp) -> None:
        try:
            hwp.XHwpWindows.Item(0).Visible = self.visible
        except Exception:
            pass

    def _register_security_module(self, hwp) -> None:
        try:
            hwp.RegisterModule("FilePathCheckDLL", self.security_module_name)
        except Exception:
            pass

    def _open_document(self, hwp, hwpx_path: Path) -> bool:
        attempts = [
            ("HWPX", "forceopen:true;versionwarning:false;"),
            ("", "forceopen:true;versionwarning:false;"),
            ("", ""),
        ]
        last_exc: Exception | None = None
        for fmt, arg in attempts:
            try:
                if hwp.Open(str(hwpx_path), fmt, arg):
                    return True
            except Exception as exc:
                last_exc = exc
        if last_exc is not None:
            raise HwpxPdfRenderError(f"HWPX 문서를 여는 중 오류가 발생했습니다: {last_exc}") from last_exc
        return False

    def _save_as_pdf(self, hwp, pdf_path: Path) -> bool:
        try:
            return bool(hwp.SaveAs(str(pdf_path), "PDF", ""))
        except Exception as exc:
            raise HwpxPdfRenderError(f"PDF 저장 중 오류가 발생했습니다: {exc}") from exc

    def _convert_in_subprocess(self, hwpx_path: Path, pdf_path: Path) -> None:
        helper_script = r'''
import sys
import time

try:
    import pythoncom
except Exception:
    pythoncom = None

try:
    import win32com.client
except Exception as exc:
    print(f"WIN32COM_IMPORT_ERROR: {exc}", file=sys.stderr)
    raise SystemExit(2)

src = sys.argv[1]
dst = sys.argv[2]
hwp = None
try:
    if pythoncom is not None:
        pythoncom.CoInitialize()
    hwp = win32com.client.Dispatch("HWPFrame.HwpObject")
    try:
        hwp.RegisterModule("FilePathCheckDLL", "FilePathCheckerModule")
    except Exception:
        pass
    try:
        hwp.XHwpWindows.Item(0).Visible = False
    except Exception:
        pass
    opened = False
    last_error = None
    for attempt in range(5):
        try:
            opened = bool(hwp.Open(src, "HWPX", "forceopen:true;versionwarning:false;"))
            if opened:
                break
        except Exception as exc:
            last_error = exc
        time.sleep(1)
    if not opened:
        if last_error is not None:
            raise last_error
        print("OPEN_RETURNED_FALSE", file=sys.stderr)
        raise SystemExit(3)
    saved = False
    last_error = None
    for attempt in range(5):
        try:
            saved = bool(hwp.SaveAs(dst, "PDF", ""))
            if saved:
                break
        except Exception as exc:
            last_error = exc
        time.sleep(1)
    if not saved:
        if last_error is not None:
            raise last_error
        print("SAVEAS_RETURNED_FALSE", file=sys.stderr)
        raise SystemExit(4)
finally:
    try:
        if hwp is not None:
            hwp.Quit()
    except Exception:
        pass
    if pythoncom is not None:
        try:
            pythoncom.CoUninitialize()
        except Exception:
            pass
'''
        result = subprocess.run(
            [sys.executable, "-c", helper_script, str(hwpx_path), str(pdf_path)],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            message = result.stderr.strip() or result.stdout.strip() or "알 수 없는 HWP PDF 변환 오류"
            raise HwpxPdfRenderError(f"HWPX를 PDF로 변환하지 못했습니다: {message}")


def default_pdf_renderer() -> HwpxPdfRenderer:
    return HancomComPdfRenderer()
