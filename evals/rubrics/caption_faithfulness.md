# Rubric: Caption Faithfulness (images / keyframes)

Reference-free, FaithScore-style (claim decomposition vs. the image itself) —
no golden captions required. Consumed by the `eval_llm` judge lane.

## Procedure

1. **Decompose** the caption into atomic, descriptive claims (objects,
   attributes, counts, text content, spatial relations). Ignore pure style.
2. **Verify each claim against the image** (the judge receives the image):
   `supported` | `contradicted` | `not-visible`.
3. **Score** = supported / total claims. `contradicted` claims are listed as
   violations; `not-visible` claims count against the score but are reported
   separately (hallucination vs. over-reach).

## Verdict shape

```json
{"score": 0.0, "pass": false, "claims": [
  {"text": "…", "verdict": "supported|contradicted|not-visible"}
], "rationale": "…"}
```

## Gate

- `pass` requires score ≥ 0.8 **and** zero `contradicted` claims.
- CLIPScore may be logged alongside as a cheap trend signal but never gates
  alone (documented negation/long-caption weaknesses).
