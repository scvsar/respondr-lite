import {defineConfig, loadEnv, transformWithEsbuild} from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig(({mode}) => ({
  plugins: [
    {
      name: 'jsx-source-files',
      enforce: 'pre',
      transform(code, id) {
        if (id.replaceAll('\\', '/').includes('/src/') && id.endsWith('.js')) {
          return transformWithEsbuild(code, id, {loader: 'jsx', jsx: 'automatic'});
        }
      },
    },
    react(),
  ],
  // Existing deployment variables are public and use the REACT_APP_ prefix.
  define: mode === 'test' ? {} : {
    'process.env': JSON.stringify({
      ...loadEnv(mode, process.cwd(), 'REACT_APP_'),
      NODE_ENV: mode === 'production' ? 'production' : 'development',
    }),
  },
  optimizeDeps: {esbuildOptions: {loader: {'.js': 'jsx'}}},
  server: {port: 3000, strictPort: true, proxy: {'/api': 'http://localhost:8000'}},
  build: {
    outDir: 'build',
    assetsDir: 'static',
    target: 'es2020',
    rollupOptions: {output: {manualChunks: {
      authentication: ['@azure/msal-browser'],
      react: ['react', 'react-dom', 'react-router-dom'],
    }}},
  },
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: ['./src/setupTests.js'],
    maxWorkers: 2,
    coverage: {provider: 'v8'},
  },
}));
