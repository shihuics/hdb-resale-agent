
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  SELECT * FROM "hdb"."main"."fct_resale"
WHERE price_psm NOT BETWEEN 1500 AND 25000
  
  
      
    ) dbt_internal_test