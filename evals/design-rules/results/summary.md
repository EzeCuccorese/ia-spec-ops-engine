# Design-rules eval summary

| condition | runs | violations/100 lines | hidden pass rate | mean cost (USD) | mean turns |
|---|---|---|---|---|---|
| none | 9 | 0.46 | 100% | 0.211 | 10.8 |
| rules | 9 | 0.16 | 100% | 0.330 | 13.4 |
| gate | 9 | 0.00 | 100% | 0.357 | 16.6 |
| rules+gate | 9 | 0.04 | 100% | 0.369 | 14.6 |

## Violations per 100 added lines, by metric

- **none**: {'complexity': 0.092, 'nesting': 0.046, 'args': 0.185, 'empty-catch': 0.139}
- **rules**: {'args': 0.156}
- **gate**: {}
- **rules+gate**: {'args': 0.044}

## Decision

- `rules` vs `none`: violations/100 lines reduced by 66.3% (meets the 30% bar); pass rate 100% vs 100%. **Decision: keep the text rules on their own.**
- `rules+gate` vs `gate`: violations/100 lines reduced by 0.0%; turns 14.6 vs 16.6, cost $0.369 vs $0.357. **Decision: rules are worth it on top of the gate.**

