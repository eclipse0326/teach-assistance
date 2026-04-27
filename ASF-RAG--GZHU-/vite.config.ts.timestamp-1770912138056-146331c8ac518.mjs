// vite.config.ts
import { defineConfig } from "file:///E:/%E6%AF%95%E8%AE%BE/kngraph/KnowledgeRAG/ASF-RAG--GZHU-/node_modules/vite/dist/node/index.js";
import vue from "file:///E:/%E6%AF%95%E8%AE%BE/kngraph/KnowledgeRAG/ASF-RAG--GZHU-/node_modules/@vitejs/plugin-vue/dist/index.mjs";
import svgLoader from "file:///E:/%E6%AF%95%E8%AE%BE/kngraph/KnowledgeRAG/ASF-RAG--GZHU-/node_modules/vite-svg-loader/index.js";
import vueDevTools from "file:///E:/%E6%AF%95%E8%AE%BE/kngraph/KnowledgeRAG/ASF-RAG--GZHU-/node_modules/vite-plugin-vue-devtools/dist/vite.mjs";
import { fileURLToPath, URL } from "node:url";
var __vite_injected_original_import_meta_url = "file:///E:/%E6%AF%95%E8%AE%BE/kngraph/KnowledgeRAG/ASF-RAG--GZHU-/vite.config.ts";
var vite_config_default = defineConfig({
  plugins: [vue(), svgLoader(), vueDevTools()],
  server: {
    // 确保开发服务器配置正确
    hmr: true,
    host: "0.0.0.0",
    // 允许外部访问
    port: 5173,
    // 端口号
    watch: {
      usePolling: true
      // 在Docker中启用文件监听
    },
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true
      },
      "/lens-api": {
        target: "https://api.lens.org",
        changeOrigin: true,
        secure: false,
        rewrite: (path) => path.replace(/^\/lens-api/, "")
      }
    }
  },
  resolve: {
    alias: {
      // 使用新的方式来设置别名
      "@": fileURLToPath(new URL("./src", __vite_injected_original_import_meta_url))
    }
  }
});
export {
  vite_config_default as default
};
//# sourceMappingURL=data:application/json;base64,ewogICJ2ZXJzaW9uIjogMywKICAic291cmNlcyI6IFsidml0ZS5jb25maWcudHMiXSwKICAic291cmNlc0NvbnRlbnQiOiBbImNvbnN0IF9fdml0ZV9pbmplY3RlZF9vcmlnaW5hbF9kaXJuYW1lID0gXCJFOlxcXFxcdTZCRDVcdThCQkVcXFxca25ncmFwaFxcXFxLbm93bGVkZ2VSQUdcXFxcQVNGLVJBRy0tR1pIVS1cIjtjb25zdCBfX3ZpdGVfaW5qZWN0ZWRfb3JpZ2luYWxfZmlsZW5hbWUgPSBcIkU6XFxcXFx1NkJENVx1OEJCRVxcXFxrbmdyYXBoXFxcXEtub3dsZWRnZVJBR1xcXFxBU0YtUkFHLS1HWkhVLVxcXFx2aXRlLmNvbmZpZy50c1wiO2NvbnN0IF9fdml0ZV9pbmplY3RlZF9vcmlnaW5hbF9pbXBvcnRfbWV0YV91cmwgPSBcImZpbGU6Ly8vRTovJUU2JUFGJTk1JUU4JUFFJUJFL2tuZ3JhcGgvS25vd2xlZGdlUkFHL0FTRi1SQUctLUdaSFUtL3ZpdGUuY29uZmlnLnRzXCI7Ly8gdml0ZS5jb25maWcudHNcbmltcG9ydCB7IGRlZmluZUNvbmZpZyB9IGZyb20gJ3ZpdGUnXG5pbXBvcnQgdnVlIGZyb20gJ0B2aXRlanMvcGx1Z2luLXZ1ZSdcbmltcG9ydCBzdmdMb2FkZXIgZnJvbSAndml0ZS1zdmctbG9hZGVyJ1xuaW1wb3J0IHZ1ZURldlRvb2xzIGZyb20gJ3ZpdGUtcGx1Z2luLXZ1ZS1kZXZ0b29scydcbmltcG9ydCB7IGZpbGVVUkxUb1BhdGgsIFVSTCB9IGZyb20gJ25vZGU6dXJsJ1xuXG5leHBvcnQgZGVmYXVsdCBkZWZpbmVDb25maWcoe1xuICBwbHVnaW5zOiBbdnVlKCksIHN2Z0xvYWRlcigpLCB2dWVEZXZUb29scygpXSxcbiAgc2VydmVyOiB7XG4gICAgLy8gXHU3ODZFXHU0RkREXHU1RjAwXHU1M0QxXHU2NzBEXHU1MkExXHU1NjY4XHU5MTREXHU3RjZFXHU2QjYzXHU3ODZFXG4gICAgaG1yOiB0cnVlLFxuICAgIGhvc3Q6ICcwLjAuMC4wJywgLy8gXHU1MTQxXHU4QkI4XHU1OTE2XHU5MEU4XHU4QkJGXHU5NUVFXG4gICAgcG9ydDogNTE3MywgICAgICAvLyBcdTdBRUZcdTUzRTNcdTUzRjdcbiAgICB3YXRjaDoge1xuICAgICAgdXNlUG9sbGluZzogdHJ1ZSAvLyBcdTU3MjhEb2NrZXJcdTRFMkRcdTU0MkZcdTc1MjhcdTY1ODdcdTRFRjZcdTc2RDFcdTU0MkNcbiAgICB9LFxuICAgIHByb3h5OiB7XG4gICAgICAnL2FwaSc6IHtcbiAgICAgICAgdGFyZ2V0OiAnaHR0cDovL2xvY2FsaG9zdDo4MDAwJyxcbiAgICAgICAgY2hhbmdlT3JpZ2luOiB0cnVlXG4gICAgICB9LFxuICAgICAgJy9sZW5zLWFwaSc6IHtcbiAgICAgICAgdGFyZ2V0OiAnaHR0cHM6Ly9hcGkubGVucy5vcmcnLFxuICAgICAgICBjaGFuZ2VPcmlnaW46IHRydWUsXG4gICAgICAgIHNlY3VyZTogZmFsc2UsXG4gICAgICAgIHJld3JpdGU6IChwYXRoKSA9PiBwYXRoLnJlcGxhY2UoL15cXC9sZW5zLWFwaS8sICcnKVxuICAgICAgfVxuICAgIH1cbiAgfSxcbiAgcmVzb2x2ZToge1xuICAgIGFsaWFzOiB7XG4gICAgICAvLyBcdTRGN0ZcdTc1MjhcdTY1QjBcdTc2ODRcdTY1QjlcdTVGMEZcdTY3NjVcdThCQkVcdTdGNkVcdTUyMkJcdTU0MERcbiAgICAgICdAJzogZmlsZVVSTFRvUGF0aChuZXcgVVJMKCcuL3NyYycsIGltcG9ydC5tZXRhLnVybCkpXG4gICAgfVxuICB9XG59KVxuIl0sCiAgIm1hcHBpbmdzIjogIjtBQUNBLFNBQVMsb0JBQW9CO0FBQzdCLE9BQU8sU0FBUztBQUNoQixPQUFPLGVBQWU7QUFDdEIsT0FBTyxpQkFBaUI7QUFDeEIsU0FBUyxlQUFlLFdBQVc7QUFMZ0ssSUFBTSwyQ0FBMkM7QUFPcFAsSUFBTyxzQkFBUSxhQUFhO0FBQUEsRUFDMUIsU0FBUyxDQUFDLElBQUksR0FBRyxVQUFVLEdBQUcsWUFBWSxDQUFDO0FBQUEsRUFDM0MsUUFBUTtBQUFBO0FBQUEsSUFFTixLQUFLO0FBQUEsSUFDTCxNQUFNO0FBQUE7QUFBQSxJQUNOLE1BQU07QUFBQTtBQUFBLElBQ04sT0FBTztBQUFBLE1BQ0wsWUFBWTtBQUFBO0FBQUEsSUFDZDtBQUFBLElBQ0EsT0FBTztBQUFBLE1BQ0wsUUFBUTtBQUFBLFFBQ04sUUFBUTtBQUFBLFFBQ1IsY0FBYztBQUFBLE1BQ2hCO0FBQUEsTUFDQSxhQUFhO0FBQUEsUUFDWCxRQUFRO0FBQUEsUUFDUixjQUFjO0FBQUEsUUFDZCxRQUFRO0FBQUEsUUFDUixTQUFTLENBQUMsU0FBUyxLQUFLLFFBQVEsZUFBZSxFQUFFO0FBQUEsTUFDbkQ7QUFBQSxJQUNGO0FBQUEsRUFDRjtBQUFBLEVBQ0EsU0FBUztBQUFBLElBQ1AsT0FBTztBQUFBO0FBQUEsTUFFTCxLQUFLLGNBQWMsSUFBSSxJQUFJLFNBQVMsd0NBQWUsQ0FBQztBQUFBLElBQ3REO0FBQUEsRUFDRjtBQUNGLENBQUM7IiwKICAibmFtZXMiOiBbXQp9Cg==
