"""Import ALL sample-document catalogs into Postgres (Solh + prisoner requests).

Run on the server (inside backend container or on host with DB access):

  docker exec -it yourLawyer_fastapi_app python scripts/import_sample_catalog.py

Or for one type only:

  docker exec -it yourLawyer_fastapi_app python scripts/import_sample_catalog.py --doc-type prisoner_request

Prerequisites:
  - Table sample_documents exists (created on API startup via create_all)
  - PDF folders under /app/data (mounted from host ./data):
      outputs_solh_* /
      outputs_prisoner_requests/  (+ *_index.json)
"""

from __future__ import annotations

import runpy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Reuse the existing importer entrypoint
if __name__ == "__main__":
    runpy.run_path(str(ROOT / "scripts" / "import_solh_catalog.py"), run_name="__main__")
