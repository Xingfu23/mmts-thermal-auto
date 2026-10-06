-- 1. Prepare a list of sensor types (if it does not already exist).  
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'sensor_kind') THEN
        CREATE TYPE sensor_kind AS ENUM ('RTD', 'DMT', 'OTHER');
    END IF;
END $$;

--2. Create a table named 'detector'.  
CREATE TABLE IF NOT EXISTS detector (
    sensor_id VARCHAR(16) PRIMARY KEY, -- example: RTD-01, Chiller-01
    kind      sensor_kind NOT NULL,    -- sensor's type
    active    BOOLEAN NOT NULL DEFAULT TRUE
);

-- 3. Create a table named 'measurement' to record values from the detector or system in a time series format.  
CREATE TABLE IF NOT EXISTS measurement (
    id          BIGSERIAL PRIMARY KEY,
    sensor_id   VARCHAR(16) REFERENCES detector(sensor_id),
    metric      TEXT NOT NULL,       
    value       NUMERIC(10,4) NOT NULL,
    measured_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 4. Add an index to facilitate searching.
CREATE INDEX IF NOT EXISTS idx_measurement_sensor_time ON measurement (sensor_id, measured_at);
CREATE INDEX IF NOT EXISTS idx_measurement_time ON measurement (measured_at);

-- 5. Insert the list of sensors that have been installed in the system.   
INSERT INTO detector (sensor_id, kind) VALUES
    ('RTD-01', 'RTD'), ('RTD-02', 'RTD'), ('RTD-03', 'RTD'), ('RTD-04', 'RTD'),
    ('RTD-05', 'RTD'), ('RTD-06', 'RTD'), ('RTD-07', 'RTD'), ('RTD-08', 'RTD'),
    ('DMT-01', 'DMT'), ('DMT-02', 'DMT'),
    ('Chiller-01', 'OTHER'), ('Chiller-T', 'OTHER'), ('Chiller-PrevT', 'OTHER'),
    ('System Status', 'OTHER')
ON CONFLICT (sensor_id) DO NOTHING;