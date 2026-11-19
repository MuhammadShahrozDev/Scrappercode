<?php
declare(strict_types=1);
/**
 * GET /api/v1/smart_scraper/daily-count.php
 * Returns how many NEW leads were inserted today (Asia/Karachi day), so the GitHub scraper can
 * respect the daily cap (default 1000). Same bearer token as ingest.php / run-status.php.
 */
require_once dirname(__DIR__,4) . '/src/bootstrap.php';

use App\Database;

$auth=(string)($_SERVER['HTTP_AUTHORIZATION']??'');
$expected=(string)env('SMART_SCRAPER_INGEST_TOKEN','');
if($expected===''||!str_starts_with($auth,'Bearer ')||!hash_equals($expected,trim(substr($auth,7)))){
    json_response(['ok'=>false,'error'=>'Unauthorized'],401);
}
if($_SERVER['REQUEST_METHOD']!=='GET')json_response(['ok'=>false,'error'=>'Method not allowed'],405);

$limit=(int)env('SMART_SCRAPER_DAILY_LIMIT',1000);
if($limit<=0)$limit=1000;

// Seconds since local midnight (Pakistan). Compared against the DB's own NOW(), so the result
// does not depend on the MySQL server time zone.
$tz=new DateTimeZone('Asia/Karachi');
$now=new DateTimeImmutable('now',$tz);
$secondsToday=max(0,$now->getTimestamp()-$now->setTime(0,0,0)->getTimestamp());

$pdo=Database::connection();
$st=$pdo->prepare("SELECT COUNT(*) FROM scraped_jobs WHERE created_at >= (NOW() - INTERVAL ? SECOND)");
$st->execute([$secondsToday]);
$today=(int)$st->fetchColumn();

json_response([
    'ok'=>true,
    'date'=>$now->format('Y-m-d'),
    'today'=>$today,
    'limit'=>$limit,
    'remaining'=>max(0,$limit-$today),
]);
