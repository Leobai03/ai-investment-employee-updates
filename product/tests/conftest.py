from __future__ import annotations

import os


# Pytest imports modules during collection, so isolate the application before
# any test file can import app.config or app.update_service.
os.environ["AI_RESEARCH_DEMO"] = "1"
os.environ["AI_RESEARCH_DB"] = f"/tmp/ai_research_product_test_{os.getpid()}.db"
os.environ["AI_RESEARCH_WORKSPACE"] = f"/tmp/ai_research_product_workspace_{os.getpid()}"

