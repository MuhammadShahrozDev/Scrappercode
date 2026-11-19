<?php
declare(strict_types=1);
require_once dirname(__DIR__,4) . '/src/bootstrap.php';

use App\Database;

$auth=(string)($_SERVER['HTTP_AUTHORIZATION']??'');
$expected=(string)env('SMART_SCRAPER_INGEST_TOKEN','');
if($expected===''||!str_starts_with($auth,'Bearer ')||!hash_equals($expected,trim(substr($auth,7)))){
    json_response(['ok'=>false,'error'=>'Unauthorized'],401);
}
if($_SERVER['REQUEST_METHOD']!=='POST')json_response(['ok'=>false,'error'=>'Method not allowed'],405);
$data=json_decode((string)file_get_contents('php://input'),true);
if(!is_array($data))json_response(['ok'=>false,'error'=>'Invalid JSON'],400);
$runId=trim((string)($data['run_id']??''));
$status=trim((string)($data['status']??''));
$message=trim((string)($data['message']??''));
$source=trim((string)($data['source']??'all'));
if($runId===''||!in_array($status,['completed','completed_with_warnings','failed','timeout','cancelled'],true))json_response(['ok'=>false,'error'=>'Invalid run status payload'],422);
$pdo=Database::connection();
$pdo->prepare("UPDATE scraper_runs SET status=?,source_scope=COALESCE(NULLIF(?,''),source_scope),message=?,finished_at=NOW() WHERE external_run_id=?")
    ->execute([$status,$source,$message?:null,$runId]);
json_response(['ok'=>true,'run_id'=>$runId,'status'=>$status]);
