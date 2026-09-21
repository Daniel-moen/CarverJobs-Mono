import { mount } from 'svelte'
import './app.css'
import App from './App.svelte'
import { initMixpanel } from './config/mixpanel'

const app = mount(App, {
  target: document.getElementById('app'),
})

// Drop the pre-JS shell from index.html now that the real app owns the page.
document.getElementById('app-prelude')?.remove()

// Load the analytics SDK (~300 kB) once the browser is idle so it never
// competes with page chunks for bandwidth on first paint. Events fired
// before it arrives are queued inside config/mixpanel.js.
if (typeof requestIdleCallback === 'function') {
  requestIdleCallback(() => initMixpanel(), { timeout: 3000 })
} else {
  setTimeout(initMixpanel, 1500)
}

export default app
