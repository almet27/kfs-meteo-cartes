<?php
declare(strict_types=1);

/**
 * KFS METEO - relais Infoclimat prive (PHP 8+).
 *
 * Doit etre heberge sur un serveur avec IP de sortie stable et autorisee
 * dans la cle d'API Infoclimat. Ne placez pas le jeton dans ce fichier
 * ni dans un fichier du depot public.
 *
 * Variables d'environnement du serveur :
 *   INFOCLIMAT_API_TOKEN  = cle Infoclimat liee a l'IP serveur
 *   INFOCLIMAT_RELAY_SECRET = mot de passe secret fort partage avec le Worker
 */
header('Content-Type: application/json; charset=utf-8');
header('Cache-Control: no-store');
header('X-Content-Type-Options: nosniff');
function deny(int $code, string $msg): never {
    http_response_code($code);
    echo json_encode(['error'=>$msg], JSON_UNESCAPED_UNICODE);
    exit;
}
if ($_SERVER['REQUEST_METHOD'] !== 'GET') deny(405, 'Méthode interdite');
$expected = getenv('INFOCLIMAT_RELAY_SECRET');
$token = getenv('INFOCLIMAT_API_TOKEN');
if (!$expected || !$token) deny(503, 'Relais non configuré.');
$authorization = $_SERVER['HTTP_AUTHORIZATION'] ?? '';
if (!preg_match('/^Bearer (.+)$/', $authorization, $matches) ||
    !hash_equals($expected, $matches[1])) {
    deny(401, 'Non autorisé');
}
$rawIds = $_GET['stations'] ?? [];
if (!is_array($rawIds) || count($rawIds) < 1 || count($rawIds) > 12) {
    deny(400, 'Nombre de stations incorrect');
}
$ids = array_values(array_unique($rawIds));
foreach ($ids as $id) {
    if (!is_string($id) || !preg_match('/^[A-Za-z0-9_-]{4,25}$/D', $id))
        deny(400, 'Identifiant station non valide');
}
$start = $_GET['start'] ?? '';
$end = $_GET['end'] ?? '';
if (!is_string($start) || !is_string($end) ||
    !preg_match('/^\d{4}-\d{2}-\d{2}$/D', $start) ||
    !preg_match('/^\d{4}-\d{2}-\d{2}$/D', $end)) {
    deny(400, 'Dates invalides');
}
try {
    $d1 = new DateTimeImmutable($start, new DateTimeZone('UTC'));
    $d2 = new DateTimeImmutable($end, new DateTimeZone('UTC'));
    $today = new DateTimeImmutable('today', new DateTimeZone('UTC'));
    if ($d1 > $d2 || $d1 < $today->modify('-2 day') ||
        $d2 > $today || $d1->diff($d2)->days > 2)
        deny(400, 'Période autorisée : 2 derniers jours UTC');
} catch (Throwable $e) {
    deny(400, 'Dates invalides');
}
$params = ['method'=>'get','format'=>'json','start'=>$start,'end'=>$end,'token'=>$token];
$url = 'https://www.infoclimat.fr/opendata/?' . http_build_query($params, '', '&', PHP_QUERY_RFC3986);
foreach ($ids as $id) $url .= '&stations%5B%5D=' . rawurlencode($id);
$ch = curl_init($url);
curl_setopt_array($ch, [
    CURLOPT_RETURNTRANSFER => true,
    CURLOPT_CONNECTTIMEOUT => 7,
    CURLOPT_TIMEOUT => 18,
    CURLOPT_FOLLOWLOCATION => false,
    CURLOPT_PROTOCOLS => CURLPROTO_HTTPS,
    CURLOPT_USERAGENT => 'KFS-Meteo-Infoclimat-Relay/1.0',
    CURLOPT_HTTPHEADER => ['Accept: application/json']
]);
$data = curl_exec($ch);
$http = curl_getinfo($ch, CURLINFO_HTTP_CODE);
$error = curl_error($ch);
curl_close($ch);
if (!is_string($data) || $http < 200 || $http >= 300)
    deny(502, 'API Infoclimat non disponible.');
if (strlen($data) > 6_000_000) deny(502, 'Réponse trop volumineuse');
if (stripos($data, 'Wrong ip address') !== false)
    deny(502, 'Adresse IP du serveur non autorisée dans la clé Infoclimat.');
$decoded = json_decode($data, true);
if (!is_array($decoded) || !isset($decoded['hourly']))
    deny(502, 'La réponse Infoclimat ne contient aucun relevé exploitable.');
echo json_encode($decoded, JSON_UNESCAPED_UNICODE | JSON_INVALID_UTF8_SUBSTITUTE);
