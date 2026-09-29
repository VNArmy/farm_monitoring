<script setup lang="ts">
import { RouterLink } from 'vue-router';
</script>

<template>
  <div class="empty" style="max-width: 560px">
    <h2>Không tìm thấy trang</h2>
    <p>Đường dẫn này không có trong web app.</p>
    <RouterLink class="btn" to="/">Về Tổng quan</RouterLink>
  </div>
</template>
