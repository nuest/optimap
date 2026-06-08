# Accessing OPTIMAP via OGC API - Features

OPTIMAP exposes its published works through an [OGC API - Features](https://ogcapi.ogc.org/features/) endpoint
at `/ogcapi/`. This is a standards-compliant interface that any WFS3-capable client can consume.

**Base URL:** `https://optimap.science/ogcapi/`

Key endpoints:

| URL | Description |
|-----|-------------|
| `/ogcapi/` | Landing page |
| `/ogcapi/conformance` | Conformance declaration |
| `/ogcapi/collections` | Available collections |
| `/ogcapi/collections/works/items` | Published works (GeoJSON FeatureCollection) |
| `/ogcapi/collections/works/items/{id}` | Single work by ID |

**Query parameters** on the items endpoint:

| Parameter | Description | Example |
|-----------|-------------|---------|
| `bbox` | Spatial filter (minLon,minLat,maxLon,maxLat) | `bbox=5,47,15,55` |
| `datetime` | Temporal filter (ISO 8601 date or interval) | `datetime=2023-01-01/2024-01-01` |
| `limit` | Page size (default 10) | `limit=100` |
| `offset` | Pagination offset | `offset=200` |

---

## Python

**Dependencies:** `requests`, `geopandas`, `folium`

```python
import requests
import geopandas as gpd
import folium

# Fetch publications within a bounding box (central Europe)
resp = requests.get(
    "https://optimap.science/ogcapi/collections/works/items",
    params={"bbox": "5,47,15,55", "limit": 100},
)
resp.raise_for_status()
geojson = resp.json()

print(f"{geojson['numberMatched']} total works matched, showing {geojson['numberReturned']}")

gdf = gpd.GeoDataFrame.from_features(geojson["features"], crs="EPSG:4326")
print(gdf[["title", "doi", "publicationDate"]].head())

# Interactive map saved to HTML
centroid = [gdf.geometry.centroid.y.mean(), gdf.geometry.centroid.x.mean()]
m = folium.Map(location=centroid, zoom_start=5)
folium.GeoJson(
    gdf,
    popup=folium.GeoJsonPopup(fields=["title", "doi"]),
).add_to(m)
m.save("works_map.html")
print("Map saved to works_map.html")
```

For **pagination** over all results:

```python
import requests

base = "https://optimap.science/ogcapi/collections/works/items"
params = {"bbox": "5,47,15,55", "limit": 100, "offset": 0}
all_features = []

while True:
    resp = requests.get(base, params=params)
    data = resp.json()
    all_features.extend(data["features"])
    next_link = next((l for l in data["links"] if l["rel"] == "next"), None)
    if not next_link or len(all_features) >= data["numberMatched"]:
        break
    params["offset"] += params["limit"]

print(f"Fetched {len(all_features)} of {data['numberMatched']} works")
```

---

## R

**Dependencies:** `sf`, `mapview` (for quick look); `httr2`, `jsonlite` for pagination control.

### Quick one-liner (sf + mapview)

```r
library(sf)
library(mapview)

# sf reads GeoJSON over HTTP via GDAL — simplest approach
works <- read_sf(
  "https://optimap.science/ogcapi/collections/works/items?bbox=5,47,15,55&limit=100"
)
print(works[, c("title", "doi", "publicationDate")])
mapview(works)
```

### With pagination control (httr2)

```r
library(httr2)
library(jsonlite)
library(sf)
library(mapview)

resp <- request("https://optimap.science/ogcapi/collections/works/items") |>
  req_url_query(bbox = "5,47,15,55", limit = 100) |>
  req_perform()

data <- resp |> resp_body_json()
cat("Total matched:", data$numberMatched, "\n")

works <- st_as_sf(fromJSON(resp_body_string(resp)))
mapview(works)
```

---

## QGIS

### GUI (no coding needed)

> **HTTPS required.** QGIS's OGC API - Features dialog only accepts `https://` URLs.
> For local development use the PyQGIS console approach below.

1. Open QGIS 3.28+
2. **Layer → Add Layer → Add WFS / OGC API - Features Layer**
3. Click **New** to add a connection:
   - **Name:** `OPTIMAP`
   - **URL:** `https://optimap.science/ogcapi/`
   - **WFS Version:** select **OGC API - Features** from the dropdown
4. Click **Detect** to confirm the endpoint, then **OK**
5. Select the `works` collection and click **Add**

You can apply a bounding box filter directly in the connection dialog.

### PyQGIS console

```python
from qgis.core import QgsVectorLayer, QgsProject
from qgis.utils import iface

# Production
uri = "oapif://https://optimap.science/ogcapi/collections/works/items?bbox=5,47,15,55"

# Local development (http:// is only supported via the OGR OAPIF driver)
# uri = "OAPIF:http://localhost:8000/ogcapi/"

layer = QgsVectorLayer(uri, "OPTIMAP Works", "OAPIF")

if layer.isValid():
    QgsProject.instance().addMapLayer(layer)
    iface.mapCanvas().zoomToFullExtent()
    print(f"Loaded {layer.featureCount()} features")
else:
    print("Failed:", layer.error().message())
```

Remove the `?bbox=…` parameter to load all published works globally (may be slow for large datasets).
