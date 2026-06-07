# Memory Retrieval Benchmark Update (2026-04)

Published: 2026-04-20

Re-running the 2025 benchmark with current-generation embedding models
reverses last year's headline result on mixed corpora: hybrid BM25+embedding
retrieval now beats BM25 alone by 6 points of nDCG@10. However, on purely
identifier-heavy queries, BM25 alone is still ahead — the 2025 finding holds
for that slice.

## Recommendation

Hybrid retrieval is now the recommended default for mixed technical corpora.
Pure BM25 remains correct where queries are dominated by code identifiers.
