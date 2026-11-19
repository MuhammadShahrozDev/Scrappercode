<?php
declare(strict_types=1);

require_once dirname(__DIR__, 4) . '/src/bootstrap.php';

use App\Database;
use App\LeadAssignmentService;

function ingest_json(mixed $value): ?string
{
    if ($value === null || $value === '') {
        return null;
    }

    if (is_string($value)) {
        $trimmed = trim($value);
        if ($trimmed === '') {
            return null;
        }

        json_decode($trimmed, true);
        if (json_last_error() === JSON_ERROR_NONE) {
            return $trimmed;
        }
    }

    $json = json_encode(
        $value,
        JSON_UNESCAPED_SLASHES |
        JSON_UNESCAPED_UNICODE |
        JSON_INVALID_UTF8_SUBSTITUTE
    );

    return $json === false ? null : $json;
}

function ingest_decimal(mixed $value): ?float
{
    if ($value === null || $value === '') {
        return null;
    }

    if (is_int($value) || is_float($value)) {
        return (float)$value;
    }

    $text = trim((string)$value);
    if ($text === '') {
        return null;
    }

    if (preg_match('/-?\d+(?:\.\d+)?/', $text, $m)) {
        return (float)$m[0];
    }

    return null;
}

function ingest_bool(mixed $value): ?int
{
    if ($value === null || $value === '') {
        return null;
    }

    if (is_bool($value)) {
        return $value ? 1 : 0;
    }

    if (is_numeric($value)) {
        return ((int)$value) !== 0 ? 1 : 0;
    }

    $text = strtolower(trim((string)$value));

    if (in_array($text, ['yes', 'true', 'remote', '1'], true)) {
        return 1;
    }

    if (in_array($text, ['no', 'false', 'onsite', 'on-site', '0'], true)) {
        return 0;
    }

    return null;
}

function ingest_text(mixed $value, int $max = 0): ?string
{
    if ($value === null) {
        return null;
    }

    if (is_array($value) || is_object($value)) {
        $value = ingest_json($value);
    }

    $text = trim((string)$value);

    if ($text === '') {
        return null;
    }

    if ($max > 0 && mb_strlen($text) > $max) {
        $text = mb_substr($text, 0, $max);
    }

    return $text;
}

function ingest_log(Throwable|string $error, array $context = []): void
{
    try {
        $dir = base_path('storage/logs');

        if (!is_dir($dir)) {
            @mkdir($dir, 0775, true);
        }

        $message = $error instanceof Throwable
            ? get_class($error) . ': ' . $error->getMessage()
            : $error;

        @file_put_contents(
            $dir . '/smart_scraper_ingest.log',
            '[' . date('c') . '] ' .
            $message .
            ($context ? ' ' . json_encode($context, JSON_UNESCAPED_SLASHES | JSON_INVALID_UTF8_SUBSTITUTE) : '') .
            PHP_EOL,
            FILE_APPEND
        );
    } catch (Throwable) {
    }
}

$auth = (string)($_SERVER['HTTP_AUTHORIZATION'] ?? '');
$expected = (string)env('SMART_SCRAPER_INGEST_TOKEN', '');

if (
    $expected === '' ||
    !str_starts_with($auth, 'Bearer ') ||
    !hash_equals($expected, trim(substr($auth, 7)))
) {
    json_response([
        'ok' => false,
        'error' => 'Unauthorized'
    ], 401);
}

if ($_SERVER['REQUEST_METHOD'] !== 'POST') {
    json_response([
        'ok' => false,
        'error' => 'Method not allowed'
    ], 405);
}

$data = json_decode(
    (string)file_get_contents('php://input'),
    true
);

if (!is_array($data)) {
    json_response([
        'ok' => false,
        'error' => 'Invalid JSON'
    ], 400);
}

$runId = trim((string)($data['run_id'] ?? ''));
$source = strtolower(trim((string)($data['source'] ?? 'unknown')));
$mode = strtolower(trim((string)($data['mode'] ?? 'acquisition')));
$jobs = $data['jobs'] ?? $data['items'] ?? [];

if ($runId === '' || !is_array($jobs)) {
    json_response([
        'ok' => false,
        'error' => 'run_id and jobs are required'
    ], 422);
}

if ($source === '') {
    $source = 'unknown';
}

$pdo = Database::connection();

$jobColumns = [];
try {
    foreach ($pdo->query("SHOW COLUMNS FROM scraped_jobs")->fetchAll() as $col) {
        $jobColumns[(string)$col['Field']] = true;
    }
} catch (Throwable $schemaError) {
    ingest_log($schemaError, [
        'run_id' => $runId,
        'source' => $source,
        'stage' => 'schema_detection'
    ]);

    json_response([
        'ok' => false,
        'error' => 'Could not inspect scraped_jobs schema',
        'detail' => env('APP_DEBUG', false) ? $schemaError->getMessage() : null
    ], 500);
}

$new = 0;
$updated = 0;
$dupe = 0;
$failed = 0;
$touched = [];
$jobErrors = [];

try {
    $pdo->beginTransaction();

    $rq = $pdo->prepare(
        "SELECT *
         FROM scraper_runs
         WHERE external_run_id = ?
         FOR UPDATE"
    );

    $rq->execute([$runId]);
    $run = $rq->fetch();

    if (!$run) {
        $cfg = $pdo->query(
            "SELECT *
             FROM scraper_settings
             WHERE id = 1"
        )->fetch() ?: [];

        $pdo->prepare(
            "INSERT INTO scraper_runs(
                external_run_id,
                trigger_type,
                target_new_jobs,
                batch_size,
                max_runtime_minutes,
                status,
                started_at
             )
             VALUES(
                ?,
                'api',
                ?,
                ?,
                ?,
                'running',
                NOW()
             )"
        )->execute([
            $runId,
            (int)($cfg['target_new_jobs'] ?? 500),
            (int)($cfg['batch_size'] ?? 100),
            (int)($cfg['max_runtime_minutes'] ?? 180)
        ]);

        $rq->execute([$runId]);
        $run = $rq->fetch();
    } elseif (($run['status'] ?? '') === 'queued') {
        $pdo->prepare(
            "UPDATE scraper_runs
             SET status = 'running',
                 started_at = COALESCE(started_at, NOW())
             WHERE id = ?"
        )->execute([(int)$run['id']]);
    }

    if (!$run) {
        throw new RuntimeException('Could not create or load scraper run.');
    }

    $runPk = (int)$run['id'];

    $findBySourceJobId = $pdo->prepare(
        "SELECT id
         FROM scraped_jobs
         WHERE source = ?
           AND source_job_id = ?
         ORDER BY id
         LIMIT 1"
    );

    $findByCanonicalUrl = $pdo->prepare(
        "SELECT id
         FROM scraped_jobs
         WHERE source = ?
           AND canonical_job_url = ?
         ORDER BY id
         LIMIT 1"
    );

    $findFingerprint = $pdo->prepare(
        "SELECT scraped_job_id
         FROM scraper_job_fingerprints
         WHERE fingerprint = ?
         LIMIT 1"
    );

    foreach ($jobs as $index => $j) {
        if (!is_array($j)) {
            $failed++;
            $jobErrors[] = [
                'index' => $index,
                'error' => 'Job payload is not an object'
            ];
            continue;
        }

        $savepoint = 'job_' . (int)$index;

        try {
            $pdo->exec("SAVEPOINT {$savepoint}");

            $sj = trim((string)(
                $j['source_job_id']
                ?? $j['id']
                ?? $j['job_id']
                ?? ''
            ));

            $url = trim((string)(
                $j['canonical_job_url']
                ?? $j['job_url']
                ?? $j['url']
                ?? ''
            ));

            $title = trim((string)(
                $j['job_title']
                ?? $j['title']
                ?? $j['role']
                ?? ''
            ));

            $company = trim((string)(
                $j['company_name']
                ?? $j['company']
                ?? ''
            ));

            if ($sj === '' && $url === '' && $title === '') {
                throw new RuntimeException('Job has no source id, URL or title.');
            }

            $fingerprint = hash(
                'sha256',
                strtolower(
                    $source . '|' .
                    $sj . '|' .
                    $url . '|' .
                    $title . '|' .
                    $company
                )
            );

            $findFingerprint->execute([$fingerprint]);
            $id = $findFingerprint->fetchColumn();

            if (!$id && $sj !== '') {
                $findBySourceJobId->execute([
                    $source,
                    $sj
                ]);

                $id = $findBySourceJobId->fetchColumn();
            }

            if (!$id && $url !== '') {
                $findByCanonicalUrl->execute([
                    $source,
                    $url
                ]);

                $id = $findByCanonicalUrl->fetchColumn();
            }

            $contactEmail = ingest_text(
                $j['contact_email']
                ?? $j['email']
                ?? null,
                320
            );

            $emailStatus = $contactEmail ? 'found' : 'unknown';

            $vals = [
                'role' => ingest_text($j['role'] ?? null, 255),
                'job_description' => ingest_text(
                    $j['job_description']
                    ?? $j['description']
                    ?? null
                ),
                'job_url' => ingest_text(
                    $j['job_url']
                    ?? $j['url']
                    ?? null
                ),
                'canonical_job_url' => ingest_text($url, 1000),
                'company_id' => ingest_text($j['company_id'] ?? null, 255),
                'company_name' => ingest_text($company, 500),
                'company_slug' => ingest_text($j['company_slug'] ?? null, 255),
                'company_website' => ingest_text($j['company_website'] ?? null),
                'company_linkedin' => ingest_text($j['company_linkedin'] ?? null),
                'company_location' => ingest_json($j['company_location'] ?? null),
                'company_size' => ingest_text($j['company_size'] ?? null, 255),
                'job_location' => ingest_json(
                    $j['job_location']
                    ?? $j['location']
                    ?? null
                ),
                'remote' => ingest_bool($j['remote'] ?? null),
                'remote_type' => ingest_text($j['remote_type'] ?? null, 100),
                'relocation_allowed' => ingest_bool($j['relocation_allowed'] ?? null),
                'job_type' => ingest_text($j['job_type'] ?? null, 100),
                'experience_min' => ingest_decimal($j['experience_min'] ?? null),
                'experience_max' => ingest_decimal($j['experience_max'] ?? null),
                'experience_text' => ingest_text(
                    $j['experience_text']
                    ?? $j['experience']
                    ?? null,
                    255
                ),
                'skills' => ingest_json($j['skills'] ?? null),
                'compensation' => ingest_json($j['compensation'] ?? null),
                'salary_min' => ingest_decimal($j['salary_min'] ?? null),
                'salary_max' => ingest_decimal($j['salary_max'] ?? null),
                'salary_currency' => ingest_text($j['salary_currency'] ?? null, 20),
                'equity' => ingest_json($j['equity'] ?? null),
                'visa_sponsorship' => ingest_bool($j['visa_sponsorship'] ?? null),
                'posted_timestamp' => ingest_text(
                    $j['posted_timestamp']
                    ?? $j['created_at']
                    ?? null,
                    100
                ),
                'hiring_contact' => ingest_text($j['hiring_contact'] ?? null, 500),
                'hiring_manager' => ingest_text($j['hiring_manager'] ?? null, 500),
                'founders' => ingest_json($j['founders'] ?? null),
                'person_1_name' => ingest_text($j['person_1_name'] ?? null, 255),
                'person_1_role' => ingest_text($j['person_1_role'] ?? null, 255),
                'person_1_profile_url' => ingest_text($j['person_1_profile_url'] ?? null),
                'person_2_name' => ingest_text($j['person_2_name'] ?? null, 255),
                'person_2_role' => ingest_text($j['person_2_role'] ?? null, 255),
                'person_2_profile_url' => ingest_text($j['person_2_profile_url'] ?? null),
                'contact_email' => $contactEmail,
                'email_status' => $emailStatus,
                'email_source' => ingest_text($j['email_source'] ?? null, 120),
                'raw_payload' => ingest_json($j)
            ];

            $vals = array_filter(
                $vals,
                static fn($value, $column) => isset($jobColumns[$column]),
                ARRAY_FILTER_USE_BOTH
            );

            if ($id) {
                $sets = [];
                $args = [];

                foreach ($vals as $column => $value) {
                    if ($value !== null && $value !== '') {
                        $sets[] = "{$column} = ?";
                        $args[] = $value;
                    }
                }

                if (isset($jobColumns['last_seen_run_id'])) {
                    $sets[] = 'last_seen_run_id = ?';
                    $args[] = $runPk;
                }

                if (isset($jobColumns['last_seen_at'])) {
                    $sets[] = 'last_seen_at = NOW()';
                }

                $args[] = (int)$id;

                $pdo->prepare(
                    "UPDATE scraped_jobs
                     SET " . implode(', ', $sets) . "
                     WHERE id = ?"
                )->execute($args);

                if ($mode === 'enrichment') {
                    $updated++;
                } else {
                    $dupe++;
                }

                $touched[] = (int)$id;
            } else {
                $cols = [];
                $args = [];

                $baseInsert = [
                    'source' => $source,
                    'source_job_id' => $sj !== '' ? $sj : null,
                    'job_title' => $title !== '' ? $title : null
                ];

                foreach ($baseInsert as $column => $value) {
                    if (isset($jobColumns[$column])) {
                        $cols[] = $column;
                        $args[] = $value;
                    }
                }

                foreach ($vals as $column => $value) {
                    $cols[] = $column;
                    $args[] = $value;
                }

                if (isset($jobColumns['first_seen_run_id'])) {
                    $cols[] = 'first_seen_run_id';
                    $args[] = $runPk;
                }

                if (isset($jobColumns['last_seen_run_id'])) {
                    $cols[] = 'last_seen_run_id';
                    $args[] = $runPk;
                }

                $placeholders = implode(
                    ',',
                    array_fill(0, count($cols), '?')
                );

                $pdo->prepare(
                    "INSERT INTO scraped_jobs(" .
                    implode(',', $cols) .
                    ")
                    VALUES({$placeholders})"
                )->execute($args);

                $id = (int)$pdo->lastInsertId();

                $pdo->prepare(
                    "INSERT IGNORE INTO scraper_job_fingerprints(
                        scraped_job_id,
                        fingerprint
                     )
                     VALUES(?, ?)"
                )->execute([
                    $id,
                    $fingerprint
                ]);

                $new++;
                $touched[] = $id;
            }

            $pdo->exec("RELEASE SAVEPOINT {$savepoint}");
        } catch (Throwable $jobError) {
            try {
                $pdo->exec("ROLLBACK TO SAVEPOINT {$savepoint}");
            } catch (Throwable) {
            }

            $failed++;

            $jobErrors[] = [
                'index' => $index,
                'source_job_id' => $j['source_job_id'] ?? $j['id'] ?? null,
                'title' => $j['job_title'] ?? $j['title'] ?? null,
                'error' => $jobError->getMessage()
            ];

            ingest_log($jobError, [
                'run_id' => $runId,
                'source' => $source,
                'job_index' => $index,
                'source_job_id' => $j['source_job_id'] ?? $j['id'] ?? null
            ]);
        }
    }

    $sourceColumn = match ($source) {
        'ycombinator', 'yc' => 'yc_count',
        'wellfound' => 'wellfound_count',
        'linkedin' => 'linkedin_enrichment_count',
        'upwork' => 'upwork_count',
        default => null
    };

    // upwork_count is added by hostinger/migration_upwork.sql; stay safe until it has been run.
    if ($sourceColumn === 'upwork_count') {
        $runColumns = [];
        foreach ($pdo->query("SHOW COLUMNS FROM scraper_runs")->fetchAll() as $col) {
            $runColumns[(string)$col['Field']] = true;
        }
        if (!isset($runColumns['upwork_count'])) {
            $sourceColumn = null;
        }
    }

    $set = "
        new_jobs_count = new_jobs_count + ?,
        updated_jobs_count = updated_jobs_count + ?,
        duplicate_jobs_count = duplicate_jobs_count + ?,
        failed_jobs_count = failed_jobs_count + ?
    ";

    if ($sourceColumn !== null) {
        $set .= ",
            {$sourceColumn} = {$sourceColumn} + " . ($new + $updated + $dupe);
    }

    $pdo->prepare(
        "UPDATE scraper_runs
         SET {$set}
         WHERE id = ?"
    )->execute([
        $new,
        $updated,
        $dupe,
        $failed,
        $runPk
    ]);

    $healthMessage =
        "Accepted batch: {$new} new, {$updated} updated, " .
        "{$dupe} duplicates, {$failed} failed";

    $pdo->prepare(
        "INSERT INTO scraper_source_health(
            source_key,
            last_success_at,
            last_failure_at,
            consecutive_failures,
            last_message,
            last_records_count
         )
         VALUES(
            ?,
            NOW(),
            NULL,
            0,
            ?,
            ?
         )
         ON DUPLICATE KEY UPDATE
            last_success_at = NOW(),
            consecutive_failures = 0,
            last_message = VALUES(last_message),
            last_records_count = VALUES(last_records_count)"
    )->execute([
        $source,
        $healthMessage,
        $new + $updated + $dupe
    ]);

    $pdo->commit();
} catch (Throwable $e) {
    if ($pdo->inTransaction()) {
        $pdo->rollBack();
    }

    ingest_log($e, [
        'run_id' => $runId,
        'source' => $source,
        'stage' => 'database'
    ]);

    json_response([
        'ok' => false,
        'error' => 'Ingestion database failure',
        'detail' => env('APP_DEBUG', false)
            ? $e->getMessage()
            : null
    ], 500);
}

/*
 * Assignment is deliberately OUTSIDE the DB ingestion transaction.
 * A lead-assignment problem must not turn a successful ingestion into HTTP 500.
 */
$assignmentResult = null;
$assignmentWarning = null;

if ($touched) {
    try {
        $assignmentResult = (
            new LeadAssignmentService()
        )->assignFreshJobs(
            array_values(
                array_unique($touched)
            )
        );
    } catch (Throwable $assignmentError) {
        $assignmentWarning = $assignmentError->getMessage();

        ingest_log($assignmentError, [
            'run_id' => $runId,
            'source' => $source,
            'stage' => 'lead_assignment',
            'jobs' => count($touched)
        ]);
    }
}

$response = [
    'ok' => true,
    'run_id' => $runId,
    'source' => $source,
    'mode' => $mode,
    'received' => count($jobs),
    'new' => $new,
    'inserted' => $new,
    'updated' => $updated,
    'duplicates' => $dupe,
    'failed' => $failed,
    'assigned' => $assignmentResult,
    'schema_columns_detected' => count($jobColumns)
];

if ($assignmentWarning !== null) {
    $response['assignment_warning'] = 'Jobs were ingested, but automatic assignment needs attention.';
}

if ($failed > 0) {
    $response['job_errors'] = array_slice($jobErrors, 0, 10);
}

json_response($response);
