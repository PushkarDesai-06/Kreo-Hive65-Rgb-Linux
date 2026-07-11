import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.jsx'

// NOTE: StrictMode intentionally omitted. Its dev-only double mount/unmount
// tears down React Three Fiber's render loop and leaves it stopped (the Dither
// canvas rendered one static frame). Our own effect loops handle StrictMode
// fine, but R3F does not here, so we disable it app-wide.
createRoot(document.getElementById('root')).render(<App />)
