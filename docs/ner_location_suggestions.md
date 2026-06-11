# NER-based location and date suggestions

The work landing page includes a "Suggest locations and dates from text" panel that uses Named Entity Recognition (NER) to find place names and date mentions in a work's title and abstract, then looks up place names in a gazetteer to produce map-ready geometries and fills in temporal extent from date mentions.

## How it works

1. Expand the "Suggest locations and dates from text" panel, which sits between the spatial and temporal contribution sections (since it feeds both).
2. The title and abstract are pre-filled in two editable text areas.
3. Click **Suggest locations and dates**: OPTIMAP sends each text separately to `/api/v1/geoextent/extract-text/` (two parallel requests), which runs:
   - **spaCy NER** — detects location entity spans (`GPE`, `LOC`) and date mentions in the text.
   - **Gazetteer lookup** — each detected place name is forward-geocoded (Nominatim by default) to a coordinate and polygon boundary.
4. Results appear below the text areas. Place names in the text are highlighted (green = matched, yellow = ambiguous).
5. **Dates found**: if date mentions were extracted, a "Suggested dates" row shows the detected period with a **Use these dates** button that fills the start/end date fields.
6. **Places found**: Click **Add to map** next to any resolved place, or **Add all to map** to bulk-add matched places to the map drawing layer.
7. After adding places and dates, submit the contribution as normal.

## Result states

| Icon | Meaning |
|------|---------|
| 📍 (green) | Matched — the name resolved to a unique gazetteer result. "Add to map" is available. |
| ⚠️ (yellow) | Ambiguous — the name matched multiple gazetteer candidates. Dropped in strict mode; included in lenient mode. |
| ✗ (red) | Not found — the name was detected by NER but the gazetteer returned no results. |

## Ambiguity modes

| Mode | Behaviour |
|------|-----------|
| **Drop ambiguous (strict)** (default) | Place names with more than one gazetteer match (e.g. "Paris" → France, Texas, …) are excluded. Fewer results but higher precision. |
| **Keep best match (lenient)** | The highest-ranked gazetteer result is kept even when multiple candidates exist. More results, but some may be incorrect. |

Switch modes and click **Suggest locations and dates** again to re-run.

## Gazetteers

| Gazetteer | Notes |
|-----------|-------|
| **Nominatim** (default) | OpenStreetMap data. Free, no key required. Returns administrative polygon boundaries when available. |
| **Photon** | Also OSM-based. Faster for some queries. |
| **GeoNames** | Requires `OPTIMAP_GEOEXTENT_GEONAMES_USERNAME` to be set in the environment. |

## Provenance

When you submit a contribution after adding NER suggestions to the map, the provenance log records a `geometry_source` entry on the contribution event:

```json
{
  "source": "ner",
  "ner_model": "en_core_web_sm",
  "ner_gazetteer": "nominatim",
  "place_names": ["Berlin", "Germany"]
}
```

This lets curators and admins see that the geometry was derived from text extraction rather than drawn manually.

## First-call latency

On first use, spaCy downloads its default English model (`en_core_web_sm`, ~12 MB). This is a one-off download; subsequent calls reuse the cached model. Expect 5–15 s for the first request; subsequent requests are typically 1–3 s.

## Configuration

| Environment variable | Default | Description |
|----------------------|---------|-------------|
| `OPTIMAP_GEOEXTENT_NER_GAZETTEER` | `nominatim` | Default gazetteer for NER extraction. |
| `OPTIMAP_GEOEXTENT_NER_MODEL` | *(empty)* | spaCy model name override. Leave blank to use geoextent's default. |

## API reference

See the OpenAPI docs at `/api/schema/ui/` → **Geoextent** → `POST /api/v1/geoextent/extract-text/`.

The endpoint is public (no authentication required) and accepts:

```json
{
  "text": "Fieldwork was conducted in the city of Hannover, Germany, in summer 2023.",
  "gazetteer": "nominatim",
  "ner_ambiguity": "drop",
  "tbox": true,
  "convex_hull": false
}
```

The response is a GeoJSON FeatureCollection. The `geoextent_extraction` property contains `place_names`, a list of all detected entities with character offsets, match status, coordinates, and gazetteer URLs.
