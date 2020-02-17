# This file is part of the pyMOR project (http://www.pymor.org).
# Copyright 2013-2020 pyMOR developers and contributors. All rights reserved.
# License: BSD 2-Clause License (http://opensource.org/licenses/BSD-2-Clause)

import numpy as np
import pytest

from pymor.algorithms.eigs import eigs
from pymor.operators.numpy import NumpyMatrixOperator

n_list = [100, 200]
k_list = [1, 7]
which_list = ['LM', 'LR', 'SI']


@pytest.mark.parametrize('n', n_list)
@pytest.mark.parametrize('k', k_list)
@pytest.mark.parametrize('which', which_list)
def test_eigs(n, k, which):
    np.random.seed(0)
    A = np.random.random((n, n))
    i = np.random.randint(n, size=n**2 // 2)
    j = np.random.randint(n, size=n**2 // 2)
    A[i, j] = 0
    Aop = NumpyMatrixOperator(A)
    ew, ev = eigs(Aop, k=k, which=which, tol=0)

    assert np.sum((Aop.apply(ev) - ev * ew).l2_norm()) < 1e-4
