"""Shared long-only cost accounting; rates are fractions, not percentages."""
import math


def break_even_exit(size, quantity, exit_fee, exit_slip=0, net_buffer_pct=0):
    values=(size,quantity,exit_fee,exit_slip,net_buffer_pct)
    if not all(math.isfinite(float(v)) for v in values) or size<=0 or quantity<=0 or not 0<=exit_fee<1 or not 0<=exit_slip<1 or net_buffer_pct<0:
        raise ValueError("Invalid break-even inputs")
    return size*(1+net_buffer_pct/100)/(quantity*(1-exit_fee)*(1-exit_slip))


def target_cost_budget(target_pct, liquidation_value, size=50):
    cost_pct=max(0,(1-liquidation_value/size)*100)
    return {"roundtrip_cost_pct":cost_pct,"allowed":target_pct>=5*cost_pct}
