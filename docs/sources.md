# Configured harvesting sources

All sources are defined in `SOURCE_CONFIG` in
[`works/management/commands/harvest_sources.py`](../works/management/commands/harvest_sources.py).
Each entry maps a short CLI key to a source configuration.
The key is used with `--source <key>` and `--source-prefix <prefix>`.

Run `python manage.py harvest_sources --list` to see the current list with live status.

Disabled sources (upstream endpoint unavailable) are included for reference.
`--all` skips them; use `--include-disabled` to attempt them anyway.

## Work count statistics

After every harvest, three optional count statistics are fetched and stored in `Source.statistics`:

| Count | Key | Applies to | How fetched | What it counts |
|-------|-----|------------|-------------|----------------|
| **OpenAlex** | `openalex_works_count` | Sources with `openalex_id` | `GET /api/openalex.org/sources/{id}` → `works_count` | All works indexed by OpenAlex for this source, including works from years/platforms not yet harvested by OPTIMAP. May differ from OAI count when OpenAlex indexes more publication history than the OAI set covers. |
| **OAI-PMH** | `oai_works_count` | `oai-pmh`, `ojs`, `janeway` | `ListIdentifiers?set=…` → `completeListSize` | Total records available in the OAI-PMH set we harvest from. Reflects only what the upstream endpoint exposes in that set — journals that migrated platforms may have older records elsewhere. |
| **Crossref** | `crossref_works_count` | `crossref-prefix` | `GET /works?filter=prefix:{p}[,container-title:{t}]&rows=0` → `total-results` | Total DOIs registered under the given prefix (and title filter if set). For broad prefixes without a title filter (e.g. 10.5194 = all Copernicus), this reflects the entire publisher output. For narrow-filtered sources (Scientific Data on 10.1038, AGILE GIScience Series on 10.5194) it reflects only that journal. |

**Why counts differ between sources for the same journal:** OpenAlex aggregates metadata from multiple origin systems (Crossref, PubMed, repository OAI-PMH feeds, etc.), often indexing older volumes that a single OAI set does not expose. For example, *Bulletin of Insectology* has been published since 1948 but the OAI endpoint only exposes recent volumes (OAI: ~30 records, OpenAlex: ~360). Both counts are correct — they measure different things.

These statistics are refreshed after each successful harvest and displayed:
- In the Source admin list (three dedicated columns).
- In the HarvestingEvent log text.
- In the `harvest_sources` command summary.
- In the collection landing page admin section (collapsed "Sources" list).

---

## AGILE GIS

Conference proceedings of the [AGILE International Conference on Geographic Information Science](https://agile-gi.eu/).
Two sources cover different publication periods and publishers; both feed the same collection.

| Key | Name | Publisher | Years | Type |
|-----|------|-----------|-------|------|
| `agile-giss` | AGILE: GIScience Series | Copernicus Publications | 2020–present | Crossref |
| `agile-springer-lncs` | AGILE: Springer LNCS Proceedings | Springer | 2008–2019 | Crossref |

```bash
python manage.py harvest_sources --source agile-giss
python manage.py harvest_sources --source agile-springer-lncs
```

---

## Copernicus Publications

Copernicus runs an OAI-PMH endpoint, but it has returned HTTP 404 since December 2025.
Crossref (DOI prefix 10.5194) is therefore the primary harvest route for all Copernicus journals.

| Key | Name | Publisher | Type |
|-----|------|-----------|------|
| `copernicus` | Copernicus Publications | Copernicus Publications | Crossref (DOI prefix 10.5194) |

```bash
python manage.py harvest_sources --source copernicus
# narrow to a single journal, e.g. Earth System Science Data:
python manage.py harvest_sources --source copernicus --source-title "Earth System Science Data"
```

---

## EarthArXiv

[EarthArXiv](https://eartharxiv.org/) is a preprint server for Earth Sciences
hosted by the California Digital Library (~7,000 preprints).

| Key | Name | Publisher | Type |
|-----|------|-----------|------|
| `eartharxiv` | EarthArXiv | California Digital Library | OAI-PMH |

```bash
python manage.py harvest_sources --source eartharxiv --max-records 100  # test run
python manage.py harvest_sources --source eartharxiv                     # full harvest
```

---

## GEO-LEO e-docs

[GEO-LEO e-docs](https://e-docs.geo-leo.de/) is an open-access repository for
geoscience and related earth and space science literature.

| Key | Name | Publisher | Type |
|-----|------|-----------|------|
| `geo-leo` | GEO-LEO e-docs | GEO-LEO | OAI-PMH |

```bash
python manage.py harvest_sources --source geo-leo
```

---

## GeoScienceWorld

[GeoScienceWorld](https://pubs.geoscienceworld.org/) hosts journals from multiple
geoscience societies. Articles include GeoRef coordinates embedded as WKT in
landing pages; spatial extraction uses geoextent's GSW content provider.

Harvest all GSW sources in one run with `--source-prefix gsw`.

| Key | Name | Publisher | DOI prefix |
|-----|------|-----------|------------|
| `gsw-seg` | GeoScienceWorld — SEG Journals | Society of Exploration Geophysicists | 10.1190 |
| `gsw-gsl` | GeoScienceWorld — Geological Society of London | Geological Society of London | 10.1144 |
| `gsw-mineralogical` | GeoScienceWorld — Mineralogical Society | Mineralogical Society of Great Britain and Ireland | 10.1180 |
| `gsw-gsa` | GeoScienceWorld — Geological Society of America | Geological Society of America | 10.1130 |
| `gsw-own` | GeoScienceWorld — Aggregated (10.2113) | GeoScienceWorld | 10.2113 |
| `gsw-aapg` | GeoScienceWorld — AAPG/Datapages | AAPG/Datapages | 10.1306 |
| `gsw-seg-econ` | GeoScienceWorld — Society of Economic Geologists | Society of Economic Geologists | 10.5382 |
| `gsw-clay` | GeoScienceWorld — Clay Minerals Society | Clay Minerals Society | 10.1346 |
| `gsw-cushman` | GeoScienceWorld — Cushman Foundation for Foraminiferal Research | Cushman Foundation for Foraminiferal Research | 10.61551 |

```bash
python manage.py harvest_sources --source-prefix gsw
```

---

## Mountain Wetlands Repository

The [Mountain Wetlands Repository](https://andes.mountain-wetlands-repository.info/)
(part of the MaRESS project) aggregates research on mountain wetland ecosystems.
Uses a dedicated REST API harvester.

| Key | Name | Publisher | Type |
|-----|------|-----------|------|
| `mountain-wetlands` | Mountain Wetlands Repository | Mountain Wetlands Repository (MaRESS) | MaRESS API |

```bash
python manage.py harvest_sources --source mountain-wetlands
```

---

## Pensoft / ARPHA platform journals

[Pensoft Publishers](https://pensoft.net/) journals served via the
[ARPHA publishing platform](https://arpha.pensoft.net/).
All confirmed to embed `schema:contentLocation` GeoCoordinates JSON-LD in article pages
(spatial coverage is article-type-dependent: data papers and taxonomic revisions ~80–100%;
reviews and methods articles ~0%).

Harvest all Pensoft sources in one run with `--source-prefix pensoft`.

| Key | Name | ISSN-L | OpenAlex |
|-----|------|--------|----------|
| `pensoft-bdj` | [Biodiversity Data Journal](https://bdj.pensoft.net/) | 1314-2828 | [S2764367193](https://openalex.org/S2764367193) |
| `pensoft-zookeys` | [ZooKeys](https://zookeys.pensoft.net/) | 1313-2970 | [S199213172](https://openalex.org/S199213172) |
| `pensoft-phytokeys` | [PhytoKeys](https://phytokeys.pensoft.net/) | 1314-2003 | [S138605562](https://openalex.org/S138605562) |
| `pensoft-neobiota` | [NeoBiota](https://neobiota.pensoft.net/) | 1314-2488 | [S4210189550](https://openalex.org/S4210189550) |
| `pensoft-mycokeys` | [MycoKeys](https://mycokeys.pensoft.net/) | 1314-4049 | [S4210227917](https://openalex.org/S4210227917) |
| `pensoft-herpetozoa` | [Herpetozoa](https://herpetozoa.pensoft.net/) | 2682-955X | [S4210228833](https://openalex.org/S4210228833) |
| `pensoft-natureconservation` | [Nature Conservation](https://natureconservation.pensoft.net/) | 1314-3301 | [S2764730374](https://openalex.org/S2764730374) |
| `pensoft-alpineentomology` | [Alpine Entomology](https://alpineentomology.pensoft.net/) | 2535-0889 | [S4210217666](https://openalex.org/S4210217666) |
| `pensoft-oneecosystem` | [One Ecosystem](https://oneecosystem.pensoft.net/) | 2367-8194 | [S4210213968](https://openalex.org/S4210213968) |
| `pensoft-evolsyst` | [Evolutionary Systematics](https://evolsyst.pensoft.net/) | 2535-0730 | [S4210215492](https://openalex.org/S4210215492) |
| `pensoft-mbmg` | [Metabarcoding and Metagenomics](https://mbmg.pensoft.net/) | 2534-9708 | [S4210182883](https://openalex.org/S4210182883) |
| `pensoft-neotropical` | [Neotropical Biology and Conservation](https://neotropical.pensoft.net/) | 2236-3777 | [S4210214477](https://openalex.org/S4210214477) |
| `pensoft-caucasiana` | [Caucasiana](https://caucasiana.pensoft.net/) | 2667-9809 | [S4210198213](https://openalex.org/S4210198213) |
| `pensoft-italianbotanist` | [Italian Botanist](https://italianbotanist.pensoft.net/) | 2531-4033 | [S4210221877](https://openalex.org/S4210221877) |
| `pensoft-abs` | [Acta Biologica Sibirica](https://abs.pensoft.net/) | 2412-1908 | [S2737068255](https://openalex.org/S2737068255) |
| `pensoft-vdj` | [Viticulture Data Journal](https://vdj.pensoft.net/) | 2603-431X | [S4210212065](https://openalex.org/S4210212065) |
| `pensoft-nhcm` | [Natural History Collections and Museomics](https://nhcm.pensoft.net/) | 3033-0955 | [S5407045911](https://openalex.org/S5407045911) |

```bash
python manage.py harvest_sources --source-prefix pensoft
```

---

## Other journals

| Key | Name | Publisher | ISSN-L | Type | OpenAlex |
|-----|------|-----------|--------|------|----------|
| `biosystecol` | [Biosystematics and Ecology](https://biosystecol.oeaw.ac.at/) | Austrian Academy of Sciences | 1026-4949 | OAI-PMH | [S4389157932](https://openalex.org/S4389157932) |
| `bulletinofinsectology` | [Bulletin of Insectology](https://bulletinofinsectology.org/) | University of Bologna | 1721-8861 | OAI-PMH | [S13822188](https://openalex.org/S13822188) |
| `scientific-data` | [Scientific Data](https://www.nature.com/sdata/) | Nature Publishing Group | 2052-4463 | Crossref | [S2607323502](https://openalex.org/S2607323502) |

```bash
python manage.py harvest_sources --source biosystecol
python manage.py harvest_sources --source bulletinofinsectology
python manage.py harvest_sources --source scientific-data
```

---

## Disabled sources

Entries can be marked `enabled: False` in `SOURCE_CONFIG` so the config stays
self-documenting while being skipped by `--all` (use `--include-disabled` to
attempt them anyway). There are currently no disabled sources.
