"""Prospective numeric precipitation archive, separate from map colors.
Common 0.04 degree geographic grid. Sample native-rendered arrays without
extrapolation; NaN remains missing. Actual publication time is the immutable
GitHub release asset created_at, not the model run or generation time.
"""
from datetime import datetime,timezone
from pathlib import Path
import numpy as np

class PrecipArchive:
    def __init__(self,model,run):
        self.model=model
        self.run=run
        self.times=[]
        self.frames=[]
    def add(self,valid,total,covered,width,height,step):
        stride=round(.04/step)
        if stride<1 or not np.isclose(stride*step,.04) or (width-1)*step!=16 or not np.isclose((height-1)*step,11):
            raise ValueError("Archive native raster geometry mismatch")
        a=np.asarray(total,dtype=np.float32).reshape(height,width)
        mask=np.asarray(covered,dtype=bool).reshape(height,width)
        a=np.where(mask&np.isfinite(a)&(a>=0),a,np.nan)[::stride,::stride].copy()
        if a.shape!=(276,401):raise ValueError("Archive common grid mismatch")
        if self.times and valid<=self.times[-1]:raise ValueError("Nonmonotonic forecast valid times")
        self.times.append(valid)
        self.frames.append(np.round(a,2))
    def save(self,directory):
        if not self.frames:raise ValueError("No archive frames")
        p=Path(directory)/f"verify-{self.model}-{self.run:%Y%m%d%H}-{datetime.now(timezone.utc):%Y%m%d%H%M%S}.npz"
        x,y=np.meshgrid(np.linspace(-6,10,401),np.linspace(52,41,276))
        np.savez_compressed(p,schema=np.array(1),model=np.array(self.model),run_utc=np.array(self.run.isoformat()),generated_utc=np.array(datetime.now(timezone.utc).isoformat()),valid_utc=np.array([t.isoformat() for t in self.times]),interval_minutes=np.array(60),unit=np.array("mm"),lon=x.astype(np.float32),lat=y.astype(np.float32),values=np.stack(self.frames))
        print("NUMERIC ARCHIVE",p.name,p.stat().st_size,len(self.frames),flush=True)
        return p.name

if __name__=="__main__":
    import tempfile
    from datetime import timedelta
    r=datetime(2026,1,1,tzinfo=timezone.utc)
    a=PrecipArchive("test",r);v=np.ones((1101,1601));m=np.ones_like(v,dtype=bool);m[:8,:8]=False
    a.add(r+timedelta(hours=1),v,m,1601,1101,.01)
    with tempfile.TemporaryDirectory() as d:
        name=a.save(d)
        with np.load(Path(d)/name,allow_pickle=False) as n:
            assert n["values"].shape==(1,276,401) and np.isnan(n["values"][0,0,0]) and n["values"][0,5,5]==1
    print("PASS numeric archive geometry and missing data")
