// Package documents ports api/app/routes/documents.py — upload / list / delete /
// download of crew documents. AI document scanning is out of scope for the Go
// port (see TODO below); everything else (validation, storage, metadata) is kept.
package documents

import (
	"crypto/rand"
	"encoding/hex"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"time"

	"github.com/go-chi/chi/v5"

	"jobcarver/internal/config"
	"jobcarver/internal/db"
	"jobcarver/internal/httpx"
	"jobcarver/internal/metrics"
	"jobcarver/internal/models"
	"jobcarver/internal/security"
)

var validDocTypes = map[string]bool{
	"cv": true, "references": true, "passport": true, "stcw": true, "eng1": true, "photo": true,
}

var allowedExtensions = map[string]bool{
	".pdf": true, ".doc": true, ".docx": true, ".jpg": true, ".jpeg": true, ".png": true,
}

var allowedMimeTypes = map[string]bool{
	"application/pdf": true,
	"application/msword": true,
	"application/vnd.openxmlformats-officedocument.wordprocessingml.document": true,
	"image/jpeg": true,
	"image/png":  true,
}

// Register mounts /documents (all routes require a session).
func Register(r chi.Router) {
	r.Route("/documents", func(r chi.Router) {
		r.Use(security.RequireSession)
		r.Get("/", list)
		r.Post("/{docType}", upload)
		r.Delete("/{docType}", remove)
		r.Get("/{docType}/file", download)
	})
}

func uploadDir() string {
	dir := config.S.UploadDir
	_ = os.MkdirAll(dir, 0o755)
	return dir
}

func getDoc(userKey, docType string) (models.Document, bool) {
	var doc models.Document
	if err := db.DB.Where("user_key = ? AND doc_type = ?", userKey, docType).First(&doc).Error; err != nil {
		return models.Document{}, false
	}
	return doc, true
}

func list(w http.ResponseWriter, r *http.Request) {
	sess := security.SessionFromContext(r.Context())
	var docs []models.Document
	db.DB.Where("user_key = ?", sess.Sub).Find(&docs)
	out := map[string]any{}
	for _, d := range docs {
		out[d.DocType] = map[string]any{
			"original_name": d.OriginalName,
			"uploaded_at":   d.CreatedAt.Format(time.RFC3339),
			"scanned":       d.ScannedText != nil,
		}
	}
	httpx.JSON(w, http.StatusOK, out)
}

func upload(w http.ResponseWriter, r *http.Request) {
	sess := security.SessionFromContext(r.Context())
	userKey := sess.Sub
	docType := chi.URLParam(r, "docType")

	if !validDocTypes[docType] {
		httpx.WriteError(w, http.StatusBadRequest,
			"Invalid doc_type. Must be one of: cv, references, passport, stcw, eng1, photo", "")
		return
	}

	file, header, err := r.FormFile("file")
	if err != nil {
		httpx.WriteError(w, http.StatusBadRequest, "Missing file.", "")
		return
	}
	defer file.Close()

	suffix := strings.ToLower(filepath.Ext(header.Filename))
	if !allowedExtensions[suffix] {
		httpx.WriteError(w, http.StatusBadRequest,
			"File type not allowed. Accepted: .pdf, .doc, .docx, .jpg, .jpeg, .png", "")
		return
	}
	if ct := header.Header.Get("Content-Type"); ct != "" && !allowedMimeTypes[ct] {
		httpx.WriteError(w, http.StatusBadRequest, "MIME type not allowed.", "")
		return
	}

	contents, err := io.ReadAll(io.LimitReader(file, config.S.UploadMaxBytes+1))
	if err != nil {
		httpx.WriteError(w, http.StatusBadRequest, "Could not read file.", "")
		return
	}
	if int64(len(contents)) > config.S.UploadMaxBytes {
		httpx.WriteError(w, http.StatusRequestEntityTooLarge,
			fmt.Sprintf("File exceeds %d MB limit.", config.S.UploadMaxBytes/(1024*1024)), "")
		return
	}
	if len(contents) == 0 {
		httpx.WriteError(w, http.StatusBadRequest, "Empty file.", "")
		return
	}

	dir := uploadDir()
	originalName := header.Filename
	if originalName == "" {
		originalName = "upload"
	}

	// TODO(go-port): the Python route kicks off an async AI document scan
	// (scan_document) that fills `scanned_text`. AI scanning is out of scope for
	// the Go port, so scanned_text is left nil ("[scan pending]").

	if existing, ok := getDoc(userKey, docType); ok {
		_ = os.Remove(filepath.Join(dir, existing.StoredName))
		existing.OriginalName = originalName
		existing.StoredName = newStoredName(suffix)
		existing.ScannedText = nil
		if err := os.WriteFile(filepath.Join(dir, existing.StoredName), contents, 0o644); err != nil {
			httpx.WriteError(w, http.StatusInternalServerError, "Could not store file.", httpx.CRV1006)
			return
		}
		db.DB.Save(&existing)
		metrics.Increment("doc_uploads")
		httpx.JSON(w, http.StatusOK, map[string]any{"ok": true, "original_name": existing.OriginalName})
		return
	}

	storedName := newStoredName(suffix)
	if err := os.WriteFile(filepath.Join(dir, storedName), contents, 0o644); err != nil {
		httpx.WriteError(w, http.StatusInternalServerError, "Could not store file.", httpx.CRV1006)
		return
	}
	doc := models.Document{
		UserKey:      userKey,
		DocType:      docType,
		OriginalName: originalName,
		StoredName:   storedName,
	}
	if err := db.DB.Create(&doc).Error; err != nil {
		httpx.WriteError(w, http.StatusInternalServerError, "Could not save document.", httpx.CRV1002)
		return
	}
	metrics.Increment("doc_uploads")
	httpx.JSON(w, http.StatusOK, map[string]any{"ok": true, "original_name": doc.OriginalName})
}

func remove(w http.ResponseWriter, r *http.Request) {
	sess := security.SessionFromContext(r.Context())
	docType := chi.URLParam(r, "docType")
	if !validDocTypes[docType] {
		httpx.WriteError(w, http.StatusBadRequest, "Invalid doc_type.", "")
		return
	}
	doc, ok := getDoc(sess.Sub, docType)
	if !ok {
		httpx.WriteError(w, http.StatusNotFound, "Document not found.", "")
		return
	}
	_ = os.Remove(filepath.Join(uploadDir(), doc.StoredName))
	db.DB.Delete(&doc)
	metrics.Increment("doc_deletes")
	httpx.JSON(w, http.StatusOK, map[string]any{"ok": true})
}

func download(w http.ResponseWriter, r *http.Request) {
	sess := security.SessionFromContext(r.Context())
	docType := chi.URLParam(r, "docType")
	if !validDocTypes[docType] {
		httpx.WriteError(w, http.StatusBadRequest, "Invalid doc_type.", "")
		return
	}
	doc, ok := getDoc(sess.Sub, docType)
	if !ok {
		httpx.WriteError(w, http.StatusNotFound, "Document not found.", "")
		return
	}

	dir, _ := filepath.Abs(uploadDir())
	filePath, _ := filepath.Abs(filepath.Join(dir, doc.StoredName))
	if !strings.HasPrefix(filePath, dir) {
		httpx.WriteError(w, http.StatusBadRequest, "Invalid file path.", "")
		return
	}
	if _, err := os.Stat(filePath); err != nil {
		httpx.WriteError(w, http.StatusNotFound, "File missing on server.", "")
		return
	}
	metrics.Increment("doc_downloads")
	w.Header().Set("Content-Type", "application/octet-stream")
	w.Header().Set("Content-Disposition", fmt.Sprintf("attachment; filename=%q", doc.OriginalName))
	http.ServeFile(w, r, filePath)
}

func newStoredName(suffix string) string {
	b := make([]byte, 16)
	_, _ = rand.Read(b)
	return hex.EncodeToString(b) + suffix
}
