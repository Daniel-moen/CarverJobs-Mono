package main

import (
	"encoding/json"
	"strings"
)

// captureRecord is one line of the capture corpus written by the Python
// shadow_capture middleware (api/app/shadow_capture.py). Field names/shape must
// stay in sync with that writer.
type captureRecord struct {
	TS            string            `json:"ts"`
	RequestID     string            `json:"request_id"`
	Method        string            `json:"method"`
	Path          string            `json:"path"`
	Query         string            `json:"query"`
	Headers       map[string]string `json:"headers"`
	BodyB64       string            `json:"body_b64"`
	BodyTruncated bool              `json:"body_truncated"`
	BodyRedacted  bool              `json:"body_redacted"`
	Principal     json.RawMessage   `json:"principal"`
	Response      struct {
		Status      int    `json:"status"`
		ContentType string `json:"content_type"`
		BodyB64     string `json:"body_b64"`
	} `json:"response"`
}

// Severity buckets for the summary + exit-code gating.
const (
	sevOK       = "ok"
	sevInfo     = "info"
	sevWarn     = "warn"
	sevCritical = "critical"
)

// Issue buckets, in priority order (first match wins).
const (
	bucketTransportError = "transport_error" // could not reach Go at all
	bucketNotImplemented = "not_implemented" // Go returned 501 (known stub)
	bucketGo5xx          = "go_5xx"          // Go crashed where Python didn't
	bucketRoutingGap     = "routing_gap"     // Go 404/405, Python routed it
	bucketAuthDivergence = "auth_divergence" // 401/403 on exactly one side
	bucketStatusClass    = "status_class_mismatch"
	bucketContentType    = "content_type_mismatch"
	bucketBadJSON        = "bad_json" // Go claims JSON but body won't parse
	bucketOK             = "ok"
)

var bucketSeverity = map[string]string{
	bucketTransportError: sevCritical,
	bucketGo5xx:          sevCritical,
	bucketRoutingGap:     sevCritical,
	bucketNotImplemented: sevInfo,
	bucketAuthDivergence: sevWarn,
	bucketStatusClass:    sevWarn,
	bucketContentType:    sevWarn,
	bucketBadJSON:        sevWarn,
	bucketOK:             sevOK,
}

// diffResult is the per-request outcome written to the report.
type diffResult struct {
	Method   string `json:"method"`
	Path     string `json:"path"`
	PyStatus int    `json:"py_status"`
	GoStatus int    `json:"go_status"`
	Bucket   string `json:"bucket"`
	Severity string `json:"severity"`
	Note     string `json:"note"`
	ReqID    string `json:"request_id,omitempty"`
}

func statusClass(code int) int { return code / 100 }

func isJSONType(ct string) bool { return strings.Contains(strings.ToLower(ct), "json") }

// classify compares Go's response against the captured Python response.
//   - transportErr: non-nil when the request to Go failed outright.
//   - goStatus/goCT/goBody: Go's response (only when transportErr == nil).
func classify(rec *captureRecord, transportErr error, goStatus int, goCT string, goBody []byte) diffResult {
	res := diffResult{
		Method: rec.Method, Path: rec.Path,
		PyStatus: rec.Response.Status, GoStatus: goStatus, ReqID: rec.RequestID,
	}
	py := rec.Response.Status

	bucket, note := func() (string, string) {
		if transportErr != nil {
			return bucketTransportError, transportErr.Error()
		}
		if goStatus == 501 {
			return bucketNotImplemented, "Go endpoint stubbed (501)"
		}
		if goStatus >= 500 && py < 500 {
			return bucketGo5xx, "Go 5xx where Python succeeded/errored client-side"
		}
		if (goStatus == 404 || goStatus == 405) && py != 404 && py != 405 {
			return bucketRoutingGap, "Go did not route a request Python handled"
		}
		goAuth := goStatus == 401 || goStatus == 403
		pyAuth := py == 401 || py == 403
		if goAuth != pyAuth {
			if goAuth {
				return bucketAuthDivergence, "Go rejected auth/CSRF that Python accepted"
			}
			return bucketAuthDivergence, "Go accepted a request Python rejected on auth"
		}
		// Both 5xx → Python was already erroring; not a regression.
		if goStatus >= 500 && py >= 500 {
			return bucketOK, "both 5xx"
		}
		if statusClass(goStatus) != statusClass(py) {
			return bucketStatusClass, "status class differs"
		}
		// Same class from here. Check JSON validity + content type for 2xx.
		if isJSONType(goCT) && len(goBody) > 0 && !json.Valid(goBody) {
			return bucketBadJSON, "Go content-type is JSON but body is not valid JSON"
		}
		if statusClass(py) == 2 && py != 0 {
			pyJSON := isJSONType(rec.Response.ContentType)
			goJSON := isJSONType(goCT)
			if rec.Response.ContentType != "" && goCT != "" && pyJSON != goJSON {
				return bucketContentType, "content-type family differs (json vs non-json)"
			}
		}
		return bucketOK, ""
	}()

	res.Bucket = bucket
	res.Severity = bucketSeverity[bucket]
	res.Note = note
	return res
}
