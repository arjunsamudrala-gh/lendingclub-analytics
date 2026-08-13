"""
Compute time-normalized (annualized) return per loan and re-rank purposes.

Rationale: realized_pnl / funded_amnt (used in the SQL layer) treats a loan
that returns 8% over 6 months the same as one that returns 8% over 3 years -
but the first is a far better use of capital. Annualizing accounts for how
long money was actually tied up.

Methodology note: an initial pass using MEAN annualized return produced
implausible negative averages across every purpose, despite positive raw
returns. Diagnosis: linear annualization (return_pct * 12/months) massively
amplifies fast charge-offs (e.g. -100% over 1 month becomes -1200%), and a
small number of these (0.23% of loans, <-500% annualized) were enough to
drag every purpose's mean negative. Fixed by using MEDIAN instead of mean,
which is robust to this kind of outlier distortion. The median-based ranking
closely matches the original SQL-layer return-per-dollar ranking, confirming
that finding held up under a duration-adjusted check.
"""
import duckdb
import pandas as pd

con = duckdb.connect()
with open('sql/01_cleaning.sql') as f:
    con.execute(f.read())

df = con.execute("SELECT * FROM loans_clean WHERE last_pymnt_d IS NOT NULL").df()

df['issue_date'] = pd.to_datetime(df['issue_d'], format='%b-%Y')
df['last_pymnt_date'] = pd.to_datetime(df['last_pymnt_d'], format='%b-%Y')
df['months_outstanding'] = (
    (df['last_pymnt_date'].dt.year - df['issue_date'].dt.year) * 12
    + (df['last_pymnt_date'].dt.month - df['issue_date'].dt.month)
)
df['months_outstanding_floored'] = df['months_outstanding'].clip(lower=1)

df['return_pct'] = (df['realized_pnl'] / df['funded_amnt']) * 100
df['annualized_return_pct'] = df['return_pct'] * (12 / df['months_outstanding_floored'])

purpose_annualized = (
    df.groupby('purpose')
    .agg(
        loan_count=('id', 'count'),
        avg_months_outstanding=('months_outstanding_floored', 'mean'),
        median_annualized_return_pct=('annualized_return_pct', 'median'),
    )
    .round(2)
    .sort_values('median_annualized_return_pct')
)

print("Purposes ranked by MEDIAN annualized return (worst to best):")
print(purpose_annualized)

# Export for use in the writeup / Power BI
purpose_annualized.to_csv('data/processed/purpose_annualized_return.csv')
print("\nSaved to data/processed/purpose_annualized_return.csv")

# ---
# CORRECTION: median annualized return describes the "typical" loan, but
# the business question is about portfolio-level expected return, which
# must include tail losses (charge-offs). Per-loan annualization-then-average
# blows up for short-duration losses (see methodology note above); the fix
# is to aggregate dollars FIRST (which correctly weights in the tail losses),
# then annualize that aggregate ratio using the purpose's average duration.
# This gives a portfolio-relevant, duration-adjusted return that doesn't
# suffer from the individual-loan blowup problem.
purpose_portfolio = (
    df.groupby('purpose')
    .agg(
        loan_count=('id', 'count'),
        total_realized_pnl=('realized_pnl', 'sum'),
        total_funded_amnt=('funded_amnt', 'sum'),
        avg_months_outstanding=('months_outstanding_floored', 'mean'),
    )
)
purpose_portfolio['portfolio_return_pct'] = (
    purpose_portfolio['total_realized_pnl'] / purpose_portfolio['total_funded_amnt'] * 100
)
purpose_portfolio['portfolio_annualized_return_pct'] = (
    purpose_portfolio['portfolio_return_pct'] * (12 / purpose_portfolio['avg_months_outstanding'])
)
purpose_portfolio = purpose_portfolio.round(2).sort_values('portfolio_annualized_return_pct')

print("\n--- CORRECTED: Portfolio-level annualized return by purpose ---")
print(purpose_portfolio[['loan_count', 'avg_months_outstanding', 'portfolio_return_pct', 'portfolio_annualized_return_pct']])

purpose_portfolio.to_csv('data/processed/purpose_portfolio_annualized_return.csv')
print("\nSaved to data/processed/purpose_portfolio_annualized_return.csv")
