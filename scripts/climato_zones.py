"""Shared geographical viewports, not higher-resolution meteorological data."""
ZONES={
    "nord_ouest":("Nord-Ouest",(-5.7,3.0,46.3,51.5)),
    "nord_est":("Nord-Est",(2.0,8.5,46.3,51.5)),
    "sud_ouest":("Sud-Ouest",(-2.3,3.0,41.9,47.1)),
    "sud_est":("Sud-Est",(2.0,9.9,41.1,47.1)),
    "alpes":("Alpes",(4.6,7.9,43.5,46.7)),
    "pyrenees":("Pyrénées",(-2.1,3.3,42.1,43.7)),
    "massif_central":("Massif central",(1.5,4.9,43.3,46.6)),
}
def zone_filename(filename,zone):
    return filename.removesuffix(".png")+"-"+zone+".png"
def zone_files(folder,filename):
    return {z:zone_filename(filename,z) for z in ZONES if (folder/zone_filename(filename,z)).is_file()}
