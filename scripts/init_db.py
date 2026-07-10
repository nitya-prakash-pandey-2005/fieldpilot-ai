import os
import asyncio
import asyncpg
from dotenv import load_dotenv

load_dotenv()

async def init_db():
    uri = os.getenv("POSTGRES_URI", "postgresql://atw_user:atw_dev_password@localhost:5432/askthewall")
    
    # Connect to default postgres to create database if not exists
    default_uri = uri.rsplit('/', 1)[0] + "/postgres"
    db_name = uri.rsplit('/', 1)[1]
    
    print(f"Connecting to Postgres to ensure DB '{db_name}' exists...")
    try:
        sys_conn = await asyncpg.connect(default_uri)
        # asyncpg doesn't support parameterized CREATE DATABASE
        db_exists = await sys_conn.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", db_name)
        if not db_exists:
            print(f"Creating database {db_name}...")
            await sys_conn.execute(f'CREATE DATABASE "{db_name}"')
        await sys_conn.close()
    except Exception as e:
        print(f"Failed to connect to Postgres server: {e}")
        print("Continuing assuming DB exists or is mocked...")
        
    print(f"Connecting to {db_name} to create tables...")
    try:
        conn = await asyncpg.connect(uri)
        
        await conn.execute('''
        CREATE TABLE IF NOT EXISTS notification_audit (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          notification_id UUID NOT NULL,
          incident_id UUID,
          severity VARCHAR NOT NULL,
          zone_id VARCHAR,
          asset_id VARCHAR,
          channels_attempted TEXT[],
          channels_delivered TEXT[],
          dispatch_results JSONB,
          mock_channels TEXT[],
          created_at TIMESTAMPTZ DEFAULT NOW()
        );
        ''')
        print("Successfully created notification_audit table.")

        await conn.execute('''
        CREATE TABLE IF NOT EXISTS resolved_incidents (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          incident_id UUID UNIQUE NOT NULL,
          project_id VARCHAR NOT NULL,
          zone_id VARCHAR NOT NULL,
          asset_type VARCHAR NOT NULL,
          issue_type VARCHAR NOT NULL,
          measurement_at_detection FLOAT,
          spec_value FLOAT,
          resolution JSONB NOT NULL,
          photos JSONB,
          outcome_metrics JSONB NOT NULL,
          tags TEXT[],
          created_at TIMESTAMPTZ DEFAULT NOW()
        );
        ''')
        print("Successfully created resolved_incidents table.")
        
        await conn.execute('''
        DROP TABLE IF EXISTS compliance_events;
        CREATE TABLE compliance_events (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          zone_id VARCHAR,
          asset_type VARCHAR,
          severity VARCHAR,
          measured_value FLOAT,
          spec_value FLOAT,
          deviation_pct FLOAT,
          worker_id VARCHAR,
          status VARCHAR DEFAULT 'open',
          created_at TIMESTAMPTZ DEFAULT NOW()
        );
        ''')
        print("Successfully created compliance_events table.")
        
        await conn.close()
    except Exception as e:
        print(f"Failed to create tables: {e}")

if __name__ == "__main__":
    asyncio.run(init_db())
