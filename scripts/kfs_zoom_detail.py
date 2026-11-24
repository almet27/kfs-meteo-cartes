"""Compact exact model-cell temperature samples for interactive zoom."""
import base64
import numpy as np
def samples(coords, values, spacing=None):
    xy=np.asarray(coords,dtype=float)
    v=np.asarray(values,dtype=float).reshape(-1)
    if xy.shape!=(len(v),2):raise ValueError("Invalid temperature coordinates")
    ok=np.isfinite(xy).all(axis=1)&np.isfinite(v)&(v>-100)&(v<80)
    packed=np.rint(np.column_stack((xy[ok,1]*1000,xy[ok,0]*100,v[ok]*10))).astype("<i2")
    # longitude in millidegrees, latitude in hundredths, temperature in tenths
    return {"schema":1,"format":"i16le-lon1000-lat100-temp10","count":len(packed),"spacing_deg":spacing,"data":base64.b64encode(packed.tobytes()).decode("ascii")}
def native(lon,lat,values,spacing=.075):
    from shapely import contains_xy
    from kfs_surface_style import mainland
    lon=np.asarray(lon,dtype=float);lat=np.asarray(lat,dtype=float);v=np.asarray(values,dtype=float)
    if v.shape!=(len(lat),len(lon)):raise ValueError("Invalid temperature grid")
    dx=max(1,int(round(spacing/abs(float(np.median(np.diff(lon)))))))
    dy=max(1,int(round(spacing/abs(float(np.median(np.diff(lat)))))))
    x,y=np.meshgrid(lon[::dx],lat[::dy]);z=v[::dy,::dx]
    mask=contains_xy(mainland(),x,y)
    return samples(np.column_stack((y[mask],x[mask])),z[mask],max(abs(float(np.median(np.diff(lon))))*dx,abs(float(np.median(np.diff(lat))))*dy))
def geometry(ax):
    ax.apply_aspect()
    return {"axes":list(ax.get_position().bounds),"xlim":list(ax.get_xlim()),"ylim":list(ax.get_ylim())}
