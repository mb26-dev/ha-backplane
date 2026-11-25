"""Load the Backplane modules that do not depend on Home Assistant."""

import sys
import types
from pathlib import Path

PKG = Path(__file__).resolve().parents[1] / "custom_components" / "backplane"
package = types.ModuleType("backplane")
package.__path__ = [str(PKG)]
sys.modules.setdefault("backplane", package)
