import re
from pathlib import Path

MIGRATIONS = Path(__file__).resolve().parent.parent / "delivery_analysis" / "store" / "migrations"
LATEST_SCHEMA = max(int(m.group(1)) for f in MIGRATIONS.glob("*.sql") if (m := re.match(r"(\d+)_", f.name)))
