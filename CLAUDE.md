## EVA Finance: Behavioral Signal Engine

Conversational data → structured financial/behavioral insights.
Local-first, deterministic, traceable.

---

## Code Standards
```python
# Config: Pydantic Settings only
from app.config import settings
db_url = settings.DATABASE_URL

# Logging: structlog (never print)
log = structlog.get_logger()
log.info("signal_created", signal_type="financial", user_id=hash(uid))

# Validation: explicit checks
from pydantic import BaseModel, validator

class Signal(BaseModel):
    confidence: float
    
    @validator('confidence')
    def check_range(cls, v):
        assert 0.0 <= v <= 1.0
        return v

# DB: Context managers, explicit sessions
from app.db import get_session
with get_session() as session:
    result = session.query(Signal).filter_by(id=id).first()
```

---

## Signal Schema

Every signal includes:
- `confidence`: 0.0-1.0 (validated)
- `source_hash`: sha256(source) for lineage
- `extracted_at`: UTC datetime
- `metadata`: Type-specific fields

---

## Privacy Rules

- Hash user IDs before storage/logging
- Financial amounts as integers (cents, not floats)
- UTC timestamps only
- Never log PII (names, emails, account numbers)

---

## Response Style

- **Concise**: Code only unless explanation requested
- **Tradeoffs**: Show constraints and failure modes
- **Comments**: Explain WHY, not WHAT
- **Tests**: Suggest edge cases worth testing
- **Think pipeline**: What happens before/after this step?

Treat this like production infrastructure.

---

## Pre-Commit

Run before ANY commit:
```bash
pytest tests/ && black app/ && mypy app/
grep -r "sk-\|postgresql://" .  # Check for credentials
```