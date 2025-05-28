const dataCopyright = " | Publication metadata license: <a href='https://creativecommons.org/publicdomain/zero/1.0/'>CC-0</a>";
const publications_url = '/api/v1/publications.json?limit=999999';

async function initMap() {
    var map = L.map("map");

    var osmLayer = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        attribution: 'Map data: &copy; <a href="https://openstreetmap.org">OpenStreetMap</a> contributors' + dataCopyright,
        maxZoom: 18
    }).addTo(map);

    //var esriWorldImageryLayer = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', {
    //    attribution: 'Tiles &copy; Esri &mdash; Source: Esri, i-cubed, USDA, USGS, AEX, GeoEye, Getmapping, Aerogrid, IGN, IGP, UPR-EGP, and the GIS User Community' + dataCopyright,
    //    maxZoom: 18
    //}).addTo(map);

    var baseLayers = {
        "OpenStreetMap": osmLayer,
        //"Esri World Imagery": esriWorldImageryLayer
    };

    var publicationsGroup = new L.FeatureGroup();
    map.addLayer(publicationsGroup);

    var overlayMaps = {
        "Publications": publicationsGroup
    };
    
    L.control.scale({ position: 'bottomright' }).addTo(map);
    L.control.layers(baseLayers, overlayMaps).addTo(map);

    // 1) load the existing publications
    var publications = await load_publications();
    var publicationsLayer = L.geoJSON(publications, {
        pointToLayer: function(feature, latlng) {
            return L.circleMarker(latlng, { radius: 6 });
        },
        onEachFeature: publicationPopup
    });
    publicationsLayer.eachLayer(function (l) {
        publicationsGroup.addLayer(l);
    });

    // 2) load and display journals
    await load_journals(publicationsGroup);

    map.fitBounds(publicationsGroup.getBounds());
}

function publicationPopup(feature, layer) {
    // skip features with no geometry
    if (!feature.geometry) {
        layer.bindPopup("<em>No location data</em>");
        return;
    }

    var popupContent = '<div>';
    if (feature.properties['title']) {
        popupContent += '<h3>' + feature.properties['title'] + '</h3>';
    }

    if (feature.properties['timeperiod_startdate'] && feature.properties['timeperiod_enddate']) {
        popupContent += '<div><b>Timeperiod:</b> from '
            + feature.properties['timeperiod_startdate']
            + ' to ' + feature.properties['timeperiod_enddate']
            + '</div>';
    }

    if (feature.properties['abstract']) {
        popupContent += '<div><p>' + feature.properties['abstract'] + '</p></div>';
    }
    
    if (feature.properties['url']) {
        popupContent += '<div><a href="'
            + feature.properties['url']
            + '">Visit Article</a></div>';
    }

    if (feature.properties && feature.properties.popupContent) {
        popupContent += feature.properties.popupContent;
    }

    popupContent += '</div>';

    layer.bindPopup(popupContent, {
        maxHeight: 225
    });
}

async function load_publications() {
    const response = await fetch(publications_url);
    const body = await response.json();
    console.log('OPTIMAP retrieved ' + body.count + ' publications.');
    return body.results;
}

async function load_journals(featureGroup) {
    try {
        const resp = await fetch('/api/v1/journals/');
        const body = await resp.json();
        console.log('OPTIMAP retrieved ' + body.count + ' journals.');
        body.results.forEach(j => {
            // Extract GeoJSON Point coordinates [lon, lat]
            const coords = j.geometry?.coordinates;
            const latLng = coords
                ? [coords[1], coords[0]]  // Leaflet wants [lat, lon]
                : [0, 0];                // fallback if no geometry

            const marker = L.marker(latLng).addTo(featureGroup);

            let popup = `<strong>${j.display_name}</strong><br/>`;
            if (j.issn_l) {
                popup += `ISSN-L: ${j.issn_l}<br/>`;
            }
            if (j.openalex_id) {
                popup += `<a href="${j.openalex_id}" target="_blank">OpenAlex details</a>`;
            }

            marker.bindPopup(popup);
        });
    } catch (err) {
        console.error('Error loading journals:', err);
    }
}

// render publications (and journals) after page is loaded
$(function () {
    initMap();
});



