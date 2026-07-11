import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  // React Three Fiber + postprocessing must share ONE three.js instance;
  // dedupe stops Vite's dev pre-bundling from creating a second copy
  // ("Multiple instances of Three.js") which breaks the effect composer.
  resolve: { dedupe: ['three'] },
  optimizeDeps: { include: ['three'] },
})
