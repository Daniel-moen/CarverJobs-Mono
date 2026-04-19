<script>
  /**
   * TypingChat — a self-running WhatsApp conversation that types itself out.
   *
   * The script below is hand-written from the actual bot's real responses
   * in api/app/routes/whatsapp.py (match, balance, submit job, etc.) so
   * what visitors see on the landing page is exactly what they will get
   * if they text the live number.
   *
   * Animation budget:
   *  - Typing dots show for ~700-1100ms before each bot reply
   *  - Bot bubbles fade up; user bubbles appear instantly (mimicking real send)
   *  - Loop pauses at the end for ~7s, then restarts from the top.
   *
   * A `paused` prop lets the caller stop the animation when off-screen
   * (the parent uses an IntersectionObserver to set this).
   */
  import { onDestroy, onMount } from 'svelte'

  /** @type {{ paused?: boolean }} */
  let { paused = false } = $props()

  /**
   * @typedef {Object} ChatStep
   * @property {'me'|'bot'} role
   * @property {string} text         HTML allowed; *bold* and \n are converted.
   * @property {string} time         HH:MM
   * @property {number} [thinkMs]    For bot only — how long to show typing dots
   * @property {number} [afterMs]    Pause after this step before the next
   */

  /** @type {ChatStep[]} */
  const script = [
    { role: 'me',  text: 'match',                                         time: '09:14', afterMs: 700 },
    { role: 'bot', thinkMs: 850, time: '09:14', afterMs: 600,
      text: '💳 *1 token used* — *2 tokens* left.\n⏳ Scanning *312 positions* (~25s) — hang tight!' },
    { role: 'bot', thinkMs: 1400, time: '09:14', afterMs: 1100,
      text:
        '🎯 *Found 3 matches!*\n\n' +
        '1. *M/Y Lupus* — Antibes  (94%)\n' +
        '2. *M/Y Astra* — Palma    (88%)\n' +
        '3. *S/Y Hera*  — Genoa    (81%)\n\n' +
        'View all & draft applications:\n' +
        '👉 carver.app/m/8a3f\n' +
        '_Link expires in 30 min._\n\n' +
        'Tokens remaining: *2*' },
    { role: 'me',  text: 'submit job',                                    time: '09:16', afterMs: 700 },
    { role: 'bot', thinkMs: 700, time: '09:16', afterMs: 1300,
      text:
        '📸 *Submit a job to the board*\n\n' +
        'Send a *screenshot* of the listing or *paste* the text — ' +
        'I\'ll read it and add it to the board if it\'s a real yacht crew role.' },
    { role: 'me',  text: '[ screenshot.png ]',                            time: '09:16', afterMs: 600 },
    { role: 'bot', thinkMs: 1600, time: '09:17', afterMs: 1400,
      text:
        '✅ *Job posted to the board!*\n\n' +
        '⚓ *Sole Bosun — M/Y Anatolia*\n' +
        '🧑‍✈️ Role: Bosun\n' +
        '📍 Location: Antibes\n\n' +
        'You earned *1 token* for sharing this job.\n' +
        'Current balance: *3 tokens*.' },
    { role: 'me',  text: 'balance',                                       time: '09:18', afterMs: 600 },
    { role: 'bot', thinkMs: 600,  time: '09:18', afterMs: 6000,
      text: '💳 *Your balance: 3 tokens.*\nEach *Find Matches* run uses 1 token.' },
  ]

  /** Convert WhatsApp-flavoured plain text into safe display HTML.
   *  - *word*  → <strong>word</strong>
   *  - _word_  → <em>word</em>
   *  - \n      → <br/>
   *  - URLs left as plain text (they're never user-controlled here)
   */
  function format(text) {
    const escaped = text
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
    return escaped
      .replace(/\*([^*\n]+)\*/g, '<strong>$1</strong>')
      .replace(/(^|\s)_([^_\n]+)_/g, '$1<em>$2</em>')
      .replace(/\n/g, '<br/>')
  }

  /** Visible chat steps (a prefix of `script`). */
  let visible = $state(/** @type {ChatStep[]} */ ([]))
  /** True while a "typing dots" placeholder is shown for the next bot bubble. */
  let typing = $state(false)
  /** Cycle counter so {#each} re-creates bubble nodes on every loop, retriggering enter animations. */
  let cycle = $state(0)

  /** @type {ReturnType<typeof setTimeout>|null} */
  let _timer = null
  let _stopped = false

  function clearTimer() {
    if (_timer) {
      clearTimeout(_timer)
      _timer = null
    }
  }

  function schedule(fn, ms) {
    clearTimer()
    _timer = setTimeout(fn, ms)
  }

  function restart() {
    visible = []
    typing = false
    cycle++
    // tiny delay so the keyed {#each} unmounts/remounts cleanly
    schedule(() => step(0), 350)
  }

  function step(i) {
    if (_stopped) return
    if (i >= script.length) {
      // hold on the final state for a beat, then loop
      schedule(restart, 4500)
      return
    }
    const s = script[i]
    if (s.role === 'bot' && (s.thinkMs ?? 0) > 0) {
      typing = true
      schedule(() => {
        if (_stopped) return
        typing = false
        visible = [...visible, s]
        schedule(() => step(i + 1), s.afterMs ?? 600)
      }, s.thinkMs)
    } else {
      typing = false
      visible = [...visible, s]
      schedule(() => step(i + 1), s.afterMs ?? 500)
    }
  }

  onMount(() => {
    if (!paused) step(0)
  })

  onDestroy(() => {
    _stopped = true
    clearTimer()
  })

  // React to pause changes
  $effect(() => {
    if (paused) {
      _stopped = true
      clearTimer()
    } else if (_stopped) {
      _stopped = false
      // fresh restart whenever we come back into view
      restart()
    }
  })
</script>

<div class="chat" aria-label="Live demo of the Carver WhatsApp bot">
  <!-- chat header — mimics WhatsApp's native top bar -->
  <header class="chat-head">
    <div class="chat-avatar" aria-hidden="true">
      <svg viewBox="0 0 32 32" fill="currentColor"><path d="M16 3C9.4 3 4 8.4 4 15c0 2.3.7 4.5 1.8 6.4L4 29l7.8-1.8A12 12 0 0 0 16 27c6.6 0 12-5.4 12-12S22.6 3 16 3Z"/></svg>
    </div>
    <div class="chat-who">
      <p class="chat-name">CARVER · crew agent</p>
      <p class="chat-status">
        <span class="chat-status-dot"></span>
        online · typically replies in seconds
      </p>
    </div>
    <div class="chat-icons" aria-hidden="true">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72 12.84 12.84 0 0 0 .7 2.81 2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45 12.84 12.84 0 0 0 2.81.7A2 2 0 0 1 22 16.92z"/></svg>
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="1"/><circle cx="12" cy="5"  r="1"/><circle cx="12" cy="19" r="1"/></svg>
    </div>
  </header>

  <!-- chat body — paper grain over a deep WhatsApp-dark surface -->
  <div class="chat-body chat-surface" aria-live="polite">
    {#key cycle}
      {#each visible as msg, i (i)}
        {#if msg.role === 'me'}
          <div class="row row-me" style="--d:{i * 30}ms">
            <div class="bubble-me">
              {@html format(msg.text)}
              <span class="bubble-time">{msg.time}<span class="bubble-tick">✓✓</span></span>
            </div>
          </div>
        {:else}
          <div class="row" style="--d:{i * 30}ms">
            <div class="bubble-bot">
              {@html format(msg.text)}
              <span class="bubble-time">{msg.time}</span>
            </div>
          </div>
        {/if}
      {/each}

      {#if typing}
        <div class="row row-typing">
          <div class="bubble-bot bubble-typing">
            <span class="typing-dots" aria-label="Carver is typing">
              <span></span><span></span><span></span>
            </span>
          </div>
        </div>
      {/if}
    {/key}
  </div>

  <!-- chat input — non-interactive; just sets the scene -->
  <footer class="chat-input" aria-hidden="true">
    <span class="chat-input-pill">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="M8 14s1.5 2 4 2 4-2 4-2"/><line x1="9" y1="9" x2="9.01" y2="9"/><line x1="15" y1="9" x2="15.01" y2="9"/></svg>
      <span class="chat-input-text">Try “match”, “submit job”, “help”…</span>
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m3 3 18 9-18 9 4-9-4-9z"/></svg>
    </span>
  </footer>
</div>

<style>
  .chat {
    width: 100%;
    border-radius: 18px;
    overflow: hidden;
    background: #0a141a;
    border: 1px solid rgba(255, 255, 255, 0.06);
    box-shadow:
      0 1px 0 rgba(255, 255, 255, 0.04) inset,
      0 40px 120px -50px rgba(0, 0, 0, 0.85),
      0 12px 40px -20px rgba(0, 0, 0, 0.55);
    display: flex;
    flex-direction: column;
    min-height: 480px;
    max-height: 620px;
  }

  /* ── Header (WhatsApp top bar) ─────────────────────────────────────── */
  .chat-head {
    display: flex;
    align-items: center;
    gap: 0.7rem;
    padding: 0.7rem 0.85rem;
    background: #161e23;
    border-bottom: 1px solid rgba(255, 255, 255, 0.04);
  }
  .chat-avatar {
    width: 36px;
    height: 36px;
    border-radius: 9999px;
    background: linear-gradient(180deg, #25d366 0%, #1ebd5d 100%);
    color: #0a141a;
    display: inline-flex;
    align-items: center;
    justify-content: center;
  }
  .chat-avatar :global(svg) { width: 20px; height: 20px; }
  .chat-who { flex: 1; min-width: 0; }
  .chat-name {
    margin: 0;
    color: #e9edef;
    font-weight: 600;
    font-size: 13.5px;
    letter-spacing: 0.01em;
  }
  .chat-status {
    margin: 1px 0 0;
    font-size: 10.5px;
    color: rgba(233, 237, 239, 0.55);
    display: inline-flex;
    align-items: center;
    gap: 5px;
  }
  .chat-status-dot {
    width: 6px;
    height: 6px;
    border-radius: 9999px;
    background: var(--wa-green);
    box-shadow: 0 0 0 3px rgba(37, 211, 102, 0.18);
    animation: dot-pulse 2s ease-in-out infinite;
  }
  @keyframes dot-pulse {
    0%, 100% { opacity: 0.7; }
    50% { opacity: 1; }
  }
  .chat-icons {
    display: inline-flex;
    gap: 0.85rem;
    color: rgba(233, 237, 239, 0.5);
  }
  .chat-icons :global(svg) { width: 16px; height: 16px; }

  /* ── Body ─────────────────────────────────────────────────────────── */
  .chat-body {
    flex: 1;
    padding: 0.9rem 0.85rem;
    overflow-y: auto;
    display: flex;
    flex-direction: column;
    gap: 0.45rem;
    scroll-behavior: smooth;
  }
  .chat-body::-webkit-scrollbar { width: 4px; }
  .chat-body::-webkit-scrollbar-thumb {
    background: rgba(255, 255, 255, 0.08);
    border-radius: 9999px;
  }

  .row {
    display: flex;
    animation: bubble-in 0.35s ease-out backwards;
    animation-delay: var(--d, 0ms);
  }
  .row-me { justify-content: flex-end; }
  .row-typing { animation: none; }
  @keyframes bubble-in {
    from { opacity: 0; transform: translateY(6px); }
    to   { opacity: 1; transform: translateY(0); }
  }

  .bubble-typing {
    padding: 0.55rem 0.7rem 0.5rem !important;
    min-width: 52px;
  }

  /* ── Input bar (decorative) ───────────────────────────────────────── */
  .chat-input {
    padding: 0.55rem 0.7rem 0.7rem;
    background: #161e23;
    border-top: 1px solid rgba(255, 255, 255, 0.04);
  }
  .chat-input-pill {
    display: flex;
    align-items: center;
    gap: 0.55rem;
    padding: 0.55rem 0.85rem;
    background: #2a3942;
    border-radius: 24px;
    color: rgba(233, 237, 239, 0.55);
    font-size: 13px;
  }
  .chat-input-pill :global(svg) {
    width: 18px;
    height: 18px;
    flex: none;
  }
  .chat-input-text {
    flex: 1;
    font-style: italic;
  }
</style>
