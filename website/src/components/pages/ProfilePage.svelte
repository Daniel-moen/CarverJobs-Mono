<script>
  import { onMount, tick } from 'svelte'
  import { API_BASE_URL, apiFetch } from '../../config/api'
  import { trackClick, trackChat } from '../../config/analytics'

  const contractOptions = ['Permanent', 'Seasonal', 'Rotational', 'Temporary']
  const DOC_LABELS = { cv: 'CV', references: 'References', passport: 'Passport', stcw: 'STCW', eng1: 'ENG1' }

  let mounted = $state(false)
  let loadError = $state('')

  let uploadedDocs = $state({ cv: null, references: null, passport: null, stcw: null, eng1: null, photo: null })
  let uploadingDoc = $state('')
  let uploadError = $state('')

  let profile = $state({
    firstName: '', lastName: '', sex: '', phone: '',
    nationality: '', currentLocation: '', desiredRole: '',
    contractType: '', preferredLocations: '', rotationPreference: '',
    yearsExperience: '', availableFrom: '', salaryMin: '', salaryMax: '',
    certifications: '', languages: '', bio: '',
    interviewCompleted: false,
  })

  let profileSlug = $state('')
  let isSaving = $state(false)
  let saveMessage = $state('')
  let shareUrl = $derived(profileSlug ? `${window.location.origin}/crew/${profileSlug}` : '')
  let copiedLink = $state(false)

  let jobHistory = $state([])
  let jobHistoryLoading = $state(false)
  let showJobForm = $state(false)
  let editingJobId = $state(null)
  let jobForm = $state({ yacht_name: '', yacht_type: '', role: '', start_date: '', end_date: '', description: '' })
  let jobFormError = $state('')

  let photoPreviewUrl = $state('')

  let interviewOpen = $state(false)
  let interviewMessages = $state([])
  let interviewInput = $state('')
  let interviewLoading = $state(false)
  let interviewError = $state('')
  let chatEl = $state(null)

  // Active tab for mobile
  let activeTab = $state('personal')

  onMount(async () => {
    try {
      const saved = localStorage.getItem('carver_profile')
      if (saved) {
        const parsed = JSON.parse(saved)
        const stringFields = [
          'firstName','lastName','sex','nationality','currentLocation','desiredRole',
          'contractType','preferredLocations','rotationPreference','yearsExperience',
          'availableFrom','salaryMin','salaryMax','certifications','languages','bio',
        ]
        for (const key of stringFields) {
          if (typeof parsed[key] === 'string' && parsed[key].trim()) profile[key] = parsed[key]
        }
        if (parsed.interviewCompleted) profile.interviewCompleted = true
      }
    } catch { /* localStorage unavailable */ }
    await Promise.all([loadServerProfile(), loadUploadedDocs(), loadJobHistory()])
    requestAnimationFrame(() => (mounted = true))
  })

  async function loadServerProfile() {
    try {
      const res = await apiFetch(`${API_BASE_URL}/profile/me`, { credentials: 'include' })
      if (!res.ok) return
      const data = await res.json()
      if (!data.profile) return
      profileSlug = data.profile.profile_slug ?? ''
      const fieldMap = {
        first_name: 'firstName', last_name: 'lastName', sex: 'sex', phone: 'phone',
        nationality: 'nationality', current_location: 'currentLocation',
        desired_role: 'desiredRole', contract_type: 'contractType',
        preferred_locations: 'preferredLocations', rotation_preference: 'rotationPreference',
        years_experience: 'yearsExperience', available_from: 'availableFrom',
        salary_min: 'salaryMin', salary_max: 'salaryMax',
        certifications: 'certifications', languages: 'languages', bio: 'bio',
      }
      for (const [serverKey, clientKey] of Object.entries(fieldMap)) {
        const val = data.profile[serverKey]
        if (typeof val === 'string' && val.trim()) profile[clientKey] = val
      }
    } catch {
      loadError = 'Could not load profile from server.'
    }
  }

  async function loadUploadedDocs() {
    try {
      const res = await apiFetch(`${API_BASE_URL}/documents`, { credentials: 'include' })
      if (!res.ok) return
      const data = await res.json()
      uploadedDocs = { cv: data.cv ?? null, references: data.references ?? null, passport: data.passport ?? null, stcw: data.stcw ?? null, eng1: data.eng1 ?? null, photo: data.photo ?? null }
      if (data.photo) await loadPhotoBlob()
    } catch { /* ignore */ }
  }

  async function loadPhotoBlob() {
    try {
      const res = await apiFetch(`${API_BASE_URL}/documents/photo/file`, { credentials: 'include' })
      if (res.ok) {
        const blob = await res.blob()
        photoPreviewUrl = URL.createObjectURL(blob)
      }
    } catch { /* ignore */ }
  }

  async function loadJobHistory() {
    try {
      const res = await apiFetch(`${API_BASE_URL}/job-history`, { credentials: 'include' })
      if (res.ok) jobHistory = await res.json()
    } catch { /* ignore */ }
  }

  async function handleFileSelect(event, docType) {
    const file = event.target.files?.[0]
    if (!file) return
    trackClick(`doc_upload_${docType}`)
    uploadError = ''
    uploadingDoc = docType
    try {
      const form = new FormData()
      form.append('file', file)
      const res = await apiFetch(`${API_BASE_URL}/documents/${docType}`, { method: 'POST', credentials: 'include', body: form })
      if (!res.ok) {
        const err = await res.json().catch(() => ({}))
        uploadError = err.detail ?? `Upload failed (${res.status})`
      } else {
        const data = await res.json()
        uploadedDocs = { ...uploadedDocs, [docType]: { original_name: data.original_name } }
      }
    } catch {
      uploadError = 'Could not reach server.'
    } finally {
      uploadingDoc = ''
      event.target.value = ''
    }
  }

  async function removeDoc(docType) {
    trackClick(`doc_remove_${docType}`)
    uploadError = ''
    try {
      const res = await apiFetch(`${API_BASE_URL}/documents/${docType}`, { method: 'DELETE', credentials: 'include' })
      if (res.ok) uploadedDocs = { ...uploadedDocs, [docType]: null }
      else {
        const err = await res.json().catch(() => ({}))
        uploadError = err.detail ?? 'Delete failed.'
      }
    } catch { uploadError = 'Could not reach server.' }
  }

  async function handlePhotoSelect(event) {
    const file = event.target.files?.[0]
    if (!file) return
    trackClick('doc_upload_photo')
    uploadError = ''
    uploadingDoc = 'photo'
    try {
      const form = new FormData()
      form.append('file', file)
      const res = await apiFetch(`${API_BASE_URL}/documents/photo`, { method: 'POST', credentials: 'include', body: form })
      if (!res.ok) {
        const err = await res.json().catch(() => ({}))
        uploadError = err.detail ?? `Upload failed (${res.status})`
      } else {
        const data = await res.json()
        uploadedDocs = { ...uploadedDocs, photo: { original_name: data.original_name } }
        await loadPhotoBlob()
      }
    } catch { uploadError = 'Could not reach server.' }
    finally { uploadingDoc = ''; event.target.value = '' }
  }

  async function removePhoto() {
    trackClick('doc_remove_photo')
    uploadError = ''
    try {
      const res = await apiFetch(`${API_BASE_URL}/documents/photo`, { method: 'DELETE', credentials: 'include' })
      if (res.ok) { uploadedDocs = { ...uploadedDocs, photo: null }; photoPreviewUrl = '' }
    } catch { /* ignore */ }
  }

  async function saveProfile() {
    isSaving = true
    saveMessage = ''
    trackClick('save_profile')
    try {
      const body = {
        first_name: profile.firstName || null,
        last_name: profile.lastName || null,
        sex: profile.sex || null,
        phone: profile.phone || null,
        nationality: profile.nationality || null,
        current_location: profile.currentLocation || null,
        desired_role: profile.desiredRole || null,
        contract_type: profile.contractType || null,
        preferred_locations: profile.preferredLocations || null,
        rotation_preference: profile.rotationPreference || null,
        years_experience: profile.yearsExperience || null,
        available_from: profile.availableFrom || null,
        salary_min: profile.salaryMin || null,
        salary_max: profile.salaryMax || null,
        certifications: profile.certifications || null,
        languages: profile.languages || null,
        bio: profile.bio || null,
      }
      const res = await apiFetch(`${API_BASE_URL}/profile/save`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        credentials: 'include', body: JSON.stringify(body),
      })
      if (res.ok) {
        const data = await res.json()
        profileSlug = data.profile_slug ?? profileSlug
        saveMessage = 'Profile saved.'
        try { localStorage.setItem('carver_profile', JSON.stringify(profile)) } catch { /* ignore */ }
      } else {
        const err = await res.json().catch(() => ({}))
        saveMessage = err.detail ?? 'Save failed.'
      }
    } catch { saveMessage = 'Could not reach server.' }
    finally { isSaving = false; setTimeout(() => (saveMessage = ''), 4000) }
  }

  async function copyShareLink() {
    if (!shareUrl) return
    try {
      await navigator.clipboard.writeText(shareUrl)
      copiedLink = true
      setTimeout(() => (copiedLink = false), 2000)
    } catch { /* clipboard not available */ }
  }

  // ── Job history ──
  function resetJobForm() {
    jobForm = { yacht_name: '', yacht_type: '', role: '', start_date: '', end_date: '', description: '' }
    editingJobId = null
    showJobForm = false
    jobFormError = ''
  }

  function editJob(entry) {
    jobForm = {
      yacht_name: entry.yacht_name ?? '', yacht_type: entry.yacht_type ?? '',
      role: entry.role ?? '', start_date: entry.start_date ?? '',
      end_date: entry.end_date ?? '', description: entry.description ?? '',
    }
    editingJobId = entry.id
    showJobForm = true
  }

  async function submitJobForm(event) {
    event.preventDefault()
    if (!jobForm.yacht_name.trim() || !jobForm.role.trim()) {
      jobFormError = 'Yacht name and role are required.'
      return
    }
    jobHistoryLoading = true
    jobFormError = ''
    try {
      const body = {
        yacht_name: jobForm.yacht_name.trim(), yacht_type: jobForm.yacht_type.trim() || null,
        role: jobForm.role.trim(), start_date: jobForm.start_date.trim() || null,
        end_date: jobForm.end_date.trim() || null, description: jobForm.description.trim() || null,
      }
      const url = editingJobId ? `${API_BASE_URL}/job-history/${editingJobId}` : `${API_BASE_URL}/job-history`
      const method = editingJobId ? 'PATCH' : 'POST'
      const res = await apiFetch(url, {
        method, headers: { 'Content-Type': 'application/json' },
        credentials: 'include', body: JSON.stringify(body),
      })
      if (res.ok) { await loadJobHistory(); resetJobForm() }
      else {
        const err = await res.json().catch(() => ({}))
        jobFormError = err.detail ?? 'Could not save entry.'
      }
    } catch { jobFormError = 'Could not reach server.' }
    finally { jobHistoryLoading = false }
  }

  async function deleteJob(id) {
    jobHistoryLoading = true
    try {
      const res = await apiFetch(`${API_BASE_URL}/job-history/${id}`, { method: 'DELETE', credentials: 'include' })
      if (res.ok) jobHistory = jobHistory.filter(j => j.id !== id)
    } catch { /* ignore */ }
    finally { jobHistoryLoading = false }
  }

  // ── AI Interview ──
  function buildInterviewProfilePayload() {
    return {
      sex: profile.sex, desiredRole: profile.desiredRole, contractType: profile.contractType,
      preferredLocations: profile.preferredLocations, rotationPreference: profile.rotationPreference,
      availableFrom: profile.availableFrom, salaryMin: profile.salaryMin, salaryMax: profile.salaryMax,
      yearsExperience: profile.yearsExperience, languages: profile.languages,
      certifications: profile.certifications, currentLocation: profile.currentLocation,
    }
  }

  function mergeSuggestedUpdates(updates) {
    if (!updates || typeof updates !== 'object') return
    const allowedKeys = ['sex','desiredRole','preferredLocations','contractType','rotationPreference','availableFrom','salaryMin','salaryMax','languages','certifications','bio']
    const clean = {}
    for (const key of allowedKeys) {
      const value = updates[key]
      if (typeof value === 'string' && value.trim()) clean[key] = value.trim()
    }
    if (Object.keys(clean).length > 0) profile = { ...profile, ...clean, interviewCompleted: true }
  }

  async function scrollChat() {
    await tick()
    if (chatEl) chatEl.scrollTop = chatEl.scrollHeight
  }

  async function requestAITurn(userMessage = '', history = null) {
    interviewLoading = true
    interviewError = ''
    await scrollChat()
    const historyPayload = history ?? interviewMessages
    try {
      const response = await apiFetch(`${API_BASE_URL}/interview/next`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, credentials: 'include',
        body: JSON.stringify({ user_message: userMessage, history: historyPayload, profile: buildInterviewProfilePayload() }),
      })
      if (!response.ok) {
        if (response.status === 503) interviewError = 'AI interview is not configured yet.'
        else if (response.status === 429) interviewError = 'Rate limit — try again shortly.'
        else {
          let detail = ''
          try { detail = (await response.json()).detail ?? '' } catch { /* ignore */ }
          interviewError = detail || `Interview error (${response.status}).`
        }
        return
      }
      const data = await response.json()
      const message = typeof data?.message === 'string' && data.message.trim() ? data.message.trim() : ''
      if (message) {
        interviewMessages = [...interviewMessages, { role: 'assistant', content: message }]
        trackChat('receive')
      }
      mergeSuggestedUpdates(data?.updates)
    } catch { interviewError = 'Could not reach interview service.' }
    finally {
      interviewLoading = false
      await scrollChat()
    }
  }

  async function openInterview() {
    trackClick('open_interview')
    interviewOpen = true
    interviewError = ''
    if (interviewMessages.length === 0) await requestAITurn('')
  }

  async function sendInterviewMessage(event) {
    event.preventDefault()
    const message = interviewInput.trim()
    if (!message || interviewLoading) return
    trackChat('send')
    const historyBeforeSend = [...interviewMessages]
    interviewMessages = [...interviewMessages, { role: 'user', content: message }]
    interviewInput = ''
    await scrollChat()
    await requestAITurn(message, historyBeforeSend)
  }

  // ── Completion checklist ──
  const checklist = $derived([
    { label: 'Name + surname', done: Boolean(profile.firstName && profile.lastName) },
    { label: 'Phone number', done: Boolean(profile.phone) },
    { label: 'Career preferences', done: Boolean(profile.desiredRole && profile.contractType && profile.preferredLocations) },
    { label: 'Required docs', done: Boolean(uploadedDocs.passport && uploadedDocs.stcw && uploadedDocs.eng1) },
    { label: 'AI interview', done: Boolean(profile.interviewCompleted) },
  ])
  const completedItems = $derived(checklist.filter(i => i.done).length)
  const completionPercent = $derived(Math.round((completedItems / checklist.length) * 100))
</script>

<section class="grid gap-4 sm:gap-5">
  <!-- ── Header ── -->
  <header class="profile-section relative overflow-hidden rounded-2xl border border-white/8 bg-zinc-950 p-4 sm:p-6" class:visible={mounted}>
    <div class="pointer-events-none absolute -right-12 -top-12 h-40 w-40 rounded-full bg-cyan-400/8 blur-3xl hidden sm:block"></div>

    <div class="relative flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
      <div class="flex items-center gap-4">
        <!-- Photo -->
        <div class="relative h-14 w-14 flex-none overflow-hidden rounded-full border-2 {uploadedDocs.photo ? 'border-cyan-400/30' : 'border-white/10'} bg-black/40 sm:h-16 sm:w-16">
          {#if photoPreviewUrl}
            <img src={photoPreviewUrl} alt="Profile" class="h-full w-full object-cover" />
          {:else}
            <div class="flex h-full w-full items-center justify-center text-lg text-slate-600">
              {profile.firstName?.[0]?.toUpperCase() ?? '?'}{profile.lastName?.[0]?.toUpperCase() ?? ''}
            </div>
          {/if}
        </div>
        <div>
          <h1 class="text-xl font-bold text-white sm:text-2xl">
            {profile.firstName || profile.lastName ? `${profile.firstName} ${profile.lastName}`.trim() : 'Your Profile'}
          </h1>
          <p class="mt-0.5 text-xs text-slate-500">
            {profile.desiredRole || 'Set up your crew profile to start matching.'}
          </p>
        </div>
      </div>

      <div class="flex flex-wrap items-center gap-2">
        <label class="contents">
          <input type="file" class="hidden" accept=".jpg,.jpeg,.png" disabled={uploadingDoc === 'photo'} onchange={handlePhotoSelect} />
          <span class="inline-block cursor-pointer rounded-lg border border-white/10 px-3 py-1.5 text-[11px] font-medium text-slate-400 transition hover:border-white/20 hover:text-white {uploadingDoc === 'photo' ? 'cursor-not-allowed opacity-40' : ''}">
            {uploadingDoc === 'photo' ? 'Uploading...' : uploadedDocs.photo ? 'Change Photo' : 'Add Photo'}
          </span>
        </label>
        {#if uploadedDocs.photo}
          <button type="button" class="text-[10px] text-slate-600 hover:text-rose-300" onclick={removePhoto}>Remove</button>
        {/if}
        {#if shareUrl}
          <button type="button" onclick={copyShareLink}
            class="rounded-lg border border-white/10 px-3 py-1.5 text-[11px] font-medium text-slate-400 transition hover:border-white/20 hover:text-white">
            {copiedLink ? 'Copied!' : 'Share'}
          </button>
        {/if}
        <button type="button" onclick={openInterview}
          class="rounded-lg border border-cyan-300/25 bg-cyan-400/8 px-3 py-1.5 text-[11px] font-bold text-cyan-300 transition hover:border-cyan-300/45 hover:bg-cyan-400/15 hover:text-white">
          <span class="flex items-center gap-1.5">
            <span class="h-1.5 w-1.5 rounded-full bg-cyan-400 hidden sm:inline-block sm:animate-pulse"></span>
            AI Interview
          </span>
        </button>
        <button type="button" onclick={saveProfile} disabled={isSaving}
          class="rounded-lg border border-emerald-300/25 bg-emerald-400/8 px-4 py-1.5 text-[11px] font-bold text-emerald-300 transition hover:border-emerald-300/45 hover:bg-emerald-400/15 hover:text-white disabled:opacity-50">
          {isSaving ? 'Saving...' : 'Save'}
        </button>
      </div>
    </div>

    {#if saveMessage}
      <p class="relative mt-3 text-xs {saveMessage === 'Profile saved.' ? 'text-emerald-400' : 'text-rose-300'}">{saveMessage}</p>
    {/if}
    {#if loadError}
      <p class="relative mt-3 text-xs text-amber-300">{loadError}</p>
    {/if}
  </header>

  <!-- ── Completion bar ── -->
  <div class="profile-section rounded-2xl border border-white/8 bg-zinc-950 p-4 sm:p-5" class:visible={mounted} style="--delay:40ms;">
    <div class="flex items-center justify-between gap-3">
      <p class="text-[10px] font-bold uppercase tracking-[0.2em] text-slate-500">Completion</p>
      <p class="text-sm font-bold text-white">{completionPercent}%</p>
    </div>
    <div class="mt-2.5 h-1.5 overflow-hidden rounded-full bg-white/8">
      <div class="h-full rounded-full transition-all duration-700" style="width:{completionPercent}%; background:linear-gradient(90deg,#22d3ee,#38bdf8);"></div>
    </div>
    <div class="mt-3 flex flex-wrap gap-2">
      {#each checklist as item}
        <span class="inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[10px] {item.done ? 'border-emerald-400/20 bg-emerald-400/5 text-emerald-300' : 'border-white/6 text-slate-600'}">
          <span class="h-1 w-1 rounded-full {item.done ? 'bg-emerald-400' : 'bg-slate-700'}"></span>
          {item.label}
        </span>
      {/each}
    </div>
  </div>

  <!-- ── Tab nav (mobile) ── -->
  <nav class="flex gap-1 overflow-x-auto rounded-xl border border-white/8 bg-zinc-950 p-1 sm:hidden">
    {#each [['personal', 'Personal'], ['career', 'Career'], ['docs', 'Docs'], ['history', 'History']] as [key, label]}
      <button type="button" onclick={() => (activeTab = key)}
        class="flex-1 whitespace-nowrap rounded-lg px-3 py-2 text-xs font-medium transition {activeTab === key ? 'bg-white/10 text-white' : 'text-slate-500 hover:text-slate-300'}">
        {label}
      </button>
    {/each}
  </nav>

  <!-- ── Personal Info + Career Prefs ── -->
  <div class="grid gap-4 sm:gap-5 lg:grid-cols-2">
    <article class="profile-section rounded-2xl border border-white/8 bg-zinc-950 p-4 sm:p-5 {activeTab !== 'personal' ? 'hidden sm:block' : ''}" class:visible={mounted} style="--delay:80ms;">
      <p class="text-[10px] font-bold uppercase tracking-[0.2em] text-slate-500">Personal Information</p>
      <div class="mt-4 grid gap-3 sm:grid-cols-2">
        <label class="field-group">
          <span class="field-lbl">First name</span>
          <input class="field-inp" bind:value={profile.firstName} placeholder="James" />
        </label>
        <label class="field-group">
          <span class="field-lbl">Last name</span>
          <input class="field-inp" bind:value={profile.lastName} placeholder="Carter" />
        </label>
        <label class="field-group">
          <span class="field-lbl">Gender</span>
          <select class="field-inp" bind:value={profile.sex}>
            <option value="">Select...</option>
            <option value="male">Male</option>
            <option value="female">Female</option>
            <option value="other">Other</option>
            <option value="prefer_not_to_say">Prefer not to say</option>
          </select>
        </label>
        <label class="field-group">
          <span class="field-lbl">Phone</span>
          <input type="tel" class="field-inp" bind:value={profile.phone} placeholder="+44 7700 900000" />
        </label>
        <label class="field-group">
          <span class="field-lbl">Nationality</span>
          <input class="field-inp" bind:value={profile.nationality} placeholder="British" />
        </label>
        <label class="field-group sm:col-span-2">
          <span class="field-lbl">Current location</span>
          <input class="field-inp" bind:value={profile.currentLocation} placeholder="Monaco" />
        </label>
      </div>
    </article>

    <article class="profile-section rounded-2xl border border-white/8 bg-zinc-950 p-4 sm:p-5 {activeTab !== 'career' ? 'hidden sm:block' : ''}" class:visible={mounted} style="--delay:120ms;">
      <p class="text-[10px] font-bold uppercase tracking-[0.2em] text-slate-500">Career Preferences</p>
      <div class="mt-4 grid gap-3 sm:grid-cols-2">
        <label class="field-group">
          <span class="field-lbl">Desired role</span>
          <input class="field-inp" bind:value={profile.desiredRole} placeholder="Chief Officer" />
        </label>
        <label class="field-group">
          <span class="field-lbl">Contract type</span>
          <select class="field-inp" bind:value={profile.contractType}>
            <option value="">Select...</option>
            {#each contractOptions as opt}<option value={opt}>{opt}</option>{/each}
          </select>
        </label>
        <label class="field-group sm:col-span-2">
          <span class="field-lbl">Preferred locations</span>
          <input class="field-inp" bind:value={profile.preferredLocations} placeholder="Mediterranean, Caribbean" />
        </label>
        <label class="field-group">
          <span class="field-lbl">Rotation</span>
          <input class="field-inp" bind:value={profile.rotationPreference} placeholder="3/3 months" />
        </label>
        <label class="field-group">
          <span class="field-lbl">Years experience</span>
          <input type="number" min="0" class="field-inp" bind:value={profile.yearsExperience} placeholder="5" />
        </label>
        <label class="field-group">
          <span class="field-lbl">Available from</span>
          <input class="field-inp" bind:value={profile.availableFrom} placeholder="Immediately" />
        </label>
        <label class="field-group">
          <span class="field-lbl">Salary range (EUR/mo)</span>
          <div class="flex items-center gap-1.5">
            <input type="number" min="0" class="field-inp" bind:value={profile.salaryMin} placeholder="Min" />
            <span class="text-slate-600">-</span>
            <input type="number" min="0" class="field-inp" bind:value={profile.salaryMax} placeholder="Max" />
          </div>
        </label>
      </div>
    </article>
  </div>

  <!-- ── Documents ── -->
  <article class="profile-section rounded-2xl border border-white/8 bg-zinc-950 p-4 sm:p-5 {activeTab !== 'docs' ? 'hidden sm:block' : ''}" class:visible={mounted} style="--delay:160ms;">
    <p class="text-[10px] font-bold uppercase tracking-[0.2em] text-slate-500">Documents & Qualifications</p>
    <p class="mt-1 text-xs text-slate-600">Upload once — CARVER attaches them on every application.</p>

    {#if uploadError}
      <p class="mt-3 rounded-lg border border-rose-400/20 bg-rose-400/8 px-3 py-2 text-xs text-rose-300">{uploadError}</p>
    {/if}

    <div class="mt-4 grid gap-2 sm:grid-cols-2 lg:grid-cols-5">
      {#each Object.entries(DOC_LABELS) as [docType, label]}
        {@const uploaded = uploadedDocs[docType]}
        {@const isUploading = uploadingDoc === docType}
        <div class="flex items-center justify-between gap-2 rounded-xl border px-3 py-2.5 {uploaded ? 'border-emerald-400/18 bg-emerald-400/5' : 'border-white/6 bg-black/20'}">
          <div class="flex items-center gap-2 min-w-0">
            <span class="flex h-5 w-5 flex-none items-center justify-center rounded-full text-[10px] {uploaded ? 'bg-emerald-400/20 text-emerald-300' : 'bg-white/8 text-slate-700'}">
              {uploaded ? '✓' : '·'}
            </span>
            <div class="min-w-0">
              <p class="text-xs font-medium {uploaded ? 'text-emerald-200' : 'text-slate-400'}">{label}</p>
              {#if uploaded}
                <p class="truncate text-[10px] text-slate-600" title={uploaded.original_name}>{uploaded.original_name}</p>
              {/if}
            </div>
          </div>
          {#if uploaded}
            <button type="button" class="flex-none text-[10px] text-slate-600 hover:text-rose-300" onclick={() => removeDoc(docType)}>Remove</button>
          {:else}
            <label class="flex-none">
              <input type="file" class="hidden" accept=".pdf,.doc,.docx,.jpg,.jpeg,.png" disabled={isUploading} onchange={(e) => handleFileSelect(e, docType)} />
              <span class="cursor-pointer rounded-lg border border-white/10 px-2 py-1 text-[10px] font-medium text-slate-400 transition hover:border-cyan-400/30 hover:text-cyan-300 {isUploading ? 'cursor-not-allowed opacity-40' : ''}">
                {isUploading ? 'Uploading...' : 'Upload'}
              </span>
            </label>
          {/if}
        </div>
      {/each}
    </div>

    <div class="mt-4 grid gap-3">
      <label class="field-group">
        <span class="field-lbl">Certifications</span>
        <textarea rows="2" class="field-inp resize-none" bind:value={profile.certifications} placeholder="STCW, ENG1, OOW, etc."></textarea>
      </label>
      <div class="grid gap-3 sm:grid-cols-2">
        <label class="field-group">
          <span class="field-lbl">Languages</span>
          <input class="field-inp" bind:value={profile.languages} placeholder="English, Spanish" />
        </label>
        <label class="field-group">
          <span class="field-lbl">Short bio</span>
          <textarea rows="2" class="field-inp resize-none" bind:value={profile.bio} placeholder="Brief professional summary..."></textarea>
        </label>
      </div>
    </div>
  </article>

  <!-- ── Job History ── -->
  <article class="profile-section rounded-2xl border border-white/8 bg-zinc-950 p-4 sm:p-5 {activeTab !== 'history' ? 'hidden sm:block' : ''}" class:visible={mounted} style="--delay:200ms;">
    <div class="flex items-center justify-between gap-3">
      <div>
        <p class="text-[10px] font-bold uppercase tracking-[0.2em] text-slate-500">Job History</p>
        <p class="mt-1 text-xs text-slate-600">Your recent yachting positions.</p>
      </div>
      {#if !showJobForm}
        <button type="button" onclick={() => { resetJobForm(); showJobForm = true }}
          class="flex-none rounded-lg border border-cyan-300/25 bg-cyan-400/8 px-3 py-1.5 text-[11px] font-bold text-cyan-300 transition hover:border-cyan-300/45 hover:bg-cyan-400/15 hover:text-white">
          + Add
        </button>
      {/if}
    </div>

    {#if showJobForm}
      <form class="mt-4 grid gap-3 rounded-xl border border-white/8 bg-black/20 p-4" onsubmit={submitJobForm}>
        <div class="grid gap-3 sm:grid-cols-2">
          <label class="field-group">
            <span class="field-lbl">Yacht name *</span>
            <input class="field-inp" bind:value={jobForm.yacht_name} placeholder="M/Y Example" required />
          </label>
          <label class="field-group">
            <span class="field-lbl">Yacht type</span>
            <input class="field-inp" bind:value={jobForm.yacht_type} placeholder="Motor, Sail" />
          </label>
          <label class="field-group">
            <span class="field-lbl">Role *</span>
            <input class="field-inp" bind:value={jobForm.role} placeholder="Chief Officer" required />
          </label>
          <label class="field-group">
            <span class="field-lbl">Start date</span>
            <input class="field-inp" bind:value={jobForm.start_date} placeholder="Mar 2024" />
          </label>
          <label class="field-group">
            <span class="field-lbl">End date</span>
            <input class="field-inp" bind:value={jobForm.end_date} placeholder="Present" />
          </label>
        </div>
        <label class="field-group">
          <span class="field-lbl">Description</span>
          <textarea rows="2" class="field-inp resize-none" bind:value={jobForm.description} placeholder="Key responsibilities..."></textarea>
        </label>
        {#if jobFormError}
          <p class="rounded-lg border border-rose-400/20 bg-rose-400/8 px-3 py-2 text-xs text-rose-300">{jobFormError}</p>
        {/if}
        <div class="flex items-center gap-2">
          <button type="submit" disabled={jobHistoryLoading}
            class="rounded-lg border border-cyan-300/30 bg-cyan-300/10 px-4 py-2 text-xs font-medium text-cyan-200 transition hover:bg-cyan-300/20 hover:text-white disabled:opacity-50">
            {jobHistoryLoading ? 'Saving...' : editingJobId ? 'Update' : 'Add'}
          </button>
          <button type="button" onclick={resetJobForm}
            class="rounded-lg border border-white/10 px-4 py-2 text-xs text-slate-400 transition hover:border-white/20 hover:text-white">
            Cancel
          </button>
        </div>
      </form>
    {/if}

    {#if jobHistory.length > 0}
      <div class="mt-4 grid gap-2">
        {#each jobHistory as entry}
          <div class="flex items-start gap-3 rounded-xl border border-white/6 bg-black/20 px-3 py-2.5 sm:px-4 sm:py-3">
            <div class="mt-1 h-1.5 w-1.5 flex-none rounded-full bg-cyan-400/40"></div>
            <div class="min-w-0 flex-1">
              <p class="text-sm font-medium text-white">{entry.role} <span class="text-slate-500">on</span> <span class="text-cyan-200">{entry.yacht_name}</span></p>
              {#if entry.start_date || entry.end_date}
                <p class="mt-0.5 text-[11px] text-slate-500">{entry.start_date ?? '?'} — {entry.end_date ?? 'Present'}</p>
              {/if}
              {#if entry.description}
                <p class="mt-1 text-xs leading-relaxed text-slate-400">{entry.description}</p>
              {/if}
            </div>
            <div class="flex flex-none gap-1">
              <button type="button" class="rounded px-1.5 py-0.5 text-[10px] text-slate-600 hover:text-cyan-300" onclick={() => editJob(entry)}>Edit</button>
              <button type="button" class="rounded px-1.5 py-0.5 text-[10px] text-slate-600 hover:text-rose-300" onclick={() => deleteJob(entry.id)}>Del</button>
            </div>
          </div>
        {/each}
      </div>
    {:else if !showJobForm}
      <p class="mt-4 text-center text-xs text-slate-600">No positions added yet.</p>
    {/if}
  </article>
</section>

<!-- ── AI Interview Modal ── -->
{#if interviewOpen}
  <div class="interview-overlay fixed inset-0 z-40 flex items-end justify-center sm:items-center sm:p-4">
    <article class="interview-modal flex w-full flex-col overflow-hidden border-cyan-400/20 bg-zinc-950 sm:max-w-xl sm:rounded-2xl sm:border sm:shadow-[0_0_60px_rgba(34,211,238,0.15)]" style="height:100dvh; max-height:100dvh;" class:sm-modal={true}>
      <div class="flex flex-none items-center justify-between gap-3 border-b border-white/6 px-4 py-3 sm:px-5 sm:py-4">
        <div class="flex items-center gap-2">
          <span class="h-1.5 w-1.5 rounded-full bg-cyan-400"></span>
          <h3 class="text-sm font-bold text-white">AI Interview</h3>
        </div>
        <button type="button" class="rounded-lg border border-white/10 px-3 py-1 text-xs text-slate-400 transition hover:text-white" onclick={() => (interviewOpen = false)}>Close</button>
      </div>

      <div bind:this={chatEl} class="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto overscroll-contain p-4">
        {#if interviewMessages.length === 0 && interviewLoading}
          <div class="flex items-center gap-2 text-xs text-slate-500">
            <span class="h-1.5 w-1.5 rounded-full bg-cyan-400 interview-pulse"></span>
            Starting interview...
          </div>
        {:else}
          {#each interviewMessages as message}
            <div class="max-w-[88%] rounded-xl px-3.5 py-2.5 text-sm leading-relaxed {message.role === 'assistant'
              ? 'border border-cyan-400/15 bg-cyan-400/8 text-cyan-100'
              : 'ml-auto border border-white/10 bg-white/8 text-slate-100'}">
              {message.content}
            </div>
          {/each}
          {#if interviewLoading}
            <div class="flex items-center gap-2 text-xs text-slate-600">
              <span class="h-1.5 w-1.5 rounded-full bg-cyan-400/50 interview-pulse"></span>
              Thinking...
            </div>
          {/if}
        {/if}
      </div>

      {#if interviewError}
        <p class="mx-4 mb-2 rounded-lg border border-rose-400/20 bg-rose-400/8 px-3 py-2 text-xs text-rose-300">{interviewError}</p>
      {/if}

      <form class="flex flex-none gap-2 border-t border-white/6 p-3 sm:p-4" onsubmit={sendInterviewMessage}>
        <input
          class="flex-1 rounded-lg border border-white/10 bg-black/40 px-3 py-2 text-sm text-white outline-none placeholder:text-slate-600 focus:border-cyan-400/30"
          placeholder="Type your answer..."
          bind:value={interviewInput}
          disabled={interviewLoading}
        />
        <button type="submit" disabled={interviewLoading}
          class="rounded-lg border border-cyan-300/30 bg-cyan-300/10 px-4 py-2 text-sm font-medium text-cyan-200 transition hover:bg-cyan-300/20 hover:text-white disabled:opacity-50">
          Send
        </button>
      </form>

      <div class="flex flex-none justify-end border-t border-white/4 px-4 py-2">
        <button type="button" class="text-[10px] text-slate-600 transition hover:text-slate-400"
          onclick={() => { interviewMessages = []; interviewInput = ''; interviewError = '' }}>
          Reset
        </button>
      </div>
    </article>
  </div>
{/if}

<style>
  .profile-section {
    opacity: 0;
    transform: translateY(12px);
    transition: opacity 0.4s ease, transform 0.4s ease;
    transition-delay: var(--delay, 0ms);
  }
  .profile-section.visible {
    opacity: 1;
    transform: translateY(0);
  }
  @media (max-width: 768px) {
    .profile-section {
      transition-duration: 0.2s;
      transition-delay: 0ms !important;
    }
  }

  /* Interview overlay */
  .interview-overlay {
    background: rgba(0, 0, 0, 0.92);
  }
  @media (min-width: 640px) {
    .interview-overlay {
      background: rgba(0, 0, 0, 0.75);
      backdrop-filter: blur(6px);
    }
    .interview-modal.sm-modal {
      height: auto !important;
      max-height: min(85dvh, 640px) !important;
      border-radius: 1rem;
    }
  }

  .interview-pulse {
    animation: pulse 2s ease-in-out infinite;
  }
  @media (max-width: 768px) {
    .interview-pulse { animation: none; }
  }
  @keyframes pulse {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.4; }
  }

  .field-group {
    display: grid;
    gap: 0.25rem;
  }
  .field-lbl {
    font-size: 0.6875rem;
    font-weight: 500;
    color: rgb(100 116 139);
  }
  .field-inp {
    width: 100%;
    border-radius: 0.5rem;
    border: 1px solid rgba(255,255,255,0.08);
    background: rgba(0,0,0,0.3);
    padding: 0.5rem 0.75rem;
    font-size: 0.8125rem;
    color: white;
    outline: none;
    transition: border-color 0.2s;
  }
  .field-inp:focus {
    border-color: rgba(34,211,238,0.3);
  }
  .field-inp option {
    background: #18181b;
  }
</style>
