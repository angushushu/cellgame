"""Biome seed, spawn spacing, and player observation privacy."""
import sys
from pathlib import Path
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from cellgame.server.world import WorldState
from cellgame.server.perception import gather_observation
from cellgame.shared.manifest import build_manifest
from cellgame.shared.observation import observation_to_world, remember

a=WorldState(256,256,seed=42); b=WorldState(256,256,seed=42)
assert np.array_equal(a.arrays.env_biome,b.arrays.env_biome)
assert set(np.unique(a.arrays.env_biome)) == {1,2,3,4}
assert a.spawn_player(1,1)==20 and a.spawn_player(2,2)==20
p1=np.argwhere(a.arrays.owner==1).mean(axis=0);p2=np.argwhere(a.arrays.owner==2).mean(axis=0)
assert np.linalg.norm(p1-p2)>60, (p1,p2)
manifest=build_manifest({"world":{"width":256,"height":256},"perception":{"model":"radius","radius":1}})
a.configure(manifest)
obs=gather_observation(a,1,manifest)
tiles=obs["tiles"]; visible=tiles["env_visible"]
assert len(obs["biomes"])==len(tiles)
assert np.all(obs["biomes"][visible] == a.arrays.env_biome[tiles["y"][visible],tiles["x"][visible]])
assert np.all(obs["biomes"][~visible]==0)
view=observation_to_world(obs,1,256,256)
assert np.count_nonzero(view.env_biome) <= len(tiles) < 256*256
print("BIOME AND SPAWN TEST PASSED")
