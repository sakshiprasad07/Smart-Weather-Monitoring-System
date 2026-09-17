-- Run this once against your MySQL instance (local or RDS) to set up manually.
-- The dashboard also auto-creates this table on first run via init_db(),
-- so this file is mainly here for RDS setup / documentation.

CREATE DATABASE IF NOT EXISTS weather_monitor;
USE weather_monitor;

CREATE TABLE IF NOT EXISTS weather_records (
    id INT AUTO_INCREMENT PRIMARY KEY,
    location VARCHAR(100) NOT NULL,
    metric VARCHAR(50) NOT NULL,
    value FLOAT NOT NULL,
    recorded_at DATETIME NOT NULL,
    INDEX idx_location_metric (location, metric, recorded_at)
);