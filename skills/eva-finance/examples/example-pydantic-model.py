"""
EVA-Finance Pydantic Model Examples

Real examples extracted from eva-api/app.py showing the standard patterns
for request/response models in the EVA-Finance codebase.

Source: eva-api/app.py
"""

from pydantic import BaseModel, Field
from typing import Optional, Dict, Any


# ------------------------------------
# Raw Message Intake Model
# ------------------------------------
class IntakeMessage(BaseModel):
    """
    Model for incoming raw messages from external sources.

    Used by: POST /intake/message endpoint

    This is the entry point for all data into EVA-Finance.
    Messages come from Reddit ingestion, n8n workflows, or
    other external sources.

    Fields:
    - source: Origin identifier (e.g., "reddit", "n8n", "manual")
    - platform_id: Unique ID from source platform for deduplication
    - timestamp: ISO8601 timestamp when message was created at source
    - text: The actual message content to be processed
    - url: Optional link to original message
    - meta: Flexible dict for source-specific metadata
    """
    source: str
    platform_id: Optional[str] = None
    timestamp: str
    text: str
    url: Optional[str] = None
    meta: Dict[str, Any] = Field(default_factory=dict)


# ------------------------------------
# Processed Message Model
# ------------------------------------
class ProcessedMessage(BaseModel):
    """
    Model for processed/extracted message data.

    Used by: POST /processed endpoint (internal)

    After the LLM or fallback processor extracts entities from
    raw messages, this model captures the structured output.

    Fields:
    - raw_id: FK reference to the original raw_messages record
    - brand: List of brand names mentioned (e.g., ["Nike", "Hoka"])
    - product: List of specific products mentioned
    - category: List of categories (e.g., ["Footwear", "Running Shoes"])
    - sentiment: Detected sentiment level
    - intent: User's apparent intent
    - tickers: Stock tickers if applicable (e.g., ["NKE"])
    - tags: Behavioral tags (e.g., ["brand-switch", "running", "comfort"])

    Sentiment values: strong_positive, positive, neutral, negative, strong_negative
    Intent values: buy, own, recommendation, complaint, none
    """
    raw_id: int
    brand: list[str] = Field(default_factory=list)
    product: list[str] = Field(default_factory=list)
    category: list[str] = Field(default_factory=list)
    sentiment: Optional[str] = None
    intent: Optional[str] = None
    tickers: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)


# ------------------------------------
# Usage Examples
# ------------------------------------
if __name__ == "__main__":
    # Example: Creating an IntakeMessage
    intake = IntakeMessage(
        source="reddit",
        platform_id="reddit_post_abc123",
        timestamp="2026-01-15T10:30:00+00:00",
        text="Just switched from Nike to Hoka and never going back! The comfort is insane.",
        url="https://www.reddit.com/r/running/comments/abc123",
        meta={
            "subreddit": "running",
            "author": "runner123",
            "reddit_id": "abc123",
            "score": 42
        }
    )
    print("IntakeMessage:", intake.model_dump_json(indent=2))

    # Example: Creating a ProcessedMessage
    processed = ProcessedMessage(
        raw_id=1,
        brand=["Nike", "Hoka"],
        product=["running shoes"],
        category=["Footwear", "Running Shoes"],
        sentiment="strong_positive",
        intent="own",
        tickers=["NKE"],
        tags=["brand-switch", "running", "comfort"]
    )
    print("\nProcessedMessage:", processed.model_dump_json(indent=2))

    # Example: Validation
    try:
        # This will fail - missing required fields
        invalid = IntakeMessage(source="test")  # type: ignore
    except Exception as e:
        print(f"\nValidation error (expected): {e}")
