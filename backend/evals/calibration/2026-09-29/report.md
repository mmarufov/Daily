# Judge vs human adjudication

Reviewed 298 of 300 sampled rows (2 skipped) by mmarufov. Median 11.0s per row, 73 minutes total. Bootstrap B=2000, seed 20260929.

## Model judge (final two-pass verdict)

| scope | agreement | kappa | 95% CI | linear-weighted kappa |
|---|---|---|---|---|
| sample | 0.785 | 0.671 | 0.604 to 0.737 | 0.735 |
| population_weighted | 0.840 | 0.682 | 0.565 to 0.789 | 0.718 |

| class | precision (sample) | recall (sample) | precision (weighted) | recall (weighted) |
|---|---|---|---|---|
| must_see | 0.791 | 0.716 | 0.834 | 0.431 |
| fine | 0.683 | 0.774 | 0.628 | 0.912 |
| never | 0.892 | 0.839 | 0.972 | 0.856 |

Confusion (sample counts, rows = human, columns = judge):

| human \ judge | must_see | fine | never |
|---|---|---|---|
| must_see | 53 | 20 | 1 |
| fine | 13 | 82 | 11 |
| never | 1 | 18 | 99 |

| stratum | reviewed | population | agreement |
|---|---|---|---|
| fine/contested | 55 | 340 | 0.636 |
| fine/escalated | 29 | 132 | 0.862 |
| fine/pass1_only | 36 | 1981 | 0.611 |
| must_see/contested | 7 | 7 | 0.286 |
| must_see/escalated | 60 | 235 | 0.850 |
| never/contested | 40 | 47 | 0.725 |
| never/escalated | 36 | 496 | 1.000 |
| never/pass1_only | 35 | 3414 | 0.971 |

## Effective labels (agent overrides applied; what evals score against)

| scope | agreement | kappa | 95% CI | linear-weighted kappa |
|---|---|---|---|---|
| sample | 0.789 | 0.671 | 0.608 to 0.739 | 0.725 |
| population_weighted | 0.840 | 0.676 | 0.559 to 0.785 | 0.709 |

| class | precision (sample) | recall (sample) | precision (weighted) | recall (weighted) |
|---|---|---|---|---|
| must_see | 0.949 | 0.500 | 0.967 | 0.312 |
| fine | 0.660 | 0.877 | 0.625 | 0.920 |
| never | 0.890 | 0.890 | 0.967 | 0.864 |

Confusion (sample counts, rows = human, columns = judge):

| human \ judge | must_see | fine | never |
|---|---|---|---|
| must_see | 37 | 36 | 1 |
| fine | 1 | 93 | 12 |
| never | 1 | 12 | 105 |

| stratum | reviewed | population | agreement |
|---|---|---|---|
| fine/contested | 55 | 340 | 0.727 |
| fine/escalated | 29 | 132 | 0.862 |
| fine/pass1_only | 36 | 1981 | 0.611 |
| must_see/contested | 7 | 7 | 0.857 |
| must_see/escalated | 60 | 235 | 0.667 |
| never/contested | 40 | 47 | 0.800 |
| never/escalated | 36 | 496 | 1.000 |
| never/pass1_only | 35 | 3414 | 0.971 |

## Intra-rater (reviewer against themself)

Re-pass not done yet.

