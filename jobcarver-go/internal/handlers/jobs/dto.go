package jobs

import (
	"net/http"
	"strings"
	"time"

	"jobcarver/internal/httpx"
	"jobcarver/internal/models"
)

// jobWrite carries the writable JobBase/JobUpdate fields. All pointers so PATCH
// can apply only the keys that were sent (model_dump(exclude_unset=True)).
type jobWrite struct {
	Title                   *string  `json:"title"`
	Role                    *string  `json:"role"`
	Yacht                   *string  `json:"yacht"`
	YachtType               *string  `json:"yacht_type"`
	YachtLengthM            *int     `json:"yacht_length_m"`
	VesselFlag              *string  `json:"vessel_flag"`
	VesselItinerary         *string  `json:"vessel_itinerary"`
	Department              *string  `json:"department"`
	RankLevel               *string  `json:"rank_level"`
	Location                *string  `json:"location"`
	StartDate               *string  `json:"start_date"`
	ContractType            *string  `json:"contract_type"`
	LeaveStructure          *string  `json:"leave_structure"`
	Rotation                *string  `json:"rotation"`
	Season                  *string  `json:"season"`
	SalaryCurrency          *string  `json:"salary_currency"`
	SalaryMin               *float64 `json:"salary_min"`
	SalaryMax               *float64 `json:"salary_max"`
	TipsBonus               *string  `json:"tips_bonus"`
	VisaSupport             *bool    `json:"visa_support"`
	Accommodation           *string  `json:"accommodation"`
	TravelReimbursement     *bool    `json:"travel_reimbursement"`
	ExperienceRequiredYears *int     `json:"experience_required_years"`
	MinimumLicense          *string  `json:"minimum_license"`
	CertificationsRequired  *string  `json:"certifications_required"`
	LanguagesRequired       *string  `json:"languages_required"`
	Description             *string  `json:"description"`
	Responsibilities        *string  `json:"responsibilities"`
	Requirements            *string  `json:"requirements"`
	Benefits                *string  `json:"benefits"`
	ContactEmail            *string  `json:"contact_email"`
	ApplicationURL          *string  `json:"application_url"`
	RecruiterName           *string  `json:"recruiter_name"`
	RecruiterAgency         *string  `json:"recruiter_agency"`
	UrgentHire              *bool    `json:"urgent_hire"`
	Status                  *string  `json:"status"`
	AutoApplyEnabled        *bool    `json:"auto_apply_enabled"`
}

// applyWrite copies the present fields of body onto job. Returns false (and
// writes the error) if validation fails. Mirrors the pydantic validators for
// status and contact_email.
func applyWrite(job *models.Job, body jobWrite, w http.ResponseWriter) bool {
	if body.Status != nil {
		if !validJobStatuses[*body.Status] {
			httpx.WriteError(w, http.StatusUnprocessableEntity, "Invalid status.", httpx.CRV1003)
			return false
		}
		job.Status = *body.Status
	}
	if body.Title != nil {
		job.Title = *body.Title
	}
	if body.Role != nil {
		job.Role = *body.Role
	}
	if body.Yacht != nil {
		job.Yacht = *body.Yacht
	}
	if body.Location != nil {
		job.Location = *body.Location
	}
	if body.YachtType != nil {
		job.YachtType = body.YachtType
	}
	if body.YachtLengthM != nil {
		job.YachtLengthM = body.YachtLengthM
	}
	if body.VesselFlag != nil {
		job.VesselFlag = body.VesselFlag
	}
	if body.VesselItinerary != nil {
		job.VesselItinerary = body.VesselItinerary
	}
	if body.Department != nil {
		job.Department = body.Department
	}
	if body.RankLevel != nil {
		job.RankLevel = body.RankLevel
	}
	if body.StartDate != nil {
		job.StartDate = body.StartDate
	}
	if body.ContractType != nil {
		job.ContractType = body.ContractType
	}
	if body.LeaveStructure != nil {
		job.LeaveStructure = body.LeaveStructure
	}
	if body.Rotation != nil {
		job.Rotation = body.Rotation
	}
	if body.Season != nil {
		job.Season = body.Season
	}
	if body.SalaryCurrency != nil {
		job.SalaryCurrency = body.SalaryCurrency
	}
	if body.SalaryMin != nil {
		job.SalaryMin = body.SalaryMin
	}
	if body.SalaryMax != nil {
		job.SalaryMax = body.SalaryMax
	}
	if body.TipsBonus != nil {
		job.TipsBonus = body.TipsBonus
	}
	if body.VisaSupport != nil {
		job.VisaSupport = *body.VisaSupport
	}
	if body.Accommodation != nil {
		job.Accommodation = body.Accommodation
	}
	if body.TravelReimbursement != nil {
		job.TravelReimbursement = *body.TravelReimbursement
	}
	if body.ExperienceRequiredYears != nil {
		job.ExperienceRequiredYears = body.ExperienceRequiredYears
	}
	if body.MinimumLicense != nil {
		job.MinimumLicense = body.MinimumLicense
	}
	if body.CertificationsRequired != nil {
		job.CertificationsRequired = body.CertificationsRequired
	}
	if body.LanguagesRequired != nil {
		job.LanguagesRequired = body.LanguagesRequired
	}
	if body.Description != nil {
		job.Description = body.Description
	}
	if body.Responsibilities != nil {
		job.Responsibilities = body.Responsibilities
	}
	if body.Requirements != nil {
		job.Requirements = body.Requirements
	}
	if body.Benefits != nil {
		job.Benefits = body.Benefits
	}
	if body.ContactEmail != nil {
		job.ContactEmail = normaliseContactEmail(body.ContactEmail)
	}
	if body.ApplicationURL != nil {
		job.ApplicationURL = body.ApplicationURL
	}
	if body.RecruiterName != nil {
		job.RecruiterName = body.RecruiterName
	}
	if body.RecruiterAgency != nil {
		job.RecruiterAgency = body.RecruiterAgency
	}
	if body.UrgentHire != nil {
		job.UrgentHire = *body.UrgentHire
	}
	if body.AutoApplyEnabled != nil {
		job.AutoApplyEnabled = *body.AutoApplyEnabled
	}
	return true
}

// normaliseContactEmail mirrors the JobBase contact_email validator: trim, and
// drop it (to nil) if it doesn't look like an email.
func normaliseContactEmail(v *string) *string {
	if v == nil {
		return nil
	}
	s := strings.TrimSpace(*v)
	if s == "" {
		return nil
	}
	if !emailRE.MatchString(strings.ToLower(s)) {
		return nil
	}
	return &s
}

// jobRead is the JobRead response shape (JobBase + id/source/timestamps).
type jobRead struct {
	ID                      int       `json:"id"`
	Title                   string    `json:"title"`
	Role                    string    `json:"role"`
	Yacht                   string    `json:"yacht"`
	YachtType               *string   `json:"yacht_type"`
	YachtLengthM            *int      `json:"yacht_length_m"`
	VesselFlag              *string   `json:"vessel_flag"`
	VesselItinerary         *string   `json:"vessel_itinerary"`
	Department              *string   `json:"department"`
	RankLevel               *string   `json:"rank_level"`
	Location                string    `json:"location"`
	StartDate               *string   `json:"start_date"`
	ContractType            *string   `json:"contract_type"`
	LeaveStructure          *string   `json:"leave_structure"`
	Rotation                *string   `json:"rotation"`
	Season                  *string   `json:"season"`
	SalaryCurrency          *string   `json:"salary_currency"`
	SalaryMin               *float64  `json:"salary_min"`
	SalaryMax               *float64  `json:"salary_max"`
	TipsBonus               *string   `json:"tips_bonus"`
	VisaSupport             bool      `json:"visa_support"`
	Accommodation           *string   `json:"accommodation"`
	TravelReimbursement     bool      `json:"travel_reimbursement"`
	ExperienceRequiredYears *int      `json:"experience_required_years"`
	MinimumLicense          *string   `json:"minimum_license"`
	CertificationsRequired  *string   `json:"certifications_required"`
	LanguagesRequired       *string   `json:"languages_required"`
	Description             *string   `json:"description"`
	Responsibilities        *string   `json:"responsibilities"`
	Requirements            *string   `json:"requirements"`
	Benefits                *string   `json:"benefits"`
	ContactEmail            *string   `json:"contact_email"`
	ApplicationURL          *string   `json:"application_url"`
	RecruiterName           *string   `json:"recruiter_name"`
	RecruiterAgency         *string   `json:"recruiter_agency"`
	UrgentHire              bool      `json:"urgent_hire"`
	Status                  string    `json:"status"`
	AutoApplyEnabled        bool      `json:"auto_apply_enabled"`
	Source                  *string   `json:"source"`
	CreatedAt               time.Time `json:"created_at"`
	UpdatedAt               time.Time `json:"updated_at"`
}

func toJobRead(j models.Job) jobRead {
	return jobRead{
		ID:                      j.ID,
		Title:                   j.Title,
		Role:                    j.Role,
		Yacht:                   j.Yacht,
		YachtType:               j.YachtType,
		YachtLengthM:            j.YachtLengthM,
		VesselFlag:              j.VesselFlag,
		VesselItinerary:         j.VesselItinerary,
		Department:              j.Department,
		RankLevel:               j.RankLevel,
		Location:                j.Location,
		StartDate:               j.StartDate,
		ContractType:            j.ContractType,
		LeaveStructure:          j.LeaveStructure,
		Rotation:                j.Rotation,
		Season:                  j.Season,
		SalaryCurrency:          j.SalaryCurrency,
		SalaryMin:               j.SalaryMin,
		SalaryMax:               j.SalaryMax,
		TipsBonus:               j.TipsBonus,
		VisaSupport:             j.VisaSupport,
		Accommodation:           j.Accommodation,
		TravelReimbursement:     j.TravelReimbursement,
		ExperienceRequiredYears: j.ExperienceRequiredYears,
		MinimumLicense:          j.MinimumLicense,
		CertificationsRequired:  j.CertificationsRequired,
		LanguagesRequired:       j.LanguagesRequired,
		Description:             j.Description,
		Responsibilities:        j.Responsibilities,
		Requirements:            j.Requirements,
		Benefits:                j.Benefits,
		ContactEmail:            j.ContactEmail,
		ApplicationURL:          j.ApplicationURL,
		RecruiterName:           j.RecruiterName,
		RecruiterAgency:         j.RecruiterAgency,
		UrgentHire:              j.UrgentHire,
		Status:                  j.Status,
		AutoApplyEnabled:        j.AutoApplyEnabled,
		Source:                  j.Source,
		CreatedAt:               j.CreatedAt,
		UpdatedAt:               j.UpdatedAt,
	}
}
