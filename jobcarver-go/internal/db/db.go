// Package db opens the SQLite database (WAL mode), runs AutoMigrate, and seeds
// the default development user. Ports api/app/database.py + seed_users.py.
package db

import (
	stdlog "log"
	"os"
	"path/filepath"
	"strings"

	"github.com/glebarez/sqlite"
	"golang.org/x/crypto/bcrypt"
	"gorm.io/gorm"
	gormlogger "gorm.io/gorm/logger"

	"jobcarver/internal/config"
	"jobcarver/internal/models"
)

// DB is the process-wide GORM handle, set by Init.
var DB *gorm.DB

// dbPath resolves the SQLite file path: CARVER_SQLITE_PATH override, else
// data/carver.db relative to the working directory (mirrors database.py).
func dbPath() (string, error) {
	if override := strings.TrimSpace(os.Getenv("CARVER_SQLITE_PATH")); override != "" {
		abs, err := filepath.Abs(override)
		if err != nil {
			return "", err
		}
		if err := os.MkdirAll(filepath.Dir(abs), 0o755); err != nil {
			return "", err
		}
		return abs, nil
	}
	dir := filepath.Join("data")
	if err := os.MkdirAll(dir, 0o755); err != nil {
		return "", err
	}
	return filepath.Join(dir, "carver.db"), nil
}

// Init opens the database with WAL + busy_timeout pragmas and sets DB.
func Init() error {
	path, err := dbPath()
	if err != nil {
		return err
	}
	// _pragma query params are honoured by the glebarez/modernc driver.
	dsn := path + "?_pragma=journal_mode(WAL)&_pragma=busy_timeout(30000)&_pragma=foreign_keys(1)"

	level := gormlogger.Warn
	if config.S != nil && config.S.AppEnv == "production" {
		level = gormlogger.Error
	}
	// ErrRecordNotFound is normal control flow (get-or-create paths) — don't log it.
	gormLog := gormlogger.New(stdlog.New(os.Stderr, "", stdlog.LstdFlags), gormlogger.Config{
		LogLevel:                  level,
		IgnoreRecordNotFoundError: true,
		Colorful:                  config.S == nil || config.S.AppEnv != "production",
	})
	gdb, err := gorm.Open(sqlite.Open(dsn), &gorm.Config{
		Logger: gormLog,
	})
	if err != nil {
		return err
	}
	DB = gdb
	return nil
}

// AutoMigrate creates/updates all tables to match the model structs.
func AutoMigrate() error {
	return DB.AutoMigrate(models.AllModels()...)
}

// EnsureDefaultUser seeds a known crew test account in non-production envs
// (idempotent). Ports seed_users.ensure_default_user.
func EnsureDefaultUser() error {
	if config.S != nil && config.S.AppEnv == "production" {
		return nil
	}
	var existing models.User
	err := DB.Where("email = ?", "test@carver.local").First(&existing).Error
	if err == nil {
		return nil // already seeded
	}
	if err != gorm.ErrRecordNotFound {
		return err
	}
	hash, err := bcrypt.GenerateFromPassword([]byte("test1234"), bcrypt.DefaultCost)
	if err != nil {
		return err
	}
	phone := "+1-000-000-0000"
	nationality := "Unknown"
	years := 2
	loc := "Fort Lauderdale"
	user := models.User{
		Email:           "test@carver.local",
		FullName:        "Test Crew User",
		Role:            "crew",
		Phone:           &phone,
		Nationality:     &nationality,
		YearsExperience: &years,
		CurrentLocation: &loc,
		PasswordHash:    string(hash),
		IsActive:        true,
	}
	return DB.Create(&user).Error
}
