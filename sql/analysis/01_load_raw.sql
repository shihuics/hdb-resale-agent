CREATE OR REPLACE TABLE raw_resale AS
SELECT * FROM read_csv_auto('data/raw/*.csv', all_varchar = true);