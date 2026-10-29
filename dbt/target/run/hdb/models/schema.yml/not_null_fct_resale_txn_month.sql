
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  
    
    



select txn_month
from "hdb"."main"."fct_resale"
where txn_month is null



  
  
      
    ) dbt_internal_test