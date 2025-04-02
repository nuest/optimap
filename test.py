from osgeo import ogr

# Replace with the path to your GeoPackage file.
filename = "/home/bharat/optimap/optimap/publications (4).gpkg"

datasource = ogr.Open(filename)
if datasource is None:
    print("Failed to open the GeoPackage file.")
    exit(1)

layer = datasource.GetLayer(0)
print("Layer Name:", layer.GetName())

for feature in layer:
    title = feature.GetField("title")
    abstract = feature.GetField("abstract")
    doi = feature.GetField("doi")
    source = feature.GetField("source")
    print(f"Title: {title}\nAbstract: {abstract}\nDOI: {doi}\nSource: {source}\n---")

datasource = None
