-- Analysis script: purpose-level risk & profitability
-- Depends on: loans_clean (created by 01_cleaning.sql)
--
-- Note: ranking by avg_pnl_per_loan (raw dollars) would confound loan size
-- with risk - a purpose with larger average loans looks "safer" even at a
-- similar default rate, simply because non-defaulting large loans generate
-- more absolute interest. Fixed by ranking on return per dollar funded
-- (realized_pnl / funded_amnt), computed at the loan level before averaging.

CREATE OR REPLACE TABLE purpose_summary AS
SELECT
    purpose,
    COUNT(*) AS loan_count,
    SUM(CASE WHEN loan_status_clean = 'Charged Off' THEN 1 ELSE 0 END) AS charged_off_count,
    ROUND(
        SUM(CASE WHEN loan_status_clean = 'Charged Off' THEN 1 ELSE 0 END) * 100.0 / COUNT(*),
        2
    ) AS default_rate_pct,
    ROUND(AVG(realized_pnl), 2) AS avg_pnl_per_loan,
    ROUND(SUM(realized_pnl), 2) AS total_pnl,
    ROUND(AVG(realized_pnl / funded_amnt) * 100, 2) AS avg_return_pct,
    ROUND(AVG(int_rate), 2) AS avg_int_rate,
    ROUND(AVG(loan_amnt), 2) AS avg_loan_amnt
FROM loans_clean
GROUP BY purpose;

-- Rank purposes by risk-adjusted return per dollar funded (worst to best)
CREATE OR REPLACE TABLE purpose_ranked AS
SELECT
    purpose,
    loan_count,
    default_rate_pct,
    avg_pnl_per_loan,
    total_pnl,
    avg_return_pct,
    avg_int_rate,
    avg_loan_amnt,
    RANK() OVER (ORDER BY avg_return_pct ASC) AS risk_rank
FROM purpose_summary;

-- Vintage/cohort analysis: default rate by issue year x purpose
-- Uses a CTE to build the cohort table first, then a window function to
-- compute each purpose's default-rate trend year over year.
CREATE OR REPLACE TABLE purpose_vintage AS
WITH cohort AS (
    SELECT
        purpose,
        issue_year,
        COUNT(*) AS loan_count,
        SUM(CASE WHEN loan_status_clean = 'Charged Off' THEN 1 ELSE 0 END) AS charged_off_count,
        ROUND(
            SUM(CASE WHEN loan_status_clean = 'Charged Off' THEN 1 ELSE 0 END) * 100.0 / COUNT(*),
            2
        ) AS default_rate_pct
    FROM loans_clean
    GROUP BY purpose, issue_year
)
SELECT
    purpose,
    issue_year,
    loan_count,
    default_rate_pct,
    default_rate_pct - LAG(default_rate_pct) OVER (
        PARTITION BY purpose ORDER BY issue_year
    ) AS yoy_change_pct
FROM cohort
ORDER BY purpose, issue_year;

-- Percentile bucketing: within small_business, split loans into FICO
-- quartiles to check whether default risk is spread evenly across
-- borrowers or concentrated in a specific credit tier.
CREATE OR REPLACE TABLE small_business_fico_buckets AS
WITH bucketed AS (
    SELECT
        fico_range_low,
        loan_status_clean,
        NTILE(4) OVER (ORDER BY fico_range_low) AS fico_quartile
    FROM loans_clean
    WHERE purpose = 'small_business'
)
SELECT
    fico_quartile,
    COUNT(*) AS loan_count,
    MIN(fico_range_low) AS min_fico,
    MAX(fico_range_low) AS max_fico,
    SUM(CASE WHEN loan_status_clean = 'Charged Off' THEN 1 ELSE 0 END) AS charged_off_count,
    ROUND(
        SUM(CASE WHEN loan_status_clean = 'Charged Off' THEN 1 ELSE 0 END) * 100.0 / COUNT(*),
        2
    ) AS default_rate_pct
FROM bucketed
GROUP BY fico_quartile
ORDER BY fico_quartile;

-- Loan-level detail joined to purpose-level averages: gives each loan a
-- "distance from its own segment average" column. This is the project's
-- required non-trivial join - purpose-level aggregates (built above) joined
-- back to loan-level detail, rather than just aggregating in one direction.
CREATE OR REPLACE TABLE loan_detail_with_purpose_avg AS
SELECT
    l.id,
    l.purpose,
    l.grade,
    l.sub_grade,
    l.fico_range_low,
    l.dti,
    l.funded_amnt,
    l.int_rate,
    l.loan_status_clean,
    ROUND(l.realized_pnl / l.funded_amnt * 100, 2) AS loan_return_pct,
    p.avg_return_pct AS purpose_avg_return_pct,
    ROUND((l.realized_pnl / l.funded_amnt * 100) - p.avg_return_pct, 2) AS return_vs_purpose_avg,
    p.default_rate_pct AS purpose_default_rate_pct
FROM loans_clean l
JOIN purpose_summary p ON l.purpose = p.purpose;
