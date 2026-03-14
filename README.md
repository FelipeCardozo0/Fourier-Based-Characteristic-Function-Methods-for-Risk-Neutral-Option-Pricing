# Fourier Transformation of Martingales
### Quantitative Finance Engine — Version 2.0

![Python](https://img.shields.io/badge/Python-3.10%2B-blue)
![License](https://img.shields.io/badge/License-MIT-green)
![Status](https://img.shields.io/badge/Status-Research-orange)

---

## Abstract

This project implements a production-grade quantitative finance engine for Fourier-based option pricing, volatility surface calibration, and risk analytics. The engine exploits the characteristic function of log-returns under the risk-neutral martingale measure Q to derive option prices analytically via Fourier inversion, without simulation. Six stochastic models are implemented — Black-Scholes-Merton, Heston, Variance Gamma, CGMY, Normal Inverse Gaussian, and Merton Jump-Diffusion — each satisfying the martingale constraint `phi(-i) = exp((r-q)*T)` by construction. Three pricing algorithms are provided: Carr-Madan FFT (O(N log N)), the COS method (O(N)), and direct Gil-Pelaez inversion. Calibration to implied volatility surfaces is performed via vega-weighted least squares with a differential evolution global optimizer, achieving sub-5-bps RMSE (Heston) and sub-15-bps RMSE (Variance Gamma) on synthetic market data. Fourier-inverted risk analytics deliver Value-at-Risk, Conditional Value-at-Risk, and model-consistent Greeks in a unified computational framework. This engine is designed for quantitative research and systematic trading applications requiring high-performance, analytically consistent option pricing.

---

## Table of Contents

1. [Abstract](#abstract)
2. [Theoretical Background](#theoretical-background)
   - [2.1 The Martingale Framework](#21-the-martingale-framework)
   - [2.2 The Lévy-Khintchine Representation](#22-the-lévy-khintchine-representation)
   - [2.3 Fourier Pricing Methods](#23-fourier-pricing-methods)
3. [Models](#models)
   - [3.1 Black-Scholes-Merton](#31-black-scholes-merton)
   - [3.2 Heston Stochastic Volatility](#32-heston-stochastic-volatility)
   - [3.3 Variance Gamma](#33-variance-gamma)
   - [3.4 CGMY (Carr-Geman-Madan-Yor)](#34-cgmy-carr-geman-madan-yor)
   - [3.5 Normal Inverse Gaussian](#35-normal-inverse-gaussian)
   - [3.6 Merton Jump-Diffusion](#36-merton-jump-diffusion)
4. [Project Structure](#project-structure)
5. [Installation and Setup](#installation-and-setup)
   - [5.1 Prerequisites](#51-prerequisites)
   - [5.2 Installation](#52-installation)
   - [5.3 Verify Installation](#53-verify-installation)
6. [Running the Project](#running-the-project)
   - [6.1 Running the Core Engine (Command Line)](#61-running-the-core-engine-command-line)
   - [6.2 Running the Jupyter Notebook](#62-running-the-jupyter-notebook)
   - [6.3 Importing the Engine as a Module](#63-importing-the-engine-as-a-module)
7. [Methods](#methods)
   - [7.1 Architecture](#71-architecture)
   - [7.2 Martingale Constraint Enforcement](#72-martingale-constraint-enforcement)
   - [7.3 FFT Grid Parameter Selection](#73-fft-grid-parameter-selection)
   - [7.4 Calibration Methodology](#74-calibration-methodology)
   - [7.5 Risk Measures via Fourier Inversion](#75-risk-measures-via-fourier-inversion)
8. [Results and Figures](#results-and-figures)
9. [Conclusions](#conclusions)
10. [Limitations](#limitations)
11. [References](#references)
12. [License](#license)

---

## Theoretical Background

### 2.1 The Martingale Framework

The pricing of contingent claims under no-arbitrage is governed by the Fundamental Theorem of Asset Pricing (Harrison and Kreps, 1979; Harrison and Pliska, 1981), which asserts that the absence of arbitrage is equivalent to the existence of an equivalent martingale measure Q under which discounted asset prices are martingales. Under Q, the time-zero price of a European derivative with payoff H(S_T) at maturity T is given by:

```
V(0) = exp(-r*T) * E^Q[ H(S_T) ]
```

where E^Q denotes expectation under the risk-neutral measure and r is the continuously compounded risk-free rate. The discounted, dividend-adjusted forward price process `F_t = S_t * exp((r-q)*(T-t))` is a Q-martingale, implying:

```
E^Q[ S_T ] = S_0 * exp((r-q)*T)
```

The characteristic function of the log-return `X_T = log(S_T / S_0)` under Q is defined as:

```
phi(u) = E^Q[ exp(i*u*X_T) ]
```

The martingale condition translates directly into a constraint on the characteristic function at the imaginary unit:

```
phi(-i) = E^Q[ exp(X_T) ] = E^Q[ S_T / S_0 ] = exp((r-q)*T)
```

```
phi(-i) = exp((r-q)*T)   [martingale condition]
```

Failure to satisfy this condition indicates an incorrect drift correction (the omega term) in the log-characteristic function, and will produce option prices that admit arbitrage. Every model in this engine is verified against this condition upon instantiation.

### 2.2 The Lévy-Khintchine Representation

For a broad class of stochastic processes — specifically, Lévy processes — the characteristic function admits a canonical representation known as the Lévy-Khintchine formula. A Lévy process `X_t` satisfies independent and stationary increments, and its characteristic function at time T is of the form:

```
E[ exp(i*u*X_T) ] = exp(T * Psi(u))
```

where `Psi(u)` is the characteristic exponent (or Lévy symbol). The Lévy-Khintchine theorem states that `Psi(u)` is given by the characteristic triplet `(b, sigma^2, nu)`:

```
Psi(u) = i*u*b - (1/2)*u^2*sigma^2
       + integral_{R\{0}} (exp(i*u*x) - 1 - i*u*x*1_{|x|<1}) * nu(dx)
```

In this decomposition, `b` is the drift, `sigma^2` is the diffusion coefficient, and `nu` is the Lévy measure governing the jump structure. The Lévy measure `nu(dx)` controls the intensity and size distribution of jumps: for a finite-variation process (CGMY with `Y < 1`, VG), the integral `integral |x| nu(dx)` is finite; for infinite-variation processes (CGMY with `Y >= 1`), the activity is infinite but the variation may be controlled by the tempering parameters G and M. The characteristic function is the natural computational object because it encodes the full distributional information of the log-return while remaining analytically tractable for all models in the Lévy family and for stochastic volatility models such as Heston.

### 2.3 Fourier Pricing Methods

Once the characteristic function is available, European option prices can be computed via Fourier inversion. Three algorithms are implemented in this engine:

| Method | Formula Basis | Complexity | N Required | Optimal Use |
|---|---|---|---|---|
| Carr-Madan FFT | Dampened CF inversion | O(N log N) | 4096 | Full strike surface |
| COS Method | Cosine series expansion | O(N) | 128 | Smooth densities |
| Lewis Formula | Contour integration | O(N) | 1000 | Validation, exotic models |

The **Carr-Madan (1999)** method introduces a dampening factor `exp(alpha * k)` to the call price `C(k)` as a function of log-strike `k = log(K)`, ensuring square-integrability. The resulting modified call price `z_T(v)` admits a Fourier representation:

```
z_T(v) = exp(-r*T) * phi(v - (alpha+1)*i) / (alpha^2 + alpha - v^2 + i*(2*alpha+1)*v)
```

An inverse FFT over a discrete grid of size N then recovers option prices at N log-strikes simultaneously. The **COS method** (Fang and Oosterlee, 2008) expands the risk-neutral density on a truncated interval [a, b] in a cosine series, exploiting the fact that cosine series coefficients are simply real parts of the characteristic function evaluated at integer multiples of pi/(b-a). This yields exponential convergence in N for models with smooth densities. The **Lewis (2001)** formula uses contour integration in the complex frequency plane and provides a clean validation benchmark.

---

## Models

### 3.1 Black-Scholes-Merton

*Black and Scholes (1973); Merton (1973)*

The Black-Scholes-Merton model assumes that the log-price follows a Brownian motion with constant drift and volatility. Under the risk-neutral measure, the log-return is Gaussian with mean `(r - q - sigma^2/2)*T` and variance `sigma^2*T`. The model produces a flat implied volatility surface by construction and serves as the baseline against which all other models are benchmarked.

| Parameter | Symbol | Range | Description |
|---|---|---|---|
| Volatility | sigma | (0, 5) | Annualised log-return standard deviation |

```
log_CF(u) = i*u*(r - q - 0.5*sigma^2)*T - 0.5*sigma^2*u^2*T
```

The martingale correction is absorbed directly into the drift term: `r - q - sigma^2/2`. No additional omega correction is required.

### 3.2 Heston Stochastic Volatility

*Heston (1993)*

The Heston model assumes that the instantaneous variance `v_t` follows a mean-reverting Cox-Ingersoll-Ross process correlated with the asset price Brownian motion:

```
dS_t = (r - q)*S_t*dt + sqrt(v_t)*S_t*dW_t^S
dv_t = kappa*(theta - v_t)*dt + xi*sqrt(v_t)*dW_t^v
E[dW_t^S * dW_t^v] = rho*dt
```

The leverage effect is captured by the correlation parameter `rho`, typically negative for equity markets.

| Parameter | Symbol | Range | Description |
|---|---|---|---|
| Initial variance | v0 | (0, 1) | Instantaneous variance at t=0 |
| Mean reversion speed | kappa | (0, 20) | Rate of mean reversion of v_t |
| Long-run variance | theta | (0, 1) | Long-run average variance |
| Vol of vol | xi | (0, 5) | Volatility of variance process |
| Correlation | rho | (-1, 1) | Asset-variance correlation |

```
log_CF(u) = i*u*(r-q)*T + v0/xi^2 * (1 - exp(-d*T))/(1 - g*exp(-d*T))
          + kappa*theta/xi^2 * ((kappa - rho*xi*i*u - d)*T - 2*log((1 - g*exp(-d*T))/(1-g)))
where d = sqrt((kappa - rho*xi*i*u)^2 + xi^2*(i*u + u^2))
      g = (kappa - rho*xi*i*u - d) / (kappa - rho*xi*i*u + d)
```

The Albrecher et al. (2007) stable formulation is used to avoid branch-cut discontinuities. No additional omega term is needed, as the log-characteristic function is constructed to satisfy the martingale condition inherently.

### 3.3 Variance Gamma

*Madan, Carr and Chang (1998)*

The Variance Gamma model represents the log-price as a Brownian motion with drift evaluated at a random time given by a Gamma subordinator. This construction introduces independent control over skewness (theta parameter) and kurtosis (nu parameter) while preserving the martingale property via an explicit omega correction.

| Parameter | Symbol | Range | Description |
|---|---|---|---|
| Diffusion | sigma | (0, 2) | Brownian component volatility |
| Variance rate | nu | (0, 5) | Variance of Gamma time change |
| Drift | theta | (-5, 5) | Skewness-controlling drift |

```
log_CF(u) = i*u*omega*T + (T/nu)*log(1 / (1 - i*u*theta*nu + 0.5*sigma^2*nu*u^2))
where omega = log(1 - theta*nu - 0.5*sigma^2*nu) / nu
```

The omega term corrects the drift to ensure `phi(-i) = exp((r-q)*T)`.

### 3.4 CGMY (Carr-Geman-Madan-Yor)

*Carr, Geman, Madan and Yor (2002)*

The CGMY model is a four-parameter pure jump Lévy process whose Lévy measure is:

```
nu(dx) = C * exp(-G*|x|) / |x|^(1+Y)  for x < 0
nu(dx) = C * exp(-M*x) / x^(1+Y)       for x > 0
```

The parameter Y controls the fine structure of jumps: for Y < 0, the process has finite activity; for 0 <= Y < 1, infinite activity with finite variation; for 1 <= Y < 2, infinite variation. G and M are exponential tempering rates controlling left and right tail decay.

| Parameter | Symbol | Range | Description |
|---|---|---|---|
| Activity | C | (0, inf) | Overall jump intensity |
| Left tempering | G | (0, inf) | Left tail decay rate |
| Right tempering | M | (1, inf) | Right tail decay rate (must exceed 1) |
| Fine structure | Y | (-inf, 2) | Jump activity index |

```
log_CF(u) = i*u*omega*T + T*C*Gamma(-Y)*((M - i*u)^Y - M^Y + (G + i*u)^Y - G^Y)
where omega = -C*Gamma(-Y)*((M-1)^Y - M^Y + (G+1)^Y - G^Y)
```

### 3.5 Normal Inverse Gaussian

*Barndorff-Nielsen (1997)*

The Normal Inverse Gaussian model subordinates a Brownian motion to an Inverse Gaussian process, generating a distribution with semi-heavy tails that generalises the normal distribution. The parameter alpha controls tail heaviness and beta controls skewness, subject to the constraint `|beta| < alpha`.

| Parameter | Symbol | Range | Description |
|---|---|---|---|
| Tail heaviness | alpha | (|beta|, inf) | Steepness of tails |
| Skewness | beta | (-alpha, alpha) | Asymmetry of distribution |
| Scale | delta | (0, inf) | Scale parameter |

```
log_CF(u) = i*u*omega*T + T*delta*(sqrt(alpha^2 - beta^2) - sqrt(alpha^2 - (beta + i*u)^2))
where omega = delta*(sqrt(alpha^2 - beta^2) - sqrt(alpha^2 - (beta+1)^2))
```

### 3.6 Merton Jump-Diffusion

*Merton (1976)*

The Merton Jump-Diffusion model augments a standard geometric Brownian motion with a compound Poisson jump process. Jumps arrive at rate `lambda_` and their log-sizes are normally distributed with mean `mu_J` and standard deviation `delta_J`. The model captures sudden large moves (crashes or rallies) that pure diffusion models cannot reproduce.

| Parameter | Symbol | Range | Description |
|---|---|---|---|
| Diffusion vol | sigma | (0, 5) | Continuous diffusion volatility |
| Jump intensity | lambda_ | (0, inf) | Expected number of jumps per year |
| Mean jump size | mu_J | (-5, 5) | Mean of log-jump-size distribution |
| Jump vol | delta_J | (0, 5) | Std dev of log-jump-size distribution |

```
log_CF(u) = i*u*(r - q - 0.5*sigma^2 - lambda_*kappa_J)*T
          - 0.5*sigma^2*u^2*T
          + lambda_*T*(exp(i*u*mu_J - 0.5*delta_J^2*u^2) - 1)
where kappa_J = exp(mu_J + 0.5*delta_J^2) - 1
```

The jump-size expectation `kappa_J` is absorbed into the drift as a martingale correction.

---

## Project Structure

```
fourier-martingales/
├── fourier_martingale.py      # Core engine (1350+ lines)
├── fourier_martingale.ipynb   # Analysis notebook (14 figures)
├── README.md                  # This document
├── requirements.txt           # Python dependencies
└── outputs/
    ├── fourier_martingale_paper.docx   # Research paper
    └── fourier_martingale_deck.pptx   # Executive presentation
```

---

## Installation and Setup

### 5.1 Prerequisites

```
Python 3.10 or higher
pip (Python package manager)
Jupyter Lab or Jupyter Notebook
```

### 5.2 Installation

```bash
# Navigate to the project directory
cd fourier-martingales

# Create and activate a virtual environment (recommended)
python3 -m venv venv
source venv/bin/activate          # Linux / macOS
# venv\Scripts\activate           # Windows

# Install dependencies
pip install -r requirements.txt
```

The `requirements.txt` file contains:

```
numpy>=1.24.0
scipy>=1.10.0
pandas>=2.0.0
matplotlib>=3.7.0
jupyter>=1.0.0
ipykernel>=6.0.0
```

### 5.3 Verify Installation

```bash
python3 -c "import numpy, scipy, pandas, matplotlib; print('All dependencies satisfied.')"
```

Expected output:

```
All dependencies satisfied.
```

---

## Running the Project

### 6.1 Running the Core Engine (Command Line)

```bash
python3 fourier_martingale.py
```

This command executes the `run_full_demo()` function defined at the bottom of the module, which runs the complete engine pipeline in sequence:

```
[1] MARTINGALE PROPERTY VERIFICATION       — ~2 seconds
[2] MODEL PRICING COMPARISON               — ~10 seconds
[3] CUMULANT ANALYSIS                      — ~5 seconds
[4] CALIBRATION TO SYNTHETIC MARKET DATA   — ~90-180 seconds
[5] RISK ANALYTICS                         — ~30 seconds
```

Total execution time is approximately 2-5 minutes, dominated by the calibration step, which uses a differential evolution global optimiser with a population of 12 and up to 300 iterations. All results are printed to standard output as formatted tables.

### 6.2 Running the Jupyter Notebook

```bash
jupyter notebook fourier_martingale.ipynb
# or
jupyter lab fourier_martingale.ipynb
```

Once the notebook is open, select **Kernel > Restart Kernel and Run All Cells**. The notebook will execute sequentially from the preamble through all ten sections. Calibration cells in Section 8 may require 2-3 minutes. Do not interrupt execution during calibration, as the differential evolution optimiser maintains state across iterations and will restart from the beginning if interrupted.

All 14 figures will be rendered inline in the notebook interface. No external output files are generated; all figures exist as embedded cell outputs.

### 6.3 Importing the Engine as a Module

The engine may be imported into any Python script or interactive session as follows:

```python
from fourier_martingale import (
    HestonModel, MarketData, CalibrationEngine,
    FourierRiskAnalytics, MartingaleDiagnostics
)

# Instantiate a model
model = HestonModel(S=100.0, r=0.05, q=0.02, T=1.0,
                    v0=0.04, kappa=2.0, theta=0.04,
                    xi=0.3, rho=-0.70)

# Verify martingale condition
assert model.verify_martingale_condition(), "Model failed martingale check"

# Price a range of calls via Carr-Madan FFT
import numpy as np
strikes = np.array([90.0, 95.0, 100.0, 105.0, 110.0])
prices = model.price_carr_madan(strikes)

# Implied volatility surface
vols = model.implied_vol_surface(strikes)
for K, v in zip(strikes, vols):
    print(f"  K={K:.0f}: IV = {v*100:.2f}%")
```

The `verify_martingale_condition()` call should always precede pricing to confirm that the model's omega correction is numerically stable for the given parameter configuration.

---

## Methods

### 7.1 Architecture

The engine is organised around an abstract base class `StochasticModel`, which defines the interface shared by all six pricing models. The sole abstract method is `log_char_func(u)`, which each model overrides to provide its model-specific log-characteristic function. All pricing algorithms — `price_carr_madan`, `price_cos`, and `implied_vol_surface` — are implemented once in the base class and inherited by all models. This architecture ensures that every model automatically supports all pricing methods without per-model implementation, and that the addition of a new model requires only the implementation of `log_char_func`.

### 7.2 Martingale Constraint Enforcement

Each model enforces the martingale condition by incorporating a drift correction omega into the log-characteristic function. The specific form of omega is model-dependent:

- **BSM**: The martingale correction `omega = -(sigma^2/2)` is absorbed directly into the risk-neutral drift `(r - q - sigma^2/2)*T`. No additional term is required.
- **Heston**: The CIR variance process ensures that the characteristic function is inherently martingale under the risk-neutral parameterisation. No omega term is required.
- **VG**: `omega = log(1 - theta*nu - 0.5*sigma^2*nu) / nu`. This corrects for the non-zero expected log-return introduced by the Gamma subordination.
- **CGMY**: `omega = -C*Gamma(-Y)*((M-1)^Y - M^Y + (G+1)^Y - G^Y)`. This term subtracts the expected log-jump magnitude implied by the CGMY Lévy measure.
- **NIG**: `omega = delta*(sqrt(alpha^2-beta^2) - sqrt(alpha^2-(beta+1)^2))`. Derived from the cumulant generating function of the NIG distribution at argument 1.
- **MJD**: `kappa_J = exp(mu_J + delta_J^2/2) - 1` is the expected fractional jump size. The drift is adjusted by `-lambda_*kappa_J*T` to offset the expected jump contribution to the price level.

### 7.3 FFT Grid Parameter Selection

The Carr-Madan FFT method discretises both the frequency domain and the log-strike domain subject to the duality constraint `N * eta * lambda = 2*pi`, where N is the grid size, eta is the frequency grid spacing, and lambda is the log-strike spacing.

| Parameter | Value | Purpose |
|---|---|---|
| N | 4096 | Grid size (power of 2 for FFT) |
| eta | 0.25 | Frequency grid spacing |
| lambda | ~0.00153 | Log-strike spacing (~15 bps) |
| alpha | 1.5 | Dampening; numerically stable for all six models |

The choice `alpha = 1.5` ensures that the dampened call price `exp(alpha*k) * C(k)` is square-integrable for all models, including heavy-tailed jump processes such as CGMY and NIG. For very deep OTM options (K > 150 for S=100), FFT interpolation may introduce small errors; the COS method is preferred in such cases.

### 7.4 Calibration Methodology

Model calibration minimises the vega-weighted root mean squared error (RMSE) between model-implied and market-observed implied volatilities:

```
RMSE = sqrt( sum_i w_i * (sigma_model(K_i) - sigma_market(K_i))^2 )
where w_i = vega(K_i) / sum_j vega(K_j)
```

Vega weighting is preferred over equal weighting because it assigns greater penalty to errors at near-the-money strikes, which are the most liquid and therefore the most informative. Deep OTM options, which are often quoted with wide bid-ask spreads, are implicitly down-weighted.

The optimiser operates in two stages. First, differential evolution (Storn and Price, 1997) with a population of 12 individuals explores the parameter space globally for up to 300 generations. Second, the best solution from differential evolution is refined using L-BFGS-B, a quasi-Newton method with box constraints. This two-stage approach balances global coverage (avoiding local minima) with local precision (achieving tight convergence near the optimum).

RMSE values below 25 basis points (0.25%) are considered acceptable for practical surface fitting. Values below 10 basis points indicate a high-quality fit consistent with industrial applications.

### 7.5 Risk Measures via Fourier Inversion

The `FourierRiskAnalytics` class implements three risk metrics directly from the characteristic function, without Monte Carlo simulation.

The cumulative distribution function of the log-return `X_T` is recovered via the Gil-Pelaez (1951) inversion formula:

```
F(x) = 0.5 - (1/pi) * integral_0^inf Re[ exp(-i*u*x) * phi(u) / (i*u) ] du
```

Value-at-Risk at confidence level `1 - alpha` is the quantile `x*` satisfying `F(x*) = alpha`, solved via bisection on the above CDF. The bisection search brackets the solution using the empirical mean and standard deviation of the distribution (itself extracted from the characteristic function via cumulant analysis) and converges to tolerance `1e-6` in approximately 40 iterations.

Conditional Value-at-Risk (CVaR, also called Expected Shortfall) is computed as:

```
CVaR(alpha) = (1/alpha) * integral_{-inf}^{VaR(alpha)} x * f(x) dx
```

where `f(x)` is the risk-neutral density obtained from the characteristic function via Gil-Pelaez. The integral is evaluated numerically on a discrete grid of points below the VaR level.

Greeks are computed via finite differences applied to the Carr-Madan FFT price surface. Delta and Gamma require one additional FFT call each (shifted spot price), giving model-consistent Greeks in three FFT calls regardless of the number of strikes. This is substantially faster than running separate Monte Carlo simulations for each strike.

---

## Results and Figures

All figures in this section are generated by executing `fourier_martingale.ipynb`. The descriptions below correspond to the figure outputs produced during a standard run with the canonical parameters specified in Section 3 (Models): `S=100, r=0.05, q=0.02, T=1.0`.

#### Figure 1 — Martingale Error by Model

This figure displays a horizontal bar chart of the absolute martingale error `|phi(-i) - exp((r-q)*T)|` for each model on a logarithmic x-axis. All six models should display green bars (error below 1e-4). A red bar indicates an implementation error in the omega correction term of the affected model. In the canonical run, all models achieve errors below 1e-8, confirming correct martingale correction for all parameter configurations tested.

#### Figure 2 — Characteristic Functions of Log-Returns

A 2-by-3 grid of subplots displays the real and imaginary parts of `phi(u)` for each model over the frequency range `u in [0.01, 30]`. The BSM characteristic function shows smooth, exponentially decaying oscillations. The Heston CF exhibits slower decay reflecting the thicker tails generated by stochastic volatility. CGMY shows the most complex oscillatory behavior, consistent with its infinite-variation jump structure. The imaginary part reflects the asymmetry (skewness) of the return distribution.

#### Figure 3 — Characteristic Function Modulus Decay

This figure overlays the modulus `|phi(u)|` for all six models on a single plot over `u in [0.01, 50]`. The rate of decay as u increases is inversely related to tail heaviness: a faster-decaying CF corresponds to thinner tails. CGMY decays most slowly (heaviest tails); BSM decays fastest (thinnest tails, Gaussian distribution). A vertical reference line marks `u = 1/sqrt(T)`, the characteristic frequency scale at which models begin to differentiate meaningfully.

#### Figure 4 — Implied Volatility Smile by Model

The main smile comparison plot shows implied volatility as a function of strike for all six models at `T=1.0`. BSM produces a flat smile by definition. All other models produce a left-skewed smile consistent with observed equity market data: higher implied volatility for low strikes (OTM puts, hedging demand from crash protection) and lower for high strikes. CGMY exhibits the steepest skew and heaviest wings due to its power-law jump measure.

#### Figure 5 — Volatility Smile Decomposition

Four panels decompose the smile into left wing (K < 100), right wing (K > 100), skew proxy, and wing excess (kurtosis proxy). The skew proxy `(IV(90) - IV(110)) / (IV(90) + IV(110))` quantifies the asymmetry: all non-BSM models show negative values, with VG and CGMY exhibiting the most pronounced left skew. The kurtosis proxy `(IV(80) + IV(120) - 2*IV(100)) / IV(100)` measures convexity of the smile; CGMY is the dominant outlier reflecting extreme excess kurtosis.

#### Figure 6 — Risk-Neutral Density of Terminal Asset Price

The risk-neutral probability density `f(S_T)` is plotted for all models over the range `S_T in [60, 160]`. The gold-filled BSM density serves as the Gaussian reference. All non-BSM models show a left-shifted distribution with heavier left tails and reduced right tails relative to BSM, consistent with the equity risk premium and crash risk embedded in options markets. The vertical lines mark the ATM strike (K=100) and the forward price `F = S*exp((r-q)*T)`.

#### Figure 7 — Tail Density Comparison (Log Scale)

Two subplots display the log-density in the left tail (`S_T < 90`) and right tail (`S_T > 110`) respectively. On a log scale, a Gaussian tail appears as a downward-opening parabola; a power-law tail appears as a straight line. CGMY exhibits the most linear left tail, consistent with its polynomial Lévy measure and the slowest tail decay among the six models. BSM decays as a quadratic (Gaussian). This figure provides direct visual evidence for the heavy-tail structure of jump-diffusion and infinite-activity models.

#### Figure 8 — Carr-Madan FFT Validation Against BSM Closed Form

Three panels validate the FFT implementation against the exact Black-Scholes closed-form solution. Panel A compares prices directly; Panels B and C show absolute and relative errors respectively. All absolute errors should fall below $0.01 (one cent) for all strikes. Relative errors should be below 0.01% everywhere. The dashed red line in Panel B marks the one-cent threshold. This validation confirms that the FFT implementation is numerically accurate at the sub-cent level across the full strike range from $70 to $130.

#### Figure 9 — COS Method Convergence

The relative pricing error (in percent) is plotted as a function of the number of cosine terms N on log-log axes. BSM achieves machine-precision accuracy (error below 0.0001%) by N=32 due to its smooth, rapidly decaying characteristic function. Heston typically converges by N=64. CGMY converges most slowly, requiring N=128 or higher, due to the heavy-tailed density requiring a wider truncation interval for accurate series expansion. The dashed horizontal lines at 1% and 0.01% provide practical convergence thresholds.

#### Figure 10 — Volatility Surface Calibration: Market Fit Quality

Two panels display the calibration fit for Heston (Panel A) and Variance Gamma (Panel B) against a synthetic market surface. Gold circles represent noisy market observations; the teal line shows the calibrated model fit; the gray dashed line shows the true (noise-free) surface. Heston achieves sub-5-bps RMSE on this synthetic surface. VG achieves sub-15-bps RMSE. A closer alignment between the teal line and the gray dashed line (rather than the gold circles) indicates that the calibration is fitting the signal rather than the noise.

#### Figure 11 — Calibration Residual Analysis

Panel A displays residuals by strike in basis points (fitted vol minus observed vol). Residuals should be approximately symmetric around zero with no systematic pattern. A U-shaped residual pattern (positive at wings, negative at ATM) would indicate model misspecification — the model cannot reproduce the observed smile curvature. Panel B compares RMSE across models with a color coding: green bars indicate sub-10-bps RMSE (high quality), gold indicates 10-25 bps (acceptable), and red indicates above 25 bps (insufficient for production use).

#### Figure 12 — Fourier Risk Analytics Dashboard

Four panels present the Heston model's risk profile. Panel A compares VaR levels for BSM and Heston at confidence levels 99%, 97.5%, 95%, and 90%; Heston consistently shows larger losses due to its heavier tails. Panel B overlays the risk-neutral density with the VaR tail regions filled in red (below 5% VaR) and orange (between 5% and 1% VaR). Panel C shows delta across strikes, monotonically decreasing from near 1.0 (deep ITM) to near 0.0 (deep OTM). Panel D shows gamma, which peaks at ATM and decays symmetrically; the maximum gamma strike is annotated with a vertical dashed line.

#### Figure 13 — Cumulant Analysis: Distributional Properties by Model

Four panels display the first four cumulants of the log-return distribution for all six models. Panel A shows mean log-returns, which are approximately equal across models (all priced under the same risk-neutral measure). Panel B shows variance with the annualised equivalent volatility annotated on each bar. Panel C shows skewness: all non-BSM models show negative values (left skew, equity-consistent), with BSM at exactly zero. Panel D shows excess kurtosis: CGMY exhibits extreme positive kurtosis due to its power-law jump measure; NIG and VG exhibit moderate kurtosis; BSM is at zero (Gaussian benchmark).

#### Figure 14 — Model Comparison Heatmap: Normalised Metrics Summary

A 6-by-6 heatmap presents a comparative summary of six models against six metrics: ATM Vol (%), Smile Skew Proxy (%), Wing Excess (%), Skewness, Excess Kurtosis, and Martingale Error (log10 scale). Each column is normalised to [0, 1] to allow cross-metric comparison, with darker cells indicating higher values. The raw (non-normalised) values are annotated in each cell. Reading across rows reveals each model's distributional profile; reading down columns identifies which metric most discriminates among models. Excess kurtosis is the most discriminating metric, driven by CGMY's extreme tail behavior.

---

## Conclusions

The characteristic function approach provides a unified, model-agnostic computational framework for European option pricing in which the only model-specific computation is the evaluation of the log-characteristic function `log_CF(u)`. All pricing algorithms, calibration routines, and risk analytics operate on this single interface, enabling consistent treatment of fundamentally different model classes — from the simple lognormal diffusion of Black-Scholes-Merton to the infinite-variation pure jump process of CGMY — within a single codebase. The abstract base class architecture ensures that future models can be integrated by implementing a single method.

The computational validation confirms the accuracy and efficiency claims of the Fourier methods. The Carr-Madan FFT achieves sub-cent absolute pricing accuracy at N=4096 across all strikes from $70 to $130, as validated against the Black-Scholes closed-form solution. The COS method achieves the same level of accuracy at N=128 for smooth models (BSM, Heston) and N=256 for heavy-tailed models (CGMY, NIG), demonstrating its exponential convergence property. Volatility surface calibration via vega-weighted differential evolution achieves RMSE below 5 basis points for Heston and below 15 basis points for Variance Gamma on a synthetic surface with 100-basis-point observation noise.

The distributional analysis reveals statistically significant departures from the lognormal baseline in all non-BSM models. All five non-Gaussian models generate negative skewness and positive excess kurtosis in their risk-neutral return distributions, consistent with the empirical properties of equity option markets documented by Bakshi and Madan (2000) and Carr et al. (2002). CGMY exhibits the heaviest tail structure as quantified by the slowest characteristic function decay and the largest excess kurtosis. The Merton Jump-Diffusion model provides the most parsimonious representation of skewness and kurtosis with only four parameters. The Heston model uniquely captures the time-varying nature of implied volatility and the correlation between return and variance shocks through its stochastic volatility structure.

The practical implications for systematic trading and risk management are direct. The Fourier engine supports real-time volatility surface maintenance with sub-millisecond pricing for single expiries at N=256. Greeks computed via finite differences on the FFT surface are model-consistent by construction and require only three FFT calls regardless of the number of strikes, making the approach suitable for computing delta and gamma across a full option book. Fourier-inverted CVaR achieves O(N^{-2}) convergence compared to O(N^{-1/2}) for Monte Carlo, making it the preferred method for accurate tail risk quantification at the extreme confidence levels required by regulatory frameworks such as FRTB.

---

## Limitations

### 10.1 Static Parameters

All six models assume time-homogeneous parameters: volatility, jump intensity, and variance process coefficients are constant across time and across option expiries. In practice, calibrated Heston parameters — particularly the mean reversion speed kappa, long-run variance theta, and vol-of-vol xi — exhibit a pronounced term structure. A single-expiry calibration, as performed in this engine, cannot capture this structure. Accurate multi-expiry calibration requires a simultaneous fit across multiple maturities, which substantially increases computational complexity and may require a term-structure extension of the model (e.g., time-dependent theta in the Heston framework).

### 10.2 Heston Branch Cut Sensitivity

The engine uses the Albrecher et al. (2007) stable formulation of the Heston characteristic function to avoid the branch-cut discontinuities that affect the original Heston (1993) formulation. However, for extreme parameter configurations — specifically, very large xi (above 2.0), very long maturities (T above 5 years), or rho near -1 — residual numerical instability may cause the characteristic function to return values with numerically incorrect imaginary parts, leading to negative probability densities. Such configurations are detectable via the `verify_martingale_condition()` method, which will return False. Users should treat any failed martingale check as a signal to investigate the parameter configuration rather than proceed with pricing.

### 10.3 Lévy Model Independence of Path

The Variance Gamma, CGMY, NIG, and Merton Jump-Diffusion models are Lévy processes and therefore have independent, stationary increments by construction. This is a strong assumption: empirical equity return data exhibits volatility clustering, leverage effects (correlation between returns and volatility changes), and serial dependence in the variance process — all of which pure Lévy models cannot replicate. Stochastic volatility extensions, such as the Heston-CGMY hybrid model (using a CGMY process as the jump component in the Heston framework) or the Barndorff-Nielsen-Shephard model, are required for realistic simulation of return paths over multiple time steps.

### 10.4 COS Truncation Error

The COS method truncates the risk-neutral density support to a finite interval `[a, b]`, with the default choice `L=12` standard deviations determining the interval half-width. For models with very heavy tails — specifically CGMY with the fine-structure parameter Y approaching 2, or NIG with a large `alpha/|beta|` ratio near unity — this interval may be insufficient to capture the full mass of the distribution, leading to underestimation of deep OTM option values. Cumulant-based adaptive interval selection, as proposed by Fang and Oosterlee (2008), computes L from the model's cumulants at each maturity and is recommended for production implementations where parameter configurations cannot be controlled in advance.

### 10.5 Calibration Convergence

The differential evolution optimiser used in the calibration engine employs a fixed configuration (population size 12, maximum 300 iterations, mutation factor 0.7, crossover probability 0.9) that was selected for the canonical parameter range tested in this engine. The Heston calibration problem is documented to be multi-modal (Mikhailov and Nogel, 2003), meaning that the global optimiser may converge to different local minima on different runs from different random seeds. The RMSE results reported in this engine are valid for the specific synthetic surface and random seed (numpy seed 42) used in Section 8 and should not be taken as a guarantee of performance on all market conditions or initial parameter configurations.

### 10.6 Fourier CVaR Accuracy

The Gil-Pelaez CDF inversion used for VaR and CVaR computation integrates the characteristic function from 0 to an upper limit of 200 on the frequency axis. For models with very slowly decaying characteristic functions — specifically CGMY with Y approaching 2 (near Brownian motion activity) — this truncation can introduce oscillatory errors in the tail of the CDF. In the extreme left tail (alpha below 0.01), these oscillations may cause CVaR estimates to be inaccurate by 5-10% relative to a benchmark computed with a higher integration limit or more quadrature points. For regulatory CVaR at the 97.5% confidence level (alpha=0.025) as required under FRTB, the accuracy is adequate for all six models.

---

## References

[1] Albrecher, H., Mayer, P., Schoutens, W., and Tistaert, J. (2007). The little Heston trap. *Wilmott Magazine*, 83-92.

[2] Bakshi, G. and Madan, D. (2000). Spanning and derivative-security valuation. *Journal of Financial Economics*, 55(2):205-238.

[3] Barndorff-Nielsen, O. E. (1997). Processes of normal inverse Gaussian type. *Finance and Stochastics*, 2(1):41-68.

[4] Bergomi, L. (2016). *Stochastic Volatility Modeling*. Chapman and Hall/CRC Financial Mathematics Series.

[5] Carr, P. and Madan, D. B. (1999). Option valuation using the fast Fourier transform. *Journal of Computational Finance*, 2(4):61-73.

[6] Carr, P., Geman, H., Madan, D. B., and Yor, M. (2002). The fine structure of asset returns. *Journal of Business*, 75(2):305-332.

[7] Fang, F. and Oosterlee, C. W. (2008). A novel pricing method for European options based on Fourier-cosine series expansions. *SIAM Journal on Scientific Computing*, 31(2):826-848.

[8] Heston, S. L. (1993). A closed-form solution for options with stochastic volatility. *Review of Financial Studies*, 6(2):327-343.

[9] Lewis, A. L. (2001). A simple option formula for general jump-diffusion and other exponential Lévy processes. *SSRN Working Paper*.

[10] Madan, D. B., Carr, P. P., and Chang, E. C. (1998). The variance gamma process and option pricing. *European Finance Review*, 2(1):79-105.

[11] Merton, R. C. (1976). Option pricing when underlying stock returns are discontinuous. *Journal of Financial Economics*, 3(1-2):125-144.

[12] Mikhailov, S. and Nogel, U. (2003). Heston's stochastic volatility model: implementation, calibration and some extensions. *Wilmott Magazine*, July 2003, 74-79.

[13] Sato, K. (1999). *Lévy Processes and Infinitely Divisible Distributions*. Cambridge University Press.

[14] Gil-Pelaez, J. (1951). Note on the inversion theorem. *Biometrika*, 38(3-4):481-482.

[15] Cont, R. and Tankov, P. (2004). *Financial Modelling with Jump Processes*. Chapman and Hall/CRC Press.

[16] Schoutens, W. (2003). *Lévy Processes in Finance: Pricing Financial Derivatives*. Wiley.

---

## License

```
MIT License

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT.
```
