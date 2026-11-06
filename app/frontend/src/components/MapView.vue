<script setup lang="ts">
// Nền bản đồ (docs/spec-ban-do.md mục 4): MapLibre đọc file PMTiles trên Datalogger, không gọi dịch vụ ngoài.
// MapPage tải lười component này, nên chỉ khi có file bản đồ trình duyệt mới tải thư viện.
import { layers, namedFlavor } from '@protomaps/basemaps';
import { GPUInitializationError, Map as MapLibreMap, Marker, addProtocol, removeProtocol, setWorkerUrl, type LayerSpecification } from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';
import workerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?url';
import { PMTiles, Protocol } from 'pmtiles';
import { onBeforeUnmount, onMounted, ref } from 'vue';
import { inBounds, type Bounds, type LatLng } from '../lib/geo';
import Icon from './Icon.vue';

const SITE_ZOOM = 15;
// Tile có tới zoom tối đa của file; phóng thêm một chút vẫn đọc được nhờ tile vector.
const OVERZOOM = 3;
const PIN =
  '<svg viewBox="-17 -46 34 46" width="34" height="46" aria-hidden="true"><ellipse cx="0" cy="1" rx="7" ry="3" fill="rgba(28,30,27,.28)"/>' +
  '<path class="map-pin-body" d="M0 0C-2 -8 -15 -17 -15 -29A15 15 0 1 1 15 -29C15 -17 2 -8 0 0Z" stroke="#fff" stroke-width="2"/><circle cx="0" cy="-29" r="5.5" fill="#fff"/></svg>';

const props = defineProps<{ url: string; site: (LatLng & { name: string }) | null }>();
const emit = defineEmits<{ fail: [kind: 'webgl' | 'file']; outside: [] }>();

const el = ref<HTMLElement | null>(null);
const canGoHome = ref(false);
let map: MapLibreMap | null = null;
let disposed = false;

setWorkerUrl(workerUrl);

function pinElement(name: string): HTMLElement {
  const pin = document.createElement('div');
  pin.className = 'map-pin';
  pin.innerHTML = PIN;
  const label = document.createElement('span');
  label.textContent = name;
  pin.append(label);
  return pin;
}

function goHome(): void {
  if (props.site) map?.flyTo({ center: [props.site.lng, props.site.lat], zoom: SITE_ZOOM });
}

onMounted(async () => {
  const src = `${location.origin}${props.url}`;
  const archive = new PMTiles(src);
  const protocol = new Protocol();
  protocol.add(archive);
  addProtocol('pmtiles', protocol.tile);

  let bounds: Bounds;
  let maxZoom: number;
  try {
    const h = await archive.getHeader();
    bounds = [h.minLon, h.minLat, h.maxLon, h.maxLat];
    maxZoom = h.maxZoom + OVERZOOM;
  } catch {
    if (!disposed) emit('fail', 'file');
    return;
  }
  if (disposed || !el.value) return;

  const site = props.site && inBounds(props.site, bounds) ? props.site : null;
  if (props.site && !site) emit('outside');
  try {
    map = new MapLibreMap({
      container: el.value,
      style: {
        version: 8,
        glyphs: `${location.origin}/map/fonts/{fontstack}/{range}.pbf`,
        sprite: `${location.origin}/map/sprites/light`,
        sources: { protomaps: { type: 'vector', url: `pmtiles://${src}` } },
        layers: layers('protomaps', namedFlavor('light'), { lang: 'vi' }) as LayerSpecification[],
      },
      maxBounds: bounds,
      maxZoom,
      // Ghi công nằm ở link bên dưới, luôn hiện đủ (ODbL) thay vì nút thu gọn của MapLibre.
      attributionControl: false,
      locale: { 'Map.Title': 'Bản đồ quanh trại' },
      ...(site ? { center: [site.lng, site.lat] as [number, number], zoom: SITE_ZOOM } : { bounds }),
    });
  } catch (e) {
    emit('fail', e instanceof GPUInitializationError ? 'webgl' : 'file');
    return;
  }
  if (site) {
    new Marker({ element: pinElement(site.name), anchor: 'bottom' }).setLngLat([site.lng, site.lat]).addTo(map);
    canGoHome.value = true;
  }
});

onBeforeUnmount(() => {
  disposed = true;
  map?.remove();
  removeProtocol('pmtiles');
});
</script>

<template>
  <div class="map-wrap">
    <div ref="el" class="map-canvas" />
    <slot />
    <div class="map-ctrl">
      <div class="map-zoom">
        <button type="button" aria-label="Phóng to" @click="map?.zoomIn()"><Icon name="plus" /></button>
        <button type="button" aria-label="Thu nhỏ" @click="map?.zoomOut()"><Icon name="minus" /></button>
      </div>
      <button v-if="canGoHome" type="button" class="btn map-btn" @click="goHome"><Icon name="pin" />Về trại</button>
    </div>
    <a class="map-attrib" href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">© OpenStreetMap contributors</a>
  </div>
</template>
