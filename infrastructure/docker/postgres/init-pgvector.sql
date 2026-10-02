-- Initialization script for PostgreSQL in YAVURA
-- Enable pgvector extension for future vector embeddings & knowledge retrieval

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "vector";

-- Log completion
DO $$
BEGIN
    RAISE NOTICE 'YAVURA database extensions initialized: uuid-ossp and vector';
END $$;
