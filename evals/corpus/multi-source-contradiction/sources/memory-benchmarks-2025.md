# Memory Retrieval Benchmark Results (2025-09)

Published: 2025-09-12

Our 2025 benchmark run found that BM25 retrieval outperformed dense embedding
retrieval on technical-documentation corpora by 11 points of nDCG@10. Dense
retrievers degraded sharply on identifier-heavy queries (function names,
config keys), where lexical matching dominated.

## Recommendation

For technical wikis under ~1,000 pages, BM25 remains the recommended default
ranker. Embedding rankers should be reserved for natural-language-heavy
corpora.
