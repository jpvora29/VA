"""Suite-wide test settings."""

import os

# Tests drive chat turns and Studio callbacks; none of them should write usage
# workbooks into the project's usage_metrics/ folder. Tests of the recorder turn it
# back on with monkeypatch.
os.environ.setdefault("USAGE_METRICS", "off")
