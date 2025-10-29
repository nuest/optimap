# Provenance of dependencies

All external JavaScript and CSS libraries are served locally from this directory to avoid CDN dependencies.

## Automated Download Script

Run the download script to update all libraries to their specified versions:

```bash
cd publications/static
./download_libraries.sh
```

This script downloads all dependencies listed below.

## JS Libraries

### Core Libraries

- **jQuery 3.4.1** - MIT License
  - Source: https://code.jquery.com/jquery-3.4.1.slim.min.js
  - Files: `js/jquery-3.4.1.slim.min.js`

- **Bootstrap 4.4.1** - MIT License
  - Source: https://cdn.jsdelivr.net/npm/bootstrap@4.4.1/dist/js/
  - Files: `js/bootstrap.min.js`, `js/bootstrap.min.js.map`

- **Popper.js 2.x** - MIT License (required for Bootstrap tooltips)
  - Source: https://unpkg.com/@popperjs/core@2/dist/umd/
  - Files: `js/popper.min.js`

### Leaflet and Plugins

- **Leaflet 1.9.4** - BSD-2-Clause License
  - Source: https://unpkg.com/leaflet@1.9.4/dist/
  - Files: `js/leaflet.js`, `js/leaflet.js.map`
  - Homepage: https://leafletjs.com/

- **Leaflet Draw 1.0.4** - MIT License
  - Source: https://unpkg.com/leaflet-draw@1.0.4/dist/
  - Files: `js/leaflet.draw.js`
  - Homepage: https://github.com/Leaflet/Leaflet.draw

- **Leaflet Fullscreen 3.0.2** - MIT License
  - Source: https://unpkg.com/leaflet.fullscreen@3.0.2/
  - Files: `js/leaflet.fullscreen.js`
  - Homepage: https://github.com/brunob/leaflet.fullscreen

### Other Libraries

- **Bootstrap Datepicker 1.9.0** - Apache License 2.0
  - Source: https://cdnjs.cloudflare.com/ajax/libs/bootstrap-datepicker/1.9.0/
  - Files: `js/bootstrap-datepicker.min.js`
  - Homepage: https://github.com/uxsolutions/bootstrap-datepicker

## CSS Libraries

### Core Stylesheets

- **Bootstrap 4.4.1** - MIT License
  - Source: https://cdn.jsdelivr.net/npm/bootstrap@4.4.1/dist/css/
  - Files: `css/bootstrap.min.css`, `css/bootstrap.min.css.map`

- **Leaflet 1.9.4** - BSD-2-Clause License
  - Source: https://unpkg.com/leaflet@1.9.4/dist/
  - Files: `css/leaflet.css`

- **Leaflet Draw 1.0.4** - MIT License
  - Source: https://unpkg.com/leaflet-draw@1.0.4/dist/
  - Files: `css/leaflet.draw.css`

- **Leaflet Fullscreen 3.0.2** - MIT License
  - Source: https://unpkg.com/leaflet.fullscreen@3.0.2/
  - Files: `css/leaflet.fullscreen.css`

- **Bootstrap Datepicker 1.9.0** - Apache License 2.0
  - Source: https://cdnjs.cloudflare.com/ajax/libs/bootstrap-datepicker/1.9.0/
  - Files: `css/bootstrap-datepicker.min.css`

### Fonts

- **Font Awesome 4.7.0** - Font: SIL OFL 1.1, CSS: MIT License
  - Source: https://cdnjs.cloudflare.com/ajax/libs/font-awesome/4.7.0/
  - Files: `css/font-awesome.min.css`, `css/fonts/fontawesome-webfont.*`
  - Homepage: https://fontawesome.com/

## Images

### Leaflet Marker Icons

- **Default Leaflet Markers** - BSD-2-Clause License
  - Source: https://unpkg.com/leaflet@1.9.4/dist/images/
  - Files: `css/images/marker-icon*.png`, `css/images/marker-shadow.png`, `css/images/layers*.png`

- **Leaflet Draw Sprites** - MIT License
  - Source: https://unpkg.com/leaflet-draw@1.0.4/dist/images/
  - Files: `css/images/spritesheet*.png`, `css/images/spritesheet.svg`

- **Leaflet Fullscreen Icons** - MIT License
  - Source: https://unpkg.com/leaflet.fullscreen@3.0.2/
  - Files: `css/images/fullscreen/icon-fullscreen*.png`

### Colored Markers

- **Leaflet Color Markers** - BSD-2-Clause License
  - Source: https://github.com/pointhi/leaflet-color-markers
  - Files: `css/images/marker-icon-{color}.png`, `css/images/marker-icon-2x-{color}.png`
  - Colors available: red, orange, gold, blue (and others in upstream repo)
  - Used for highlighting selected features on the map
  - License: https://github.com/pointhi/leaflet-color-markers/blob/master/LICENSE

## License Compliance

All libraries used are open-source with permissive licenses (MIT, BSD-2-Clause, Apache 2.0, SIL OFL 1.1).
See individual library homepages for full license texts.
