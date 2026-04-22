import { mount } from 'svelte'
import './app.css'
import App from './App.svelte'
import { initPostHog } from './config/posthog'

initPostHog()

const app = mount(App, {
  target: document.getElementById('app'),
})

export default app
