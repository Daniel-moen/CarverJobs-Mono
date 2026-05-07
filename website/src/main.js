import { mount } from 'svelte'
import './app.css'
import App from './App.svelte'
import { initMixpanel } from './config/mixpanel'

initMixpanel()

const app = mount(App, {
  target: document.getElementById('app'),
})

export default app
