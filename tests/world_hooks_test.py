"""Custom world hooks remain authoritative and cannot mutate live arrays."""
import sys, tempfile
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from cellgame.server.world import WorldState
from cellgame.server.world_rules import WorldRuleEngine
from cellgame.server.sim_process import resolve_tick
from cellgame.shared.models import Action, INTENTION_DTYPE

source = """
def on_epoch(summary, tick): return {}
def filter_actions(actions, players, world_view, tick):
    world_view._a.owner[:] = 0
    return [False] * len(actions)
def before_ecology(world_view, tick):
    return [{"type":"adjust_energy", "x":1, "y":1, "amount":-2}]
"""
with tempfile.TemporaryDirectory() as d:
    p=Path(d)/"rules.py";p.write_text(source,encoding="utf-8")
    rules=WorldRuleEngine(str(p));w=WorldState(8,8,seed=1);w.arrays.env_material[:]=0;w.place_cell(1,1,1,10)
    action=np.array([(1,1,2,1,Action.MOVE,0,0)],dtype=INTENTION_DTYPE)
    counts=resolve_tick(w,{1:(action,np.array([1]))},rules)
    assert counts["move"]==0 and w.arrays.owner[1,1]==1 and w.arrays.energy[1,1]==8
    p.write_text("def on_epoch(summary,tick): return {}\ndef filter_actions(a,p,w,t): return [True, True]\n",encoding="utf-8")
    try: resolve_tick(w,{1:(action,np.array([1]))},WorldRuleEngine(str(p)))
    except RuntimeError: pass
    else: raise AssertionError("invalid filter must stop tick")
print("WORLD HOOKS TEST PASSED")
