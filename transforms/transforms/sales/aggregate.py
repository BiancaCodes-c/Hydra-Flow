import polars as pl
from core.task import task

@task(deps=['clean_sales'])
def daily_revenue(ctx):
    df = ctx['clean_sales'] # comes from previous task
    return df.group_by('date').agg([
        pl.sum('amount').alias('revenue'),
        pl.count('order_id').alias('orders'),
        pl.col('amount').mean().alias('aov')
    ])

@task(deps=['clean_sales'])
def daily_revenue_sql(ctx):
    return ctx['_store'].con.execute("""
        SELECT date,
               sum(amount) as revenue,
               count(*) as orders,
               avg(amount) as aov
        FROM clean_sales
        GROUP BY date
    """).pl()
