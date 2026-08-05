"""Make the bronze pipeline module importable for unit tests.

The bronze source lives under the Lakeflow pipeline glob (`src/ingest/bronze/`) and
is not a package, so put its directory on the path. Importing it is safe off-cluster:
its pipeline-registration block is guarded on pyspark + an injected `spark` global,
neither of which exists here, so only the pure helper functions load.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src" / "ingest" / "bronze"))
