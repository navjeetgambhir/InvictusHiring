-- Migration 006: store original filename when cover letter is uploaded as a file
ALTER TABLE candidate_applications
    ADD COLUMN IF NOT EXISTS cover_letter_filename VARCHAR(255);