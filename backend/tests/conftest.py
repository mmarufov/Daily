"""Install import-time stubs before any test module is imported.

Eight test modules each open with their own `if "openai" not in sys.modules:`
block, installing slightly different stubs. Whichever module pytest imported
first won, so the suite's behaviour depended on collection order and adding a
test could break an unrelated one. pytest imports `conftest.py` before any test
module, so installing the complete set here makes every module's own guard a
no-op and the environment identical regardless of order.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import tests._app_stubs  # noqa: F401,E402  (import for side effects)
