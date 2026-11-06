<script setup lang="ts">
// Trang Bản đồ (docs/spec-ban-do.md mục 3): điểm trại trên nền bản đồ offline; thiếu dữ liệu thì trang vẫn dùng được.
// Tọa độ nhập ở Quản trị · Cài đặt. Bản đồ và tọa độ chỉ có khi triển khai, nên thiếu dữ liệu là trạng thái bình thường.
import { computed, defineAsyncComponent, onMounted, ref } from 'vue';
import { RouterLink } from 'vue-router';
import Icon from '../components/Icon.vue';
import { api } from '../lib/api';
import { bboxAround, fmtLatLng } from '../lib/geo';
import { isAdmin } from '../lib/session';
import { toast } from '../lib/ui';

interface MapConfig {
  site: { name: string; lat: number; lng: number } | null;
  basemap: { url: string; size_bytes: number } | null;
}

const SETTINGS = '/quan-tri/cai-dat';

const cfg = ref<MapConfig | null>(null);
const loadError = ref('');
const failed = ref<'' | 'webgl' | 'file'>('');
const outside = ref(false);
const admin = computed(() => isAdmin());

const MapView = defineAsyncComponent(() =>
  import('../components/MapView.vue').catch((e) => {
    failed.value = 'file';
    throw e;
  }),
);

const coords = computed(() => (cfg.value?.site ? fmtLatLng(cfg.value.site) : ''));
const showMap = computed(() => Boolean(cfg.value?.basemap) && !failed.value);
const fetchCmd = computed(() => {
  const site = cfg.value?.site;
  if (!site) return '';
  return `pmtiles extract https://build.protomaps.com/YYYYMMDD.pmtiles basemap.pmtiles \\\n  --bbox=${bboxAround(site)} --maxzoom=15\nscp basemap.pmtiles <user>@<địa-chỉ-datalogger>:/tmp/`;
});
const installCmd = 'sudo -u greenhouse GREENHOUSE_DATA_DIR=/var/lib/greenhouse \\\n  /opt/greenhouse/app/.venv/bin/greenhouse install-map /tmp/basemap.pmtiles';

async function load(): Promise<void> {
  loadError.value = '';
  failed.value = '';
  outside.value = false;
  try {
    cfg.value = await api.get<MapConfig>('/api/map/config');
  } catch (e) {
    loadError.value = e instanceof Error ? e.message : String(e);
  }
}

async function copy(text: string, done: string): Promise<void> {
  try {
    await navigator.clipboard.writeText(text);
    toast(done);
  } catch {
    toast('Trình duyệt không cho chép; hãy chọn và chép thủ công', 'err');
  }
}

onMounted(load);
</script>

<template>
  <div class="map-page" :class="{ full: showMap }">
    <div class="page-head hide-phone">
      <div>
        <h1>Bản đồ</h1>
        <div class="page-sub">Vị trí của trại, xem được cả khi không có Internet</div>
      </div>
    </div>

    <div v-if="loadError" class="empty">
      <Icon name="map" :size="24" />
      <h2>Không tải được thông tin bản đồ</h2>
      <p>{{ loadError }}</p>
      <button type="button" class="btn sm" @click="load"><Icon name="refresh" />Thử lại</button>
    </div>
    <div v-else-if="!cfg" class="loading"><div class="spinner" role="status" aria-label="Đang tải" /></div>

    <template v-else-if="showMap">
      <MapView :url="cfg.basemap!.url" :site="cfg.site" @fail="failed = $event" @outside="outside = true">
        <div v-if="!cfg.site" class="banner plain sm map-note" role="status">
          <Icon name="info" />
          <div class="body">{{ admin ? 'Chưa đặt vị trí trại.' : 'Quản trị viên chưa đặt vị trí trại.' }}</div>
          <RouterLink v-if="admin" :to="SETTINGS">Đặt ở Cài đặt</RouterLink>
        </div>
        <div v-else-if="outside" class="banner warn sm map-note" role="status">
          <Icon name="warn" />
          <div class="body">Điểm trại nằm ngoài vùng của file bản đồ.</div>
          <RouterLink v-if="admin" :to="SETTINGS">Sửa ở Cài đặt</RouterLink>
        </div>
      </MapView>
      <div v-if="cfg.site" class="map-info">
        <div class="col grow" style="min-width: 0">
          <span class="fs-13 strong ellipsis">{{ cfg.site.name }}</span>
          <span class="mono small">{{ coords }}</span>
        </div>
        <button type="button" class="btn sm" aria-label="Sao chép tọa độ" @click="copy(coords, 'Đã chép tọa độ')">
          <Icon name="copy" /><span class="map-info-label">Sao chép</span>
        </button>
        <RouterLink v-if="admin" class="btn sm" :to="SETTINGS" aria-label="Sửa tọa độ ở Cài đặt"><Icon name="edit" /><span class="map-info-label">Sửa</span></RouterLink>
      </div>
    </template>

    <div v-else-if="failed" class="empty">
      <Icon name="map" :size="24" />
      <template v-if="failed === 'webgl'">
        <h2>Trình duyệt này không vẽ được bản đồ</h2>
        <p>Mở bằng trình duyệt khác{{ cfg.site ? ', hoặc dán tọa độ vào app bản đồ khác' : '' }}.</p>
      </template>
      <template v-else>
        <h2>Không đọc được file bản đồ</h2>
        <p>{{ admin ? 'Cài lại file bằng lệnh greenhouse install-map.' : 'Báo quản trị viên để cài lại file.' }}</p>
      </template>
      <div v-if="cfg.site" class="row gap-8" style="width: 100%">
        <span class="mono fs-13 grow">{{ coords }}</span>
        <button type="button" class="btn sm" @click="copy(coords, 'Đã chép tọa độ')"><Icon name="copy" />Sao chép</button>
      </div>
      <button v-if="failed === 'file'" type="button" class="btn sm" @click="load"><Icon name="refresh" />Thử lại</button>
    </div>

    <div v-else-if="!admin" class="empty">
      <Icon name="map" :size="24" />
      <template v-if="cfg.site">
        <h2>Chưa cài bản đồ nền</h2>
        <p>Tọa độ trại đã có, xem được trong app bản đồ khác.</p>
        <div class="row gap-8" style="width: 100%">
          <span class="mono fs-13 grow">{{ coords }}</span>
          <button type="button" class="btn sm" @click="copy(coords, 'Đã chép tọa độ')"><Icon name="copy" />Sao chép</button>
        </div>
      </template>
      <template v-else>
        <h2>Bản đồ trại sẽ có sau khi lắp đặt tại trại</h2>
        <p>Quản trị viên sẽ nhập tọa độ và cài bản đồ khi triển khai.</p>
      </template>
    </div>

    <template v-else>
      <div class="col gap-8">
        <h2 class="panel-title">Bản đồ trại sẽ có sau khi lắp đặt tại trại</h2>
        <span class="fs-13 text-3">Làm lần lượt khi đang ở trại.</span>
      </div>
      <div class="panel p20 map-steps">
        <div class="map-step">
          <span class="map-step-no"><Icon v-if="cfg.site" name="check" :size="16" /><template v-else>1</template></span>
          <div class="map-step-body">
            <h3>Nhập tọa độ trại</h3>
            <template v-if="cfg.site">
              <div class="row gap-8 wrap">
                <span class="mono fs-13" style="flex: 1 1 100%">{{ coords }}</span>
                <button type="button" class="btn sm" @click="copy(coords, 'Đã chép tọa độ')"><Icon name="copy" />Sao chép</button>
                <RouterLink class="btn sm" :to="SETTINGS"><Icon name="edit" />Sửa</RouterLink>
              </div>
            </template>
            <template v-else>
              <span class="fs-13 text-3">Đứng tại trại, lấy tọa độ từ app bản đồ trên điện thoại rồi dán vào ô Tọa độ trại.</span>
              <div><RouterLink class="btn sm primary" :to="SETTINGS">Mở Cài đặt</RouterLink></div>
            </template>
          </div>
        </div>
        <div class="map-step">
          <span class="map-step-no" :class="{ off: !cfg.site }">2</span>
          <div class="map-step-body">
            <template v-if="cfg.site">
              <h3>Cài bản đồ nền</h3>
              <span class="fs-13 text-3"
                >Trên laptop có Internet (4G cũng được). Thay YYYYMMDD bằng
                <a href="https://docs.protomaps.com/basemaps/downloads" target="_blank" rel="noopener">bản build mới nhất</a>.</span
              >
              <pre class="map-cmd">{{ fetchCmd }}</pre>
              <div><button type="button" class="btn sm" @click="copy(fetchCmd, 'Đã chép lệnh')"><Icon name="copy" />Sao chép lệnh</button></div>
              <span class="fs-13 text-3">Trên Datalogger, không cần Internet:</span>
              <pre class="map-cmd">{{ installCmd }}</pre>
              <div class="row gap-8 wrap">
                <button type="button" class="btn sm" @click="copy(installCmd, 'Đã chép lệnh')"><Icon name="copy" />Sao chép lệnh</button>
                <button type="button" class="btn sm" @click="load"><Icon name="refresh" />Tải lại trang</button>
              </div>
            </template>
            <template v-else>
              <h3 class="muted">Cài bản đồ nền</h3>
              <span class="fs-13 muted">Lệnh cài hiện ở đây sau khi có tọa độ.</span>
            </template>
          </div>
        </div>
      </div>
    </template>
  </div>
</template>
