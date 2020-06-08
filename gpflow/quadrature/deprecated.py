# Copyright 2017-2018 the GPflow authors.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import itertools
from collections.abc import Iterable

import numpy as np
import tensorflow as tf

from .config import default_float
from .utilities import to_default_float

from .gaussian_quadrature import NDDiagGHQuadrature


def hermgauss(n: int):
    x, w = np.polynomial.hermite.hermgauss(n)
    x, w = x.astype(default_float()), w.astype(default_float())
    return x, w


def mvhermgauss(H: int, D: int):
    """
    Return the evaluation locations 'xn', and weights 'wn' for a multivariate
    Gauss-Hermite quadrature.

    The outputs can be used to approximate the following type of integral:
    int exp(-x)*f(x) dx ~ sum_i w[i,:]*f(x[i,:])

    :param H: Number of Gauss-Hermite evaluation points.
    :param D: Number of input dimensions. Needs to be known at call-time.
    :return: eval_locations 'x' (H**DxD), weights 'w' (H**D)
    """
    gh_x, gh_w = hermgauss(H)
    x = np.array(list(itertools.product(*(gh_x,) * D)))  # H**DxD
    w = np.prod(np.array(list(itertools.product(*(gh_w,) * D))), 1)  # H**D
    return x, w


def mvnquad(func, means, covs, H: int, Din: int = None, Dout=None):
    """
    Computes N Gaussian expectation integrals of a single function 'f'
    using Gauss-Hermite quadrature.
    :param f: integrand function. Takes one input of shape ?xD.
    :param means: NxD
    :param covs: NxDxD
    :param H: Number of Gauss-Hermite evaluation points.
    :param Din: Number of input dimensions. Needs to be known at call-time.
    :param Dout: Number of output dimensions. Defaults to (). Dout is assumed
    to leave out the item index, i.e. f actually maps (?xD)->(?x*Dout).
    :return: quadratures (N,*Dout)
    """
    # Figure out input shape information
    if Din is None:
        Din = means.shape[1]

    if Din is None:
        raise ValueError(
            "If `Din` is passed as `None`, `means` must have a known shape. "
            "Running mvnquad in `autoflow` without specifying `Din` and `Dout` "
            "is problematic. Consider using your own session."
        )  # pragma: no cover

    xn, wn = mvhermgauss(H, Din)
    N = means.shape[0]

    # transform points based on Gaussian parameters
    cholXcov = tf.linalg.cholesky(covs)  # NxDxD
    Xt = tf.linalg.matmul(
        cholXcov, tf.tile(xn[None, :, :], (N, 1, 1)), transpose_b=True
    )  # NxDxH**D
    X = 2.0 ** 0.5 * Xt + tf.expand_dims(means, 2)  # NxDxH**D
    Xr = tf.reshape(tf.transpose(X, [2, 0, 1]), (-1, Din))  # (H**D*N)xD

    # perform quadrature
    fevals = func(Xr)
    if Dout is None:
        Dout = tuple((d if type(d) is int else d.value) for d in fevals.shape[1:])

    if any([d is None for d in Dout]):
        raise ValueError(
            "If `Dout` is passed as `None`, the output of `func` must have known "
            "shape. Running mvnquad in `autoflow` without specifying `Din` and `Dout` "
            "is problematic. Consider using your own session."
        )  # pragma: no cover
    fX = tf.reshape(fevals, (H ** Din, N,) + Dout)
    wr = np.reshape(wn * np.pi ** (-Din * 0.5), (-1,) + (1,) * (1 + len(Dout)))
    return tf.reduce_sum(fX * wr, 0)


def ndiagquad(funcs, H: int, Fmu, Fvar, logspace: bool = False, **Ys):
    """
    Computes N Gaussian expectation integrals of one or more functions
    using Gauss-Hermite quadrature. The Gaussians must be independent.

    The means and variances of the Gaussians are specified by Fmu and Fvar.
    The N-integrals are assumed to be taken wrt the last dimensions of Fmu, Fvar.

    :param funcs: the integrand(s):
        Callable or Iterable of Callables that operates elementwise
    :param H: number of Gauss-Hermite quadrature points
    :param Fmu: array/tensor or `Din`-tuple/list thereof
    :param Fvar: array/tensor or `Din`-tuple/list thereof
    :param logspace: if True, funcs are the log-integrands and this calculates
        the log-expectation of exp(funcs)
    :param **Ys: arrays/tensors; deterministic arguments to be passed by name

    Fmu, Fvar, Ys should all have same shape, with overall size `N`
    :return: shape is the same as that of the first Fmu
    """
    n_gh = H
    if isinstance(Fmu, (tuple, list)):
        dim = len(Fmu)
        Fmu = tf.stack(Fmu, axis=-1)
        Fvar = tf.stack(Fvar, axis=-1)
    else:
        dim = 1

    quadrature = NDDiagGHQuadrature(dim, n_gh)
    if logspace:
        return quadrature.logspace(funcs, Fmu, Fvar, **Ys)
    return quadrature(funcs, Fmu, Fvar, **Ys)
