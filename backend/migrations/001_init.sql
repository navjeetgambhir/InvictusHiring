-- Run this once against your PostgreSQL database before starting the server

CREATE EXTENSION IF NOT EXISTS vector;

-- Tables are auto-created by SQLAlchemy on startup via Base.metadata.create_all
-- This migration only handles the pgvector extension which cannot be created by SQLAlchemy
