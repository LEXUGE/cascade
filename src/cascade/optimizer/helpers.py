"""
Helper functions for defining log-normal based probabilistic objective function
"""

from typing import Callable, Optional
from scipy.stats import lognorm
import scipy.integrate as integrate
from .piecewise_functions.piecewise_linear_function import (
    PiecewiseLinearFunction,
)
import numpy as np


def lognorm_params(mu_X: int, sigma_X: int):
    """
    This produces the parameters of a log-normal distribution whose mean is mu_X and std. is sigma_X
    """
    # sigma_X = sqrt(exp(sigma^2) - 1) * mu_X where sigma is the parameter of the distribution
    s = np.sqrt(np.log(1 + (sigma_X / mu_X) ** 2))
    scale = mu_X / np.exp(s**2 / 2)
    # parameter mu of log-normal will be log(scale)

    return s, scale


def piecewise_linear_objective(
    mu_X: int,
    sigma_X: int,
    priority: int,
    total_slots: int,
    stepsize: Optional[int] = None,
    yscale: int = 100,
    integrated: bool = False,
) -> PiecewiseLinearFunction:
    stepsize = stepsize or max(mu_X // 2, 1)

    if sigma_X == 0:
        obj_fn_prime = np.vectorize(lambda x: 0 if x < mu_X else 1)
    else:
        s, scale = lognorm_params(mu_X, sigma_X)
        obj_fn_prime = lambda x: lognorm.cdf(x, s, scale=scale)

    if integrated:
        obj_fn = np.vectorize(lambda t: integrate.quad(obj_fn_prime, 0, t)[0])
    else:
        obj_fn = obj_fn_prime
    # Total length is basically the length of the schedule
    xs = np.arange(0, total_slots + 1, stepsize)
    ys = np.round(obj_fn(xs) * priority * yscale)

    return PiecewiseLinearFunction(xs=xs.tolist(), ys=ys.tolist())
