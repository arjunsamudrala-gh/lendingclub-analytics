-- Cleaning script: LendingClub loan purpose risk/profitability analysis
-- Scope: loans issued 2013-2015, resolved status only, individual applications
--
-- Filters and rationale (see README for full detail):
--   - issue_year 2013-2015: resolution-rate check showed 2016+ suffers from
--     survivorship bias (many loans still "Current" and unresolved as of the
--     data pull date), which would distort purpose-level default comparisons.
--   - loan_status: keep only Fully Paid / Charged Off (Default folded into
--     Charged Off as a credit-loss outcome, since it's a tiny bucket of 40
--     records dataset-wide). Excludes "Does not meet the credit policy"
--     variants (atypical underwriting) and unresolved statuses (Current,
--     Late, In Grace Period).
--   - purpose: excludes 'wedding' and 'educational' - both were phased out
--     by LendingClub during this window and have insufficient sample size
--     (wedding: 595 in 2013 -> 4 in 2015; educational: 1 loan total).
--   - application_type: Individual only. Joint applications report combined
--     borrower income/DTI, not comparable to individual-applicant figures,
--     and the feature largely postdates this window anyway.
--   - dti / fico nulls: only 2 null DTI rows and 0 null FICO rows in the
--     entire 2013-2015 window - dropped as negligible, no imputation needed.

CREATE OR REPLACE TABLE loans_clean AS
WITH base AS (
    SELECT
        id,
        loan_amnt,
        funded_amnt,
        term,
        int_rate,
        installment,
        grade,
        sub_grade,
        purpose,
        annual_inc,
        dti,
        fico_range_low,
        fico_range_high,
        loan_status,
        issue_d,
        STRPTIME(issue_d, '%b-%Y') AS issue_date,
        CAST(SUBSTR(issue_d, 5, 4) AS INTEGER) AS issue_year,
        total_pymnt,
        total_rec_prncp,
        total_rec_int,
        total_rec_late_fee,
        recoveries,
        last_pymnt_d,
        application_type
    FROM read_csv_auto('data/raw/accepted_2007_to_2018Q4.csv', ignore_errors=true)
)
SELECT
    *,
    CASE WHEN loan_status IN ('Charged Off', 'Default') THEN 'Charged Off'
         ELSE loan_status END AS loan_status_clean,
    total_pymnt - funded_amnt AS realized_pnl
FROM base
WHERE issue_year BETWEEN 2013 AND 2015
  AND loan_status IN ('Fully Paid', 'Charged Off', 'Default')
  AND purpose NOT IN ('wedding', 'educational')
  AND application_type = 'Individual'
  AND dti IS NOT NULL
  AND fico_range_low IS NOT NULL
  AND fico_range_high IS NOT NULL;
