
    
    

with all_values as (

    select
        flat_type as value_field,
        count(*) as n_records

    from "hdb"."main"."fct_resale"
    group by flat_type

)

select *
from all_values
where value_field not in (
    '1 ROOM','2 ROOM','3 ROOM','4 ROOM','5 ROOM','EXECUTIVE','MULTI-GENERATION'
)


