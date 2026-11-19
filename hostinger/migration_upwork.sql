-- Run once in phpMyAdmin (database u832514355_smart_leads).

-- 1) per-source counter for the dashboard (ingest.php fills it once the column exists)
ALTER TABLE `scraper_runs`
  ADD COLUMN `upwork_count` int(11) NOT NULL DEFAULT 0 AFTER `wellfound_count`;

-- 2) allow scheduling Upwork on its own (matches the other source rows)
INSERT INTO `scraper_source_schedules` (`source_scope`, `enabled`, `schedule_time`, `target_new_jobs`)
VALUES ('upwork', 0, '13:30:00', NULL)
ON DUPLICATE KEY UPDATE `source_scope` = `source_scope`;

-- 3) new meaning of "target": MINIMUM LEADS PER SOURCE (was total jobs). 50 x 4 sources = 200.
--    Runtime in minutes: 240 (4 hours).
UPDATE `scraper_settings`
SET `target_new_jobs` = 50, `max_runtime_minutes` = 240
WHERE `id` = 1;

-- 4) fast "new leads today" query used by daily-count.php
ALTER TABLE `scraped_jobs` ADD KEY `idx_scraped_jobs_created` (`created_at`);
