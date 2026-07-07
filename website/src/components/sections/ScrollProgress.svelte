<script>
  /**
   * ScrollProgress — a 2px radium→brass bar pinned to the very top of the
   * viewport that fills as the visitor scrolls the page. Cheap (one scaleX
   * transform per rAF) and a quiet nudge that there's more below the fold.
   */
  import { onMount } from 'svelte'

  /** @type {HTMLElement|null} */
  let bar = $state(null)

  onMount(() => {
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return
    let ticking = false
    function update() {
      ticking = false
      if (!bar) return
      const max = document.documentElement.scrollHeight - window.innerHeight
      const frac = max > 0 ? Math.min(1, window.scrollY / max) : 0
      bar.style.transform = `scaleX(${frac})`
    }
    function onScroll() {
      if (ticking) return
      ticking = true
      requestAnimationFrame(update)
    }
    window.addEventListener('scroll', onScroll, { passive: true })
    window.addEventListener('resize', onScroll, { passive: true })
    update()
    return () => {
      window.removeEventListener('scroll', onScroll)
      window.removeEventListener('resize', onScroll)
    }
  })
</script>

<div class="sp" bind:this={bar} aria-hidden="true"></div>

<style>
  .sp {
    position: fixed;
    top: 0;
    left: 0;
    right: 0;
    height: 2px;
    z-index: 80;
    transform: scaleX(0);
    transform-origin: 0 50%;
    background: linear-gradient(90deg, var(--radium-deep), var(--brass-bright));
    box-shadow: 0 0 12px rgba(201, 169, 110, 0.45);
    pointer-events: none;
  }
</style>
