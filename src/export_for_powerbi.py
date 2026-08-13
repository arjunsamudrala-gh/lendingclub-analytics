"""
Export final analysis tables as clean CSVs for Power BI.

Consolidates outputs from the SQL layer (sql/02_analysis.sql) and the
Python layer (src/annualized_return.py, src/purpose_regression.py) into
data/processed/, ready for Power BI to load directly - no aggregation
logic needed on the Power BI side, keeping SQL as the analytical layer.
"""
import duckdb
import pandas as pd
import statsmodels.formula.api as smf
import os

os.makedirs('data/processed', exist_ok=True)

con = duckdb.connect()
with open('sql/01_cleaning.sql') as f:
    con.execute(f.read())
with open('sql/02_analysis.sql') as f:
    con.execute(f.read())

# 1. Purpose ranking (SQL layer - RANK by return per dollar)
con.execute("COPY purpose_ranked TO 'data/processed/purpose_ranked.csv' (HEADER, DELIMITER ',')")
print("Exported purpose_ranked.csv")

# 2. Vintage/cohort trend (SQL layer - CTE + LAG)
con.execute("COPY purpose_vintage TO 'data/processed/purpose_vintage.csv' (HEADER, DELIMITER ',')")
print("Exported purpose_vintage.csv")

# 3. FICO quartile buckets for small_business (SQL layer - NTILE)
con.execute("COPY small_business_fico_buckets TO 'data/processed/small_business_fico_buckets.csv' (HEADER, DELIMITER ',')")
print("Exported small_business_fico_buckets.csv")

# 4. Loan-level detail with purpose averages (SQL layer - the join)
#    Exporting a summary, not all 732K rows, to keep the file light for BI
con.execute("""
    COPY (
        SELECT purpose, grade, loan_status_clean, 
               COUNT(*) as loan_count,
               ROUND(AVG(return_vs_purpose_avg), 2) as avg_return_vs_purpose_avg
        FROM loan_detail_with_purpose_avg
        GROUP BY purpose, grade, loan_status_clean
    ) TO 'data/processed/loan_detail_by_purpose_grade.csv' (HEADER, DELIMITER ',')
""")
print("Exported loan_detail_by_purpose_grade.csv")

# 5. Portfolio-level annualized return (Python layer - corrected version)
df = con.execute("SELECT * FROM loans_clean WHERE last_pymnt_d IS NOT NULL").df()
df['issue_date'] = pd.to_datetime(df['issue_d'], format='%b-%Y')
df['last_pymnt_date'] = pd.to_datetime(df['last_pymnt_d'], format='%b-%Y')
df['months_outstanding'] = (
    (df['last_pymnt_date'].dt.year - df['issue_date'].dt.year) * 12
    + (df['last_pymnt_date'].dt.month - df['issue_date'].dt.month)
)
df['months_outstanding_floored'] = df['months_outstanding'].clip(lower=1)

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
purpose_portfolio = purpose_portfolio.round(2).sort_values('portfolio_annualized_return_pct').reset_index()
purpose_portfolio.to_csv('data/processed/purpose_portfolio_annualized_return.csv', index=False)
print("Exported purpose_portfolio_annualized_return.csv")

# 6. Regression coefficients (Python layer)
df['charged_off'] = (df['loan_status_clean'] == 'Charged Off').astype(int)
model = smf.logit(
    'charged_off ~ C(grade) + fico_range_low + dti + int_rate + C(purpose)',
    data=df
).fit(disp=0)
purpose_params = model.params[model.params.index.str.contains('purpose')]
purpose_pvalues = model.pvalues[model.pvalues.index.str.contains('purpose')]
regression_summary = pd.DataFrame({
    'purpose_dummy': purpose_params.index,
    'coefficient': purpose_params.values,
    'p_value': purpose_pvalues.values,
    'significant_at_5pct': purpose_pvalues.values < 0.05
}).sort_values('coefficient', ascending=False)
regression_summary.to_csv('data/processed/purpose_regression_coefficients.csv', index=False)
print("Exported purpose_regression_coefficients.csv")

print("\nAll exports complete. Files in data/processed/:")
for f in sorted(os.listdir('data/processed')):
    print(" -", f)
