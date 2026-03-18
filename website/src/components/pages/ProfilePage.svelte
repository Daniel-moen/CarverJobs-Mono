<script>
  import { onMount } from 'svelte'
  import { API_BASE_URL, apiFetch } from '../../config/api'
  import { trackClick, trackChat } from '../../config/analytics'

  const contractOptions = ['Permanent', 'Seasonal', 'Rotational', 'Temporary']

  const DOC_LABELS = {
    cv: 'CV',
    references: 'References',
    passport: 'Passport',
    stcw: 'STCW',
    eng1: 'ENG1',
  }

  let uploadedDocs = $state({ cv: null, references: null, passport: null, stcw: null, eng1: null, photo: null })
  let uploadingDoc = $state('')
  let uploadError = $state('')
  let mounted = $state(false)

  let profile = $state({
    firstName: '', lastName: '', email: '', phone: '',
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

  onMount(async () => {
    try {
      const saved = localStorage.getItem('carver_profile')
      if (saved) {
        const parsed = JSON.parse(saved)
        const stringFields = [
          'firstName','lastName','nationality','currentLocation','desiredRole',
          'contractType','preferredLocations','rotationPreference','yearsExperience',
          'availableFrom','salaryMin','salaryMax','certifications','languages','bio',
        ]
        for (const key of stringFields) {
          if (typeof parsed[key] === 'string' && parsed[key].trim()) profile[key] = parsed[key]
        }
        if (Object.keys(parsed).some(k => !['firstName','lastName','desiredRole','nationality','yearsExperience','currentLocation'].includes(k))) {
          profile = { ...profile, interviewCompleted: true }
        }
      }
    } catch { /* localStorage unavailable */ }
    await Promise.all([loadUploadedDocs(), loadServerProfile(), loadJobHistory()])
    requestAnimationFrame(() => (mounted = true))
  })

  async function loadServerProfile() {
    try {
      const res = await apiFetch(`${API_BASE_URL}/profile/me`, { credentials: 'include' })
      if (res.ok) {
        const data = await res.json()
        if (data.profile) {
          profileSlug = data.profile.profile_slug ?? ''
          const fieldMap = {
            first_name: 'firstName', last_name: 'lastName', phone: 'phone',
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
        }
      }
    } catch { /* ignore */ }
  }

  async function loadUploadedDocs() {
    try {
      const res = await apiFetch(`${API_BASE_URL}/documents`, { credentials: 'include' })
      if (res.ok) {
        const data = await res.json()
        uploadedDocs = { cv: data.cv ?? null, references: data.references ?? null, passport: data.passport ?? null, stcw: data.stcw ?? null, eng1: data.eng1 ?? null, photo: data.photo ?? null }
        if (data.photo) await loadPhotoBlob()
      }
    } catch { /* silently ignore */ }
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
      if (res.ok) {
        uploadedDocs = { ...uploadedDocs, [docType]: null }
      } else {
        const err = await res.json().catch(() => ({}))
        uploadError = err.detail ?? 'Delete failed.'
      }
    } catch { uploadError = 'Could not reach server.' }
  }

  let interviewOpen = $state(false)
  let interviewMessages = $state([])
  let interviewInput = $state('')
  let interviewLoading = $state(false)
  let interviewError = $state('')
  let chatEl = $state(null)

  function buildInterviewProfilePayload() {
    return {
      desiredRole: profile.desiredRole, contractType: profile.contractType,
      preferredLocations: profile.preferredLocations, rotationPreference: profile.rotationPreference,
      availableFrom: profile.availableFrom, salaryMin: profile.salaryMin, salaryMax: profile.salaryMax,
      yearsExperience: profile.yearsExperience, languages: profile.languages,
      certifications: profile.certifications, currentLocation: profile.currentLocation,
    }
  }

  function mergeSuggestedUpdates(updates) {
    if (!updates || typeof updates !== 'object') return
    const allowedKeys = ['desiredRole','preferredLocations','contractType','rotationPreference','availableFrom','salaryMin','salaryMax','languages','certifications','bio']
    const clean = {}
    for (const key of allowedKeys) {
      const value = updates[key]
      if (typeof value === 'string' && value.trim()) clean[key] = value.trim()
    }
    if (Object.keys(clean).length > 0) profile = { ...profile, ...clean, interviewCompleted: true }
  }

  async function requestAITurn(userMessage = '', history = null) {
    interviewLoading = true
    interviewError = ''
    const historyPayload = history ?? interviewMessages
    try {
      const response = await apiFetch(`${API_BASE_URL}/interview/next`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, credentials: 'include',
        body: JSON.stringify({ user_message: userMessage, history: historyPayload, profile: buildInterviewProfilePayload() }),
      })
      if (!response.ok) {
        if (response.status === 503) interviewError = 'AI interview is not configured yet (missing OPENAI_API_KEY).'
        else if (response.status === 429) interviewError = 'OpenAI quota exceeded. Try again later.'
        else {
          let detail = ''
          try { detail = (await response.json()).detail ?? '' } catch { /* ignore */ }
          interviewError = detail || `Interview service error (${response.status}).`
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
    finally { interviewLoading = false }
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
    await requestAITurn(message, historyBeforeSend)
  }

  async function saveProfile() {
    isSaving = true
    saveMessage = ''
    trackClick('save_profile')
    try {
      const body = {
        first_name: profile.firstName || null,
        last_name: profile.lastName || null,
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
      if (res.ok) {
        uploadedDocs = { ...uploadedDocs, photo: null }
        photoPreviewUrl = ''
      }
    } catch { /* ignore */ }
  }

  function resetJobForm() {
    jobForm = { yacht_name: '', yacht_type: '', role: '', start_date: '', end_date: '', description: '' }
    editingJobId = null
    showJobForm = false
    jobFormError = ''
  }

  function editJob(entry) {
    jobForm = {
      yacht_name: entry.yacht_name ?? '',
      yacht_type: entry.yacht_type ?? '',
      role: entry.role ?? '',
      start_date: entry.start_date ?? '',
      end_date: entry.end_date ?? '',
      description: entry.description ?? '',
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
        yacht_name: jobForm.yacht_name.trim(),
        yacht_type: jobForm.yacht_type.trim() || null,
        role: jobForm.role.trim(),
        start_date: jobForm.start_date.trim() || null,
        end_date: jobForm.end_date.trim() || null,
        description: jobForm.description.trim() || null,
      }
      const url = editingJobId
        ? `${API_BASE_URL}/job-history/${editingJobId}`
        : `${API_BASE_URL}/job-history`
      const method = editingJobId ? 'PATCH' : 'POST'
      const res = await apiFetch(url, {
        method, headers: { 'Content-Type': 'application/json' },
        credentials: 'include', body: JSON.stringify(body),
      })
      if (res.ok) {
        await loadJobHistory()
        resetJobForm()
      } else {
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

  const checklist = $derived([
    { label: 'Name + surname', done: Boolean(profile.firstName && profile.lastName) },
    { label: 'Contact details', done: Boolean(profile.email && profile.phone) },
    { label: 'Career preferences', done: Boolean(profile.desiredRole && profile.contractType && profile.preferredLocations) },
    { label: 'Required docs uploaded', done: Boolean(uploadedDocs.passport && uploadedDocs.stcw && uploadedDocs.eng1) },
    { label: 'AI interview complete', done: Boolean(profile.interviewCompleted) },
  ])

  const completedItems = $derived(checklist.filter(i => i.done).length)
  const completionPercent = $derived(Math.round((completedItems / checklist.length) * 100))
</script>

<section class="grid gap-4">
  <!-- Header -->
  <header class="page-header relative overflow-hidden rounded-2xl border border-white/8 bg-zinc-950 px-6 py-5" class:visible={mounted}>
    <div class="pointer-events-none absolute -right-12 -top-12 h-44 w-44 rounded-full bg-cyan-400/10 blur-3xl header-orb"></div>
    <div class="pointer-events-none absolute -bottom-10 -left-10 h-32 w-32 rounded-full bg-sky-400/7 blur-2xl header-orb" style="animation-delay:-2s;"></div>
    <div class="header-scan-line"></div>
    <div class="relative flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between sm:gap-4">
      <div>
        <p class="text-[10px] font-bold uppercase tracking-[0.28em] text-slate-500">Profile</p>
        <h1 class="mt-2 text-2xl font-black tracking-tight text-white sm:text-3xl">Crew Profile Vault</h1>
        <p class="mt-1.5 text-sm text-slate-500">
          Your details, preferences, and documents for better job matching.
        </p>
      </div>
      <div class="flex flex-wrap items-center gap-2">
        {#if shareUrl}
          <button
            type="button"
            onclick={copyShareLink}
            class="rounded-xl border border-white/12 bg-white/5 px-3 py-2 text-xs font-bold text-slate-300 transition-all hover:border-white/25 hover:bg-white/10 hover:text-white active:scale-95"
          >
            {copiedLink ? 'Copied!' : 'Share Profile'}
          </button>
        {/if}
        <button
          type="button"
          onclick={saveProfile}
          disabled={isSaving}
          class="rounded-xl border border-emerald-300/25 bg-emerald-400/8 px-4 py-2 text-xs font-bold text-emerald-300 transition-all hover:border-emerald-300/45 hover:bg-emerald-400/15 hover:text-white disabled:opacity-50 active:scale-95"
        >
          {isSaving ? 'Saving…' : 'Save Profile'}
        </button>
        <button
          type="button"
          onclick={openInterview}
          class="rounded-xl border border-cyan-300/25 bg-cyan-400/8 px-4 py-2 text-xs font-bold text-cyan-300 shadow-[0_0_20px_rgba(34,211,238,0.12)] transition-all hover:border-cyan-300/45 hover:bg-cyan-400/15 hover:shadow-[0_0_30px_rgba(34,211,238,0.25)] hover:text-white active:scale-95"
        >
          <span class="flex items-center gap-1.5">
            <span class="h-1.5 w-1.5 animate-pulse rounded-full bg-cyan-400"></span>
            AI Interview
          </span>
        </button>
      </div>
    </div>
    {#if saveMessage}
      <p class="relative mt-2 text-xs {saveMessage === 'Profile saved.' ? 'text-emerald-400' : 'text-rose-300'}">{saveMessage}</p>
    {/if}
  </header>

  <!-- Completion tracker -->
  <article class="profile-card rounded-2xl border border-white/8 bg-zinc-950 p-5" class:visible={mounted} style="--delay:60ms;">
    <div class="flex items-center justify-between gap-3">
      <p class="text-[10px] font-bold uppercase tracking-[0.25em] text-slate-500">Profile Completion</p>
      <p class="text-sm font-black text-white">{completionPercent}%</p>
    </div>
    <div class="mt-3 h-1.5 overflow-hidden rounded-full bg-white/8">
      <div
        class="h-full rounded-full transition-all duration-700"
        style="width:{completionPercent}%; background: linear-gradient(90deg,#22d3ee,#38bdf8);"
      ></div>
    </div>
    <ul class="mt-4 grid gap-2 sm:grid-cols-2 lg:grid-cols-5">
      {#each checklist as item}
        <li
          class="flex items-center gap-2 rounded-xl border px-3 py-2 text-xs transition-all {item.done
            ? 'border-emerald-400/18 bg-emerald-400/5 text-emerald-200'
            : 'border-white/6 bg-black/30 text-slate-500'}"
        >
          <span
            class="flex h-4 w-4 flex-none items-center justify-center rounded-full text-[10px] {item.done
              ? 'bg-emerald-400/20 text-emerald-300'
              : 'bg-white/8 text-slate-700'}"
          >
            {item.done ? '✓' : '·'}
          </span>
          {item.label}
        </li>
      {/each}
    </ul>
  </article>

  <!-- Personal + Career side by side -->
  <div class="grid gap-4 lg:grid-cols-2">
    <article class="profile-card rounded-2xl border border-white/8 bg-zinc-950 p-5" class:visible={mounted} style="--delay:120ms;">
      <p class="text-[10px] font-bold uppercase tracking-[0.25em] text-slate-500">Personal Information</p>

      <!-- Profile Photo -->
      <div class="mt-4 mb-4 flex items-center gap-4">
        <div class="relative h-16 w-16 flex-none overflow-hidden rounded-full border-2 {uploadedDocs.photo ? 'border-cyan-400/30' : 'border-white/10'} bg-black/40">
          {#if photoPreviewUrl}
            <img src={photoPreviewUrl} alt="Profile" class="h-full w-full object-cover" />
          {:else}
            <div class="flex h-full w-full items-center justify-center text-xl text-slate-700">
              {profile.firstName?.[0]?.toUpperCase() ?? '?'}{profile.lastName?.[0]?.toUpperCase() ?? ''}
            </div>
          {/if}
        </div>
        <div class="grid gap-1">
          <label>
            <input type="file" class="hidden" accept=".jpg,.jpeg,.png" disabled={uploadingDoc === 'photo'} onchange={handlePhotoSelect} />
            <span class="inline-block cursor-pointer rounded-lg border border-white/12 px-3 py-1.5 text-[11px] font-medium text-slate-400 transition hover:border-cyan-400/30 hover:text-cyan-300 {uploadingDoc === 'photo' ? 'cursor-not-allowed opacity-40' : ''}">
              {uploadingDoc === 'photo' ? 'Uploading…' : uploadedDocs.photo ? 'Change photo' : 'Upload photo'}
            </span>
          </label>
          {#if uploadedDocs.photo}
            <button type="button" class="text-left text-[10px] text-slate-600 hover:text-rose-300" onclick={removePhoto}>Remove</button>
          {/if}
        </div>
      </div>

      <div class="grid gap-3 sm:grid-cols-2">
        <label class="field-label">
          Name
          <input class="field-input" bind:value={profile.firstName} placeholder="First name" />
        </label>
        <label class="field-label">
          Surname
          <input class="field-input" bind:value={profile.lastName} placeholder="Last name" />
        </label>
        <label class="field-label">
          Email
          <input type="email" class="field-input" bind:value={profile.email} placeholder="you@example.com" />
        </label>
        <label class="field-label">
          Phone
          <input class="field-input" bind:value={profile.phone} placeholder="+1 234 567 890" />
        </label>
        <label class="field-label">
          Nationality
          <input class="field-input" bind:value={profile.nationality} placeholder="British" />
        </label>
        <label class="field-label">
          Current location
          <input class="field-input" bind:value={profile.currentLocation} placeholder="Monaco" />
        </label>
      </div>
    </article>

    <article class="profile-card rounded-2xl border border-white/8 bg-zinc-950 p-5" class:visible={mounted} style="--delay:180ms;">
      <p class="text-[10px] font-bold uppercase tracking-[0.25em] text-slate-500">Career Preferences</p>
      <div class="mt-4 grid gap-3 sm:grid-cols-2">
        <label class="field-label">
          Desired role
          <input class="field-input" bind:value={profile.desiredRole} placeholder="Chief Officer" />
        </label>
        <label class="field-label">
          Contract type
          <select class="field-input" bind:value={profile.contractType}>
            <option value="">Select...</option>
            {#each contractOptions as opt}<option value={opt}>{opt}</option>{/each}
          </select>
        </label>
        <label class="field-label sm:col-span-2">
          Preferred locations
          <input class="field-input" bind:value={profile.preferredLocations} placeholder="Mediterranean, Caribbean" />
        </label>
        <label class="field-label">
          Rotation preference
          <input class="field-input" bind:value={profile.rotationPreference} placeholder="3/3 months" />
        </label>
        <label class="field-label">
          Years experience
          <input type="number" min="0" class="field-input" bind:value={profile.yearsExperience} placeholder="5" />
        </label>
        <label class="field-label">
          Available from
          <input class="field-input" bind:value={profile.availableFrom} placeholder="Immediately" />
        </label>
        <label class="field-label">
          Salary range (€/mo)
          <div class="flex items-center gap-1.5">
            <input type="number" min="0" class="field-input" bind:value={profile.salaryMin} placeholder="Min" />
            <span class="text-slate-600">–</span>
            <input type="number" min="0" class="field-input" bind:value={profile.salaryMax} placeholder="Max" />
          </div>
        </label>
      </div>
    </article>
  </div>

  <!-- Documents & Readiness -->
  <article class="profile-card rounded-2xl border border-white/8 bg-zinc-950 p-5" class:visible={mounted} style="--delay:240ms;">
    <div class="flex items-start justify-between gap-3">
      <div>
        <p class="text-[10px] font-bold uppercase tracking-[0.25em] text-slate-500">Documents & Readiness</p>
        <p class="mt-1 text-xs text-slate-600">Upload once — CARVER handles the rest on every application.</p>
      </div>
    </div>

    {#if uploadError}
      <p class="mt-3 rounded-xl border border-rose-400/20 bg-rose-400/8 px-3 py-2 text-xs text-rose-300">{uploadError}</p>
    {/if}

    <div class="mt-4 grid gap-2.5 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5">
      {#each Object.entries(DOC_LABELS) as [docType, label]}
        {@const uploaded = uploadedDocs[docType]}
        {@const isUploading = uploadingDoc === docType}
        <div
          class="flex flex-col gap-2 rounded-xl border px-3 py-3 text-sm transition-all {uploaded
            ? 'border-emerald-400/20 bg-emerald-400/5'
            : 'border-white/8 bg-black/25'}"
        >
          <div class="flex items-center gap-2">
            <span
              class="flex h-4 w-4 flex-none items-center justify-center rounded-full text-[10px] {uploaded
                ? 'bg-emerald-400/20 text-emerald-300'
                : 'bg-white/8 text-slate-700'}"
            >
              {uploaded ? '✓' : '·'}
            </span>
            <span class="text-xs font-semibold {uploaded ? 'text-emerald-200' : 'text-slate-400'}">{label}</span>
          </div>

          {#if uploaded}
            <div class="flex items-center justify-between gap-2 pl-6">
              <span class="truncate text-[10px] text-slate-500" title={uploaded.original_name}>{uploaded.original_name}</span>
              <button
                type="button"
                class="shrink-0 rounded px-1.5 py-0.5 text-[10px] text-slate-600 hover:bg-white/8 hover:text-rose-300"
                onclick={() => removeDoc(docType)}
              >
                ✕
              </button>
            </div>
          {:else}
            <label class="pl-6">
              <input
                type="file"
                class="hidden"
                accept=".pdf,.doc,.docx,.jpg,.jpeg,.png"
                disabled={isUploading}
                onchange={(e) => handleFileSelect(e, docType)}
              />
              <span
                class="inline-block cursor-pointer rounded-lg border border-white/12 px-2.5 py-1 text-[10px] font-medium text-slate-400 transition hover:border-cyan-400/30 hover:text-cyan-300 {isUploading ? 'cursor-not-allowed opacity-40' : ''}"
              >
                {isUploading ? 'Uploading…' : 'Choose file'}
              </span>
            </label>
          {/if}
        </div>
      {/each}
    </div>

    <div class="mt-4 grid gap-3">
      <label class="field-label">
        Certifications
        <textarea rows="2" class="field-input resize-none" bind:value={profile.certifications} placeholder="STCW, ENG1, OOW, etc."></textarea>
      </label>
      <div class="grid gap-3 sm:grid-cols-2">
        <label class="field-label">
          Languages
          <input class="field-input" bind:value={profile.languages} placeholder="English, Spanish" />
        </label>
        <label class="field-label">
          Short bio
          <textarea rows="2" class="field-input resize-none" bind:value={profile.bio} placeholder="Brief professional summary..."></textarea>
        </label>
      </div>
    </div>
  </article>

  <!-- Job History -->
  <article class="profile-card rounded-2xl border border-white/8 bg-zinc-950 p-5" class:visible={mounted} style="--delay:300ms;">
    <div class="flex items-start justify-between gap-3">
      <div>
        <p class="text-[10px] font-bold uppercase tracking-[0.25em] text-slate-500">Job History</p>
        <p class="mt-1 text-xs text-slate-600">Your recent yachting positions — visible on your public profile.</p>
      </div>
      {#if !showJobForm}
        <button
          type="button"
          onclick={() => { resetJobForm(); showJobForm = true }}
          class="flex-none rounded-xl border border-cyan-300/25 bg-cyan-400/8 px-3 py-1.5 text-xs font-bold text-cyan-300 transition-all hover:border-cyan-300/45 hover:bg-cyan-400/15 hover:text-white active:scale-95"
        >
          + Add Position
        </button>
      {/if}
    </div>

    {#if showJobForm}
      <form class="mt-4 grid gap-3 rounded-xl border border-white/8 bg-black/25 p-4" onsubmit={submitJobForm}>
        <div class="grid gap-3 sm:grid-cols-2">
          <label class="field-label">
            Yacht name *
            <input class="field-input" bind:value={jobForm.yacht_name} placeholder="M/Y Example" required />
          </label>
          <label class="field-label">
            Yacht type
            <input class="field-input" bind:value={jobForm.yacht_type} placeholder="Motor, Sail, etc." />
          </label>
          <label class="field-label">
            Role / position *
            <input class="field-input" bind:value={jobForm.role} placeholder="Chief Officer" required />
          </label>
          <label class="field-label">
            Start date
            <input class="field-input" bind:value={jobForm.start_date} placeholder="Mar 2024" />
          </label>
          <label class="field-label">
            End date
            <input class="field-input" bind:value={jobForm.end_date} placeholder="Present" />
          </label>
        </div>
        <label class="field-label">
          Description
          <textarea rows="2" class="field-input resize-none" bind:value={jobForm.description} placeholder="Key responsibilities, vessel details..."></textarea>
        </label>
        {#if jobFormError}
          <p class="rounded-xl border border-rose-400/20 bg-rose-400/8 px-3 py-2 text-xs text-rose-300">{jobFormError}</p>
        {/if}
        <div class="flex items-center gap-2">
          <button
            type="submit"
            disabled={jobHistoryLoading}
            class="rounded-xl border border-cyan-300/30 bg-cyan-300/10 px-4 py-2 text-xs font-semibold text-cyan-200 transition hover:bg-cyan-300/20 hover:text-white disabled:opacity-50"
          >
            {jobHistoryLoading ? 'Saving…' : editingJobId ? 'Update' : 'Add'}
          </button>
          <button type="button" onclick={resetJobForm} class="rounded-xl border border-white/10 px-4 py-2 text-xs text-slate-400 transition hover:border-white/20 hover:text-white">
            Cancel
          </button>
        </div>
      </form>
    {/if}

    {#if jobHistory.length > 0}
      <div class="mt-4 grid gap-2.5">
        {#each jobHistory as entry}
          <div class="flex items-start gap-3 rounded-xl border border-white/8 bg-black/25 px-4 py-3">
            <div class="mt-0.5 h-2 w-2 flex-none rounded-full bg-cyan-400/40"></div>
            <div class="min-w-0 flex-1">
              <div class="flex items-baseline gap-2">
                <p class="text-sm font-semibold text-white">{entry.role}</p>
                <span class="text-xs text-slate-500">on</span>
                <p class="text-sm text-cyan-200">{entry.yacht_name}</p>
                {#if entry.yacht_type}
                  <span class="rounded-full border border-white/8 px-2 py-0.5 text-[9px] text-slate-500">{entry.yacht_type}</span>
                {/if}
              </div>
              {#if entry.start_date || entry.end_date}
                <p class="mt-0.5 text-[11px] text-slate-500">{entry.start_date ?? '?'} — {entry.end_date ?? 'Present'}</p>
              {/if}
              {#if entry.description}
                <p class="mt-1 text-xs leading-relaxed text-slate-400">{entry.description}</p>
              {/if}
            </div>
            <div class="flex flex-none gap-1">
              <button type="button" class="rounded px-1.5 py-0.5 text-[10px] text-slate-600 hover:bg-white/8 hover:text-cyan-300" onclick={() => editJob(entry)}>Edit</button>
              <button type="button" class="rounded px-1.5 py-0.5 text-[10px] text-slate-600 hover:bg-white/8 hover:text-rose-300" onclick={() => deleteJob(entry.id)}>Del</button>
            </div>
          </div>
        {/each}
      </div>
    {:else if !showJobForm}
      <p class="mt-4 text-center text-xs text-slate-600">No positions added yet.</p>
    {/if}
  </article>
</section>

<!-- AI Interview Modal -->
{#if interviewOpen}
  <div class="fixed inset-0 z-40 flex items-center justify-center p-4" style="background:rgba(0,0,0,0.75);backdrop-filter:blur(6px);">
    <article class="modal-card w-full max-w-xl overflow-hidden rounded-2xl border border-cyan-400/22 bg-zinc-950 shadow-[0_0_60px_rgba(34,211,238,0.18)]">
      <!-- Modal header -->
      <div class="flex items-center justify-between gap-3 border-b border-white/6 px-5 py-4">
        <div class="flex items-center gap-2.5">
          <span class="h-1.5 w-1.5 animate-pulse rounded-full bg-cyan-400"></span>
          <h3 class="text-sm font-bold text-white">AI Interview</h3>
          <span class="rounded-full border border-cyan-400/20 bg-cyan-400/8 px-2 py-0.5 text-[9px] font-bold uppercase tracking-wider text-cyan-300">OpenAI</span>
        </div>
        <button
          type="button"
          class="rounded-lg border border-white/10 px-3 py-1 text-xs text-slate-400 transition hover:border-white/20 hover:text-white"
          onclick={() => (interviewOpen = false)}
        >
          Close
        </button>
      </div>

      <!-- Chat messages -->
      <div
        bind:this={chatEl}
        class="flex max-h-80 min-h-[12rem] flex-col gap-3 overflow-y-auto p-4"
      >
        {#if interviewMessages.length === 0 && interviewLoading}
          <div class="flex items-center gap-2 text-xs text-slate-500">
            <span class="h-1.5 w-1.5 animate-pulse rounded-full bg-cyan-400"></span>
            Starting interview…
          </div>
        {:else}
          {#each interviewMessages as message}
            <div
              class="max-w-[88%] rounded-xl px-3.5 py-2.5 text-sm leading-relaxed {message.role === 'assistant'
                ? 'border border-cyan-400/15 bg-cyan-400/8 text-cyan-100'
                : 'ml-auto border border-white/10 bg-white/8 text-slate-100'}"
            >
              {message.content}
            </div>
          {/each}
          {#if interviewLoading}
            <div class="flex items-center gap-2 text-xs text-slate-600">
              <span class="h-1.5 w-1.5 animate-pulse rounded-full bg-cyan-400/50"></span>
              OpenAI is thinking…
            </div>
          {/if}
        {/if}
      </div>

      {#if interviewError}
        <p class="mx-4 mb-2 rounded-xl border border-rose-400/20 bg-rose-400/8 px-3 py-2 text-xs text-rose-300">{interviewError}</p>
      {/if}

      <!-- Input -->
      <form class="flex gap-2 border-t border-white/6 p-4" onsubmit={sendInterviewMessage}>
        <input
          class="flex-1 rounded-xl border border-white/10 bg-black/40 px-3 py-2 text-sm text-white outline-none placeholder:text-slate-600 focus:border-cyan-400/30"
          placeholder="Type your answer…"
          bind:value={interviewInput}
          disabled={interviewLoading}
        />
        <button
          type="submit"
          class="rounded-xl border border-cyan-300/30 bg-cyan-300/10 px-4 py-2 text-sm font-semibold text-cyan-200 transition hover:bg-cyan-300/20 hover:text-white disabled:opacity-50 active:scale-95"
          disabled={interviewLoading}
        >
          Send
        </button>
      </form>

      <div class="flex justify-end border-t border-white/4 px-4 py-2.5">
        <button
          type="button"
          class="rounded-lg border border-white/8 px-3 py-1 text-[10px] text-slate-600 transition hover:border-white/15 hover:text-slate-400"
          onclick={() => { interviewMessages = []; interviewInput = ''; interviewError = '' }}
        >
          Reset Interview
        </button>
      </div>
    </article>
  </div>
{/if}

<style>
  /* Header orb pulse + scan */
  .header-orb {
    animation: headerOrbPulse 4.5s ease-in-out infinite;
  }
  .header-scan-line {
    position: absolute;
    top: -1px;
    left: 0;
    width: 100%;
    height: 1px;
    background: linear-gradient(90deg, transparent, rgba(34,211,238,0.28), transparent);
    animation: headerScan 8s linear infinite;
    pointer-events: none;
  }
  @keyframes headerOrbPulse {
    0%, 100% { opacity: 1; transform: scale(1); }
    50% { opacity: 0.55; transform: scale(1.14); }
  }
  @keyframes headerScan {
    0%   { top: -1px; opacity: 0; }
    8%   { opacity: 1; }
    92%  { opacity: 1; }
    100% { top: 100%;  opacity: 0; }
  }

  .page-header,
  .profile-card {
    opacity: 0;
    transform: translateY(14px);
    transition: opacity 0.45s ease, transform 0.45s ease;
    transition-delay: var(--delay, 0ms);
  }
  .page-header.visible,
  .profile-card.visible {
    opacity: 1;
    transform: translateY(0);
  }

  .modal-card {
    animation: modalIn 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
  }
  @keyframes modalIn {
    from { opacity: 0; transform: scale(0.95) translateY(12px); }
    to   { opacity: 1; transform: scale(1)    translateY(0);     }
  }

  /* Form field styles */
  :global(.field-label) {
    display: grid;
    gap: 0.375rem;
    font-size: 0.6875rem;
    font-weight: 600;
    letter-spacing: 0.05em;
    text-transform: uppercase;
    color: rgb(100 116 139);
  }
  :global(.field-input) {
    width: 100%;
    border-radius: 0.625rem;
    border: 1px solid rgba(255,255,255,0.08);
    background: rgba(0,0,0,0.35);
    padding: 0.5rem 0.75rem;
    font-size: 0.8125rem;
    color: white;
    outline: none;
    transition: border-color 0.2s;
  }
  :global(.field-input:focus) {
    border-color: rgba(34,211,238,0.28);
  }
  :global(.field-input option) {
    background: #18181b;
  }
</style>
