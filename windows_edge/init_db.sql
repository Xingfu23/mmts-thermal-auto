-- 1. Prepare a list of sensor types (if it does not already exist).  
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'sensor_kind') THEN
        CREATE TYPE sensor_kind AS ENUM ('RTD', 'DMT', 'OTHER');
    END IF;
END $$;

-- 2. Create a table named 'detector'.  
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
    ('RTD-A01', 'RTD'), ('RTD-A02', 'RTD'),
    ('DMT-01', 'DMT'), ('DMT-02', 'DMT'),
    ('Chiller-01', 'OTHER'), ('Chiller-T', 'OTHER'), ('Chiller-PrevT', 'OTHER'),
    ('System Status', 'OTHER')
ON CONFLICT (sensor_id) DO NOTHING;

-- 6. Create function to calculate Relative Humidity (%) from Air Temp (°C) and Dew Point (°C).
CREATE OR REPLACE FUNCTION public.rh_from_t_td_c(t_c numeric, td_c numeric)
 RETURNS numeric
 LANGUAGE sql
 IMMUTABLE
AS $function$
  SELECT 100 * exp(17.625*td_c/(243.04+td_c)) / exp(17.625*t_c/(243.04+t_c));
$function$;

-- 7. Create 1-minute rolling average view for ambient air temperature.
--    Prefers ambient sensors (RTD-A01, RTD-A02); falls back to RTD-01, RTD-02 if absent.
CREATE OR REPLACE VIEW public.avg1m_air_temperature AS
 SELECT date_trunc('minute'::text, m.measured_at) AS bucket_min,
    COALESCE(
        avg(m.value) FILTER (WHERE m.sensor_id IN ('RTD-A01', 'RTD-A02')),
        avg(m.value) FILTER (WHERE m.sensor_id IN ('RTD-01', 'RTD-02'))
    ) AS avg_air_temp_c
   FROM measurement m
     JOIN detector d USING (sensor_id)
  WHERE m.sensor_id IN ('RTD-A01', 'RTD-A02', 'RTD-01', 'RTD-02')
    AND m.metric = 'temperature_C'
    AND m.value >= -100.0
  GROUP BY (date_trunc('minute'::text, m.measured_at));

-- 8. Create 1-minute rolling average view for dew point temperature.
CREATE OR REPLACE VIEW public.avg1m_dewpoint AS
 SELECT date_trunc('minute'::text, m.measured_at) AS bucket_min,
    avg(m.value) AS avg_dewpoint_c
   FROM measurement m
     JOIN detector d USING (sensor_id)
  WHERE d.kind = 'DMT'::sensor_kind
    AND m.metric = 'dewpoint_C'
  GROUP BY (date_trunc('minute'::text, m.measured_at));

-- 9. Create combined view for ambient air temperature, dew point, and relative humidity.
CREATE OR REPLACE VIEW public.avg1m_air_humidity AS
 SELECT a.bucket_min,
    a.avg_air_temp_c,
    d.avg_dewpoint_c,
    rh_from_t_td_c(a.avg_air_temp_c, d.avg_dewpoint_c) AS avg_air_rh_pct
   FROM avg1m_air_temperature a
     JOIN avg1m_dewpoint d USING (bucket_min);