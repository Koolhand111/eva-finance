"""
AI Approval Agent for EVA-Finance Recommendations

Uses LLM to evaluate recommendation quality and decide if notification-worthy.
"""

import os
import json
from pathlib import Path
from typing import Dict, Optional


def evaluate_recommendation(
    markdown_path: str,
    evidence_path: str,
    brand: str,
    tag: str,
    final_confidence: Optional[float],
    openai_api_key: Optional[str] = None
) -> Dict:
    """
    Use LLM to evaluate if recommendation is notification-worthy.

    Args:
        markdown_path: Path to human-readable recommendation markdown
        evidence_path: Path to evidence.json.gz bundle
        brand: Brand name from signal
        tag: Behavioral tag from signal
        final_confidence: Numeric confidence score (0-1), may be None
        openai_api_key: OpenAI API key (defaults to env var)

    Returns:
        {
            "approved": bool,
            "confidence": float,  # LLM's confidence in its decision
            "reasoning": str,
            "method": "ai"
        }
    """

    # Read markdown summary
    try:
        with open(markdown_path, 'r', encoding='utf-8') as f:
            markdown_content = f.read()
    except Exception as e:
        return {
            "approved": False,
            "confidence": 0.0,
            "reasoning": f"Failed to read markdown: {str(e)}",
            "method": "ai"
        }

    # Get API key
    api_key = openai_api_key or os.getenv('OPENAI_API_KEY')
    if not api_key:
        # Fall back to simple approval if no API key
        return evaluate_recommendation_simple(brand, tag, final_confidence)

    # Build evaluation prompt
    confidence_text = f"{final_confidence:.2f}" if final_confidence is not None else "N/A"

    prompt = f"""You are an expert financial analyst reviewing a behavioral trend signal for EVA-Finance.

Your task: Decide if this recommendation is strong enough to notify human analysts.

BRAND: {brand}
TAG (Behavior): {tag}
SYSTEM CONFIDENCE: {confidence_text}

RECOMMENDATION REPORT:
{markdown_content}

EVALUATION CRITERIA:
1. Evidence Quality: Is the evidence compelling and from credible sources?
2. Trend Authenticity: Does this represent a genuine trend vs random noise or spam?
3. Signal Strength: Is the confidence score justified by the supporting data?
4. Actionability: Would an analyst find this interesting and actionable?
5. Coherence: Does the narrative make logical sense?

DECISION GUIDELINES:
- APPROVE if: Strong evidence, clear trend, high confidence, actionable insight
- REJECT if: Weak evidence, unclear pattern, low quality data, not actionable
- When in doubt, prefer false negatives (reject) over false positives (approve)

Respond in JSON format:
{{
    "approved": true or false,
    "confidence": 0.0-1.0 (your confidence in this decision),
    "reasoning": "2-3 sentence explanation of your decision, citing specific evidence"
}}
"""

    # Call OpenAI
    try:
        import openai

        client = openai.OpenAI(api_key=api_key)
        response = client.chat.completions.create(
            model="gpt-4o-mini",  # Fast and cost-effective
            messages=[
                {
                    "role": "system",
                    "content": "You are a senior financial analyst AI specializing in behavioral trend signals. You make conservative, evidence-based decisions."
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            temperature=0.2,  # Lower temp for consistent, conservative decisions
            response_format={"type": "json_object"}
        )

        result = json.loads(response.choices[0].message.content)
        result["method"] = "ai"

        # Validate response structure
        if not all(k in result for k in ["approved", "confidence", "reasoning"]):
            raise ValueError("LLM response missing required fields")

        # Validate types
        result["approved"] = bool(result["approved"])
        result["confidence"] = float(result["confidence"])
        result["reasoning"] = str(result["reasoning"])

        return result

    except Exception as e:
        # Fall back to simple approval on any error
        fallback = evaluate_recommendation_simple(brand, tag, final_confidence)
        fallback["reasoning"] = f"AI approval failed ({str(e)}), using fallback: {fallback['reasoning']}"
        return fallback


def evaluate_recommendation_simple(
    brand: str,
    tag: str,
    final_confidence: Optional[float]
) -> Dict:
    """
    Fallback: Simple rule-based approval if AI fails.

    Auto-approve only very high confidence signals.
    """
    if final_confidence is None:
        approved = False
        reasoning = "No confidence score available, rejecting by default"
    else:
        approved = final_confidence >= 0.85
        reasoning = f"Rule-based approval: confidence {final_confidence:.2f} {'≥' if approved else '<'} 0.85 threshold"

    return {
        "approved": approved,
        "confidence": 1.0 if approved else 0.0,
        "reasoning": reasoning,
        "method": "auto"
    }
