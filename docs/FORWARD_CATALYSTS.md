# Forward catalysts / v1.3.0
This is a presentation/API promotion of the existing outlook research engine, not a newly trained prediction model.

GET /api/v1/catalysts/state: existing local cache by price snapshot. No paid research or SEC fetch.
POST /api/v1/catalysts/analyze: strict schema; requires explicit paid consent + same-origin token; fixed catalysts scope; delegates to ResearchService.analyze_outlook.

Source linkage, issuer checks, date validation, 180-day horizon, source conflicts and unknown dates reuse the existing outlook/source-schedule parsers. This checks structure and provenance, not the semantic truth of an AI claim. New display helper forwardInsight prioritizes linked company-specific positive/negative conditions and adds the question to inspect after the announcement. Missing sources or conflicting dates are not upgraded into facts.

The SEC dilution/contact routes and direct client are removed. Thesis uses a separate local WatchStore without email or SEC methods. The original cache directory is retained to preserve past thesis research.

No new automatic calls, webhook/watch process, trade advice, probability, price target or hidden retries.
