"""Stable identities for connected components of actual cell bonds.

Birth without a parent bond creates a child organism; a bonded birth is growth.
On split the largest surviving fragment keeps the ID and others are split-derived
children. On merge the largest contribution keeps its ID; ties use the lowest ID.
"""
from collections import Counter
import numpy as np

DIRECTIONS = [(dx,dy) for dy in (-1,0,1) for dx in (-1,0,1) if (dx,dy)!=(0,0)]

class Organisms:
    def __init__(self):
        self.next_id = 1
        self.records = {}
        self.live = {}

    def create(self, owner, tick, parent=None, origin="founder"):
        oid = self.next_id
        if oid > 2147483647: raise OverflowError("organism IDs exhausted")
        self.next_id += 1
        self.records[oid] = {"id":oid, "owner":int(owner), "parent":int(parent) if parent else None,
                             "origin":origin, "birth_tick":int(tick), "children":0, "merged_from":[]}
        if parent in self.records:
            self.records[parent]["children"] += 1
        return oid

    def update(self, arrays, tick):
        # Connectivity follows the eight explicit bonds, not merely adjacency.
        h,w=arrays.owner.shape
        visited=np.zeros((h,w),dtype=np.bool_)
        components=[]
        ys,xs=np.where(arrays.owner!=0)
        arrays.organism[arrays.owner==0]=0
        for y,x in zip(ys.tolist(),xs.tolist()):
            if visited[y,x]: continue
            owner=int(arrays.owner[y,x]); stack=[(x,y)]; visited[y,x]=True; coords=[]; counts=Counter()
            while stack:
                cx,cy=stack.pop(); coords.append((cx,cy)); old=int(arrays.organism[cy,cx])
                if old: counts[old]+=1
                mask=int(arrays.bonds[cy,cx])
                for bit,(dx,dy) in enumerate(DIRECTIONS):
                    nx,ny=cx+dx,cy+dy
                    if mask & (1<<bit) and 0<=nx<w and 0<=ny<h and not visited[ny,nx] and arrays.owner[ny,nx]==owner:
                        visited[ny,nx]=True;stack.append((nx,ny))
            components.append((owner,coords,counts))
        # Each old ID can survive in at most one component. Largest fragment wins.
        best={}
        for index,(_,coords,counts) in enumerate(components):
            for oid,count in counts.items():
                candidate=(count,len(coords),-index)
                if oid not in best or candidate>best[oid][0]: best[oid]=(candidate,index)
        live={}
        for index,(owner,coords,counts) in enumerate(components):
            eligible=[oid for oid in counts if oid in self.records and self.records[oid]["owner"]==owner and best[oid][1]==index]
            if eligible:
                oid=min(eligible,key=lambda x:(-counts[x],x))
                merged=[old for old in eligible if old!=oid]
                rec=self.records[oid]
                rec["merged_from"]=(rec["merged_from"]+merged)[-20:]
            elif counts:
                parent=min(counts,key=lambda x:(-counts[x],x))
                oid=self.create(owner,tick,parent=parent,origin="split")
            else:
                oid=self.create(owner,tick)
            rec=self.records[oid]
            for x,y in coords: arrays.organism[y,x]=oid
            energy=sum(int(arrays.energy[y,x]) for x,y in coords)
            live[str(oid)]={**rec,"cells":len(coords),"energy":energy}
        for key, record in live.items():
            record.update(self.records[int(key)])
        # Keep extinct ancestors referenced by living records, plus bounded recent history.
        if len(self.records)>50000:
            required={int(i) for i in live}
            required.update(r["parent"] for r in live.values() if r["parent"] is not None)
            for oid in list(self.records):
                if len(self.records)<=50000: break
                if oid not in required: del self.records[oid]
        self.live=live
        return live
