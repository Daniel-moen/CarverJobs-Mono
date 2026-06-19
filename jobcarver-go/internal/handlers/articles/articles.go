// Package articles ports api/app/routes/articles.py: the public SEO article API
// + SSR HTML pages, plus the agent-authenticated authoring endpoints (bearer
// AGENT_API_TOKEN). All DB logic over models.Article is real. The SSR HTML and
// sitemap renderers are ported functionally with the same HTML-escaping +
// JSON-LD "</" escaping safety; the Mixpanel browser snippet is omitted because
// the Go config does not carry the MIXPANEL_* settings.
// TODO(go-port): add MIXPANEL_* to config and emit the SSR analytics snippet.
package articles

import (
	"crypto/subtle"
	"encoding/json"
	"html"
	"net/http"
	"regexp"
	"strings"
	"time"

	"github.com/go-chi/chi/v5"

	"jobcarver/internal/config"
	"jobcarver/internal/db"
	"jobcarver/internal/httpx"
	"jobcarver/internal/models"
)

var (
	slugPattern = regexp.MustCompile(`^[a-z0-9]+(?:-[a-z0-9]+)*$`)
	isoDatePat  = regexp.MustCompile(`^\d{4}-\d{2}-\d{2}$`)
)

const (
	maxTitle       = 200
	maxDescription = 400
	maxBlockText   = 4000
	maxListItem    = 500
	maxListItems   = 20
	maxBlocks      = 200
	maxKeywords    = 20
	maxKeywordLen  = 80
	maxPublicList  = 500
)

// Register mounts the public /articles routes and the agent /agent/articles
// routes. chi's router prioritises the static /articles/sitemap.xml and
// /articles/list.html and /articles/{slug}/page.html patterns over /articles/{slug}.
func Register(r chi.Router) {
	r.Get("/articles", listArticles)
	r.Get("/articles/list.html", articlesListPage)
	r.Get("/articles/sitemap.xml", articlesSitemap)
	r.Get("/articles/{slug}/page.html", articlePage)
	r.Get("/articles/{slug}", getArticle)

	r.Post("/agent/articles", requireAgent(upsertArticle))
	r.Delete("/agent/articles/{slug}", requireAgent(deleteArticle))
}

// ── auth ─────────────────────────────────────────────────────────────────────

func requireAgent(next http.HandlerFunc) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if config.S.AgentAPIToken == "" {
			httpx.WriteError(w, http.StatusServiceUnavailable,
				"Agent API is not configured (set AGENT_API_TOKEN).", httpx.CRV5005)
			return
		}
		token := ""
		if auth := r.Header.Get("Authorization"); strings.HasPrefix(auth, "Bearer ") {
			token = strings.TrimSpace(auth[7:])
		}
		if token == "" || subtle.ConstantTimeCompare([]byte(token), []byte(config.S.AgentAPIToken)) != 1 {
			httpx.WriteError(w, http.StatusUnauthorized, "Invalid or missing agent token.", httpx.CRV2004)
			return
		}
		next(w, r)
	}
}

// ── helpers ──────────────────────────────────────────────────────────────────

func normaliseSlug(slug string) (string, bool) {
	s := strings.ToLower(strings.TrimSpace(slug))
	if !slugPattern.MatchString(s) {
		return "", false
	}
	return s, true
}

func publishedQuery() *db0 { return &db0{} }

// db0 is a tiny helper to keep the ordering identical across list/SSR/sitemap.
type db0 struct{}

func (db0) rows(limit int) []models.Article {
	var rows []models.Article
	db.DB.Where("published = ?", true).Order("date DESC, id DESC").Limit(limit).Find(&rows)
	return rows
}

func getPublishedArticleOrNone(slug string) (models.Article, bool) {
	norm, ok := normaliseSlug(slug)
	if !ok {
		return models.Article{}, false
	}
	var row models.Article
	if db.DB.Where("slug = ? AND published = ?", norm, true).First(&row).Error != nil {
		return models.Article{}, false
	}
	return row, true
}

func serialise(row models.Article) map[string]any {
	var keywords []any
	_ = json.Unmarshal([]byte(orList(row.KeywordsJSON)), &keywords)
	if keywords == nil {
		keywords = []any{}
	}
	var body []any
	_ = json.Unmarshal([]byte(orList(row.BodyJSON)), &body)
	if body == nil {
		body = []any{}
	}
	return map[string]any{
		"slug":         row.Slug,
		"title":        row.Title,
		"description":  row.Description,
		"date":         row.Date,
		"read_minutes": row.ReadMinutes,
		"keywords":     keywords,
		"body":         body,
		"published":    row.Published,
		"created_at":   row.CreatedAt.Format(time.RFC3339),
		"updated_at":   row.UpdatedAt.Format(time.RFC3339),
	}
}

func orList(s string) string {
	if strings.TrimSpace(s) == "" {
		return "[]"
	}
	return s
}

// ── public endpoints ─────────────────────────────────────────────────────────

func listArticles(w http.ResponseWriter, r *http.Request) {
	rows := publishedQuery().rows(maxPublicList)
	out := make([]map[string]any, 0, len(rows))
	for _, row := range rows {
		out = append(out, serialise(row))
	}
	httpx.JSON(w, http.StatusOK, map[string]any{"ok": true, "articles": out})
}

func getArticle(w http.ResponseWriter, r *http.Request) {
	row, ok := getPublishedArticleOrNone(chi.URLParam(r, "slug"))
	if !ok {
		httpx.WriteError(w, http.StatusNotFound, "Article not found.", httpx.CRV1005)
		return
	}
	httpx.JSON(w, http.StatusOK, map[string]any{"ok": true, "article": serialise(row)})
}

func articlesListPage(w http.ResponseWriter, r *http.Request) {
	rows := publishedQuery().rows(maxPublicList)
	writeHTML(w, renderArticlesListHTML(rows))
}

func articlePage(w http.ResponseWriter, r *http.Request) {
	row, ok := getPublishedArticleOrNone(chi.URLParam(r, "slug"))
	if !ok {
		httpx.WriteError(w, http.StatusNotFound, "Article not found.", httpx.CRV1005)
		return
	}
	var pool []models.Article
	db.DB.Where("published = ? AND slug != ?", true, row.Slug).Order("date DESC, id DESC").Limit(100).Find(&pool)
	related := pickRelated(row, pool, 4)
	writeHTML(w, renderArticleHTML(row, related))
}

func articlesSitemap(w http.ResponseWriter, r *http.Request) {
	rows := publishedQuery().rows(2000)
	w.Header().Set("Content-Type", "application/xml")
	w.WriteHeader(http.StatusOK)
	_, _ = w.Write([]byte(renderSitemap(rows)))
}

// ── agent endpoints ──────────────────────────────────────────────────────────

type blockIn struct {
	Type  string   `json:"type"`
	Text  *string  `json:"text"`
	Items []string `json:"items"`
}

type articleIn struct {
	Slug        string    `json:"slug"`
	Title       string    `json:"title"`
	Description string    `json:"description"`
	Date        string    `json:"date"`
	ReadMinutes int       `json:"read_minutes"`
	Keywords    []string  `json:"keywords"`
	Body        []blockIn `json:"body"`
	Published   *bool     `json:"published"`
}

func upsertArticle(w http.ResponseWriter, r *http.Request) {
	var payload articleIn
	if err := httpx.Decode(r, &payload); err != nil {
		httpx.WriteError(w, http.StatusUnprocessableEntity, "Invalid request body.", httpx.CRV1003)
		return
	}
	if msg := validateArticle(&payload); msg != "" {
		httpx.WriteError(w, http.StatusUnprocessableEntity, msg, httpx.CRV1003)
		return
	}

	// Serialise body (drop nil fields per block type) + keywords.
	bodyOut := make([]map[string]any, 0, len(payload.Body))
	for _, b := range payload.Body {
		m := map[string]any{"type": b.Type}
		if b.Type == "ul" {
			m["items"] = b.Items
		} else if b.Text != nil {
			m["text"] = strings.TrimSpace(*b.Text)
		}
		bodyOut = append(bodyOut, m)
	}
	bodyJSON, _ := json.Marshal(bodyOut)
	keywordsJSON, _ := json.Marshal(payload.Keywords)

	published := true
	if payload.Published != nil {
		published = *payload.Published
	}
	readMinutes := payload.ReadMinutes
	if readMinutes == 0 {
		readMinutes = 3
	}

	var row models.Article
	created := db.DB.Where("slug = ?", payload.Slug).First(&row).Error != nil
	if created {
		row = models.Article{Slug: payload.Slug}
	}
	row.Title = payload.Title
	row.Description = payload.Description
	row.Date = payload.Date
	row.ReadMinutes = readMinutes
	row.KeywordsJSON = string(keywordsJSON)
	row.BodyJSON = string(bodyJSON)
	row.Published = published

	if created {
		db.DB.Create(&row)
	} else {
		db.DB.Save(&row)
	}

	httpx.JSON(w, http.StatusOK, map[string]any{
		"ok": true, "created": created, "article": serialise(row),
	})
}

func deleteArticle(w http.ResponseWriter, r *http.Request) {
	slug, ok := normaliseSlug(chi.URLParam(r, "slug"))
	if !ok {
		httpx.WriteError(w, http.StatusNotFound, "Article not found.", httpx.CRV1005)
		return
	}
	var row models.Article
	if db.DB.Where("slug = ?", slug).First(&row).Error != nil {
		httpx.WriteError(w, http.StatusNotFound, "Article not found.", httpx.CRV1005)
		return
	}
	db.DB.Delete(&row)
	httpx.JSON(w, http.StatusOK, map[string]any{"ok": true, "deleted": slug})
}

// validateArticle ports the pydantic field validators; returns "" when valid.
func validateArticle(p *articleIn) string {
	slug, ok := normaliseSlug(p.Slug)
	if !ok || len(slug) > 120 {
		return "slug must be lowercase letters, digits and single hyphens (max 120 chars)"
	}
	p.Slug = slug
	p.Title = strings.TrimSpace(p.Title)
	if p.Title == "" || len(p.Title) > maxTitle {
		return "title must be non-empty and at most 200 chars"
	}
	p.Description = strings.TrimSpace(p.Description)
	if p.Description == "" || len(p.Description) > maxDescription {
		return "description must be non-empty and at most 400 chars"
	}
	p.Date = strings.TrimSpace(p.Date)
	if !isoDatePat.MatchString(p.Date) {
		return "date must be an ISO date (YYYY-MM-DD)"
	}
	if p.ReadMinutes != 0 && (p.ReadMinutes < 1 || p.ReadMinutes > 60) {
		return "read_minutes must be between 1 and 60"
	}
	if len(p.Keywords) > maxKeywords {
		return "too many keywords (max 20)"
	}
	cleanKw := make([]string, 0, len(p.Keywords))
	for _, k := range p.Keywords {
		s := strings.TrimSpace(k)
		if s == "" {
			continue
		}
		if len(s) > maxKeywordLen {
			return "keyword too long (max 80 chars)"
		}
		cleanKw = append(cleanKw, s)
	}
	p.Keywords = cleanKw
	if len(p.Body) == 0 {
		return "body must contain at least one block"
	}
	if len(p.Body) > maxBlocks {
		return "too many blocks (max 200)"
	}
	for i, b := range p.Body {
		switch b.Type {
		case "p", "h2":
			if b.Text == nil || strings.TrimSpace(*b.Text) == "" {
				return b.Type + " block requires 'text'"
			}
			if len(strings.TrimSpace(*b.Text)) > maxBlockText {
				return "block text too long (max 4000 chars)"
			}
		case "ul":
			if len(b.Items) == 0 {
				return "ul block requires non-empty 'items'"
			}
			if len(b.Items) > maxListItems {
				return "too many list items (max 20)"
			}
			for j, it := range b.Items {
				s := strings.TrimSpace(it)
				if s == "" {
					return "list items must not be empty"
				}
				if len(s) > maxListItem {
					return "list item too long (max 500 chars)"
				}
				p.Body[i].Items[j] = s
			}
		default:
			return "invalid block type (allowed: p, h2, ul)"
		}
	}
	return ""
}

// ── related selection (ports _pick_related) ──────────────────────────────────

func articleKeywordSet(row models.Article) map[string]bool {
	out := map[string]bool{}
	var kws []string
	if json.Unmarshal([]byte(orList(row.KeywordsJSON)), &kws) != nil {
		return out
	}
	for _, k := range kws {
		out[strings.ToLower(k)] = true
	}
	return out
}

func pickRelated(current models.Article, candidates []models.Article, k int) []models.Article {
	currentKw := articleKeywordSet(current)
	type scored struct {
		score int
		date  string
		id    int
		row   models.Article
	}
	var items []scored
	for _, row := range candidates {
		if row.Slug == current.Slug {
			continue
		}
		kw := articleKeywordSet(row)
		overlap := 0
		for key := range currentKw {
			if kw[key] {
				overlap++
			}
		}
		items = append(items, scored{overlap, row.Date, row.ID, row})
	}
	// sort by score desc, date desc, id desc
	for i := 0; i < len(items); i++ {
		for j := i + 1; j < len(items); j++ {
			if less(items[i], items[j]) {
				items[i], items[j] = items[j], items[i]
			}
		}
	}
	if len(items) > k {
		items = items[:k]
	}
	out := make([]models.Article, 0, len(items))
	for _, it := range items {
		out = append(out, it.row)
	}
	return out
}

func less(a, b struct {
	score int
	date  string
	id    int
	row   models.Article
}) bool {
	if a.score != b.score {
		return a.score < b.score
	}
	if a.date != b.date {
		return a.date < b.date
	}
	return a.id < b.id
}

// ── HTML/XML rendering ───────────────────────────────────────────────────────

func siteOrigin() string {
	base := strings.TrimRight(strings.TrimSpace(config.S.FrontendBaseURL), "/")
	if base == "" || strings.HasPrefix(base, "http://localhost") {
		return "https://jobcarver.co"
	}
	return base
}

func esc(s string) string { return html.EscapeString(s) }

func writeHTML(w http.ResponseWriter, body string) {
	w.Header().Set("Content-Type", "text/html; charset=utf-8")
	w.WriteHeader(http.StatusOK)
	_, _ = w.Write([]byte(body))
}

func renderArticleHTML(row models.Article, related []models.Article) string {
	art := serialise(row)
	origin := siteOrigin()
	slug := row.Slug
	canonical := origin + "/articles/" + slug

	var bodyParts []string
	var body []map[string]any
	_ = json.Unmarshal([]byte(orList(row.BodyJSON)), &body)
	for _, block := range body {
		switch block["type"] {
		case "h2":
			if t, ok := block["text"].(string); ok && t != "" {
				bodyParts = append(bodyParts, "<h2>"+esc(t)+"</h2>")
			}
		case "p":
			if t, ok := block["text"].(string); ok && t != "" {
				bodyParts = append(bodyParts, "<p>"+esc(t)+"</p>")
			}
		case "ul":
			if items, ok := block["items"].([]any); ok {
				var lis strings.Builder
				for _, it := range items {
					if s, ok := it.(string); ok {
						lis.WriteString("<li>" + esc(s) + "</li>")
					}
				}
				if lis.Len() > 0 {
					bodyParts = append(bodyParts, "<ul>"+lis.String()+"</ul>")
				}
			}
		}
	}

	jsonLD := map[string]any{
		"@context":         "https://schema.org",
		"@type":            "Article",
		"headline":         row.Title,
		"description":      row.Description,
		"datePublished":    row.Date,
		"dateModified":     row.Date,
		"author":           map[string]string{"@type": "Organization", "name": "Carver"},
		"publisher":        map[string]string{"@type": "Organization", "name": "Carver"},
		"mainEntityOfPage": canonical,
	}
	ldBytes, _ := json.Marshal(jsonLD)
	ldSafe := strings.ReplaceAll(string(ldBytes), "</", "<\\/")

	var b strings.Builder
	b.WriteString("<!doctype html>\n<html lang=\"en\">\n<head>\n")
	b.WriteString("<meta charset=\"UTF-8\" />\n")
	b.WriteString("<meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\" />\n")
	b.WriteString("<title>" + esc(row.Title+" — Carver") + "</title>\n")
	b.WriteString("<meta name=\"description\" content=\"" + esc(row.Description) + "\" />\n")
	b.WriteString("<link rel=\"canonical\" href=\"" + esc(canonical) + "\" />\n")
	b.WriteString("<meta property=\"og:type\" content=\"article\" />\n")
	b.WriteString("<meta property=\"og:title\" content=\"" + esc(row.Title+" — Carver") + "\" />\n")
	b.WriteString("<meta property=\"og:description\" content=\"" + esc(row.Description) + "\" />\n")
	b.WriteString("<meta property=\"og:url\" content=\"" + esc(canonical) + "\" />\n")
	b.WriteString("<script type=\"application/ld+json\">" + ldSafe + "</script>\n")
	b.WriteString("</head>\n<body>\n")
	b.WriteString("<nav><a href=\"/\">CARVER</a> · <a href=\"/articles\">Articles</a></nav>\n")
	b.WriteString("<main><article>\n")
	b.WriteString("<p class=\"crumbs\"><a href=\"/articles\">Articles</a> · <time>" + esc(row.Date) + "</time> · <span>")
	b.WriteString(itoa(art["read_minutes"]) + " min read</span></p>\n")
	b.WriteString("<h1>" + esc(row.Title) + "</h1>\n")
	b.WriteString("<p class=\"lede\">" + esc(row.Description) + "</p>\n")
	b.WriteString("<div class=\"body\">\n" + strings.Join(bodyParts, "\n") + "\n</div>\n")
	b.WriteString(renderRelated(related))
	b.WriteString("<footer><a href=\"/articles\">← All articles</a></footer>\n")
	b.WriteString("</article></main>\n</body>\n</html>\n")
	return b.String()
}

func renderRelated(related []models.Article) string {
	if len(related) == 0 {
		return ""
	}
	var b strings.Builder
	b.WriteString("<aside class=\"related\" aria-label=\"Related articles\"><h2>More reading</h2><ul>")
	for _, row := range related {
		href := "/articles/" + row.Slug
		b.WriteString("<li><a href=\"" + esc(href) + "\">" + esc(row.Title) + "</a>")
		b.WriteString("<span class=\"related-desc\">" + esc(row.Description) + "</span></li>")
	}
	b.WriteString("</ul></aside>")
	return b.String()
}

func renderArticlesListHTML(rows []models.Article) string {
	origin := siteOrigin()
	canonical := origin + "/articles"
	var b strings.Builder
	b.WriteString("<!doctype html>\n<html lang=\"en\">\n<head>\n<meta charset=\"UTF-8\" />\n")
	b.WriteString("<title>" + esc("Articles — Carver") + "</title>\n")
	b.WriteString("<link rel=\"canonical\" href=\"" + esc(canonical) + "\" />\n")
	b.WriteString("</head>\n<body>\n<nav><a href=\"/\">CARVER</a> · <a href=\"/articles\">Articles</a></nav>\n")
	b.WriteString("<main><h1>Articles for superyacht crew</h1>\n")
	if len(rows) == 0 {
		b.WriteString("<p class=\"empty\">No articles have been published yet. Please check back soon.</p>")
	} else {
		b.WriteString("<ul class=\"list\" aria-label=\"Articles\">\n")
		for _, row := range rows {
			href := "/articles/" + row.Slug
			b.WriteString("<li class=\"card\"><a href=\"" + esc(href) + "\">")
			b.WriteString("<p class=\"meta\"><time>" + esc(row.Date) + "</time> · <span>" + itoaInt(row.ReadMinutes) + " min read</span></p>")
			b.WriteString("<h2>" + esc(row.Title) + "</h2>")
			b.WriteString("<p class=\"desc\">" + esc(row.Description) + "</p>")
			b.WriteString("<span class=\"cta\">Read article →</span></a></li>\n")
		}
		b.WriteString("</ul>")
	}
	b.WriteString("</main>\n</body>\n</html>\n")
	return b.String()
}

func renderSitemap(rows []models.Article) string {
	origin := siteOrigin()
	var b strings.Builder
	b.WriteString("<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n")
	b.WriteString("<urlset xmlns=\"http://www.sitemaps.org/schemas/sitemap/0.9\">\n")
	for _, row := range rows {
		loc := origin + "/articles/" + row.Slug
		lastmod := row.Date
		if !row.UpdatedAt.IsZero() {
			lastmod = row.UpdatedAt.Format("2006-01-02")
		}
		b.WriteString("  <url>\n")
		b.WriteString("    <loc>" + esc(loc) + "</loc>\n")
		if lastmod != "" {
			b.WriteString("    <lastmod>" + esc(lastmod) + "</lastmod>\n")
		}
		b.WriteString("    <changefreq>monthly</changefreq>\n    <priority>0.7</priority>\n  </url>\n")
	}
	b.WriteString("</urlset>\n")
	return b.String()
}

func itoa(v any) string {
	if n, ok := v.(int); ok {
		return itoaInt(n)
	}
	return "3"
}

func itoaInt(n int) string {
	if n == 0 {
		return "0"
	}
	neg := n < 0
	if neg {
		n = -n
	}
	var buf [20]byte
	pos := len(buf)
	for n > 0 {
		pos--
		buf[pos] = byte('0' + n%10)
		n /= 10
	}
	if neg {
		pos--
		buf[pos] = '-'
	}
	return string(buf[pos:])
}
