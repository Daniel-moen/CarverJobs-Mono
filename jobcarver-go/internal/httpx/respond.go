package httpx

import (
	"encoding/json"
	"errors"
	"io"
	"net/http"
)

// JSON writes v as a JSON response with the given status code.
func JSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	if v == nil {
		return
	}
	_ = json.NewEncoder(w).Encode(v)
}

// errorBody is the standard error envelope: {"detail":..,"code":..}.
type errorBody struct {
	Detail string `json:"detail"`
	Code   string `json:"code"`
}

// WriteError writes a CRV error envelope. If code is empty, it falls back to the
// status-code mapping (then CRV-1006).
func WriteError(w http.ResponseWriter, status int, detail, code string) {
	if code == "" {
		if mapped, ok := StatusCodeToCRV[status]; ok {
			code = mapped
		} else {
			code = CRV1006
		}
	}
	JSON(w, status, errorBody{Detail: detail, Code: code})
}

// Decode reads and JSON-decodes the request body into dst. Rejects unknown
// fields and empty bodies.
func Decode(r *http.Request, dst any) error {
	if r.Body == nil {
		return errors.New("empty request body")
	}
	dec := json.NewDecoder(r.Body)
	if err := dec.Decode(dst); err != nil {
		if errors.Is(err, io.EOF) {
			return errors.New("empty request body")
		}
		return err
	}
	return nil
}
