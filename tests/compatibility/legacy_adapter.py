"""Narrow, isolated loader for the frozen legacy reference.

The adapter imports no live application data. It suppresses only the legacy
module's import-time logging setup and exposes the module for synthetic pure
contract probes in later milestones.
"""

import logging
from pathlib import Path
import types
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[2]
LEGACY_SOURCE = PROJECT_ROOT / "legacy" / "profile_manager.py"


def load_legacy():
    module = types.ModuleType("legacy_refactor_adapter")
    module.__file__ = str(LEGACY_SOURCE)
    source = LEGACY_SOURCE.read_text(encoding="utf-8")
    with patch.object(Path, "mkdir"), patch.object(logging, "FileHandler"), patch.object(
        logging, "basicConfig"
    ):
        exec(compile(source, str(LEGACY_SOURCE), "exec"), module.__dict__)
    return module

