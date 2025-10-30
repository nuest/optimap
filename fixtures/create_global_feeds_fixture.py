#!/usr/bin/env python3
"""
Generate comprehensive test_data_global_feeds.json fixture with:
- One work completely within each global region (continents + oceans)
- One work overlapping two neighboring regions
- Seven works spanning more than two global regions
- Metadata diversity matching test_data_optimap.json patterns
"""

import json
from datetime import datetime, timedelta
import random

# Metadata samples for diversity (matching optimap patterns)
AUTHOR_SAMPLES = [
    [],  # No authors (for some publications)
    ["Dr. Single Author"],
    ["Dr. First Author", "Prof. Second Author"],
    ["Dr. Alice Smith", "Prof. Bob Jones", "Dr. Carol Williams"],
    ["Dr. Maria Garcia", "Prof. John Smith", "Dr. Emma Johnson", "Dr. Li Wei"],
    ["Prof. A", "Dr. B", "Dr. C", "Dr. D", "Dr. E", "Prof. F"],
    ["Dr. Zhang Wei", "Prof. Sarah Johnson", "Dr. Ahmed Hassan", "Dr. Maria Rodriguez", "Dr. John O'Connor", "Prof. Yuki Tanaka", "Dr. Pierre Dubois"],
]

KEYWORD_SAMPLES = [
    [],  # No keywords
    ["single keyword"],
    ["first keyword", "second keyword"],
    ["climate change", "remote sensing", "geospatial analysis"],
    ["biodiversity", "ecosystem services", "conservation", "habitat mapping"],
    ["urban planning", "sustainability", "GIS", "land use", "spatial analysis", "demographics"],
]

TOPIC_SAMPLES = [
    [],  # No topics
    ["Geography"],
    ["Environmental Science", "Ecology"],
    ["Climate Science", "Atmospheric Science", "Meteorology"],
]

OPENALEX_STATUS_SAMPLES = [None, "green", "gold", "hybrid", "bronze", "closed", "diamond"]

PROVENANCE_TEMPLATES = [
    "Harvested via OAI-PMH from {source_name} on {timestamp}.\nHarvestingEvent ID: {event_id}.\n\nMetadata Sources:\n  - authors: original_source\n  - keywords: original_source\n  - topics: openalex\n  - openalex_metadata: openalex",
    "Harvested via RSS/Atom feed from {source_name} on {timestamp}.\nHarvestingEvent ID: {event_id}.\n\nMetadata Sources:\n  - authors: openalex\n  - keywords: original_source\n  - topics: openalex\n  - openalex_metadata: openalex",
    "Harvested via OAI-PMH from {source_name} on {timestamp}.\nHarvestingEvent ID: {event_id}.\n\nNo authors or keywords found in original source. OpenAlex matching found partial matches but no exact match.",
    "Harvested via RSS/Atom feed from {source_name} on {timestamp}.\nHarvestingEvent ID: {event_id}.\n\nMetadata Sources:\n  - authors: original_source\n  - keywords: original_source\n  - topics: (none - OpenAlex match not found)",
]

# Global region definitions with representative geometries
# Format: (name, geometry_wkt, description)
CONTINENTS = [
    # Africa (completely within)
    ("Africa", "POLYGON ((10 -25, 40 -25, 40 30, 10 30, 10 -25))", "Central and Eastern Africa"),
    # Asia (completely within)
    ("Asia", "POLYGON ((70 15, 120 15, 120 50, 70 50, 70 15))", "Central and East Asia"),
    # Europe (completely within)
    ("Europe", "POLYGON ((0 45, 30 45, 30 65, 0 65, 0 45))", "Central and Western Europe"),
    # North America (completely within)
    ("North America", "POLYGON ((-120 30, -80 30, -80 50, -120 50, -120 30))", "Central United States and Canada"),
    # South America (completely within)
    ("South America", "POLYGON ((-70 -30, -50 -30, -50 0, -70 0, -70 -30))", "Brazil and surrounding regions"),
    # Australia (completely within)
    ("Australia", "POLYGON ((120 -35, 145 -35, 145 -15, 120 -15, 120 -35))", "Eastern Australia"),
    # Antarctica (completely within)
    ("Antarctica", "POLYGON ((-60 -75, 60 -75, 60 -65, -60 -65, -60 -75))", "Antarctic Peninsula region"),
]

OCEANS = [
    # Arctic Ocean (completely within)
    ("Arctic Ocean", "POLYGON ((-20 75, 20 75, 20 85, -20 85, -20 75))", "Arctic Ocean near North Pole"),
    # North Atlantic Ocean (completely within)
    ("North Atlantic Ocean", "POLYGON ((-40 25, -20 25, -20 50, -40 50, -40 25))", "North Atlantic Ocean"),
    # South Atlantic Ocean (completely within)
    ("South Atlantic Ocean", "POLYGON ((-30 -35, -10 -35, -10 -10, -30 -10, -30 -35))", "South Atlantic Ocean"),
    # Indian Ocean (completely within)
    ("Indian Ocean", "POLYGON ((60 -30, 80 -30, 80 -10, 60 -10, 60 -30))", "Western Indian Ocean"),
    # North Pacific Ocean (completely within)
    ("North Pacific Ocean", "POLYGON ((150 10, 170 10, 170 40, 150 40, 150 10))", "North Pacific Ocean"),
    # South Pacific Ocean (completely within)
    ("South Pacific Ocean", "POLYGON ((160 -35, 180 -35, 180 -10, 160 -10, 160 -35))", "South Pacific Ocean"),
    # Southern Ocean (completely within)
    ("Southern Ocean", "POLYGON ((0 -65, 40 -65, 40 -55, 0 -55, 0 -65))", "Southern Ocean around Antarctica"),
    # Mediterranean Region (completely within)
    ("Mediterranean Region", "POLYGON ((10 32, 25 32, 25 42, 10 42, 10 32))", "Mediterranean Region"),
    # South China and Easter Archipelagic Seas (completely within)
    ("South China and Easter Archipelagic Seas", "POLYGON ((110 -30, 130 -30, 130 10, 110 10, 110 -30))", "South China and Easter Archipelagic Seas"),
    # Baltic Sea (completely within)
    ("Baltic Sea", "POLYGON ((15 54, 25 54, 25 62, 15 62, 15 54))", "Baltic Sea"),
]

# Works that overlap two neighboring regions
TWO_REGION_OVERLAPS = [
    ("Europe-Asia", "POLYGON ((25 40, 65 40, 65 55, 25 55, 25 40))", "Spanning Eastern Europe and Western Asia"),
    ("North America-Atlantic", "POLYGON ((-80 25, -50 25, -50 45, -80 45, -80 25))", "Eastern North America and Western Atlantic"),
    ("Africa-Indian Ocean", "POLYGON ((35 -20, 55 -20, 55 5, 35 5, 35 -20))", "East African coast and Western Indian Ocean"),
    ("South America-Pacific", "POLYGON ((-85 -20, -65 -20, -65 5, -85 5, -85 -20))", "Western South America and Eastern Pacific"),
    ("Asia-Pacific", "POLYGON ((115 20, 140 20, 140 45, 115 45, 115 20))", "East Asian coast and Western Pacific"),
]

# Works that span more than two global regions (7 required)
MULTI_REGION_SPANS = [
    ("Global Ocean Survey", "MULTIPOLYGON (((-40 -10, -20 -10, -20 10, -40 10, -40 -10)), ((60 -20, 80 -20, 80 0, 60 0, 60 -20)), ((150 -30, 170 -30, 170 -10, 150 -10, 150 -30)))", "Atlantic, Indian, and Pacific Oceans"),
    ("Trans-Atlantic Research", "POLYGON ((-70 20, 10 20, 10 50, -70 50, -70 20))", "North America, Atlantic Ocean, and Europe"),
    ("African-Asian Monsoon Study", "POLYGON ((20 -10, 90 -10, 90 25, 20 25, 20 -10))", "Africa, Indian Ocean, and Asia"),
    ("Pan-Pacific Study", "POLYGON ((110 -40, -80 -40, -80 50, 110 50, 110 -40))", "Asia, Pacific Ocean, North America, South America, Australia"),
    ("Southern Hemisphere Ocean Study", "POLYGON ((-180 -60, 180 -60, 180 -35, -180 -35, -180 -60))", "Southern Ocean, Pacific, Atlantic, Indian Oceans, South America, Africa, Australia, Antarctica"),
    ("Arctic Circumpolar Study", "POLYGON ((-180 65, 180 65, 180 85, -180 85, -180 65))", "Arctic Ocean, North America, Europe, Asia"),
    ("Global Climate Network", "MULTIPOLYGON (((-120 30, -100 30, -100 45, -120 45, -120 30)), ((10 40, 30 40, 30 55, 10 55, 10 40)), ((120 -30, 140 -30, 140 -20, 120 -20, 120 -30)), ((-50 -20, -40 -20, -40 -10, -50 -10, -50 -20)))", "North America, Europe, Australia, South America"),
]

# Point geometries - one per global region (7 continents + 10 oceans = 17 points)
REGION_POINTS = [
    # Continental points
    ("Field Site: Central Africa", "POINT (20 0)", "field research station in central Africa"),
    ("Field Site: Central Europe", "POINT (15 50)", "field research station in central Europe"),
    ("Field Site: Central Asia", "POINT (85 45)", "field research station in central Asia"),
    ("Field Site: Central North America", "POINT (-100 45)", "field research station in central North America"),
    ("Field Site: Central South America", "POINT (-60 -15)", "field research station in central South America"),
    ("Field Site: Central Australia", "POINT (135 -25)", "field research station in central Australia"),
    ("Field Site: Antarctic Peninsula", "POINT (-60 -70)", "field research station in Antarctica"),
    # Ocean points (10 oceans)
    ("Monitoring Buoy: Arctic Ocean", "POINT (0 80)", "ocean monitoring buoy in the Arctic Ocean"),
    ("Monitoring Buoy: North Atlantic", "POINT (-30 35)", "ocean monitoring buoy in the North Atlantic Ocean"),
    ("Monitoring Buoy: South Atlantic", "POINT (-20 -20)", "ocean monitoring buoy in the South Atlantic Ocean"),
    ("Monitoring Buoy: Indian Ocean", "POINT (70 -20)", "ocean monitoring buoy in the Indian Ocean"),
    ("Monitoring Buoy: North Pacific", "POINT (160 25)", "ocean monitoring buoy in the North Pacific Ocean"),
    ("Monitoring Buoy: South Pacific", "POINT (170 -20)", "ocean monitoring buoy in the South Pacific Ocean"),
    ("Monitoring Buoy: Southern Ocean", "POINT (20 -60)", "ocean monitoring buoy in the Southern Ocean"),
    ("Monitoring Buoy: Mediterranean", "POINT (18 37)", "ocean monitoring buoy in the Mediterranean Region"),
    ("Monitoring Buoy: South China Seas", "POINT (120 0)", "ocean monitoring buoy in the South China and Easter Archipelagic Seas"),
    ("Monitoring Buoy: Baltic Sea", "POINT (20 58)", "ocean monitoring buoy in the Baltic Sea"),
    ("Monitoring Buoy: Central Indian Ocean", "POINT (75 -20)", "ocean monitoring buoy in the Indian Ocean"),
    ("Monitoring Buoy: Arctic Ocean 2", "POINT (0 85)", "ocean monitoring buoy in the Arctic Ocean"),
    ("Monitoring Buoy: Southern Ocean 2", "POINT (100 -65)", "ocean monitoring buoy in the Southern Ocean"),
]

# Line geometries - spanning at least two regions (10 lines)
CROSS_REGION_LINES = [
    ("Migration Route: Africa to Europe", "LINESTRING (20 -5, 25 10, 15 35, 10 45)", "bird migration corridor from Africa through Mediterranean to Europe"),
    ("Migration Route: Asia to Australia", "LINESTRING (100 30, 110 10, 120 -10, 130 -20)", "bird migration corridor from Asia to Australia"),
    ("Shipping Lane: Atlantic Crossing", "LINESTRING (-75 40, -50 45, -25 50, -5 52)", "major shipping route across North Atlantic from North America to Europe"),
    ("Shipping Lane: Pacific Crossing", "LINESTRING (140 35, 170 38, -160 40, -130 42)", "major shipping route across North Pacific from Asia to North America"),
    ("Ocean Current: Gulf Stream", "LINESTRING (-80 25, -70 30, -50 35, -30 40, -10 50)", "Gulf Stream current from Gulf of Mexico to North Atlantic"),
    ("Ocean Current: Kuroshio", "LINESTRING (125 25, 135 30, 145 35, 155 40)", "Kuroshio Current along eastern Asia into Pacific"),
    ("Seismic Survey: Mid-Atlantic Ridge", "LINESTRING (-35 -30, -30 -10, -25 10, -20 30, -15 50)", "geological survey along Mid-Atlantic Ridge from South Atlantic to North Atlantic"),
    ("Seismic Survey: Ring of Fire West", "LINESTRING (120 -10, 125 0, 130 10, 135 20, 140 30)", "seismic monitoring along western Pacific Ring of Fire from Indian Ocean to Pacific"),
    ("Cable Route: Trans-Pacific", "LINESTRING (-120 35, -140 32, -160 30, -180 28, 170 26, 150 25)", "undersea telecommunications cable across Pacific from North America to Asia"),
    ("Cable Route: Europe-Africa", "LINESTRING (10 55, 5 45, 0 35, -5 25, 0 10, 5 0)", "undersea cable from Europe through Atlantic to Africa"),
]

# Complex polygon geometries (triangles, pentagons, concave shapes, holes)
COMPLEX_POLYGONS = [
    ("Triangular Survey Area: Mediterranean", "POLYGON ((10 35, 20 45, 5 42, 10 35))", "triangular research zone in Mediterranean Region"),
    ("Pentagon Study Region: Central Europe", "POLYGON ((10 48, 15 50, 17 47, 12 44, 8 46, 10 48))", "five-sided ecological study area in Central Europe"),
    ("Concave Polygon Zone: Southeast Asia", "POLYGON ((100 5, 105 5, 105 10, 103 8, 101 10, 100 10, 100 5))", "irregularly shaped coastal research area"),
    ("Protected Area with Exclusion Zone: Amazon", "POLYGON ((-65 -5, -60 -5, -60 0, -65 0, -65 -5), (-63 -3, -62 -3, -62 -2, -63 -2, -63 -3))", "conservation area with restricted inner zone in Amazon rainforest"),
    ("Star-shaped Survey: Arabian Peninsula", "POLYGON ((50 22, 51 23, 52 22, 51 21, 52 20, 51 19, 50 20, 49 19, 48 20, 49 21, 48 22, 49 23, 50 22))", "multi-pronged geological survey region"),
]

# Mixed geometry collections - all permutations of point, line, polygon
MIXED_GEOMETRIES = [
    # Point only (single)
    ("Point-only Study: Remote Island", "GEOMETRYCOLLECTION (POINT (-10 75))", "single monitoring station on remote Arctic island"),
    # Line only (single)
    ("Line-only Survey: Shipping Route", "GEOMETRYCOLLECTION (LINESTRING (-15 70, 5 72, 25 75))", "linear shipping route survey in North Atlantic"),
    # Polygon only (single)
    ("Polygon-only Region: Coastal Zone", "GEOMETRYCOLLECTION (POLYGON ((0 80, 10 80, 10 85, 0 85, 0 80)))", "coastal research zone in Arctic Ocean"),
    # Point + Line
    ("Point-Line Study: River Monitoring", "GEOMETRYCOLLECTION (POINT (0 5), LINESTRING (-5 0, 0 5, 5 10))", "river monitoring with station and flow path"),
    # Point + Polygon
    ("Point-Polygon Study: Harbor Analysis", "GEOMETRYCOLLECTION (POINT (100 10), POLYGON ((98 8, 102 8, 102 12, 98 12, 98 8)))", "harbor with central buoy and boundary zone"),
    # Line + Polygon
    ("Line-Polygon Study: Coastal Transect", "GEOMETRYCOLLECTION (LINESTRING (80 27, 85 29, 90 28), POLYGON ((82 26, 88 26, 88 30, 82 30, 82 26)))", "coastal transect through study area"),
    # Point + Line + Polygon (full combination)
    ("Multi-site Arctic Study", "GEOMETRYCOLLECTION (POINT (-10 75), LINESTRING (-15 70, 5 72, 25 75), POLYGON ((0 80, 10 80, 10 85, 0 85, 0 80)))", "integrated Arctic research with monitoring stations, survey transects, and study areas"),
    # Multiple Points + Line
    ("Multi-Point-Line: Island Network", "GEOMETRYCOLLECTION (POINT (160 -5), POINT (165 0), POINT (170 5), LINESTRING (158 -8, 172 8))", "island monitoring network with connection route"),
    # Multiple Points + Polygon
    ("Multi-Point-Polygon: Lake Study", "GEOMETRYCOLLECTION (POINT (-75 20), POINT (-70 18), POLYGON ((-80 15, -60 15, -60 25, -80 25, -80 15)))", "lake study with sampling stations and boundary"),
    # Multiple Lines + Polygon
    ("Multi-Line-Polygon: Watershed Analysis", "GEOMETRYCOLLECTION (LINESTRING (50 20, 52 22), LINESTRING (51 19, 52 21), POLYGON ((48 18, 54 18, 54 24, 48 24, 48 18)))", "watershed with multiple streams and catchment area"),
]

# Very small and very large geometries for edge case testing
EXTREME_SCALE_GEOMETRIES = [
    ("Micro-site Study: Urban Park", "POLYGON ((13.40500 52.52000, 13.40510 52.52000, 13.40510 52.52005, 13.40500 52.52005, 13.40500 52.52000))", "very small urban ecology study (sub-meter precision)"),
    ("Continental-scale Transect", "LINESTRING (-120 25, -80 30, -40 35, 0 40, 40 45, 80 50, 120 55)", "global east-west transect spanning multiple continents"),
]

# MultiPoint and MultiLineString for additional complexity
MULTI_GEOMETRY_TYPES = [
    ("Scattered Monitoring Network: Pacific Islands", "MULTIPOINT ((160 -10), (165 -5), (170 0), (175 5), (180 10))", "distributed ocean monitoring stations across Pacific"),
    ("Multi-route Shipping Analysis", "MULTILINESTRING ((140 30, 150 32, 160 33), (142 28, 152 29, 162 30), (138 32, 148 34, 158 35))", "parallel shipping corridor analysis in Northwest Pacific"),
    ("Fragmented Habitat Study: Indonesia", "MULTIPOLYGON (((120 -5, 122 -5, 122 -3, 120 -3, 120 -5)), ((124 -4, 126 -4, 126 -2, 124 -2, 124 -4)), ((128 -6, 130 -6, 130 -4, 128 -4, 128 -6)))", "island biogeography across separated land masses"),
]

def create_source(pk, name, issn_l=None, is_oa=True):
    """Create a source object."""
    return {
        "model": "works.source",
        "pk": pk,
        "fields": {
            "name": name,
            "issn_l": issn_l,
            "openalex_id": f"https://openalex.org/S{pk}000000" if random.random() > 0.3 else None,
            "openalex_url": f"https://api.openalex.org/sources/S{pk}000000" if random.random() > 0.3 else None,
            "publisher_name": f"{name.split()[0]} Publishers",
            "works_count": random.randint(100, 5000),
            "homepage_url": f"http://{name.lower().replace(' ', '')}.example.org",
            "abbreviated_title": name[:15] + ".",
            "is_oa": is_oa,
            "cited_by_count": random.randint(500, 50000),
            "is_preprint": random.choice([True, False]),
            "default_work_type": "article",
        }
    }

def create_publication(pk, source_pk, title, abstract, geometry_wkt, region_desc,
                      authors_idx, keywords_idx, topics_idx,
                      has_openalex=True, is_retracted=False, event_id=1000):
    """Create a publication object with varied metadata."""

    # Generate dates
    base_date = datetime(2020, 1, 1)
    pub_date = base_date + timedelta(days=random.randint(0, 1800))
    creation_date = pub_date + timedelta(days=random.randint(1, 30))

    # Select metadata
    authors = AUTHOR_SAMPLES[authors_idx % len(AUTHOR_SAMPLES)]
    keywords = KEYWORD_SAMPLES[keywords_idx % len(KEYWORD_SAMPLES)]
    topics = TOPIC_SAMPLES[topics_idx % len(TOPIC_SAMPLES)]

    # Generate DOI
    doi = f"10.5555/global-{pk}-{random.randint(1000, 9999)}"

    # OpenAlex fields
    openalex_id = None
    openalex_match_info = None
    openalex_fulltext_origin = None
    openalex_ids = None
    openalex_open_access_status = None

    if has_openalex:
        if random.random() > 0.2:  # 80% have full OpenAlex match
            openalex_id = f"https://openalex.org/W{3000000 + pk}"
            openalex_fulltext_origin = random.choice(["repository", "publisher", None])
            openalex_ids = json.dumps({"doi": f"https://doi.org/{doi}", "pmid": f"{38000000 + pk}" if random.random() > 0.5 else None})
            openalex_open_access_status = random.choice(OPENALEX_STATUS_SAMPLES)
        else:  # 20% have partial match info
            openalex_match_info = json.dumps([{
                "openalex_id": f"https://openalex.org/W{2900000 + pk}",
                "title": f"Similar Study {pk}",
                "doi": None,
                "match_type": "title"
            }])

    # Generate provenance
    source_name = f"Global Source {source_pk}"
    timestamp = creation_date.isoformat() + "Z"
    provenance_template = random.choice(PROVENANCE_TEMPLATES)
    provenance = provenance_template.format(
        source_name=source_name,
        timestamp=timestamp,
        event_id=event_id + pk
    )

    return {
        "model": "works.work",
        "pk": pk,
        "fields": {
            "status": "p",  # all published for UI testing
            "title": title,
            "abstract": abstract,
            "publicationDate": pub_date.strftime("%Y-%m-%d"),
            "doi": doi,
            "url": f"https://example.org/publications/{pk}",
            "geometry": f"SRID=4326;GEOMETRYCOLLECTION({geometry_wkt})",
            "creationDate": creation_date.isoformat() + "Z",
            "lastUpdate": (creation_date + timedelta(hours=random.randint(1, 48))).isoformat() + "Z",
            "source": source_pk,
            "timeperiod_startdate": f"[\"{pub_date.year - random.randint(1, 3)}\"]",
            "timeperiod_enddate": f"[\"{pub_date.year}\"]",
            "provenance": provenance,
            "authors": authors,
            "keywords": keywords,
            "topics": topics,
            "openalex_id": openalex_id,
            "openalex_match_info": openalex_match_info,
            "openalex_fulltext_origin": openalex_fulltext_origin,
            "openalex_is_retracted": is_retracted,
            "openalex_ids": openalex_ids,
            "openalex_open_access_status": openalex_open_access_status,
            "type": "article",
        }
    }

def main():
    print("Creating comprehensive test_data_global_feeds.json fixture...")

    fixture_data = []
    pk_counter = 2000
    source_pk = 2000

    # Create a few diverse sources
    sources = [
        create_source(2000, "Global Geoscience Journal", "2234-5678", True),
        create_source(2001, "International Earth Sciences", "3345-6789", True),
        create_source(2002, "World Environmental Research", "4456-7890", False),
        create_source(2003, "Planetary Studies Quarterly", "5567-8901", True),
    ]
    fixture_data.extend(sources)

    print(f"\nCreating {len(sources)} sources...")

    # Track metadata distribution for similar patterns to optimap
    author_idx = 0
    keyword_idx = 0
    topic_idx = 0

    print("\n=== Creating works for each continent ===")
    for i, (region_name, geometry, description) in enumerate(CONTINENTS):
        pk = pk_counter
        pk_counter += 1
        source_pk_choice = 2000 + (i % len(sources))

        pub = create_publication(
            pk=pk,
            source_pk=source_pk_choice,
            title=f"Geological Survey of {region_name}",
            abstract=f"Comprehensive geological and environmental study covering {description}. This research examines {region_name.lower()} geology, climate patterns, and ecological systems.",
            geometry_wkt=geometry,
            region_desc=description,
            authors_idx=author_idx,
            keywords_idx=keyword_idx,
            topics_idx=topic_idx,
            has_openalex=True,
        )
        fixture_data.append(pub)
        print(f"  [{pk}] {region_name}: {len(pub['fields']['authors'])} authors, {len(pub['fields']['keywords'])} keywords, {len(pub['fields']['topics'])} topics")

        author_idx += 1
        keyword_idx += 1
        topic_idx += 1

    print("\n=== Creating works for each ocean ===")
    for i, (region_name, geometry, description) in enumerate(OCEANS):
        pk = pk_counter
        pk_counter += 1
        source_pk_choice = 2000 + (i % len(sources))

        pub = create_publication(
            pk=pk,
            source_pk=source_pk_choice,
            title=f"Marine Biology and Oceanography of the {region_name}",
            abstract=f"Detailed oceanographic study of {description}. Research includes marine ecosystems, ocean currents, temperature patterns, and biodiversity in the {region_name.lower()}.",
            geometry_wkt=geometry,
            region_desc=description,
            authors_idx=author_idx,
            keywords_idx=keyword_idx,
            topics_idx=topic_idx,
            has_openalex=True,
        )
        fixture_data.append(pub)
        print(f"  [{pk}] {region_name}: {len(pub['fields']['authors'])} authors, {len(pub['fields']['keywords'])} keywords, {len(pub['fields']['topics'])} topics")

        author_idx += 1
        keyword_idx += 1
        topic_idx += 1

    print("\n=== Creating works overlapping two neighboring regions ===")
    for i, (region_name, geometry, description) in enumerate(TWO_REGION_OVERLAPS):
        pk = pk_counter
        pk_counter += 1
        source_pk_choice = 2000 + (i % len(sources))

        pub = create_publication(
            pk=pk,
            source_pk=source_pk_choice,
            title=f"Cross-Regional Study: {region_name}",
            abstract=f"Cross-border environmental and geological research {description}. This study analyzes patterns that span multiple geographical regions.",
            geometry_wkt=geometry,
            region_desc=description,
            authors_idx=author_idx,
            keywords_idx=keyword_idx,
            topics_idx=topic_idx,
            has_openalex=True,
        )
        fixture_data.append(pub)
        print(f"  [{pk}] {region_name}: {len(pub['fields']['authors'])} authors, {len(pub['fields']['keywords'])} keywords, {len(pub['fields']['topics'])} topics")

        author_idx += 1
        keyword_idx += 1
        topic_idx += 1

    print("\n=== Creating works spanning more than two regions ===")
    for i, (title_suffix, geometry, description) in enumerate(MULTI_REGION_SPANS):
        pk = pk_counter
        pk_counter += 1
        source_pk_choice = 2000 + (i % len(sources))

        pub = create_publication(
            pk=pk,
            source_pk=source_pk_choice,
            title=title_suffix,
            abstract=f"Large-scale multi-regional research project covering {description}. This comprehensive study examines global patterns and connections across multiple continents and oceans.",
            geometry_wkt=geometry,
            region_desc=description,
            authors_idx=author_idx,
            keywords_idx=keyword_idx,
            topics_idx=topic_idx,
            has_openalex=True,
        )
        fixture_data.append(pub)
        print(f"  [{pk}] {title_suffix}: {len(pub['fields']['authors'])} authors, {len(pub['fields']['keywords'])} keywords, {len(pub['fields']['topics'])} topics")

        author_idx += 1
        keyword_idx += 1
        topic_idx += 1

    print("\n=== Creating point-based field sites and monitoring stations ===")
    for i, (title, geometry, description) in enumerate(REGION_POINTS):
        pk = pk_counter
        pk_counter += 1
        source_pk_choice = 2000 + (i % len(sources))

        pub = create_publication(
            pk=pk,
            source_pk=source_pk_choice,
            title=title,
            abstract=f"Point-based monitoring and research from {description}. This site provides continuous data collection and analysis for local environmental conditions.",
            geometry_wkt=geometry,
            region_desc=description,
            authors_idx=author_idx,
            keywords_idx=keyword_idx,
            topics_idx=topic_idx,
            has_openalex=True,
        )
        fixture_data.append(pub)
        print(f"  [{pk}] {title}: {len(pub['fields']['authors'])} authors, {len(pub['fields']['keywords'])} keywords, {len(pub['fields']['topics'])} topics")

        author_idx += 1
        keyword_idx += 1
        topic_idx += 1

    print("\n=== Creating cross-region line features (routes, currents, surveys) ===")
    for i, (title, geometry, description) in enumerate(CROSS_REGION_LINES):
        pk = pk_counter
        pk_counter += 1
        source_pk_choice = 2000 + (i % len(sources))

        pub = create_publication(
            pk=pk,
            source_pk=source_pk_choice,
            title=title,
            abstract=f"Linear pathway study documenting {description}. This research traces continuous phenomena across regional boundaries.",
            geometry_wkt=geometry,
            region_desc=description,
            authors_idx=author_idx,
            keywords_idx=keyword_idx,
            topics_idx=topic_idx,
            has_openalex=True,
        )
        fixture_data.append(pub)
        print(f"  [{pk}] {title}: {len(pub['fields']['authors'])} authors, {len(pub['fields']['keywords'])} keywords, {len(pub['fields']['topics'])} topics")

        author_idx += 1
        keyword_idx += 1
        topic_idx += 1

    print("\n=== Creating complex polygon geometries ===")
    for i, (title, geometry, description) in enumerate(COMPLEX_POLYGONS):
        pk = pk_counter
        pk_counter += 1
        source_pk_choice = 2000 + (i % len(sources))

        pub = create_publication(
            pk=pk,
            source_pk=source_pk_choice,
            title=title,
            abstract=f"Complex polygon study focusing on {description}. This research examines irregular boundaries and geometric complexity in spatial analysis.",
            geometry_wkt=geometry,
            region_desc=description,
            authors_idx=author_idx,
            keywords_idx=keyword_idx,
            topics_idx=topic_idx,
            has_openalex=True,
        )
        fixture_data.append(pub)
        print(f"  [{pk}] {title}: {len(pub['fields']['authors'])} authors, {len(pub['fields']['keywords'])} keywords, {len(pub['fields']['topics'])} topics")

        author_idx += 1
        keyword_idx += 1
        topic_idx += 1

    print("\n=== Creating mixed geometry collections ===")
    for i, (title, geometry, description) in enumerate(MIXED_GEOMETRIES):
        pk = pk_counter
        pk_counter += 1
        source_pk_choice = 2000 + (i % len(sources))

        pub = create_publication(
            pk=pk,
            source_pk=source_pk_choice,
            title=title,
            abstract=f"Multi-component spatial study integrating {description}. Combines point-based, linear, and areal data collection methods.",
            geometry_wkt=geometry,
            region_desc=description,
            authors_idx=author_idx,
            keywords_idx=keyword_idx,
            topics_idx=topic_idx,
            has_openalex=True,
        )
        fixture_data.append(pub)
        print(f"  [{pk}] {title}: {len(pub['fields']['authors'])} authors, {len(pub['fields']['keywords'])} keywords, {len(pub['fields']['topics'])} topics")

        author_idx += 1
        keyword_idx += 1
        topic_idx += 1

    print("\n=== Creating extreme scale geometries ===")
    for i, (title, geometry, description) in enumerate(EXTREME_SCALE_GEOMETRIES):
        pk = pk_counter
        pk_counter += 1
        source_pk_choice = 2000 + (i % len(sources))

        pub = create_publication(
            pk=pk,
            source_pk=source_pk_choice,
            title=title,
            abstract=f"Scale-specific analysis examining {description}. Tests spatial processing at extreme precision or extent.",
            geometry_wkt=geometry,
            region_desc=description,
            authors_idx=author_idx,
            keywords_idx=keyword_idx,
            topics_idx=topic_idx,
            has_openalex=True,
        )
        fixture_data.append(pub)
        print(f"  [{pk}] {title}: {len(pub['fields']['authors'])} authors, {len(pub['fields']['keywords'])} keywords, {len(pub['fields']['topics'])} topics")

        author_idx += 1
        keyword_idx += 1
        topic_idx += 1

    print("\n=== Creating multi-geometry types ===")
    for i, (title, geometry, description) in enumerate(MULTI_GEOMETRY_TYPES):
        pk = pk_counter
        pk_counter += 1
        source_pk_choice = 2000 + (i % len(sources))

        pub = create_publication(
            pk=pk,
            source_pk=source_pk_choice,
            title=title,
            abstract=f"Multi-feature spatial analysis documenting {description}. Studies distributed or parallel spatial phenomena.",
            geometry_wkt=geometry,
            region_desc=description,
            authors_idx=author_idx,
            keywords_idx=keyword_idx,
            topics_idx=topic_idx,
            has_openalex=True,
        )
        fixture_data.append(pub)
        print(f"  [{pk}] {title}: {len(pub['fields']['authors'])} authors, {len(pub['fields']['keywords'])} keywords, {len(pub['fields']['topics'])} topics")

        author_idx += 1
        keyword_idx += 1
        topic_idx += 1

    # Create backup of original
    import os
    import shutil
    fixture_path = "test_data_global_feeds.json"
    backup_path = fixture_path + ".backup"

    if os.path.exists(fixture_path):
        print(f"\n=== Creating backup: {backup_path} ===")
        shutil.copy(fixture_path, backup_path)

    # Write fixture
    print(f"\n=== Writing fixture to {fixture_path} ===")
    with open(fixture_path, "w") as f:
        json.dump(fixture_data, f, indent=2)

    # Calculate statistics
    publications = [item for item in fixture_data if item["model"] == "works.work"]

    with_authors = sum(1 for p in publications if p["fields"]["authors"])
    with_keywords = sum(1 for p in publications if p["fields"]["keywords"])
    with_topics = sum(1 for p in publications if p["fields"]["topics"])
    with_openalex = sum(1 for p in publications if p["fields"]["openalex_id"])
    is_retracted = sum(1 for p in publications if p["fields"]["openalex_is_retracted"])

    print("\n=== Summary ===")
    print(f"Total publications: {len(publications)}")
    print(f"\nBasic geometry types:")
    print(f"  - Continents (polygons): {len(CONTINENTS)}")
    print(f"  - Oceans (polygons): {len(OCEANS)}")
    print(f"  - Two-region overlaps (polygons): {len(TWO_REGION_OVERLAPS)}")
    print(f"  - Multi-region spans (polygons): {len(MULTI_REGION_SPANS)}")
    print(f"  - Region points (points): {len(REGION_POINTS)}")
    print(f"  - Cross-region lines (linestrings): {len(CROSS_REGION_LINES)}")
    print(f"\nComplex geometry types:")
    print(f"  - Complex polygons (triangles, pentagons, concave, holes): {len(COMPLEX_POLYGONS)}")
    print(f"  - Mixed geometries (point+line+polygon): {len(MIXED_GEOMETRIES)}")
    print(f"  - Extreme scale geometries: {len(EXTREME_SCALE_GEOMETRIES)}")
    print(f"  - Multi-geometry types (multipoint, multiline, multipoly): {len(MULTI_GEOMETRY_TYPES)}")
    print(f"\nMetadata coverage:")
    print(f"  - With authors: {with_authors}/{len(publications)}")
    print(f"  - With keywords: {with_keywords}/{len(publications)}")
    print(f"  - With topics: {with_topics}/{len(publications)}")
    print(f"  - With OpenAlex ID: {with_openalex}/{len(publications)}")
    print(f"  - Retracted: {is_retracted}/{len(publications)}")

    # Calculate array field distributions
    from collections import Counter
    authors_counts = Counter(len(p["fields"]["authors"]) for p in publications)
    keywords_counts = Counter(len(p["fields"]["keywords"]) for p in publications)
    topics_counts = Counter(len(p["fields"]["topics"]) for p in publications)

    print(f"\nArray field diversity:")
    print(f"  - Authors distribution: {dict(sorted(authors_counts.items()))}")
    print(f"  - Keywords distribution: {dict(sorted(keywords_counts.items()))}")
    print(f"  - Topics distribution: {dict(sorted(topics_counts.items()))}")

    print("\n✓ Fixture creation complete!")
    print(f"\nTo load the fixture:")
    print(f"  python manage.py loaddata {fixture_path}")

if __name__ == "__main__":
    main()
