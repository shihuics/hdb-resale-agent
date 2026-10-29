
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  
    
    



select resale_price
from "hdb"."main"."fct_resale"
where resale_price is null



  
  
      
    ) dbt_internal_test