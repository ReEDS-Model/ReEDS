import numpy as np
import pandas as pd

from reeds.resource_adequacy.stress_periods import calc_neue_stderr


def test_calc_neue_stderr_normalizes_sample_sem_by_total_load():
    shortfall_samples = pd.DataFrame({
        'r1': [1, 3, 5],
        'r2': [2, 2, 2],
    })
    load = pd.DataFrame({
        'r1': [10, 10],
        'r2': [5, 5],
    })

    stderr = calc_neue_stderr(shortfall_samples, load)

    np.testing.assert_allclose(stderr['r1'], 2 / np.sqrt(3) / 20 * 1e6)
    np.testing.assert_allclose(stderr['r2'], 0)
