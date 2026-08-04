#!/usr/bin/env python3
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.hwpx_service import validate_hwpx  # noqa: E402

parser = argparse.ArgumentParser(description="HWPX 템플릿 구조와 플레이스홀더를 검사합니다.")
parser.add_argument("path")
parser.add_argument("--type", required=True, choices=["MEAL_PLAN", "COOKING_INSTRUCTION", "PRESERVATION_RECORD"])
args = parser.parse_args()
print(validate_hwpx(args.path, args.type))
