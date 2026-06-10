import { GoogleMapsOverlay } from '@deck.gl/google-maps';
import { importLibrary, setOptions } from '@googlemaps/js-api-loader';

let _map = null;
let _overlay = null;

export async function initMap(container, config) {
    // js-api-loader v2 functional API — the old `new Loader().load()` class was
    // removed in v2 and throws if used (silent blank map). Configure once, then
    // import only the libraries we use.
    setOptions({ key: config.mapsApiKey, v: 'weekly' });

    const [{ Map }] = await Promise.all([
        importLibrary('maps'),
        importLibrary('geometry'),
        importLibrary('visualization'),
    ]);

    _map = new Map(container, {
        center: config.center,
        zoom: config.zoom || 12,
        tilt: 45,
        heading: 0,
        mapId: config.mapId || undefined,
        mapTypeId: 'hybrid',
        mapTypeControl: true,
        fullscreenControl: true,
        rotateControl: true,
        tiltControl: true,
        streetViewControl: false,
        styles: DARK_STYLE,
    });

    _overlay = new GoogleMapsOverlay({ layers: [] });
    _overlay.setMap(_map);

    return { map: _map, overlay: _overlay };
}

export function getMap() { return _map; }
export function getOverlay() { return _overlay; }

export function updateLayers(layers) {
    if (_overlay) _overlay.setProps({ layers });
}

const DARK_STYLE = [
    { elementType: 'geometry', stylers: [{ color: '#1d2c4d' }] },
    { elementType: 'labels.text.fill', stylers: [{ color: '#8ec3b9' }] },
    { elementType: 'labels.text.stroke', stylers: [{ color: '#1a3646' }] },
    { featureType: 'administrative.country', elementType: 'geometry.stroke', stylers: [{ color: '#4b6878' }] },
    { featureType: 'landscape', elementType: 'geometry', stylers: [{ color: '#0e1626' }] },
    { featureType: 'poi', elementType: 'geometry', stylers: [{ color: '#283d6a' }] },
    { featureType: 'poi', elementType: 'labels.text.fill', stylers: [{ color: '#6f9ba5' }] },
    { featureType: 'road', elementType: 'geometry', stylers: [{ color: '#304a7d' }] },
    { featureType: 'road', elementType: 'labels.text.fill', stylers: [{ color: '#98a5be' }] },
    { featureType: 'transit', elementType: 'geometry', stylers: [{ color: '#2f3948' }] },
    { featureType: 'water', elementType: 'geometry', stylers: [{ color: '#0e1626' }] },
    { featureType: 'water', elementType: 'labels.text.fill', stylers: [{ color: '#4e6d70' }] },
];
