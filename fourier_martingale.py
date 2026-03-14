"""
Fourier Transformation of Martingales: Quantitative Finance Engine
===================================================================
Version 2.0

A production-grade quantitative finance engine implementing Fourier-based option
pricing, volatility surface calibration, and risk analytics. Designed for quant
researchers at systematic trading firms.

Models Implemented
------------------
1. Black-Scholes-Merton (BSM) — Log-normal diffusion baseline
2. Heston Stochastic Volatility — CIR variance process with leverage effect
3. Variance Gamma (VG) — Time-changed Brownian motion by Gamma subordinator
4. CGMY (Carr-Geman-Madan-Yor) — Tempered stable Lévy process
5. Normal Inverse Gaussian (NIG) — Inverse Gaussian subordinated Brownian motion
6. Merton Jump-Diffusion (MJD) — Diffusion plus compound Poisson jumps

Pricing Methods
---------------
1. Carr-Madan (1999) FFT — O(N log N) dampened Fourier inversion via FFT
2. Fang-Oosterlee (2008) COS — O(N) Fourier-cosine expansion method
3. Gil-Pelaez inversion — Direct numerical integration for CDF/density

Applications
------------
- Calibration of stochastic models to implied volatility surfaces
- CVaR / VaR risk metrics via Fourier inversion of characteristic functions
- Greeks computation (Delta, Gamma, Theta) via finite differences on FFT prices
- Martingale condition verification for all models
"""
from __future__ import annotations

import warnings
warnings.filterwarnings("ignore")

import numpy as np
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional
from scipy.stats import norm
from scipy.fft import fft
from scipy import integrate, optimize, special


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 2: DATA STRUCTURES
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class MarketData:
    """Container for market observables used in model calibration.

    Parameters
    ----------
    S : float
        Current spot price of the underlying asset.
    r : float
        Continuously compounded risk-free interest rate.
    q : float
        Continuously compounded dividend yield.
    T : float
        Time to expiry in years.
    strikes : np.ndarray
        Array of option strike prices.
    market_vols : np.ndarray
        Array of Black-Scholes implied volatilities corresponding to strikes.

    Properties
    ----------
    F : float
        Forward price F = S * exp((r - q) * T).
    market_prices : np.ndarray
        Call option prices computed from market_vols via BSM formula.
    """
    S: float
    r: float
    q: float
    T: float
    strikes: np.ndarray
    market_vols: np.ndarray

    @property
    def F(self) -> float:
        """Forward price: F = S * exp((r - q) * T)."""
        return self.S * np.exp((self.r - self.q) * self.T)

    @property
    def market_prices(self) -> np.ndarray:
        """Call prices from implied vols using the BSM formula."""
        return np.array([
            bsm_call(self.S, K, self.r, self.q, self.T, sigma)
            for K, sigma in zip(self.strikes, self.market_vols)
        ])


@dataclass
class CalibrationResult:
    """Results container for model calibration.

    Parameters
    ----------
    model_name : str
        Name of the calibrated model.
    params : dict
        Optimized model parameters.
    rmse : float
        Root mean square error of implied vol fit.
    max_error : float
        Maximum absolute implied vol error across strikes.
    avg_relative_error : float
        Average relative error |model_vol - market_vol| / market_vol.
    n_iterations : int
        Number of objective function evaluations.
    success : bool
        Whether the optimizer reported convergence.
    fitted_vols : np.ndarray
        Model-implied volatilities at calibration strikes.
    """
    model_name: str
    params: dict
    rmse: float
    max_error: float
    avg_relative_error: float
    n_iterations: int
    success: bool
    fitted_vols: np.ndarray = field(default_factory=lambda: np.array([]))

    def summary(self) -> str:
        """Return a formatted multi-line summary of calibration results.

        Returns
        -------
        str
            Box-formatted summary with all fields shown to 6 decimal places.
        """
        lines = []
        width = 60
        lines.append("=" * width)
        lines.append(f"  Calibration Result: {self.model_name}")
        lines.append("=" * width)
        lines.append(f"  Success:            {self.success}")
        lines.append(f"  Iterations:         {self.n_iterations}")
        lines.append(f"  RMSE:               {self.rmse:.6f}")
        lines.append(f"  Max Error:          {self.max_error:.6f}")
        lines.append(f"  Avg Relative Error: {self.avg_relative_error:.6f}")
        lines.append("  Parameters:")
        for k, v in self.params.items():
            lines.append(f"    {k:20s} = {v:.6f}")
        lines.append("=" * width)
        return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 3: UTILITY FUNCTIONS
# ─────────────────────────────────────────────────────────────────────────────

def bsm_call(S: float, K: float, r: float, q: float, T: float, sigma: float) -> float:
    """Black-Scholes-Merton European call option price.

    Parameters
    ----------
    S : float
        Spot price.
    K : float
        Strike price.
    r : float
        Risk-free rate.
    q : float
        Dividend yield.
    T : float
        Time to expiry in years.
    sigma : float
        Volatility (annualized).

    Returns
    -------
    float
        Call option price C = S*exp(-qT)*N(d1) - K*exp(-rT)*N(d2).

    Notes
    -----
    Formula: d1 = [log(S/K) + (r - q + sigma^2/2)*T] / (sigma*sqrt(T))
             d2 = d1 - sigma*sqrt(T)

    Reference: Black, F. & Scholes, M. (1973).
    """
    if T <= 0 or sigma <= 0:
        return max(S * np.exp(-q * T) - K * np.exp(-r * T), 0.0)
    d1 = (np.log(S / K) + (r - q + 0.5 * sigma ** 2) * T) / (sigma * np.sqrt(T))
    d2 = d1 - sigma * np.sqrt(T)
    return S * np.exp(-q * T) * norm.cdf(d1) - K * np.exp(-r * T) * norm.cdf(d2)


def bsm_vega(S: float, K: float, r: float, q: float, T: float, sigma: float) -> float:
    """Black-Scholes-Merton vega: dC/d(sigma).

    Parameters
    ----------
    S, K, r, q, T, sigma : float
        Standard BSM parameters.

    Returns
    -------
    float
        Vega = S * exp(-qT) * N'(d1) * sqrt(T).

    Reference: Hull, J.C. (2018). Options, Futures, and Other Derivatives.
    """
    if T <= 0 or sigma <= 0:
        return 0.0
    d1 = (np.log(S / K) + (r - q + 0.5 * sigma ** 2) * T) / (sigma * np.sqrt(T))
    return S * np.exp(-q * T) * norm.pdf(d1) * np.sqrt(T)


def implied_vol(S: float, K: float, r: float, q: float, T: float,
                price: float, tol: float = 1e-8, max_iter: int = 200) -> float:
    """Newton-Raphson implied volatility solver.

    Parameters
    ----------
    S, K, r, q, T : float
        Standard BSM parameters.
    price : float
        Observed option price to invert.
    tol : float
        Convergence tolerance on price difference.
    max_iter : int
        Maximum Newton-Raphson iterations.

    Returns
    -------
    float
        Implied volatility, or np.nan if solver fails.

    Notes
    -----
    Uses Newton's method: sigma_{n+1} = sigma_n - (C(sigma_n) - price) / vega(sigma_n).
    Initial guess: sigma_0 = 0.2.

    Reference: Jäckel, P. (2015). Let's Be Rational.
    """
    sigma = 0.2
    for _ in range(max_iter):
        p = bsm_call(S, K, r, q, T, sigma)
        v = bsm_vega(S, K, r, q, T, sigma)
        if abs(v) < 1e-12:
            break
        sigma -= (p - price) / v
        if sigma < 1e-6:
            sigma = 1e-6
        if abs(p - price) < tol:
            break
    if sigma < 1e-4 or sigma > 10.0:
        return np.nan
    return sigma


def risk_neutral_density(char_func, S: float, r: float, q: float, T: float,
                         n_points: int = 2048) -> tuple:
    """Extract risk-neutral density via Gil-Pelaez Fourier inversion.

    Parameters
    ----------
    char_func : callable
        Characteristic function phi(u) of log(S_T / S_0).
    S : float
        Spot price.
    r, q : float
        Risk-free rate and dividend yield.
    T : float
        Time to expiry.
    n_points : int
        Number of grid points for the density.

    Returns
    -------
    tuple of (np.ndarray, np.ndarray)
        (S_grid, density) where S_grid = F * exp(x_grid).

    Notes
    -----
    Gil-Pelaez inversion: f(x) = (1/pi) * Re[int_0^inf exp(-iux) * phi(u) du].
    Integration over u from 1e-8 to 200 using trapezoidal rule.

    Reference: Gil-Pelaez, J. (1951). Note on the inversion theorem.
    """
    F = S * np.exp((r - q) * T)
    x_grid = np.linspace(-3.0, 3.0, n_points)
    u_grid = np.linspace(1e-8, 200.0, 4096)
    du = u_grid[1] - u_grid[0]
    density = np.zeros(n_points)
    phi_vals = np.array([char_func(u) for u in u_grid])
    for idx, x in enumerate(x_grid):
        integrand = np.real(phi_vals * np.exp(-1j * u_grid * x))
        density[idx] = np.trapz(integrand, dx=du) / np.pi
    density = np.maximum(density, 0.0)
    S_grid = F * np.exp(x_grid)
    return S_grid, density


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 4: ABSTRACT MODEL BASE CLASS
# ─────────────────────────────────────────────────────────────────────────────

class StochasticModel(ABC):
    """Abstract base class for stochastic asset price models with characteristic functions.

    All subclasses must implement log_char_func(u) returning the log of the
    characteristic function phi(u) = E^Q[exp(iu * log(S_T / S_0))].

    All subclasses must incorporate the risk-neutral drift correction so that
    phi(-i) = exp((r-q)*T), the martingale condition.

    Parameters
    ----------
    S : float
        Spot price.
    r : float
        Risk-free rate.
    q : float
        Dividend yield.
    T : float
        Time to expiry.

    Reference: Cont, R. & Tankov, P. (2004). Financial Modelling with Jump Processes.
    """

    def __init__(self, S: float, r: float, q: float, T: float) -> None:
        self.S = S
        self.r = r
        self.q = q
        self.T = T

    @abstractmethod
    def log_char_func(self, u: complex) -> complex:
        """Log of the characteristic function: log phi(u) = log E^Q[exp(iu * log(S_T/S_0))].

        All subclasses must incorporate the risk-neutral drift correction so that
        phi(-i) = exp((r-q)*T), the martingale condition.

        Parameters
        ----------
        u : complex
            Fourier frequency argument.

        Returns
        -------
        complex
            Log of the characteristic function value.
        """
        ...

    def char_func(self, u: complex) -> complex:
        """Characteristic function phi(u) = exp(log_char_func(u)).

        Parameters
        ----------
        u : complex
            Fourier frequency argument.

        Returns
        -------
        complex
            Characteristic function value.
        """
        return np.exp(self.log_char_func(u))

    def verify_martingale_condition(self, tol: float = 1e-6) -> bool:
        """Verify the martingale condition: |phi(-i) - exp((r-q)*T)| < tol.

        Under Q, E^Q[S_T] = S_0 * exp((r-q)*T). Since phi(u) = E^Q[exp(iu*log(S_T/S_0))],
        evaluating at u = -i gives phi(-i) = E^Q[exp(log(S_T/S_0))] = E^Q[S_T/S_0]
        = exp((r-q)*T).

        Parameters
        ----------
        tol : float
            Tolerance for the martingale error.

        Returns
        -------
        bool
            True if the martingale condition is satisfied within tolerance.

        Reference: Schoutens, W. (2003). Lévy Processes in Finance.
        """
        cf_val = self.char_func(-1j)
        expected = np.exp((self.r - self.q) * self.T)
        return abs(cf_val - expected) < tol

    def price_carr_madan(self, strikes: np.ndarray, N: int = 4096,
                         alpha: float = 1.5, eta: float = 0.25) -> np.ndarray:
        """Carr-Madan (1999) FFT option pricing algorithm. O(N log N) complexity.

        The dampening parameter alpha ensures square-integrability of the modified
        call transform. The modified CF is:
            psi_T(v) = exp(-rT) * phi(v - (alpha+1)i) / (alpha^2 + alpha - v^2 + i(2*alpha+1)*v)

        Simpson weights improve quadrature accuracy over the trapezoidal rule.

        Grid construction:
            lambda = 2*pi / (N*eta),  b = N*lambda/2
            u_j = j * eta  (frequency grid)
            k_j = -b + lambda * j  (log-moneyness grid)

        Parameters
        ----------
        strikes : np.ndarray
            Array of strike prices.
        N : int
            FFT grid size (power of 2 recommended).
        alpha : float
            Dampening parameter (typically 1.0 to 2.0).
        eta : float
            Frequency grid spacing.

        Returns
        -------
        np.ndarray
            European call option prices at requested strikes.

        Reference: Carr, P. & Madan, D. (1999). Option valuation using the FFT.
        """
        F = self.S * np.exp((self.r - self.q) * self.T)
        lambda_ = 2.0 * np.pi / (N * eta)
        b = N * lambda_ / 2.0

        u = np.arange(N) * eta
        k_grid = -b + lambda_ * np.arange(N)

        # Modified characteristic function values
        phi_u = np.zeros(N, dtype=complex)
        for j in range(N):
            v = u[j]
            try:
                cf_val = self.char_func(v - (alpha + 1.0) * 1j)
                denom = alpha ** 2 + alpha - v ** 2 + 1j * (2.0 * alpha + 1.0) * v
                phi_u[j] = np.exp(-self.r * self.T) * cf_val / denom
            except Exception:
                phi_u[j] = 0.0

        # Simpson weights: w[j] = (3 + (-1)^j - delta_{j,0}) / 3
        w = np.zeros(N)
        for j in range(N):
            w[j] = (3.0 + (-1.0) ** j) / 3.0
        w[0] = 1.0 / 3.0  # Simpson weight correction for j=0

        x = np.exp(1j * b * u) * phi_u * eta * w
        fft_result = np.real(fft(x))
        call_prices = np.exp(-alpha * k_grid) / np.pi * fft_result

        # Interpolate to requested strikes
        k_requested = np.log(strikes / F)
        prices = np.interp(k_requested, k_grid, call_prices)
        return np.maximum(prices, 0.0)

    def price_cos(self, strikes: np.ndarray, N: int = 256, L: float = 12.0) -> np.ndarray:
        """Fang-Oosterlee (2008) COS method for option pricing. O(N) complexity.

        Expands the risk-neutral density in a Fourier-cosine basis on [a, b] = [-L, L].
        Coefficients: A_k = (2/(b-a)) * Re[phi(k*pi/(b-a)) * exp(-i*k*pi*a/(b-a))].
        Achieves exponential convergence in N for smooth densities.

        Parameters
        ----------
        strikes : np.ndarray
            Array of strike prices.
        N : int
            Number of Fourier-cosine terms.
        L : float
            Half-width of the truncation domain in log-moneyness.

        Returns
        -------
        np.ndarray
            European call option prices at requested strikes.

        Reference: Fang, F. & Oosterlee, C.W. (2008). A novel pricing method for
                   European options based on Fourier-cosine series expansions.
        """
        F = self.S * np.exp((self.r - self.q) * self.T)
        a, b = -L, L
        prices = np.zeros(len(strikes))

        for idx, K in enumerate(strikes):
            x = np.log(F / K)
            total = 0.0
            for k in range(N):
                kpi_ba = k * np.pi / (b - a)
                try:
                    A_k = (2.0 / (b - a)) * np.real(
                        self.char_func(kpi_ba) * np.exp(-1j * kpi_ba * a)
                    )
                except Exception:
                    A_k = 0.0

                # Payoff coefficients for call: chi_k - psi_k
                # chi_k = integral_a^b exp(y)*cos(k*pi*(y-a)/(b-a)) dy
                # psi_k = integral_a^b cos(k*pi*(y-a)/(b-a)) dy
                if k == 0:
                    chi_k = np.exp(b) - np.exp(a)
                    psi_k = b - a
                else:
                    kp = k * np.pi / (b - a)
                    chi_k = (np.exp(b) * (kp * np.sin(kp * (b - a)) + np.cos(kp * (b - a)))
                             - np.exp(a)) / (1.0 + kp ** 2)
                    psi_k = np.sin(kp * (b - a)) / kp

                V_k = chi_k - psi_k
                weight = 0.5 if k == 0 else 1.0
                total += weight * A_k * V_k

            prices[idx] = max(K * np.exp(-self.r * self.T) * total, 0.0)
        return prices

    def implied_vol_surface(self, strikes: np.ndarray, method: str = 'carr_madan') -> np.ndarray:
        """Compute implied volatility surface for given strikes.

        Parameters
        ----------
        strikes : np.ndarray
            Array of strike prices.
        method : str
            Pricing method: 'carr_madan' or 'cos'.

        Returns
        -------
        np.ndarray
            Implied volatilities corresponding to each strike.
        """
        if method == 'carr_madan':
            prices = self.price_carr_madan(strikes)
        elif method == 'cos':
            prices = self.price_cos(strikes)
        else:
            prices = self.price_carr_madan(strikes)
        vols = np.array([
            implied_vol(self.S, K, self.r, self.q, self.T, p)
            for K, p in zip(strikes, prices)
        ])
        return vols


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 5: SIX MODEL IMPLEMENTATIONS
# ─────────────────────────────────────────────────────────────────────────────

class BlackScholesMerton(StochasticModel):
    """Black-Scholes-Merton geometric Brownian motion model.

    Dynamics: dS_t = (r - q) * S_t * dt + sigma * S_t * dW_t
    Log-normal returns with constant volatility.

    Characteristic function:
        log phi(u) = iu(r - q - sigma^2/2)T - 0.5 u^2 sigma^2 T

    No omega correction needed — the drift is already the martingale drift.

    Parameters
    ----------
    sigma : float
        Constant volatility (annualized).

    Reference: Black, F. & Scholes, M. (1973). The pricing of options and
               corporate liabilities. Journal of Political Economy, 81(3).
    """

    def __init__(self, S: float, r: float, q: float, T: float, sigma: float) -> None:
        super().__init__(S, r, q, T)
        self.sigma = sigma

    def log_char_func(self, u: complex) -> complex:
        """Log characteristic function for BSM.

        Parameters
        ----------
        u : complex
            Fourier frequency.

        Returns
        -------
        complex
            log phi(u) = iu(r-q-sigma^2/2)T - 0.5 u^2 sigma^2 T
        """
        drift = (self.r - self.q - 0.5 * self.sigma ** 2) * self.T
        return 1j * u * drift - 0.5 * u ** 2 * self.sigma ** 2 * self.T


class HestonModel(StochasticModel):
    """Heston (1993) stochastic volatility model.

    Dynamics:
        dS_t = (r - q) * S_t * dt + sqrt(v_t) * S_t * dW_1
        dv_t = kappa * (theta - v_t) * dt + xi * sqrt(v_t) * dW_2
        Corr(dW_1, dW_2) = rho

    Feller condition: 2 * kappa * theta > xi^2 ensures v_t > 0 a.s.

    Uses the Albrecher et al. (2007) numerically stable formulation to
    avoid branch cut issues present in the original Heston (1993) form.

    Parameters
    ----------
    v0 : float
        Initial variance.
    kappa : float
        Mean-reversion speed.
    theta : float
        Long-run variance.
    xi : float
        Vol-of-vol.
    rho : float
        Correlation between asset and variance Brownian motions.

    Reference: Albrecher, H. et al. (2007). The little Heston trap.
               Heston, S. (1993). A closed-form solution for options with
               stochastic volatility.
    """

    def __init__(self, S: float, r: float, q: float, T: float,
                 v0: float, kappa: float, theta: float, xi: float, rho: float) -> None:
        super().__init__(S, r, q, T)
        self.v0 = v0
        self.kappa = kappa
        self.theta = theta
        self.xi = xi
        self.rho = rho

    @property
    def feller_ratio(self) -> float:
        """Feller ratio: 2*kappa*theta / xi^2. Must be > 1 for strict positivity."""
        return 2.0 * self.kappa * self.theta / (self.xi ** 2)

    def log_char_func(self, u: complex) -> complex:
        """Log characteristic function using Albrecher et al. (2007) stable formulation.

        Parameters
        ----------
        u : complex
            Fourier frequency.

        Returns
        -------
        complex
            Log of phi(u) with branch-cut-stable computation.

        Notes
        -----
        Uses the formulation:
            a = kappa * theta
            x = iu
            b = kappa - rho * xi * x
            d = sqrt(b^2 + xi^2 * x * (x + i))
            g = (b - d) / (b + d)
        with Re(d) >= 0 enforced to avoid branch cut discontinuities.
        """
        a = self.kappa * self.theta
        x = 1j * u
        b = self.kappa - self.rho * self.xi * x
        d = np.sqrt(b ** 2 + self.xi ** 2 * x * (x + 1j))

        # Enforce Re(d) >= 0 for branch cut stability
        if np.real(d) < 0:
            d = -d

        g = (b - d) / (b + d)
        exp_dT = np.exp(-d * self.T)
        denom = 1.0 - g * exp_dT

        log_phi = (1j * u * (self.r - self.q) * self.T
                   + (a / self.xi ** 2) * ((b - d) * self.T - 2.0 * np.log(denom / (1.0 - g)))
                   + (self.v0 / self.xi ** 2) * (b - d) * (1.0 - exp_dT) / denom)
        return log_phi


class VarianceGammaModel(StochasticModel):
    """Variance Gamma (VG) model.

    VG process = Brownian motion with drift theta time-changed by Gamma(t/nu, nu).
    Pure-jump process with infinite activity and finite variation.
    Lévy triplet: no Gaussian component.
    Special case: nu -> 0 recovers Black-Scholes-Merton.

    log phi(u) = iu(r - q + omega)T - (T/nu) * log(1 - iu*theta*nu + 0.5*sigma^2*nu*u^2)
    omega = log(1 - theta*nu - 0.5*sigma^2*nu) / nu  (martingale correction)

    Parameters
    ----------
    sigma : float
        Volatility of the Brownian motion component.
    nu : float
        Variance rate of the Gamma time change.
    theta : float
        Drift of the Brownian motion component (controls skewness).

    Reference: Madan, D., Carr, P. & Chang, E. (1998). The Variance Gamma
               process and option pricing.
    """

    def __init__(self, S: float, r: float, q: float, T: float,
                 sigma: float, nu: float, theta: float) -> None:
        super().__init__(S, r, q, T)
        self.sigma = sigma
        self.nu = nu
        self.theta = theta

    @property
    def omega(self) -> float:
        """Martingale correction: omega = log(1 - theta*nu - 0.5*sigma^2*nu) / nu."""
        arg = 1.0 - self.theta * self.nu - 0.5 * self.sigma ** 2 * self.nu
        if arg <= 0:
            raise ValueError(
                f"VG omega log argument non-positive: {arg:.6f}. "
                "Check parameter constraints."
            )
        return np.log(arg) / self.nu

    def log_char_func(self, u: complex) -> complex:
        """Log characteristic function for the Variance Gamma model.

        Parameters
        ----------
        u : complex
            Fourier frequency.

        Returns
        -------
        complex
            log phi(u) = iu(r-q+omega)T - (T/nu)*log(1 - iu*theta*nu + 0.5*sigma^2*nu*u^2)
        """
        psi = np.log(1.0 - 1j * u * self.theta * self.nu
                     + 0.5 * self.sigma ** 2 * self.nu * u ** 2)
        return 1j * u * (self.r - self.q + self.omega) * self.T - (self.T / self.nu) * psi


class CGMYModel(StochasticModel):
    """CGMY (Carr-Geman-Madan-Yor) tempered stable Lévy model.

    Lévy measure:
        nu(dx) = C * exp(-G|x|) / |x|^(1+Y) * 1_{x<0}
               + C * exp(-Mx) / x^(1+Y) * 1_{x>0}

    Special cases: Y=0 -> VG, Y=0.5 -> NIG, Y -> 2 -> Brownian motion.
    Infinite variation for Y > 1, infinite activity for all Y in (0, 2).

    Parameters
    ----------
    C : float
        Overall activity level (C > 0).
    G : float
        Rate of exponential decay for negative jumps (G > 0).
    M : float
        Rate of exponential decay for positive jumps (M > 0).
    Y : float
        Fine structure parameter (0 < Y < 2).

    Reference: Carr, P., Geman, H., Madan, D. & Yor, M. (2002). The fine
               structure of asset returns.
    """

    def __init__(self, S: float, r: float, q: float, T: float,
                 C: float, G: float, M: float, Y: float) -> None:
        super().__init__(S, r, q, T)
        if not (0 < Y < 2):
            raise ValueError("CGMY requires 0 < Y < 2")
        self.C = C
        self.G = G
        self.M = M
        self.Y = Y

    @property
    def omega(self) -> float:
        """Martingale correction: omega = -C * Gamma(-Y) * [(M-1)^Y - M^Y + (G+1)^Y - G^Y]."""
        gY = special.gamma(-self.Y)
        return -self.C * gY * (
            (self.M - 1.0) ** self.Y - self.M ** self.Y
            + (self.G + 1.0) ** self.Y - self.G ** self.Y
        )

    def log_char_func(self, u: complex) -> complex:
        """Log characteristic function for the CGMY model.

        Parameters
        ----------
        u : complex
            Fourier frequency.

        Returns
        -------
        complex
            log phi(u) = iu(r-q+omega)T + C*T*Gamma(-Y)*[(M-iu)^Y - M^Y + (G+iu)^Y - G^Y]
        """
        gY = special.gamma(-self.Y)
        levy_exp = self.C * self.T * gY * (
            (self.M - 1j * u) ** self.Y - self.M ** self.Y
            + (self.G + 1j * u) ** self.Y - self.G ** self.Y
        )
        return 1j * u * (self.r - self.q + self.omega) * self.T + levy_exp


class NormalInverseGaussianModel(StochasticModel):
    """Normal Inverse Gaussian (NIG) model.

    NIG = Brownian motion time-changed by an Inverse Gaussian process.

    Lévy density:
        nu(dx) = (alpha * delta / pi) * K_1(alpha * |x|) * exp(beta * x) / |x|
    where K_1 is the modified Bessel function of the second kind.

    Special case: corresponds to Y = 0.5 in the CGMY framework.

    Parameters
    ----------
    alpha : float
        Tail heaviness parameter (alpha > 0).
    beta : float
        Asymmetry parameter (|beta| < alpha).
    delta : float
        Scale parameter (delta > 0).

    Reference: Barndorff-Nielsen, O.E. (1997). Normal Inverse Gaussian
               distributions and stochastic volatility modelling.
    """

    def __init__(self, S: float, r: float, q: float, T: float,
                 alpha: float, beta: float, delta: float) -> None:
        super().__init__(S, r, q, T)
        if not (alpha > abs(beta)):
            raise ValueError("NIG requires alpha > |beta|")
        self.alpha = alpha
        self.beta = beta
        self.delta = delta

    @property
    def omega(self) -> float:
        """Martingale correction: omega = delta*(sqrt(alpha^2 - beta^2) - sqrt(alpha^2 - (beta+1)^2))."""
        return self.delta * (
            np.sqrt(self.alpha ** 2 - self.beta ** 2)
            - np.sqrt(self.alpha ** 2 - (self.beta + 1.0) ** 2)
        )

    def log_char_func(self, u: complex) -> complex:
        """Log characteristic function for the NIG model.

        Parameters
        ----------
        u : complex
            Fourier frequency.

        Returns
        -------
        complex
            log phi(u) = iu(r-q+omega)T + T*delta*(sqrt(alpha^2-beta^2) - sqrt(alpha^2-(beta+iu)^2))
        """
        psi = self.delta * (
            np.sqrt(self.alpha ** 2 - self.beta ** 2)
            - np.sqrt(self.alpha ** 2 - (self.beta + 1j * u) ** 2)
        )
        return 1j * u * (self.r - self.q + self.omega) * self.T + self.T * psi


class MertonJumpDiffusion(StochasticModel):
    """Merton (1976) jump-diffusion model.

    Dynamics:
        dS_t / S_t = (r - q - lambda * kappa_J) * dt + sigma * dW_t + (J_t - 1) * dN_t
    where N_t ~ Poisson(lambda), log(J_t) ~ N(mu_J, delta_J^2).
    kappa_J = exp(mu_J + delta_J^2/2) - 1 is the expected relative jump size.

    Parameters
    ----------
    sigma : float
        Diffusion volatility.
    lambda_ : float
        Jump intensity (expected number of jumps per year).
    mu_J : float
        Mean of log-jump size.
    delta_J : float
        Volatility of log-jump size.

    Reference: Merton, R.C. (1976). Option pricing when underlying stock
               returns are discontinuous. Journal of Financial Economics, 3.
    """

    def __init__(self, S: float, r: float, q: float, T: float,
                 sigma: float, lambda_: float, mu_J: float, delta_J: float) -> None:
        super().__init__(S, r, q, T)
        self.sigma = sigma
        self.lambda_ = lambda_
        self.mu_J = mu_J
        self.delta_J = delta_J

    def log_char_func(self, u: complex) -> complex:
        """Log characteristic function for Merton jump-diffusion.

        Parameters
        ----------
        u : complex
            Fourier frequency.

        Returns
        -------
        complex
            Diffusion + jump components with martingale-corrected drift.

        Notes
        -----
        kappa_J = exp(mu_J + delta_J^2/2) - 1
        diffusion = iu(r - q - lambda*kappa_J)T - 0.5 u^2 sigma^2 T
        jump_cf = lambda*T*(exp(iu*mu_J - 0.5*u^2*delta_J^2) - 1)
        """
        kappa_J = np.exp(self.mu_J + 0.5 * self.delta_J ** 2) - 1.0
        diffusion = (1j * u * (self.r - self.q - self.lambda_ * kappa_J) * self.T
                     - 0.5 * u ** 2 * self.sigma ** 2 * self.T)
        jump_cf = self.lambda_ * self.T * (
            np.exp(1j * u * self.mu_J - 0.5 * u ** 2 * self.delta_J ** 2) - 1.0
        )
        return diffusion + jump_cf


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 6: CALIBRATION ENGINE
# ─────────────────────────────────────────────────────────────────────────────

class CalibrationEngine:
    """Engine for calibrating stochastic models to market implied volatility data.

    Uses vega-weighted RMSE as the objective function, ensuring that options
    with higher vega (typically ATM) receive proportionally more weight.

    Parameters
    ----------
    market : MarketData
        Market observables including strikes and implied vols.
    method : str
        Optimization method: 'differential_evolution' or 'L-BFGS-B'.

    Reference: Cont, R. & Tankov, P. (2004). Financial Modelling with Jump Processes.
    """

    def __init__(self, market: MarketData, method: str = 'differential_evolution') -> None:
        self.market = market
        self.method = method
        # Compute vega weights for balanced objective
        raw_weights = np.array([
            bsm_vega(market.S, K, market.r, market.q, market.T, sig)
            for K, sig in zip(market.strikes, market.market_vols)
        ])
        self.weights = raw_weights / (raw_weights.sum() + 1e-12)
        self._n_iter = [0]

    def _objective(self, model_vols: np.ndarray) -> float:
        """Vega-weighted RMSE between model and market implied vols.

        Parameters
        ----------
        model_vols : np.ndarray
            Model-implied volatilities.

        Returns
        -------
        float
            sqrt(sum(weights * (model_vols - market_vols)^2))
        """
        self._n_iter[0] += 1
        diff = model_vols - self.market.market_vols
        return np.sqrt(np.sum(self.weights * diff ** 2))

    def calibrate_heston(self) -> CalibrationResult:
        """Calibrate the Heston stochastic volatility model.

        Bounds: v0 in [0.001, 1], kappa in [0.1, 15], theta in [0.001, 1],
                xi in [0.01, 2], rho in [-0.99, 0].

        Returns
        -------
        CalibrationResult
            Fitted parameters, errors, and diagnostics.

        Reference: Heston, S. (1993). A closed-form solution for options
                   with stochastic volatility.
        """
        self._n_iter = [0]
        bounds = [(0.001, 1.0), (0.1, 15.0), (0.001, 1.0), (0.01, 2.0), (-0.99, 0.0)]
        m = self.market

        def obj(x):
            try:
                model = HestonModel(m.S, m.r, m.q, m.T,
                                    v0=x[0], kappa=x[1], theta=x[2], xi=x[3], rho=x[4])
                vols = model.implied_vol_surface(m.strikes)
                if np.any(np.isnan(vols)):
                    return 1.0
                return self._objective(vols)
            except Exception:
                return 1.0

        if self.method == 'differential_evolution':
            result = optimize.differential_evolution(
                obj, bounds, seed=42, maxiter=300, tol=1e-6, workers=1, popsize=12
            )
        else:
            x0 = [0.04, 1.5, 0.04, 0.3, -0.7]
            result = optimize.minimize(obj, x0, method='L-BFGS-B', bounds=bounds)

        params = dict(v0=result.x[0], kappa=result.x[1], theta=result.x[2],
                      xi=result.x[3], rho=result.x[4])
        best_model = HestonModel(m.S, m.r, m.q, m.T, **params)
        fitted_vols = best_model.implied_vol_surface(m.strikes)
        fitted_vols = np.nan_to_num(fitted_vols, nan=0.0)
        errors = np.abs(fitted_vols - m.market_vols)
        rel_errors = errors / (m.market_vols + 1e-12)

        return CalibrationResult(
            model_name='Heston',
            params=params,
            rmse=result.fun,
            max_error=float(np.max(errors)),
            avg_relative_error=float(np.mean(rel_errors)),
            n_iterations=self._n_iter[0],
            success=result.success,
            fitted_vols=fitted_vols,
        )

    def calibrate_vg(self) -> CalibrationResult:
        """Calibrate the Variance Gamma model.

        Bounds: sigma in [0.01, 1], nu in [0.001, 2], theta in [-0.5, 0.5].

        Returns
        -------
        CalibrationResult
            Fitted parameters, errors, and diagnostics.

        Reference: Madan, D., Carr, P. & Chang, E. (1998). The VG process.
        """
        self._n_iter = [0]
        bounds = [(0.01, 1.0), (0.001, 2.0), (-0.5, 0.5)]
        m = self.market

        def obj(x):
            try:
                model = VarianceGammaModel(m.S, m.r, m.q, m.T,
                                           sigma=x[0], nu=x[1], theta=x[2])
                vols = model.implied_vol_surface(m.strikes)
                if np.any(np.isnan(vols)):
                    return 1.0
                return self._objective(vols)
            except Exception:
                return 1.0

        if self.method == 'differential_evolution':
            result = optimize.differential_evolution(
                obj, bounds, seed=42, maxiter=300, tol=1e-6, workers=1, popsize=12
            )
        else:
            x0 = [0.2, 0.5, -0.1]
            result = optimize.minimize(obj, x0, method='L-BFGS-B', bounds=bounds)

        params = dict(sigma=result.x[0], nu=result.x[1], theta=result.x[2])
        best_model = VarianceGammaModel(m.S, m.r, m.q, m.T, **params)
        fitted_vols = best_model.implied_vol_surface(m.strikes)
        fitted_vols = np.nan_to_num(fitted_vols, nan=0.0)
        errors = np.abs(fitted_vols - m.market_vols)
        rel_errors = errors / (m.market_vols + 1e-12)

        return CalibrationResult(
            model_name='Variance Gamma',
            params=params,
            rmse=result.fun,
            max_error=float(np.max(errors)),
            avg_relative_error=float(np.mean(rel_errors)),
            n_iterations=self._n_iter[0],
            success=result.success,
            fitted_vols=fitted_vols,
        )


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 7: FOURIER RISK ANALYTICS
# ─────────────────────────────────────────────────────────────────────────────

class FourierRiskAnalytics:
    """Risk analytics via Fourier inversion of characteristic functions.

    Provides VaR, CVaR, and Greeks computation using the model's characteristic
    function, avoiding Monte Carlo simulation entirely.

    Parameters
    ----------
    model : StochasticModel
        A calibrated stochastic model with a characteristic function.

    Reference: Glasserman, P. & Liu, Z. (2010). Sensitivity estimates from
               characteristic functions.
    """

    def __init__(self, model: StochasticModel) -> None:
        self.model = model

    def cdf(self, x: float, n_quad: int = 500) -> float:
        """CDF of log-returns via Gil-Pelaez inversion.

        F(x) = 0.5 - (1/pi) * int_0^inf Im[phi(u) * exp(-iux)] / u du

        Parameters
        ----------
        x : float
            Log-return level.
        n_quad : int
            Number of quadrature points.

        Returns
        -------
        float
            Probability P(log(S_T/S_0) <= x).

        Reference: Gil-Pelaez, J. (1951). Note on the inversion theorem.
        """
        def integrand(u):
            try:
                cf_val = self.model.char_func(u)
                return np.imag(cf_val * np.exp(-1j * u * x)) / u
            except Exception:
                return 0.0

        result, _ = integrate.quad(integrand, 1e-8, 200.0, limit=n_quad)
        return 0.5 - result / np.pi

    def var(self, alpha: float = 0.05, tol: float = 1e-6) -> float:
        """Value-at-Risk via bisection on the CDF.

        Returns the alpha-quantile of log(S_T / S_0). Convert to gross return
        via exp(result) - 1.

        Parameters
        ----------
        alpha : float
            Tail probability (e.g. 0.05 for 5th percentile).
        tol : float
            Bisection convergence tolerance.

        Returns
        -------
        float
            Log-return quantile q such that P(log(S_T/S_0) <= q) = alpha.

        Reference: McNeil, A., Frey, R. & Embrechts, P. (2005).
                   Quantitative Risk Management.
        """
        lo, hi = np.log(0.01), np.log(10.0)
        for _ in range(80):
            mid = (lo + hi) / 2.0
            if self.cdf(mid) < alpha:
                lo = mid
            else:
                hi = mid
            if hi - lo < tol:
                break
        return (lo + hi) / 2.0

    def cvar(self, alpha: float = 0.05, n_points: int = 200) -> float:
        """Conditional Value-at-Risk (Expected Shortfall) via Fourier inversion.

        CVaR_alpha = (1/alpha) * int_{-inf}^{VaR} x * f(x) dx

        Parameters
        ----------
        alpha : float
            Tail probability.
        n_points : int
            Number of integration grid points.

        Returns
        -------
        float
            Expected log-return in the alpha tail.

        Reference: Acerbi, C. & Tasche, D. (2002). On the coherence of
                   expected shortfall.
        """
        var_alpha = self.var(alpha)
        x_grid = np.linspace(-5.0, var_alpha, n_points)
        pdf_vals = np.zeros(n_points)

        for i, x in enumerate(x_grid):
            def integrand(u, x_val=x):
                try:
                    cf_val = self.model.char_func(u)
                    return np.real(cf_val * np.exp(-1j * u * x_val))
                except Exception:
                    return 0.0
            result, _ = integrate.quad(integrand, 1e-8, 100.0, limit=200)
            pdf_vals[i] = max(result / np.pi, 0.0)

        return np.trapz(x_grid * pdf_vals, x_grid) / alpha

    def compute_greeks_fourier(self, K: float) -> dict:
        """Compute option Greeks via finite differences on FFT prices.

        Uses central differences for Delta and Gamma, forward difference for Theta.
        Step sizes: h = S * 0.001 for spot, dt = 1/252 for time.

        Parameters
        ----------
        K : float
            Strike price.

        Returns
        -------
        dict
            Keys: 'price', 'delta', 'gamma', 'theta'.

        Reference: Glasserman, P. (2004). Monte Carlo Methods in Financial Engineering.
        """
        import copy
        strikes = np.array([K])
        h = self.model.S * 0.001

        # Base price
        price_0 = self.model.price_carr_madan(strikes)[0]

        # Delta & Gamma: bump spot
        model_up = copy.copy(self.model)
        model_up.__dict__.update({'S': self.model.S + h})
        price_up = model_up.price_carr_madan(strikes)[0]

        model_dn = copy.copy(self.model)
        model_dn.__dict__.update({'S': self.model.S - h})
        price_dn = model_dn.price_carr_madan(strikes)[0]

        delta = (price_up - price_dn) / (2.0 * h)
        gamma = (price_up - 2.0 * price_0 + price_dn) / (h ** 2)

        # Theta: bump time
        dt = 1.0 / 252.0
        if self.model.T > dt:
            model_t = copy.copy(self.model)
            model_t.__dict__.update({'T': self.model.T - dt})
            price_t = model_t.price_carr_madan(strikes)[0]
            theta = (price_t - price_0) / dt
        else:
            theta = 0.0

        return {'price': price_0, 'delta': delta, 'gamma': gamma, 'theta': theta}


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 8: MARTINGALE DIAGNOSTICS
# ─────────────────────────────────────────────────────────────────────────────

class MartingaleDiagnostics:
    """Diagnostics for verifying the martingale condition and extracting
    distributional cumulants from stochastic model characteristic functions.

    Reference: Schoutens, W. (2003). Lévy Processes in Finance: Pricing
               Financial Derivatives.
    """

    @staticmethod
    def check_all_models(S: float = 100.0, r: float = 0.05, q: float = 0.02,
                         T: float = 1.0) -> 'pd.DataFrame':
        """Verify the martingale condition for all 6 canonical model instances.

        Instantiates each model with canonical parameters and checks that
        phi(-i) = exp((r-q)*T) to within tolerance 1e-4.

        Parameters
        ----------
        S, r, q, T : float
            Common market parameters.

        Returns
        -------
        pd.DataFrame
            Columns: 'CF(-i) Real Part', 'CF(-i) Imag Part',
            'Expected exp((r-q)T)', 'Martingale Error', 'Pass (tol=1e-4)'.
        """
        import pandas as pd
        expected = np.exp((r - q) * T)
        models = {
            'Black-Scholes': BlackScholesMerton(S, r, q, T, sigma=0.20),
            'Heston': HestonModel(S, r, q, T, v0=0.04, kappa=2.0, theta=0.04, xi=0.3, rho=-0.7),
            'Variance Gamma': VarianceGammaModel(S, r, q, T, sigma=0.20, nu=0.5, theta=-0.1),
            'CGMY': CGMYModel(S, r, q, T, C=1.0, G=5.0, M=10.0, Y=0.7),
            'NIG': NormalInverseGaussianModel(S, r, q, T, alpha=15.0, beta=-5.0, delta=0.5),
            'Merton JD': MertonJumpDiffusion(S, r, q, T, sigma=0.15, lambda_=0.5, mu_J=-0.05, delta_J=0.1),
        }
        rows = []
        for name, model in models.items():
            cf_val = model.char_func(-1j)
            cf_error = abs(cf_val - expected)
            feller = ''
            if hasattr(model, 'feller_ratio'):
                feller = f"{model.feller_ratio:.2f}"
            else:
                feller = 'N/A'
            rows.append({
                'Model': name,
                'CF(-i) Real Part': np.real(cf_val),
                'CF(-i) Imag Part': np.imag(cf_val),
                'Expected exp((r-q)T)': expected,
                'Martingale Error': cf_error,
                'Pass (tol=1e-4)': cf_error < 1e-4,
                'Feller Ratio': feller,
            })
        df = pd.DataFrame(rows).set_index('Model')
        return df

    @staticmethod
    def cumulant_analysis(model: StochasticModel) -> dict:
        """Extract cumulants via numerical differentiation of the log-CF at u=0.

        Formula: c_n = (-i)^n * d^n/du^n log_phi(u) |_{u=0}

        Uses finite differences:
        - c1 (mean): Im(log_phi(h) - log_phi(-h)) / (2h)
        - c2 (variance): -Re(log_phi(h) + log_phi(-h) - 2*log_phi(0)) / h^2
        - c3, c4: higher-order finite differences

        Parameters
        ----------
        model : StochasticModel
            Model instance.

        Returns
        -------
        dict
            Keys: 'mean_log_return', 'variance', 'skewness', 'excess_kurtosis'.

        Reference: Cont, R. & Tankov, P. (2004). Financial Modelling with Jump Processes.
        """
        lf = model.log_char_func
        h = 1e-5
        dh = 1e-4

        # c1: mean = Im(log_phi(h) - log_phi(-h)) / (2h)
        c1 = np.imag(lf(h) - lf(-h)) / (2.0 * h)

        # c2: variance = -Re(log_phi(h) + log_phi(-h) - 2*log_phi(0)) / h^2
        c2 = -np.real(lf(h) + lf(-h) - 2.0 * lf(0.0)) / (h ** 2)

        # c3: third cumulant via finite difference
        c3 = -np.imag(lf(2*dh) - 2*lf(dh) + 2*lf(-dh) - lf(-2*dh)) / (2.0 * dh ** 3)

        # c4: fourth cumulant via finite difference
        c4 = -np.real(lf(2*dh) - 4*lf(dh) + 6*lf(0.0) - 4*lf(-dh) + lf(-2*dh)) / (dh ** 4)

        return {
            'mean_log_return': float(np.real(c1)),
            'variance': float(np.real(c2)),
            'skewness': float(np.real(c3 / c2 ** 1.5)) if c2 > 0 else 0.0,
            'excess_kurtosis': float(np.real(c4 / c2 ** 2)) if c2 > 0 else 0.0,
        }

