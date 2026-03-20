-- PostgreSQL setup for PMC backend (matches backend/settings.py defaults)
-- Run in psql as superuser, or pgAdmin Query Tool.
--
-- Django defaults: DB_USER=postgres, DB_PASSWORD=root, DB_NAME=pmc_db

-- Align postgres user password with Django (local dev only)
ALTER USER postgres WITH PASSWORD 'root';

-- Create database (skip error if it already exists)
CREATE DATABASE pmc_db;

-- Connect to the database (in psql: \c pmc_db)

-- (Optional) Create a dedicated user for better security
CREATE USER pmc_user WITH PASSWORD 'your_secure_password_here';

-- Grant privileges
GRANT ALL PRIVILEGES ON DATABASE pmc_db TO pmc_user;

-- Grant schema privileges (run after connecting to pmc_db)
-- \c pmc_db
-- GRANT ALL ON SCHEMA public TO pmc_user;
