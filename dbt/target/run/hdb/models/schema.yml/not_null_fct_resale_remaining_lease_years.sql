
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  
    
    



select remaining_lease_years
from "hdb"."main"."fct_resale"
where remaining_lease_years is null



  
  
      
    ) dbt_internal_test