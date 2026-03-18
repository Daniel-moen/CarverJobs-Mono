<script>
  import { onMount, tick } from 'svelte'
  import { API_BASE_URL, apiFetch } from '../../config/api'
  import { trackClick, trackChat, trackFunnel } from '../../config/analytics'

  /** @type {() => void} */
  export let onComplete

  // 0 = welcome, 1 = ai chat, 2 = tour
  let step = 0

  function goToStep(n) {
    step = n
    trackFunnel('onboard_step_reached', { value: String(n) })
  }

  // AI chat state
  let messages = []
  let inputText = ''
  let isLoading = false
  let aiError = ''
  let isDone = false
  let collectedProfile = {}
  let chatEl

  // Tour pages
  const tourPages = [
    {
      icon: '⚡',
      label: 'Auto Apply',
      desc: 'CARVER automatically matches and applies to superyacht positions on your behalf.',
    },
    {
      icon: '🛥️',
      label: 'Job Board',
      desc: 'Browse live listings — roles, vessels, compensation, and contracts at a glance.',
    },
    {
      icon: '👤',
      label: 'Profile',
      desc: 'Your Crew Profile Vault. Everything the AI just learned about you lives here.',
    },
    {
      icon: '📡',
      label: 'System Status',
      desc: 'Live health dashboard — AI, matching engine, database, and every connected service.',
    },
  ]

  // ── AI chat ──

  async function callOnboard(userMessage = '', history = null) {
    isLoading = true
    aiError = ''
    const historyPayload = history ?? messages
    try {
      const res = await apiFetch(`${API_BASE_URL}/interview/onboard`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({
          user_message: userMessage,
          history: historyPayload,
          profile: collectedProfile,
        }),
      })
      if (!res.ok) {
        if (res.status === 503) {
          aiError = 'AI not configured (OPENAI_API_KEY missing). You can skip to continue.'
        } else if (res.status === 429) {
          aiError = 'OpenAI quota exceeded. Skip to continue — you can fill your profile manually.'
        } else {
          aiError = `AI error (${res.status}). You can skip to continue.`
        }
        trackFunnel('onboard_ai_error', { value: String(res.status) })
        return
      }
      const data = await res.json()
      if (data?.message) {
        messages = [...messages, { role: 'assistant', content: data.message }]
        trackChat('receive')
      }
      mergeUpdates(data?.updates)
      if (data?.done) isDone = true
    } catch {
      aiError = 'Could not reach the AI. You can skip to continue.'
      trackFunnel('onboard_ai_error', { value: 'network' })
    } finally {
      isLoading = false
      await tick()
      scrollChat()
    }
  }

  async function sendMessage(event) {
    event?.preventDefault()
    const text = inputText.trim()
    if (!text || isLoading) return
    const historyBefore = [...messages]
    messages = [...messages, { role: 'user', content: text }]
    inputText = ''
    trackChat('send')
    await tick()
    scrollChat()
    await callOnboard(text, historyBefore)
  }

  function mergeUpdates(updates) {
    if (!updates || typeof updates !== 'object') return
    const allowed = [
      'firstName', 'lastName', 'desiredRole', 'yearsExperience', 'nationality',
      'currentLocation', 'preferredLocations', 'contractType', 'salaryMin',
      'salaryMax', 'certifications', 'languages',
    ]
    for (const key of allowed) {
      const v = updates[key]
      if (typeof v === 'string' && v.trim()) {
        collectedProfile = { ...collectedProfile, [key]: v.trim() }
      }
    }
  }

  function scrollChat() {
    if (chatEl) chatEl.scrollTop = chatEl.scrollHeight
  }

  function saveAndContinue() {
    const fieldsFilled = REQUIRED_FIELDS.length - missingFields.length
    trackClick('onboard_save_continue')
    trackFunnel('onboard_chat_skipped', { value: String(fieldsFilled) })
    try {
      localStorage.setItem('carver_profile', JSON.stringify(collectedProfile))
    } catch { /* ignore */ }
    goToStep(2)
  }

  function finish() {
    const fieldsFilled = REQUIRED_FIELDS.length - missingFields.length
    trackFunnel('onboard_complete', { value: String(fieldsFilled) })
    try {
      localStorage.setItem('carver_onboarding_complete', 'true')
    } catch { /* ignore */ }
    onComplete()
  }

  // Start chat when step transitions to 1
  $: if (step === 1 && messages.length === 0) {
    callOnboard('')
  }

  // All required fields must be present for the AI to signal done
  const REQUIRED_FIELDS = [
    'firstName', 'lastName', 'desiredRole', 'yearsExperience',
    'nationality', 'currentLocation', 'preferredLocations',
    'contractType', 'salaryMin', 'salaryMax', 'certifications', 'languages',
  ]

  $: missingFields = REQUIRED_FIELDS.filter(f => !collectedProfile[f]?.trim())
  $: allFieldsFilled = missingFields.length === 0

  onMount(() => {})
</script>

<div class="fixed inset-0 z-50 flex flex-col bg-black" style="height: 100dvh">

  <!-- Progress bar -->
  <div class="h-0.5 w-full bg-white/10">
    <div
      class="h-full bg-cyan-400 transition-all duration-500"
      style="width: {((step + 1) / 3) * 100}%"
    ></div>
  </div>

  <!-- Step dots -->
  <div class="flex items-center justify-center gap-2 pt-5">
    {#each [0, 1, 2] as i}
      <div
        class="h-1.5 rounded-full transition-all duration-300 {i === step
          ? 'w-6 bg-cyan-400'
          : i < step
          ? 'w-1.5 bg-cyan-600'
          : 'w-1.5 bg-white/20'}"
      ></div>
    {/each}
  </div>

  <div class="flex flex-1 flex-col items-center justify-center overflow-y-auto px-4 py-6 sm:py-8">

    <!-- ── STEP 0: Welcome ── -->
    {#if step === 0}
      <div class="w-full max-w-md text-center">
        <div class="mb-6 inline-flex items-center justify-center rounded-2xl border border-white/10 bg-zinc-950 p-4">
          <span class="text-4xl">🛥️</span>
        </div>
        <p class="text-xs uppercase tracking-[0.25em] text-cyan-400">Welcome aboard</p>
        <h1 class="mt-3 text-4xl font-bold tracking-tight text-white sm:text-5xl">CARVER</h1>
        <p class="mt-3 text-base text-slate-400">Automated superyacht job applications.</p>

        <p class="mt-6 text-sm leading-relaxed text-slate-300">
          Our AI will have a quick conversation with you to build your crew profile.
          Just answer naturally — it only takes a couple of minutes.
        </p>

        <button
          onclick={() => goToStep(1)}
          class="mt-8 w-full rounded-xl border border-cyan-300/40 bg-cyan-300/15 py-3 text-sm font-semibold text-cyan-100 transition hover:bg-cyan-300/25 hover:text-white"
        >
          Let's go →
        </button>

        <button
          onclick={() => { trackFunnel('onboard_skipped_setup'); finish() }}
          class="mt-3 w-full text-xs text-slate-600 underline underline-offset-2 hover:text-slate-400 transition"
        >
          Skip setup and go straight to the app
        </button>
      </div>

    <!-- ── STEP 1: AI Chat ── -->
    {:else if step === 1}
      <div
        class="flex w-full max-w-lg flex-col"
        style="height: min(600px, calc(100dvh - 120px))"
      >
        <!-- Header -->
        <div class="mb-3 flex-none">
          <div class="flex items-center gap-2">
            <div class="flex h-7 w-7 items-center justify-center rounded-full bg-cyan-400/20 text-sm">🤖</div>
            <div>
              <p class="text-sm font-semibold text-white">CARVER AI</p>
              <p class="text-xs text-slate-500">Building your crew profile</p>
            </div>
          </div>
        </div>

        <!-- Chat messages -->
        <div
          bind:this={chatEl}
          class="flex-1 overflow-y-auto rounded-xl border border-white/10 bg-zinc-950 p-4 space-y-3"
        >
          {#if isLoading && messages.length === 0}
            <div class="flex items-center gap-2 text-sm text-slate-400">
              <span class="inline-flex gap-0.5">
                <span class="inline-block h-1.5 w-1.5 animate-bounce rounded-full bg-cyan-400" style="animation-delay:0ms"></span>
                <span class="inline-block h-1.5 w-1.5 animate-bounce rounded-full bg-cyan-400" style="animation-delay:150ms"></span>
                <span class="inline-block h-1.5 w-1.5 animate-bounce rounded-full bg-cyan-400" style="animation-delay:300ms"></span>
              </span>
              <span class="text-xs text-slate-500">CARVER AI is starting…</span>
            </div>
          {/if}

          {#each messages as msg}
            <div class="flex {msg.role === 'user' ? 'justify-end' : 'justify-start'}">
              {#if msg.role === 'assistant'}
                <div class="mr-8 flex items-start gap-2">
                  <div class="mt-0.5 flex h-5 w-5 flex-none items-center justify-center rounded-full bg-cyan-400/15 text-[10px]">🤖</div>
                  <div class="rounded-2xl rounded-tl-sm border border-white/10 bg-zinc-900 px-4 py-2.5 text-sm leading-relaxed text-slate-200">
                    {msg.content}
                  </div>
                </div>
              {:else}
                <div class="ml-8 rounded-2xl rounded-tr-sm bg-cyan-300/20 px-4 py-2.5 text-sm leading-relaxed text-cyan-50">
                  {msg.content}
                </div>
              {/if}
            </div>
          {/each}

          {#if isLoading && messages.length > 0}
            <div class="flex items-start gap-2">
              <div class="mt-0.5 flex h-5 w-5 flex-none items-center justify-center rounded-full bg-cyan-400/15 text-[10px]">🤖</div>
              <div class="rounded-2xl rounded-tl-sm border border-white/10 bg-zinc-900 px-4 py-2.5">
                <span class="inline-flex gap-0.5">
                  <span class="inline-block h-1.5 w-1.5 animate-bounce rounded-full bg-slate-400" style="animation-delay:0ms"></span>
                  <span class="inline-block h-1.5 w-1.5 animate-bounce rounded-full bg-slate-400" style="animation-delay:150ms"></span>
                  <span class="inline-block h-1.5 w-1.5 animate-bounce rounded-full bg-slate-400" style="animation-delay:300ms"></span>
                </span>
              </div>
            </div>
          {/if}

          {#if aiError}
            <p class="rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
              {aiError}
            </p>
          {/if}
        </div>

        <!-- Input row -->
        {#if !isDone && !allFieldsFilled}
          <form onsubmit={sendMessage} class="mt-3 flex-none flex gap-2">
            <input
              class="flex-1 rounded-xl border border-white/15 bg-zinc-950 px-4 py-2.5 text-sm text-white outline-none ring-cyan-300/40 transition placeholder:text-slate-600 focus:border-cyan-300/40 focus:ring disabled:opacity-50"
              type="text"
              bind:value={inputText}
              placeholder="Type your reply…"
              disabled={isLoading}
            />
            <button
              type="submit"
              disabled={isLoading || !inputText.trim()}
              class="rounded-xl border border-cyan-300/40 bg-cyan-300/15 px-4 py-2.5 text-sm font-medium text-cyan-100 transition hover:bg-cyan-300/25 disabled:cursor-not-allowed disabled:opacity-40"
            >
              Send
            </button>
          </form>
        {/if}

        <!-- Progress indicator -->
        {#if messages.length > 0 && !isDone}
          <div class="mt-3 flex-none">
            <div class="flex items-center justify-between mb-1">
              <span class="text-xs text-slate-600">Profile completion</span>
              <span class="text-xs text-slate-500">{REQUIRED_FIELDS.length - missingFields.length} / {REQUIRED_FIELDS.length}</span>
            </div>
            <div class="h-0.5 w-full rounded-full bg-white/10">
              <div
                class="h-full rounded-full bg-cyan-500 transition-all duration-500"
                style="width: {((REQUIRED_FIELDS.length - missingFields.length) / REQUIRED_FIELDS.length) * 100}%"
              ></div>
            </div>
          </div>
        {/if}

        <!-- Bottom bar -->
        <div class="mt-3 flex-none flex items-center justify-between">
          <button
            onclick={() => saveAndContinue()}
            class="text-xs text-slate-600 underline underline-offset-2 hover:text-slate-400 transition"
          >
            Skip
          </button>
          {#if isDone || allFieldsFilled}
            <button
              onclick={() => saveAndContinue()}
              class="rounded-xl border border-cyan-300/40 bg-cyan-300/15 px-5 py-2 text-sm font-semibold text-cyan-100 transition hover:bg-cyan-300/25 hover:text-white"
            >
              Continue →
            </button>
          {/if}
        </div>
      </div>

    <!-- ── STEP 2: Tour ── -->
    {:else if step === 2}
      <div class="w-full max-w-md">
        <p class="text-xs uppercase tracking-[0.2em] text-cyan-400">You're all set</p>
        <h2 class="mt-3 text-2xl font-semibold text-white">
          {collectedProfile.firstName ? `Welcome, ${collectedProfile.firstName}` : 'Welcome to CARVER'} 👋
        </h2>
        <p class="mt-1.5 text-sm text-slate-400">
          Your profile has been saved. Here's a quick look at what's waiting for you.
        </p>

        <div class="mt-6 grid gap-3">
          {#each tourPages as page}
            <div class="flex items-start gap-4 rounded-xl border border-white/10 bg-zinc-950 px-4 py-4 transition hover:border-white/20">
              <span class="mt-0.5 text-2xl">{page.icon}</span>
              <div>
                <p class="text-sm font-semibold text-white">{page.label}</p>
                <p class="mt-0.5 text-xs leading-relaxed text-slate-400">{page.desc}</p>
              </div>
            </div>
          {/each}
        </div>

        <button
          onclick={() => finish()}
          class="mt-8 w-full rounded-xl border border-cyan-300/40 bg-cyan-300/15 py-3 text-sm font-semibold text-cyan-100 transition hover:bg-cyan-300/25 hover:text-white"
        >
          Start Using CARVER →
        </button>
      </div>
    {/if}

  </div>
</div>
