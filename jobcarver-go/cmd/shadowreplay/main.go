// Command shadowreplay replays a captured-traffic corpus (produced by the Python
// API's shadow_capture middleware) against a running jobcarver-go server and
// structurally diffs each response against what Python returned — surfacing
// routing gaps, 5xx crashes, auth divergence and shape mismatches before the Go
// port is promoted to production. See ../../SHADOW.md.
//
//	go run ./cmd/shadowreplay -corpus ../data/shadow_capture.jsonl -target http://localhost:3000
//
// IMPORTANT: run the target Go server against a snapshot of the production DB and
// with the SAME SECRET_KEY as production, so the minted sessions resolve to real
// users and validate. The tool reads SECRET_KEY/SESSION_COOKIE_NAME from the Go
// config (jobcarver-go/.env + env), exactly like the server.
package main

import (
	"bufio"
	"bytes"
	"context"
	"encoding/base64"
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"net/http"
	"os"
	"sort"
	"strings"
	"sync"
	"time"

	"jobcarver/internal/config"
	"jobcarver/internal/security"
)

type options struct {
	corpus      string
	target      string
	report      string
	concurrency int
	timeout     time.Duration
	limit       int
	mintAuth    bool
	failOn      string
}

func main() {
	opt := options{}
	flag.StringVar(&opt.corpus, "corpus", "data/shadow_capture.jsonl", "path to the capture JSONL corpus")
	flag.StringVar(&opt.target, "target", "http://localhost:3000", "base URL of the Go server to replay against")
	flag.StringVar(&opt.report, "report", "data/shadow_report.jsonl", "path to write the per-request JSONL report")
	flag.IntVar(&opt.concurrency, "concurrency", 4, "number of concurrent replay workers")
	flag.DurationVar(&opt.timeout, "timeout", 30*time.Second, "per-request timeout")
	flag.IntVar(&opt.limit, "limit", 0, "max records to replay (0 = all)")
	flag.BoolVar(&opt.mintAuth, "mint-auth", true, "mint a native Go session+CSRF for the captured principal")
	flag.StringVar(&opt.failOn, "fail-on", "critical", "exit non-zero when issues at/above this severity exist: none|warn|critical")
	flag.Parse()

	config.Load() // SECRET_KEY, SESSION_COOKIE_NAME, SESSION_TTL — same as the server.

	records, err := loadCorpus(opt.corpus, opt.limit)
	if err != nil {
		fmt.Fprintf(os.Stderr, "shadowreplay: %v\n", err)
		os.Exit(2)
	}
	if len(records) == 0 {
		fmt.Fprintln(os.Stderr, "shadowreplay: corpus is empty — capture some traffic first")
		os.Exit(2)
	}

	fmt.Printf("Replaying %d requests against %s (concurrency=%d, mint-auth=%v)\n\n",
		len(records), opt.target, opt.concurrency, opt.mintAuth)

	results := run(opt, records)

	if err := writeReport(opt.report, results); err != nil {
		fmt.Fprintf(os.Stderr, "shadowreplay: failed to write report: %v\n", err)
	}
	printSummary(results, opt.report)

	os.Exit(exitCode(results, opt.failOn))
}

// loadCorpus reads and parses the JSONL capture file.
func loadCorpus(path string, limit int) ([]*captureRecord, error) {
	f, err := os.Open(path)
	if err != nil {
		return nil, fmt.Errorf("open corpus %q: %w", path, err)
	}
	defer f.Close()

	var out []*captureRecord
	sc := bufio.NewScanner(f)
	sc.Buffer(make([]byte, 0, 1024*1024), 16*1024*1024) // allow large lines
	line := 0
	for sc.Scan() {
		line++
		raw := bytes.TrimSpace(sc.Bytes())
		if len(raw) == 0 {
			continue
		}
		var rec captureRecord
		if err := json.Unmarshal(raw, &rec); err != nil {
			fmt.Fprintf(os.Stderr, "warn: skipping malformed corpus line %d: %v\n", line, err)
			continue
		}
		out = append(out, &rec)
		if limit > 0 && len(out) >= limit {
			break
		}
	}
	return out, sc.Err()
}

// run replays all records through a fixed worker pool, preserving input order
// in the results slice.
func run(opt options, records []*captureRecord) []diffResult {
	client := &http.Client{
		Timeout: opt.timeout,
		// Don't follow redirects — we want to compare the raw status (301/302/etc).
		CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse },
	}

	results := make([]diffResult, len(records))
	jobs := make(chan int)
	var wg sync.WaitGroup
	var done int
	var mu sync.Mutex

	for w := 0; w < opt.concurrency; w++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			for i := range jobs {
				results[i] = replayOne(client, opt, records[i])
				mu.Lock()
				done++
				if done%50 == 0 || done == len(records) {
					fmt.Printf("\r  replayed %d/%d", done, len(records))
				}
				mu.Unlock()
			}
		}()
	}
	for i := range records {
		jobs <- i
	}
	close(jobs)
	wg.Wait()
	fmt.Print("\r")
	return results
}

// headers we never copy from the corpus onto the replay request.
var skipHeaders = map[string]bool{
	"host": true, "content-length": true, "cookie": true,
	"x-csrf-token": true, "accept-encoding": true, "connection": true,
}

// replayOne issues one captured request against the Go target and classifies it.
func replayOne(client *http.Client, opt options, rec *captureRecord) diffResult {
	var body []byte
	if rec.BodyB64 != "" {
		if b, err := base64.StdEncoding.DecodeString(rec.BodyB64); err == nil {
			body = b
		}
	}

	url := strings.TrimRight(opt.target, "/") + rec.Path
	if rec.Query != "" {
		url += "?" + rec.Query
	}

	ctx, cancel := context.WithTimeout(context.Background(), opt.timeout)
	defer cancel()

	req, err := http.NewRequestWithContext(ctx, rec.Method, url, bytes.NewReader(body))
	if err != nil {
		return classify(rec, fmt.Errorf("build request: %w", err), 0, "", nil)
	}
	for k, v := range rec.Headers {
		if !skipHeaders[strings.ToLower(k)] {
			req.Header.Set(k, v)
		}
	}
	req.Header.Set("Accept-Encoding", "identity")
	req.Header.Set("X-Shadow-Replay", "1") // lets the Go server tag/ignore shadow traffic

	if opt.mintAuth {
		applyAuth(req, rec)
	}

	resp, err := client.Do(req)
	if err != nil {
		return classify(rec, err, 0, "", nil)
	}
	defer resp.Body.Close()
	goBody, _ := io.ReadAll(io.LimitReader(resp.Body, 1<<20))
	return classify(rec, nil, resp.StatusCode, resp.Header.Get("Content-Type"), goBody)
}

// applyAuth mints a native Go session for the captured principal and a fresh
// CSRF token for mutating requests, so auth is genuinely exercised on the Go
// side despite Python and Go using different session-token formats.
func applyAuth(req *http.Request, rec *captureRecord) {
	if len(rec.Principal) > 0 && !bytes.Equal(rec.Principal, []byte("null")) {
		var sess security.Session
		if err := json.Unmarshal(rec.Principal, &sess); err == nil && (sess.Sub != "" || sess.UserID != 0) {
			if tok, err := security.IssueSessionToken(sess); err == nil {
				req.AddCookie(&http.Cookie{Name: config.S.SessionCookieName, Value: tok})
			}
		}
	}
	switch req.Method {
	case http.MethodPost, http.MethodPut, http.MethodPatch, http.MethodDelete:
		req.Header.Set(security.CSRFHeaderName, security.GenerateCSRFToken())
	}
}

func writeReport(path string, results []diffResult) error {
	f, err := os.Create(path)
	if err != nil {
		return err
	}
	defer f.Close()
	w := bufio.NewWriter(f)
	defer w.Flush()
	enc := json.NewEncoder(w)
	for i := range results {
		if err := enc.Encode(results[i]); err != nil {
			return err
		}
	}
	return nil
}

// severityRank orders severities for fail-on gating.
var severityRank = map[string]int{sevOK: 0, sevInfo: 1, sevWarn: 2, sevCritical: 3}

func printSummary(results []diffResult, reportPath string) {
	byBucket := map[string]int{}
	bySeverity := map[string]int{}
	examples := map[string][]string{} // bucket -> "METHOD path" samples
	for _, r := range results {
		byBucket[r.Bucket]++
		bySeverity[r.Severity]++
		if r.Severity == sevCritical || r.Severity == sevWarn {
			key := r.Method + " " + r.Path
			if len(examples[r.Bucket]) < 10 && !contains(examples[r.Bucket], key) {
				examples[r.Bucket] = append(examples[r.Bucket], key)
			}
		}
	}

	fmt.Printf("── Shadow replay summary (%d requests) ──\n\n", len(results))

	order := []string{
		bucketTransportError, bucketGo5xx, bucketRoutingGap,
		bucketAuthDivergence, bucketStatusClass, bucketContentType, bucketBadJSON,
		bucketNotImplemented, bucketOK,
	}
	for _, b := range order {
		n := byBucket[b]
		if n == 0 {
			continue
		}
		fmt.Printf("  %-22s %5d  [%s]\n", b, n, bucketSeverity[b])
	}

	// Detail the actionable buckets.
	fmt.Println()
	for _, b := range order {
		if bucketSeverity[b] == sevOK || bucketSeverity[b] == sevInfo {
			continue
		}
		if len(examples[b]) == 0 {
			continue
		}
		fmt.Printf("  %s — sample endpoints:\n", b)
		paths := examples[b]
		sort.Strings(paths)
		for _, p := range paths {
			fmt.Printf("      %s\n", p)
		}
	}

	fmt.Printf("\n  severity totals: critical=%d warn=%d info=%d ok=%d\n",
		bySeverity[sevCritical], bySeverity[sevWarn], bySeverity[sevInfo], bySeverity[sevOK])
	fmt.Printf("  full report: %s\n", reportPath)
}

func exitCode(results []diffResult, failOn string) int {
	threshold, ok := severityRank[failOn]
	if !ok || failOn == "none" {
		return 0
	}
	worst := 0
	for _, r := range results {
		if rank := severityRank[r.Severity]; rank > worst {
			worst = rank
		}
	}
	if worst >= threshold {
		return 1
	}
	return 0
}

func contains(s []string, v string) bool {
	for _, x := range s {
		if x == v {
			return true
		}
	}
	return false
}
