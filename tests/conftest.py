"""Suite-wide fixtures: the whole test run enforces cross-skill schema contracts.

Production runs default to ``YAOBI_CONTRACT_MODE=warn`` (violations are counted and
audited, never crash a clinical request). CI/tests run in ``enforce`` so any contract
drift — a renamed field, a type change, a missing required key — fails loudly here
instead of silently corrupting downstream reasoning in production.
"""

from __future__ import annotations

import os

os.environ.setdefault("YAOBI_CONTRACT_MODE", "enforce")
