## 2. Learning curve (RF, system layer, 10-fold OOF, 5 repeats)

At the full n = 486 the mean / median OOF R-squared is 0.752 / 0.880 (repeat 0 is the draft seed; the five fold-assignment seeds span 0.748-0.756 mean and 0.873-0.884 median), with 29.2 outputs at R-squared >= 0.9 on average (range 29-30).
With n = 50 runs the OOF mean / median R-squared is 0.455 / 0.531 (repeat spread 0.418-0.529 on the mean) and 2.8 outputs reach R-squared >= 0.9 (range 1-5); scored on the 436 undrawn runs the mean R-squared is 0.499 (pooled-variance R-squared).
With n = 100 runs the OOF mean / median R-squared is 0.555 / 0.677 (repeat spread 0.505-0.597 on the mean) and 11.2 outputs reach R-squared >= 0.9 (range 9-13); scored on the 386 undrawn runs the mean R-squared is 0.610 (pooled-variance R-squared).
With n = 150 runs the OOF mean / median R-squared is 0.626 / 0.743 (repeat spread 0.591-0.645 on the mean) and 15.2 outputs reach R-squared >= 0.9 (range 13-17); scored on the 336 undrawn runs the mean R-squared is 0.651 (pooled-variance R-squared).
With n = 200 runs the OOF mean / median R-squared is 0.666 / 0.789 (repeat spread 0.661-0.671 on the mean) and 19.4 outputs reach R-squared >= 0.9 (range 18-21); scored on the 286 undrawn runs the mean R-squared is 0.676 (pooled-variance R-squared).
With n = 300 runs the OOF mean / median R-squared is 0.695 / 0.822 (repeat spread 0.679-0.718 on the mean) and 22.4 outputs reach R-squared >= 0.9 (range 21-24); scored on the 186 undrawn runs the mean R-squared is 0.706 (pooled-variance R-squared).
With n = 400 runs the OOF mean / median R-squared is 0.734 / 0.872 (repeat spread 0.717-0.757 on the mean) and 28.0 outputs reach R-squared >= 0.9 (range 27-29); scored on the 86 undrawn runs the mean R-squared is 0.785 (pooled-variance R-squared).
Half of the R-squared gain between n = 50 and n = 486 is reached by n = 150, and n = 400 is the first size within 5 % of the full-table mean R-squared; the curve has not flattened at 486, so a national design with more dials should expect to need more than 486 runs for the same per-output accuracy.

Per-size summary (mean over 5 repeats; min-max in the CSV):

| eval | n | r2_mean | r2_mean_sd | r2_median | r2_median_sd | n_ge_0_9 |
|---|---|---|---|---|---|---|
| external | 50 | 0.499 | 0.037 | 0.566 | 0.069 | 2.600 |
| external | 100 | 0.610 | 0.015 | 0.716 | 0.046 | 11.200 |
| external | 150 | 0.651 | 0.025 | 0.785 | 0.036 | 16.200 |
| external | 200 | 0.676 | 0.038 | 0.830 | 0.023 | 20.200 |
| external | 300 | 0.706 | 0.026 | 0.867 | 0.032 | 26.400 |
| external | 400 | 0.785 | 0.017 | 0.896 | 0.014 | 32.000 |
| oof | 50 | 0.455 | 0.049 | 0.531 | 0.076 | 2.800 |
| oof | 100 | 0.555 | 0.036 | 0.677 | 0.025 | 11.200 |
| oof | 150 | 0.626 | 0.023 | 0.743 | 0.031 | 15.200 |
| oof | 200 | 0.666 | 0.005 | 0.789 | 0.028 | 19.400 |
| oof | 300 | 0.695 | 0.017 | 0.822 | 0.031 | 22.400 |
| oof | 400 | 0.734 | 0.014 | 0.872 | 0.006 | 28.000 |
| oof | 486 | 0.752 | 0.003 | 0.880 | 0.005 | 29.200 |

Figure: figs/fig02_learning_curve (shaded = min-max over 5 repeats).
