"""
Does loan purpose still predict default after controlling for grade, FICO,
DTI, and interest rate?

This matters because of an earlier finding: high-risk-grade loans (e.g.
Grade G) showed extreme return variance regardless of purpose, raising the
question of whether "purpose" is doing real explanatory work or just acting
as a weak proxy for who happens to have worse credit. If purpose remains
significant after controlling for these factors, that's evidence the
purpose itself carries independent risk information (e.g. business cash
flow volatility for small_business) - which is a stronger basis for a
purpose-based underwriting recommendation than an uncontrolled comparison.
"""
import duckdb
import pandas as pd
import statsmodels.api as sm
import statsmodels.formula.api as smf

con = duckdb.connect()
with open('sql/01_cleaning.sql') as f:
    con.execute(f.read())

df = con.execute("SELECT * FROM loans_clean").df()

df['charged_off'] = (df['loan_status_clean'] == 'Charged Off').astype(int)

# grade as ordered category, purpose as categorical - statsmodels' formula
# API handles dummy encoding automatically via C()
model = smf.logit(
    'charged_off ~ C(grade) + fico_range_low + dti + int_rate + C(purpose)',
    data=df
).fit()

print(model.summary())

# Isolate just the purpose coefficients for a cleaner read
print("\n--- Purpose coefficients only (relative to baseline category) ---")
purpose_params = model.params[model.params.index.str.contains('purpose')]
purpose_pvalues = model.pvalues[model.pvalues.index.str.contains('purpose')]
purpose_summary = pd.DataFrame({
    'coefficient': purpose_params,
    'p_value': purpose_pvalues,
    'significant_at_5pct': purpose_pvalues < 0.05
}).sort_values('coefficient')
print(purpose_summary)
