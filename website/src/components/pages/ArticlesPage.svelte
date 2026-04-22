<script>
  /**
   * ArticlesPage — SEO-friendly blog surface.
   *
   * Renders either the article index (when `slug` is empty) or a single
   * article (when `slug` matches an entry in `content/articles.js`).
   *
   * Security note: article content is rendered as structured blocks
   * (paragraphs, headings, lists) — never as raw HTML. Content is
   * author-controlled, but keeping the render path escaped means a stray
   * entry can never introduce script injection.
   */
  import { onMount, onDestroy } from 'svelte'
  import { articles as staticArticles, findArticle as findStaticArticle } from '../../content/articles.js'
  import { trackPageView } from '../../config/analytics'
  import { API_BASE_URL, apiFetch } from '../../config/api'

  let { slug = '', onBack = () => {} } = $props()

  // Articles are fetched from the API on mount. If the API returns any,
  // we use those; otherwise we fall back to the local seed so the page is
  // never empty (e.g. during local dev without the API running).
  let liveArticles = $state(/** @type {any[] | null} */ (null))
  let loadError = $state('')

  const articles = $derived(
    liveArticles && liveArticles.length > 0 ? liveArticles : staticArticles,
  )
  const current = $derived(
    slug
      ? (articles.find((a) => a.slug === slug) ?? findStaticArticle(slug))
      : null,
  )
  const isDetail = $derived(Boolean(slug))
  const notFound = $derived(isDetail && liveArticles !== null && !current)

  /** @type {HTMLScriptElement|null} */
  let jsonLdEl = null
  /** Remember what the document head looked like so we can restore it. */
  const originalTitle = typeof document !== 'undefined' ? document.title : ''

  function ensureMetaTag(/** @type {string} */ name, /** @type {'name'|'property'} */ attr = 'name') {
    let el = /** @type {HTMLMetaElement|null} */ (document.querySelector(`meta[${attr}="${name}"]`))
    if (!el) {
      el = document.createElement('meta')
      el.setAttribute(attr, name)
      document.head.appendChild(el)
    }
    return el
  }

  function ensureCanonical() {
    let el = /** @type {HTMLLinkElement|null} */ (document.querySelector('link[rel="canonical"]'))
    if (!el) {
      el = document.createElement('link')
      el.setAttribute('rel', 'canonical')
      document.head.appendChild(el)
    }
    return el
  }

  function applyMeta() {
    if (typeof document === 'undefined') return

    const origin = window.location.origin
    const url = origin + window.location.pathname

    let title
    let description
    let jsonLd = null

    if (current) {
      title = `${current.title} — Carver`
      description = current.description
      jsonLd = {
        '@context': 'https://schema.org',
        '@type': 'Article',
        headline: current.title,
        description: current.description,
        datePublished: current.date,
        dateModified: current.date,
        author: { '@type': 'Organization', name: 'Carver' },
        publisher: { '@type': 'Organization', name: 'Carver' },
        mainEntityOfPage: url,
        keywords: (Array.isArray(current.keywords) ? current.keywords : []).join(', '),
      }
    } else if (notFound) {
      title = 'Article not found — Carver'
      description = 'This article could not be found.'
    } else {
      title = 'Articles — Carver'
      description =
        'Guides and stories for superyacht crew — CV tips, season timelines, and how Carver matches you to live roles over WhatsApp.'
    }

    document.title = title
    ensureMetaTag('description').setAttribute('content', description)
    ensureCanonical().setAttribute('href', url)
    ensureMetaTag('og:title', 'property').setAttribute('content', title)
    ensureMetaTag('og:description', 'property').setAttribute('content', description)
    ensureMetaTag('og:type', 'property').setAttribute('content', current ? 'article' : 'website')
    ensureMetaTag('og:url', 'property').setAttribute('content', url)
    ensureMetaTag('twitter:card').setAttribute('content', 'summary')
    ensureMetaTag('twitter:title').setAttribute('content', title)
    ensureMetaTag('twitter:description').setAttribute('content', description)

    if (jsonLdEl) {
      jsonLdEl.remove()
      jsonLdEl = null
    }
    if (jsonLd) {
      jsonLdEl = document.createElement('script')
      jsonLdEl.setAttribute('type', 'application/ld+json')
      jsonLdEl.textContent = JSON.stringify(jsonLd)
      document.head.appendChild(jsonLdEl)
    }
  }

  $effect(() => {
    // Re-apply whenever slug changes.
    // Reference reactive values so Svelte tracks them.
    void slug
    void current
    applyMeta()
  })

  async function loadArticles() {
    try {
      // Detail fetches direct by slug for fewer bytes; list fetches all.
      const url = slug
        ? `${API_BASE_URL}/articles/${encodeURIComponent(slug)}`
        : `${API_BASE_URL}/articles`
      const response = await apiFetch(url, {
        method: 'GET',
        skipAuthHandling: true,
        timeoutMs: 6000,
      })
      if (!response.ok) {
        if (response.status === 404 && slug) {
          liveArticles = []
          return
        }
        throw new Error(`HTTP ${response.status}`)
      }
      const payload = await response.json()
      const normalise = (a) => ({
        ...a,
        readMinutes: a.read_minutes ?? a.readMinutes ?? 3,
      })
      if (slug) {
        liveArticles = payload?.article ? [normalise(payload.article)] : []
      } else {
        liveArticles = Array.isArray(payload?.articles)
          ? payload.articles.map(normalise)
          : []
      }
    } catch (err) {
      loadError = String(err?.message ?? err)
      liveArticles = []
    }
  }

  onMount(() => {
    trackPageView(isDetail ? `article:${slug}` : 'articles')
    window.scrollTo({ top: 0, behavior: 'auto' })
    loadArticles()
  })

  onDestroy(() => {
    if (typeof document === 'undefined') return
    if (jsonLdEl) {
      jsonLdEl.remove()
      jsonLdEl = null
    }
    if (originalTitle) document.title = originalTitle
  })

  function formatDate(/** @type {string} */ iso) {
    try {
      return new Date(iso).toLocaleDateString(undefined, {
        year: 'numeric',
        month: 'long',
        day: 'numeric',
      })
    } catch {
      return iso
    }
  }

  function goHome(/** @type {MouseEvent} */ event) {
    event.preventDefault()
    onBack()
  }
</script>

<div class="articles">
  <nav class="a-nav" aria-label="Primary">
    <a href="/" class="a-brand" onclick={goHome}>
      <span class="a-pip" aria-hidden="true"></span>
      <span class="wordmark text-[14px] text-ivory">CARVER</span>
      <span class="font-display italic text-[13px] text-brass">v3</span>
    </a>
    <div class="a-nav-links">
      <a href="/" class="a-nav-link" onclick={goHome}>Home</a>
      <a href="/articles" class="a-nav-link a-nav-link-active">Articles</a>
    </div>
  </nav>

  <main class="a-main">
    {#if notFound}
      <section class="a-missing">
        <p class="engraved">404</p>
        <h1 class="a-missing-title">Article not found</h1>
        <p class="a-missing-text">
          This piece may have moved or been taken down.
          <a href="/articles">Back to all articles</a>.
        </p>
      </section>
    {:else if current}
      <article class="a-article" itemscope itemtype="https://schema.org/Article">
        <p class="a-crumbs">
          <a href="/articles">Articles</a>
          <span aria-hidden="true">·</span>
          <time datetime={current.date} itemprop="datePublished">{formatDate(current.date)}</time>
          <span aria-hidden="true">·</span>
          <span>{current.readMinutes} min read</span>
        </p>
        <h1 class="a-article-title" itemprop="headline">{current.title}</h1>
        <p class="a-article-lede" itemprop="description">{current.description}</p>

        <div class="a-article-body" itemprop="articleBody">
          {#each current.body ?? [] as block}
            {#if block.type === 'h2'}
              <h2>{block.text}</h2>
            {:else if block.type === 'p'}
              <p>{block.text}</p>
            {:else if block.type === 'ul' && block.items}
              <ul>
                {#each block.items as item}
                  <li>{item}</li>
                {/each}
              </ul>
            {/if}
          {/each}
        </div>

        <footer class="a-article-foot">
          <a href="/articles" class="a-back">← All articles</a>
        </footer>
      </article>
    {:else}
      <header class="a-index-head">
        <p class="engraved text-brass">Carver journal</p>
        <h1 class="a-index-title">Articles for superyacht crew</h1>
        <p class="a-index-lede">
          Short guides on landing berths, staying match-ready between seasons,
          and how Carver's WhatsApp bot actually works.
        </p>
      </header>

      <ul class="a-list" aria-label="Articles">
        {#each articles as a}
          <li class="a-card">
            <a href={`/articles/${a.slug}`} class="a-card-link">
              <p class="a-card-meta">
                <time datetime={a.date}>{formatDate(a.date)}</time>
                <span aria-hidden="true">·</span>
                <span>{a.readMinutes} min read</span>
              </p>
              <h2 class="a-card-title">{a.title}</h2>
              <p class="a-card-desc">{a.description}</p>
              <span class="a-card-cta">Read article →</span>
            </a>
          </li>
        {/each}
      </ul>
    {/if}
  </main>

  <footer class="a-foot">
    <div class="a-foot-inner">
      <div class="a-foot-brand">
        <span class="a-pip" aria-hidden="true"></span>
        <span class="wordmark text-[12px] text-ivory">CARVER</span>
        <span class="font-display italic text-[12px] text-brass">v3</span>
      </div>
      <div class="a-foot-links">
        <a href="/">Home</a>
        <a href="/articles">Articles</a>
        <a href="/privacy">Privacy</a>
        <a href="/terms">Terms</a>
      </div>
      <p class="a-foot-meta">© {new Date().getFullYear()} Carver</p>
    </div>
  </footer>
</div>

<style>
  .articles {
    background: var(--bg-base);
    color: var(--text-primary);
    min-height: 100vh;
  }

  .a-nav {
    position: sticky;
    top: 0;
    z-index: 50;
    backdrop-filter: blur(14px);
    background: rgba(4, 7, 11, 0.62);
    border-bottom: 1px solid rgba(255, 255, 255, 0.05);
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 1rem;
    max-width: 1280px;
    margin: 0 auto;
    padding: 0.85rem 1rem;
  }
  @media (min-width: 768px) { .a-nav { padding: 1rem 1.5rem; } }

  .a-brand {
    display: inline-flex;
    align-items: baseline;
    gap: 0.55rem;
    text-decoration: none;
  }
  .a-pip {
    width: 6px;
    height: 6px;
    border-radius: 9999px;
    background: var(--brass-bright, #c9a96e);
    box-shadow: 0 0 8px rgba(201, 169, 110, 0.55);
    align-self: center;
  }

  .a-nav-links {
    display: inline-flex;
    align-items: center;
    gap: 0.4rem;
  }
  .a-nav-link {
    color: var(--text-secondary);
    font-size: 12.5px;
    padding: 0.5rem 0.85rem;
    border-radius: 9999px;
    text-decoration: none;
    transition: color 0.18s ease, background 0.18s ease;
  }
  .a-nav-link:hover { color: var(--ivory); }
  .a-nav-link-active {
    color: var(--ivory);
    background: rgba(201, 169, 110, 0.08);
    border: 1px solid rgba(201, 169, 110, 0.22);
  }

  .a-main {
    max-width: 760px;
    margin: 0 auto;
    padding: 3rem 1.25rem 5rem;
  }
  @media (min-width: 768px) { .a-main { padding: 4.5rem 1.5rem 6rem; } }

  /* Index */
  .a-index-head { margin-bottom: 2.75rem; }
  .a-index-title {
    margin: 0.75rem 0 0;
    font-family: var(--font-serif);
    font-weight: 300;
    color: var(--ivory);
    font-size: clamp(2rem, 4vw, 2.75rem);
    line-height: 1.05;
    letter-spacing: -0.025em;
  }
  .a-index-lede {
    margin: 1.25rem 0 0;
    color: var(--text-secondary);
    font-size: 1rem;
    line-height: 1.6;
    max-width: 36rem;
  }

  .a-list {
    list-style: none;
    margin: 0;
    padding: 0;
    display: grid;
    gap: 1rem;
  }
  .a-card {
    border: 1px solid rgba(255, 255, 255, 0.06);
    background: rgba(255, 255, 255, 0.015);
    border-radius: 14px;
    transition: border-color 0.2s ease, background 0.2s ease, transform 0.2s ease;
  }
  .a-card:hover {
    border-color: rgba(201, 169, 110, 0.35);
    background: rgba(201, 169, 110, 0.04);
  }
  .a-card-link {
    display: block;
    padding: 1.25rem 1.4rem 1.4rem;
    text-decoration: none;
    color: inherit;
  }
  .a-card-meta {
    margin: 0 0 0.4rem;
    font-family: var(--font-mono);
    font-size: 11px;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    color: var(--text-muted);
    display: inline-flex;
    gap: 0.5rem;
    align-items: center;
  }
  .a-card-title {
    margin: 0;
    font-family: var(--font-serif);
    font-weight: 400;
    color: var(--ivory);
    font-size: 1.35rem;
    line-height: 1.25;
    letter-spacing: -0.015em;
  }
  .a-card-desc {
    margin: 0.6rem 0 0.9rem;
    color: var(--text-secondary);
    font-size: 0.95rem;
    line-height: 1.55;
  }
  .a-card-cta {
    font-size: 12.5px;
    color: var(--brass-bright, #d4b97a);
    letter-spacing: 0.02em;
  }

  /* Detail */
  .a-crumbs {
    margin: 0 0 1.5rem;
    font-family: var(--font-mono);
    font-size: 11px;
    letter-spacing: 0.14em;
    text-transform: uppercase;
    color: var(--text-muted);
    display: flex;
    gap: 0.5rem;
    align-items: center;
    flex-wrap: wrap;
  }
  .a-crumbs a {
    color: var(--text-secondary);
    text-decoration: none;
    border-bottom: 1px dashed rgba(255, 255, 255, 0.18);
  }
  .a-crumbs a:hover { color: var(--ivory); }

  .a-article-title {
    margin: 0;
    font-family: var(--font-serif);
    font-weight: 300;
    color: var(--ivory);
    font-size: clamp(2rem, 4.5vw, 3rem);
    line-height: 1.05;
    letter-spacing: -0.025em;
  }
  .a-article-lede {
    margin: 1.25rem 0 0;
    color: var(--text-secondary);
    font-size: 1.05rem;
    line-height: 1.6;
  }

  .a-article-body {
    margin-top: 2.25rem;
    color: var(--text-primary);
    font-size: 1rem;
    line-height: 1.7;
  }
  .a-article-body :global(h2) {
    margin: 2.25rem 0 0.75rem;
    font-family: var(--font-serif);
    font-weight: 400;
    color: var(--ivory);
    font-size: 1.35rem;
    line-height: 1.25;
    letter-spacing: -0.015em;
  }
  .a-article-body :global(p) {
    margin: 0 0 1.1rem;
    color: var(--text-secondary);
  }
  .a-article-body :global(ul) {
    margin: 0 0 1.25rem;
    padding-left: 1.25rem;
    color: var(--text-secondary);
  }
  .a-article-body :global(li) {
    margin: 0.35rem 0;
  }

  .a-article-foot {
    margin-top: 3rem;
    padding-top: 1.5rem;
    border-top: 1px solid rgba(255, 255, 255, 0.06);
  }
  .a-back {
    color: var(--text-secondary);
    font-size: 13px;
    text-decoration: none;
    border-bottom: 1px dashed rgba(255, 255, 255, 0.18);
  }
  .a-back:hover { color: var(--ivory); }

  /* 404 */
  .a-missing { text-align: center; padding: 3rem 0; }
  .a-missing-title {
    margin: 0.5rem 0 0.75rem;
    font-family: var(--font-serif);
    font-weight: 300;
    color: var(--ivory);
    font-size: 2rem;
  }
  .a-missing-text { color: var(--text-secondary); font-size: 0.95rem; }
  .a-missing-text a {
    color: var(--brass-bright, #d4b97a);
    text-decoration: none;
    border-bottom: 1px dashed rgba(201, 169, 110, 0.35);
  }

  /* Footer */
  .a-foot {
    border-top: 1px solid rgba(201, 169, 110, 0.18);
    padding: 2rem 1rem 2.5rem;
  }
  .a-foot-inner {
    max-width: 1280px;
    margin: 0 auto;
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    justify-content: space-between;
    gap: 1rem;
  }
  .a-foot-brand {
    display: inline-flex;
    align-items: baseline;
    gap: 0.55rem;
  }
  .a-foot-links {
    display: inline-flex;
    gap: 1.25rem;
    font-size: 12px;
  }
  .a-foot-links a {
    color: var(--text-muted);
    text-decoration: none;
    transition: color 0.18s ease;
  }
  .a-foot-links a:hover { color: var(--ivory); }
  .a-foot-meta {
    color: var(--text-muted);
    font-size: 11px;
    font-family: var(--font-mono);
    letter-spacing: 0.06em;
    margin: 0;
  }
</style>
