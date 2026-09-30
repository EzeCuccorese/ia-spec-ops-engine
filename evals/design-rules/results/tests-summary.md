# Test-guidance eval summary

## Test-guidance conditions

| condition | runs | test LOC/100 prod LOC | test funcs/run | test violations/run | mutation score | hidden pass rate | mean cost (USD) | mean turns |
|---|---|---|---|---|---|---|---|---|
| tests-none | 9 | 68.1 | 7.0 | 0.00 | 83% | 100% | 0.090 | 3.2 |
| tests-rules | 9 | 75.2 | 3.9 | 0.00 | 82% | 100% | 0.093 | 3.2 |
| tests-gate | 9 | 62.0 | 7.4 | 0.00 | 81% | 100% | 0.120 | 5.0 |
| tests-rules+gate | 9 | 71.5 | 3.4 | 0.00 | 83% | 100% | 0.145 | 8.3 |

### Test decision

- `tests-rules` vs `tests-none`: test LOC/100 prod LOC -10.5% reduction (bar 20%); test violations +0.0% reduction (bar 30%); mutation score drop 0.9 pts (max 5); hidden pass 100% vs 100%. **Decision: drop the guidance on its own.**
- `tests-rules+gate` vs `tests-gate`: test LOC/100 prod LOC -15.4% reduction (bar 20%); test violations +0.0% reduction (bar 30%); mutation score drop -2.2 pts (max 5); hidden pass 100% vs 100%. **Decision: drop the guidance on top of the gate.**

