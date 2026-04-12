<?php
/**
 * Plugin Name: SVRT — Software Version Reference Tool
 * Description: Backend for askmcconnell.com/svrt — open-source EOL detection tool. Contributor auth, inventory upload, EOL report generation, and reference DB management.
 * Version: 1.0.0
 * Author: Ask McConnell
 */
defined('ABSPATH') || exit;

define('SVRT_VERSION',      '1.0.0');
define('SVRT_TOKEN_EXPIRY', 30 * DAY_IN_SECONDS);
define('SVRT_TOKEN_PREFIX', 'svrt_auth_');
define('SVRT_UPLOAD_LIMIT', 5000);   // max rows per upload
define('SVRT_UPLOAD_MB',    2);      // max file size in MB

// ============================================================
// ACTIVATION / DEACTIVATION
// ============================================================

register_activation_hook(__FILE__, function () {
    svrt_create_tables();
    flush_rewrite_rules();
});

register_deactivation_hook(__FILE__, function () {
    flush_rewrite_rules();
});

// Run table creation on every load (safe — uses IF NOT EXISTS).
add_action('init', 'svrt_create_tables');

// ============================================================
// DATABASE TABLES
// ============================================================

function svrt_create_tables(): void {
    global $wpdb;
    $c = $wpdb->get_charset_collate();

    require_once ABSPATH . 'wp-admin/includes/upgrade.php';

    // Subscribers — one row per registered user
    dbDelta("CREATE TABLE IF NOT EXISTS {$wpdb->prefix}svrt_subscribers (
        id            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
        user_id       BIGINT UNSIGNED NOT NULL,
        plan          VARCHAR(20)  NOT NULL DEFAULT 'trial',
        upload_quota  INT          NOT NULL DEFAULT 10,
        uploads_used  INT          NOT NULL DEFAULT 0,
        company       VARCHAR(255) DEFAULT '',
        created_at    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
        expires_at    DATETIME     DEFAULT NULL,
        PRIMARY KEY (id),
        UNIQUE KEY user_id (user_id)
    ) $c;");

    // Upload jobs — one row per CSV upload session
    dbDelta("CREATE TABLE IF NOT EXISTS {$wpdb->prefix}svrt_upload_jobs (
        id                   BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
        uuid                 VARCHAR(36)  NOT NULL,
        user_id              BIGINT UNSIGNED NOT NULL,
        status               VARCHAR(20)  NOT NULL DEFAULT 'pending',
        row_count            INT          NOT NULL DEFAULT 0,
        matched_count        INT          NOT NULL DEFAULT 0,
        eol_count            INT          NOT NULL DEFAULT 0,
        filename             VARCHAR(255) DEFAULT '',
        created_at           DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
        completed_at         DATETIME     DEFAULT NULL,
        error_msg            TEXT         DEFAULT NULL,
        report_token         VARCHAR(64)  DEFAULT NULL,
        report_token_expires DATETIME     DEFAULT NULL,
        PRIMARY KEY (id),
        UNIQUE KEY uuid (uuid),
        KEY user_id (user_id),
        KEY status (status)
    ) $c;");

    // Add report token columns to existing installs (dbDelta doesn't reliably add columns)
    svrt_maybe_add_column(
        "{$wpdb->prefix}svrt_upload_jobs", 'report_token',
        "ALTER TABLE {$wpdb->prefix}svrt_upload_jobs ADD COLUMN report_token VARCHAR(64) DEFAULT NULL"
    );
    svrt_maybe_add_column(
        "{$wpdb->prefix}svrt_upload_jobs", 'report_token_expires',
        "ALTER TABLE {$wpdb->prefix}svrt_upload_jobs ADD COLUMN report_token_expires DATETIME DEFAULT NULL"
    );

    // Uploaded inventory rows — individual software items per job
    dbDelta("CREATE TABLE IF NOT EXISTS {$wpdb->prefix}svrt_inventory_rows (
        id            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
        job_id        BIGINT UNSIGNED NOT NULL,
        user_id       BIGINT UNSIGNED NOT NULL,
        hostname_hash VARCHAR(64)  DEFAULT '',
        platform      VARCHAR(20)  DEFAULT '',
        filename      VARCHAR(255) DEFAULT '',
        filepath      VARCHAR(1024) DEFAULT '',
        software_name VARCHAR(255) NOT NULL DEFAULT '',
        vendor        VARCHAR(255) DEFAULT '',
        version       VARCHAR(100) DEFAULT '',
        file_type     VARCHAR(50)  DEFAULT '',
        parent_app    VARCHAR(255) DEFAULT '',
        scan_date     DATE         DEFAULT NULL,
        eol_status    VARCHAR(20)  DEFAULT 'unknown',
        eol_date      VARCHAR(20)  DEFAULT '',
        latest_version VARCHAR(100) DEFAULT '',
        latest_source_url TEXT     DEFAULT NULL,
        confidence    TINYINT      DEFAULT 0,
        ref_source    VARCHAR(50)  DEFAULT '',
        ref_notes     TEXT         DEFAULT NULL,
        PRIMARY KEY (id),
        KEY job_id (job_id),
        KEY user_id (user_id),
        KEY eol_status (eol_status)
    ) $c;");

    // Reference database — pushed from Pi nightly, served to subscribers
    dbDelta("CREATE TABLE IF NOT EXISTS {$wpdb->prefix}svrt_reference (
        id                BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
        lookup_key        VARCHAR(100) NOT NULL,
        software_name     VARCHAR(255) NOT NULL DEFAULT '',
        vendor            VARCHAR(255) DEFAULT '',
        version           VARCHAR(100) DEFAULT '',
        platform          VARCHAR(20)  DEFAULT '',
        eol_status        VARCHAR(20)  NOT NULL DEFAULT 'unknown',
        eol_date          VARCHAR(20)  DEFAULT '',
        latest_version    VARCHAR(100) DEFAULT '',
        latest_source_url TEXT         DEFAULT NULL,
        confidence        TINYINT      DEFAULT 0,
        ref_source        VARCHAR(50)  DEFAULT '',
        notes             TEXT         DEFAULT NULL,
        hit_count         INT          NOT NULL DEFAULT 0,
        checked_at        DATETIME     DEFAULT NULL,
        expires_at        DATETIME     DEFAULT NULL,
        PRIMARY KEY (id),
        UNIQUE KEY lookup_key (lookup_key),
        KEY eol_status (eol_status),
        KEY software_name (software_name(100))
    ) $c;");
}

function svrt_maybe_add_column(string $table, string $col, string $sql): void {
    global $wpdb;
    $cols = $wpdb->get_col("DESCRIBE $table", 0);
    if (!in_array($col, $cols, true)) {
        $wpdb->query($sql);
    }
}

// One-time migration: reset stuck inventory rows so they can be re-processed.
// Rows inserted before this fix had eol_status='unknown' as their initial state,
// making them indistinguishable from "looked up but no match". This resets any
// row that was never actually looked up (ref_source is empty) on incomplete jobs.
function svrt_migrate_stuck_rows(): void {
    if (get_option('svrt_migrated_eol_sentinel_v1')) return;
    global $wpdb;

    // Reset rows on pending/processing jobs that were never actually looked up.
    // Before this fix, newly inserted rows had eol_status='unknown' (DB default),
    // making them indistinguishable from "looked up, no match found". This resets
    // any row with an empty ref_source (processor never wrote a result) so the
    // new sentinel query (WHERE eol_status='') will pick them up.
    $wpdb->query(
        "UPDATE {$wpdb->prefix}svrt_inventory_rows ir
         INNER JOIN {$wpdb->prefix}svrt_upload_jobs j ON ir.job_id = j.id
         SET ir.eol_status = ''
         WHERE (ir.eol_status = 'unknown' OR ir.eol_status IS NULL OR ir.eol_status = '')
           AND (ir.ref_source = '' OR ir.ref_source IS NULL)
           AND j.status IN ('pending', 'processing')"
    );

    // Reset matched_count on incomplete jobs so progress bar restarts cleanly
    $wpdb->query(
        "UPDATE {$wpdb->prefix}svrt_upload_jobs
         SET matched_count = 0
         WHERE status IN ('pending', 'processing')"
    );

    update_option('svrt_migrated_eol_sentinel_v1', true);
}
add_action('init', 'svrt_migrate_stuck_rows', 20);

// ============================================================
// CORS HEADERS
// ============================================================

function svrt_send_cors_headers(): void {
    $origin = $_SERVER['HTTP_ORIGIN'] ?? '';
    $allowed = [
        'https://askmcconnell.com',
        'https://www.askmcconnell.com',
        'http://localhost:5173',
        'http://localhost:3000',
    ];
    if (in_array($origin, $allowed, true)) {
        header('Access-Control-Allow-Origin: ' . $origin);
        header('Vary: Origin');
    }
    header('Access-Control-Allow-Methods: GET, POST, DELETE, OPTIONS');
    header('Access-Control-Allow-Headers: Authorization, Content-Type');
    header('Access-Control-Max-Age: 86400');
}

add_action('init', function () {
    if (($_SERVER['REQUEST_METHOD'] ?? '') === 'OPTIONS') {
        svrt_send_cors_headers();
        status_header(200);
        exit;
    }
});

add_filter('rest_pre_serve_request', function ($served, $result, $request) {
    svrt_send_cors_headers();
    return $served;
}, 10, 3);

// ============================================================
// BEARER TOKEN AUTH  (Apache-safe — query-param fallback)
// ============================================================

add_filter('determine_current_user', function ($user_id) {
    $token = svrt_get_bearer_token();
    if ($token) {
        $stored = get_transient(SVRT_TOKEN_PREFIX . hash('sha256', $token));
        if ($stored) {
            return (int) $stored;
        }
    }
    return $user_id;
}, 20);

add_filter('rest_authentication_errors', function ($result) {
    $token = svrt_get_bearer_token();
    if (!$token) return $result;
    $stored = get_transient(SVRT_TOKEN_PREFIX . hash('sha256', $token));
    if (!$stored) return $result;
    wp_set_current_user((int) $stored);
    return is_wp_error($result) ? null : $result;
}, 200);

function svrt_get_bearer_token(): ?string {
    if (!empty($_GET['_token'])) {
        return sanitize_text_field(wp_unslash($_GET['_token']));
    }
    $header = $_SERVER['HTTP_AUTHORIZATION']
           ?? $_SERVER['REDIRECT_HTTP_AUTHORIZATION']
           ?? null;
    if (!$header && function_exists('getallheaders')) {
        foreach (getallheaders() as $name => $value) {
            if (strtolower($name) === 'authorization') { $header = $value; break; }
        }
    }
    if (!$header || stripos($header, 'Bearer ') !== 0) return null;
    return trim(substr($header, 7));
}

function svrt_generate_token(int $user_id): string {
    $token = wp_generate_password(64, false, false);
    set_transient(SVRT_TOKEN_PREFIX . hash('sha256', $token), $user_id, SVRT_TOKEN_EXPIRY);
    update_user_meta($user_id, '_svrt_last_login', current_time('mysql'));
    return $token;
}

function svrt_invalidate_token(string $token): void {
    delete_transient(SVRT_TOKEN_PREFIX . hash('sha256', $token));
}

// ============================================================
// PERMISSION CALLBACKS
// ============================================================

function svrt_require_auth(): bool|WP_Error {
    if (!is_user_logged_in()) {
        return new WP_Error('unauthorized', 'Authentication required.', ['status' => 401]);
    }
    return true;
}

function svrt_require_admin(): bool|WP_Error {
    if (!is_user_logged_in()) {
        return new WP_Error('unauthorized', 'Authentication required.', ['status' => 401]);
    }
    if (!current_user_can('manage_options')) {
        return new WP_Error('forbidden', 'Admin access required.', ['status' => 403]);
    }
    return true;
}

// Allows Bearer-authenticated users OR a valid short-lived report token
function svrt_require_auth_or_rtoken(WP_REST_Request $req): bool|WP_Error {
    if (is_user_logged_in()) return true;
    if (!empty($req->get_param('rtoken'))) return true; // token validity checked inside handler
    return new WP_Error('unauthorized', 'Authentication required.', ['status' => 401]);
}

// ── Email helper ─────────────────────────────────────────────────────────────

function svrt_send_report_email(string $to, string $uuid, string $token, array $job): void {
    $link     = "https://askmcconnell.com/svrt/results/{$uuid}?rtoken={$token}";
    $filename = $job['filename'] ?? 'your inventory';
    $rows     = number_format((int) ($job['row_count'] ?? 0));

    $subject  = 'Your SVRT report is ready — ' . $filename;

    $message  = "Hi,\n\n";
    $message .= "Your Software Version Reference Tool report has finished processing.\n\n";
    $message .= "  File:          {$filename}\n";
    $message .= "  Items scanned: {$rows}\n\n";
    $message .= "View your report (link valid for 24 hours):\n";
    $message .= "{$link}\n\n";
    $message .= "Once the link expires, log in at https://askmcconnell.com/svrt/ to access\n";
    $message .= "your report history at any time.\n\n";
    $message .= "---\n";
    $message .= "Software Version Reference Tool\n";
    $message .= "https://askmcconnell.com/svrt/\n";

    $headers = [
        'Content-Type: text/plain; charset=UTF-8',
        'From: SVRT <noreply@askmcconnell.com>',
    ];

    $sent = wp_mail($to, $subject, $message, $headers);

    if ( ! $sent ) {
        $mailer = isset( $GLOBALS['phpmailer'] ) ? $GLOBALS['phpmailer'] : null;
        $err    = $mailer ? $mailer->ErrorInfo : 'unknown error';
        error_log( "[SVRT] wp_mail FAILED to {$to} (job {$uuid}): {$err}" );
    } else {
        error_log( "[SVRT] wp_mail sent OK to {$to} (job {$uuid})" );
    }
}

function svrt_get_subscriber(int $user_id): ?array {
    global $wpdb;
    $row = $wpdb->get_row($wpdb->prepare(
        "SELECT * FROM {$wpdb->prefix}svrt_subscribers WHERE user_id = %d",
        $user_id
    ), ARRAY_A);
    return $row ?: null;
}

// ============================================================
// REST API ROUTES
// ============================================================

add_action('rest_api_init', function () {
    $ns = 'svrt/v1';

    // ── Auth ────────────────────────────────────────────────
    register_rest_route($ns, '/auth/register', [
        'methods'             => 'POST',
        'callback'            => 'svrt_api_register',
        'permission_callback' => '__return_true',
    ]);
    register_rest_route($ns, '/auth/login', [
        'methods'             => 'POST',
        'callback'            => 'svrt_api_login',
        'permission_callback' => '__return_true',
    ]);
    register_rest_route($ns, '/auth/logout', [
        'methods'             => 'POST',
        'callback'            => 'svrt_api_logout',
        'permission_callback' => 'svrt_require_auth',
    ]);
    register_rest_route($ns, '/auth/me', [
        'methods'             => 'GET',
        'callback'            => 'svrt_api_me',
        'permission_callback' => 'svrt_require_auth',
    ]);

    // ── Inventory Upload ────────────────────────────────────
    register_rest_route($ns, '/upload', [
        'methods'             => 'POST',
        'callback'            => 'svrt_api_upload',
        'permission_callback' => 'svrt_require_auth',
    ]);

    // ── Job Status + Report ─────────────────────────────────
    register_rest_route($ns, '/job/(?P<uuid>[a-f0-9\-]{36})', [
        'methods'             => 'GET',
        'callback'            => 'svrt_api_job_status',
        'permission_callback' => 'svrt_require_auth_or_rtoken',
    ]);
    register_rest_route($ns, '/job/(?P<uuid>[a-f0-9\-]{36})/report', [
        'methods'             => 'GET',
        'callback'            => 'svrt_api_job_report',
        'permission_callback' => 'svrt_require_auth_or_rtoken',
    ]);
    register_rest_route($ns, '/job/(?P<uuid>[a-f0-9\-]{36})/resend', [
        'methods'             => 'POST',
        'callback'            => 'svrt_api_resend_report',
        'permission_callback' => 'svrt_require_auth',
    ]);
    register_rest_route($ns, '/job/(?P<uuid>[a-f0-9\-]{36})', [
        'methods'             => 'DELETE',
        'callback'            => 'svrt_api_delete_job',
        'permission_callback' => 'svrt_require_auth',
    ]);

    register_rest_route($ns, '/jobs', [
        'methods'             => 'GET',
        'callback'            => 'svrt_api_my_jobs',
        'permission_callback' => 'svrt_require_auth',
    ]);

    // ── Reference DB Download (authenticated) ───────────────
    register_rest_route($ns, '/reference', [
        'methods'             => 'GET',
        'callback'            => 'svrt_api_reference_db',
        'permission_callback' => 'svrt_require_auth',
    ]);
    register_rest_route($ns, '/reference/search', [
        'methods'             => 'GET',
        'callback'            => 'svrt_api_reference_search',
        'permission_callback' => 'svrt_require_auth',
    ]);

    // ── Stats (public — for landing page) ───────────────────
    register_rest_route($ns, '/stats', [
        'methods'             => 'GET',
        'callback'            => 'svrt_api_stats',
        'permission_callback' => '__return_true',
    ]);

    // ── Admin ────────────────────────────────────────────────
    register_rest_route($ns, '/admin/reference/import', [
        'methods'             => 'POST',
        'callback'            => 'svrt_api_admin_import_reference',
        'permission_callback' => 'svrt_require_admin',
    ]);
    register_rest_route($ns, '/admin/jobs', [
        'methods'             => 'GET',
        'callback'            => 'svrt_api_admin_jobs',
        'permission_callback' => 'svrt_require_admin',
    ]);
    register_rest_route($ns, '/admin/subscribers', [
        'methods'             => 'GET',
        'callback'            => 'svrt_api_admin_subscribers',
        'permission_callback' => 'svrt_require_admin',
    ]);
    // Queue dashboard — secret-based auth (no WP session needed)
    register_rest_route($ns, '/admin/queue', [
        'methods'             => 'GET',
        'callback'            => 'svrt_api_admin_queue',
        'permission_callback' => '__return_true',   // secret checked inside
    ]);

    // ── Public industry dashboard ────────────────────────────
    register_rest_route($ns, '/dashboard', [
        'methods'             => 'GET',
        'callback'            => 'svrt_api_dashboard',
        'permission_callback' => '__return_true',
    ]);

    // ── Export unknown software for Pi research queue ─────────
    register_rest_route($ns, '/admin/unknown-software', [
        'methods'             => 'GET',
        'callback'            => 'svrt_api_unknown_software',
        'permission_callback' => '__return_true',   // secret checked inside
    ]);

    // ── Re-enrich unknown rows against updated reference DB ───
    register_rest_route($ns, '/reenrich', [
        'methods'             => 'GET',
        'callback'            => 'svrt_api_reenrich',
        'permission_callback' => '__return_true',   // secured by secret key check inside
    ]);

    // ── Process upload queue (triggered by cron/ping) ────────
    register_rest_route($ns, '/process', [
        'methods'             => 'GET',
        'callback'            => 'svrt_api_process_queue',
        'permission_callback' => '__return_true',   // secured by secret key check inside
    ]);
});

// ============================================================
// AUTH ENDPOINTS
// ============================================================

function svrt_api_register(WP_REST_Request $req): WP_REST_Response|WP_Error {
    $email    = sanitize_email($req->get_param('email') ?? '');
    $password = $req->get_param('password') ?? '';
    $first    = sanitize_text_field($req->get_param('first_name') ?? '');
    $last     = sanitize_text_field($req->get_param('last_name') ?? '');
    $company  = sanitize_text_field($req->get_param('company') ?? '');

    if (!$email || !$password || !$first || !$last) {
        return new WP_Error('missing_fields', 'first_name, last_name, email, and password are required.', ['status' => 400]);
    }
    if (!is_email($email)) {
        return new WP_Error('invalid_email', 'Invalid email address.', ['status' => 400]);
    }
    if (strlen($password) < 8) {
        return new WP_Error('weak_password', 'Password must be at least 8 characters.', ['status' => 400]);
    }
    if (email_exists($email)) {
        return new WP_Error('email_exists', 'An account with that email already exists.', ['status' => 409]);
    }

    $username = sanitize_user(strtolower($first . '.' . $last . '.' . wp_rand(100, 999)));
    $user_id  = wp_create_user($username, $password, $email);
    if (is_wp_error($user_id)) {
        return $user_id;
    }

    wp_update_user(['ID' => $user_id, 'first_name' => $first, 'last_name' => $last]);
    update_user_meta($user_id, '_svrt_company', $company);

    // Create contributor record
    global $wpdb;
    $wpdb->insert("{$wpdb->prefix}svrt_subscribers", [
        'user_id'      => $user_id,
        'plan'         => 'contributor',
        'upload_quota' => 0,
        'uploads_used' => 0,
        'company'      => $company,
    ]);

    $token = svrt_generate_token($user_id);
    return new WP_REST_Response([
        'token'   => $token,
        'user_id' => $user_id,
        'email'   => $email,
        'name'    => "$first $last",
        'plan'    => 'contributor',
    ], 201);
}

function svrt_api_login(WP_REST_Request $req): WP_REST_Response|WP_Error {
    $email    = sanitize_email($req->get_param('email') ?? '');
    $password = $req->get_param('password') ?? '';

    if (!$email || !$password) {
        return new WP_Error('missing_fields', 'Email and password are required.', ['status' => 400]);
    }

    $user = get_user_by('email', $email);
    if (!$user || !wp_check_password($password, $user->user_pass, $user->ID)) {
        return new WP_Error('invalid_credentials', 'Invalid email or password.', ['status' => 401]);
    }

    $sub = svrt_get_subscriber($user->ID);
    $token = svrt_generate_token($user->ID);

    return new WP_REST_Response([
        'token'   => $token,
        'user_id' => $user->ID,
        'email'   => $user->user_email,
        'name'    => trim($user->first_name . ' ' . $user->last_name),
        'plan'    => $sub['plan'] ?? 'contributor',
    ], 200);
}

function svrt_api_logout(WP_REST_Request $req): WP_REST_Response {
    $token = svrt_get_bearer_token();
    if ($token) svrt_invalidate_token($token);
    return new WP_REST_Response(['message' => 'Logged out.'], 200);
}

function svrt_api_me(WP_REST_Request $req): WP_REST_Response {
    $user = wp_get_current_user();
    $sub  = svrt_get_subscriber($user->ID);
    return new WP_REST_Response([
        'user_id'      => $user->ID,
        'email'        => $user->user_email,
        'name'         => trim($user->first_name . ' ' . $user->last_name),
        'company'      => get_user_meta($user->ID, '_svrt_company', true),
        'plan'         => $sub['plan'] ?? 'contributor',
        'uploads_used' => (int) ($sub['uploads_used'] ?? 0),
    ], 200);
}

// ============================================================
// UPLOAD ENDPOINT
// ============================================================

function svrt_api_upload(WP_REST_Request $req): WP_REST_Response|WP_Error {
    $user    = wp_get_current_user();
    $sub     = svrt_get_subscriber($user->ID);
    global $wpdb;

    if (!$sub) {
        return new WP_Error('no_account', 'Contributor account record not found.', ['status' => 403]);
    }

    // Get uploaded file
    $files = $req->get_file_params();
    if (empty($files['file'])) {
        return new WP_Error('no_file', 'No file uploaded. POST with multipart/form-data and field name "file".', ['status' => 400]);
    }

    $file = $files['file'];
    if ($file['error'] !== UPLOAD_ERR_OK) {
        return new WP_Error('upload_error', 'File upload failed (PHP error ' . $file['error'] . ').', ['status' => 400]);
    }

    $max_bytes = SVRT_UPLOAD_MB * 1024 * 1024;
    if ($file['size'] > $max_bytes) {
        return new WP_Error('file_too_large', 'File exceeds ' . SVRT_UPLOAD_MB . ' MB limit.', ['status' => 413]);
    }

    $mime      = mime_content_type($file['tmp_name']);
    $ext       = strtolower(pathinfo($file['name'], PATHINFO_EXTENSION));
    $is_json   = ($ext === 'json' || in_array($mime, ['application/json', 'text/json'], true));
    $is_csv    = ($ext === 'csv'  || in_array($mime, ['text/plain', 'text/csv', 'application/csv', 'application/octet-stream'], true));

    if (!$is_json && !$is_csv) {
        return new WP_Error('invalid_type',
            'Accepted formats: SVRT CSV (.csv), CycloneDX JSON (.json), SPDX JSON (.json).',
            ['status' => 415]
        );
    }

    // ── Parse rows from whichever format was uploaded ──────────────────────────
    $rows = [];

    if ($is_json) {
        $raw = file_get_contents($file['tmp_name']);
        $doc = json_decode($raw, true);
        if (json_last_error() !== JSON_ERROR_NONE || !is_array($doc)) {
            return new WP_Error('invalid_json', 'File is not valid JSON.', ['status' => 422]);
        }

        $parse_result = svrt_parse_sbom($doc);
        if (is_wp_error($parse_result)) return $parse_result;
        $rows = $parse_result;

    } else {
        // SVRT CSV format
        $handle  = fopen($file['tmp_name'], 'r');
        $headers = fgetcsv($handle);
        $headers = array_map(fn($h) => strtolower(trim($h)), $headers ?: []);

        $missing = array_diff(['software_name'], $headers);
        if ($missing) {
            fclose($handle);
            return new WP_Error('invalid_format',
                'CSV missing required column(s): ' . implode(', ', $missing) .
                '. Expected SVRT format v1.0 — download a scanner from the docs page.',
                ['status' => 422]
            );
        }

        $col = array_flip($headers);
        while (($data = fgetcsv($handle)) !== false) {
            if (count($data) < count($headers)) continue;
            $name = trim($data[$col['software_name']] ?? '');
            if (!$name) continue;

            $rows[] = [
                'hostname_hash' => substr(sanitize_text_field($data[$col['hostname_hash']] ?? ''), 0, 64),
                'platform'      => substr(sanitize_text_field($data[$col['platform']]      ?? ''), 0, 20),
                'filename'      => substr(sanitize_text_field($data[$col['filename']]      ?? ''), 0, 255),
                'filepath'      => substr(sanitize_text_field($data[$col['filepath']]      ?? ''), 0, 1024),
                'software_name' => substr($name, 0, 255),
                'vendor'        => substr(sanitize_text_field($data[$col['vendor']]        ?? ''), 0, 255),
                'version'       => substr(sanitize_text_field($data[$col['version']]       ?? ''), 0, 100),
                'file_type'     => substr(sanitize_text_field($data[$col['file_type']]     ?? ''), 0, 50),
                'parent_app'    => substr(sanitize_text_field($data[$col['parent_app']]    ?? ''), 0, 255),
                'scan_date'     => sanitize_text_field($data[$col['scan_date']] ?? ''),
            ];
            if (count($rows) >= SVRT_UPLOAD_LIMIT) break;
        }
        fclose($handle);
    }

    if (empty($rows)) {
        return new WP_Error('empty_file', 'No components found in file.', ['status' => 422]);
    }

    // Create job
    $uuid = wp_generate_uuid4();
    $wpdb->insert("{$wpdb->prefix}svrt_upload_jobs", [
        'uuid'      => $uuid,
        'user_id'   => $user->ID,
        'status'    => 'pending',
        'row_count' => count($rows),
        'filename'  => sanitize_text_field($file['name']),
    ]);
    $job_id = $wpdb->insert_id;

    // Insert inventory rows — eol_status='' is the "not yet processed" sentinel.
    // Never rely on the DB default here; an explicit '' ensures the processor
    // query (WHERE eol_status='') only picks up rows it hasn't touched yet.
    foreach ($rows as $row) {
        $wpdb->insert("{$wpdb->prefix}svrt_inventory_rows", array_merge($row, [
            'job_id'     => $job_id,
            'user_id'    => $user->ID,
            'eol_status' => '',
        ]));
    }

    // Increment uploads_used
    $wpdb->query($wpdb->prepare(
        "UPDATE {$wpdb->prefix}svrt_subscribers SET uploads_used = uploads_used + 1 WHERE user_id = %d",
        $user->ID
    ));

    // DO NOT call spawn_cron() here — on IONOS shared hosting it runs synchronously
    // within this request and hits the 30-second PHP timeout (504).
    // Processing is handled exclusively by UptimeRobot pinging /process every 5 min.

    return new WP_REST_Response([
        'uuid'      => $uuid,
        'job_id'    => $job_id,
        'row_count' => count($rows),
        'status'    => 'pending',
        'message'   => 'Upload accepted. Poll /wp-json/svrt/v1/job/' . $uuid . ' for status.',
    ], 202);
}

// ============================================================
// SBOM PARSERS  (CycloneDX JSON + SPDX JSON)
// Fields extracted: only what SVRT needs for EOL lookup.
// Deliberately ignored: licenses, hashes, externalReferences,
//   dependencies, vulnerabilities, properties, evidence.
// ============================================================

function svrt_parse_sbom(array $doc): array|WP_Error {
    // Detect format by signature fields
    if (isset($doc['bomFormat']) && $doc['bomFormat'] === 'CycloneDX') {
        return svrt_parse_cyclonedx($doc);
    }
    if (isset($doc['spdxVersion'])) {
        return svrt_parse_spdx($doc);
    }
    return new WP_Error('unknown_sbom',
        'Unrecognised SBOM format. Supported: CycloneDX JSON (bomFormat=CycloneDX), SPDX JSON (spdxVersion present).',
        ['status' => 422]
    );
}

// ── CycloneDX JSON parser ─────────────────────────────────────────────────────

function svrt_parse_cyclonedx(array $doc): array|WP_Error {
    $components = $doc['components'] ?? [];
    if (empty($components) || !is_array($components)) {
        return new WP_Error('no_components', 'CycloneDX SBOM contains no components.', ['status' => 422]);
    }

    // Metadata: parent app name + scan date
    $meta       = $doc['metadata'] ?? [];
    $parent_app = sanitize_text_field(($meta['component']['name'] ?? ''));
    $scan_date  = '';
    if (!empty($meta['timestamp'])) {
        $scan_date = substr($meta['timestamp'], 0, 10); // ISO date portion only
    }

    // Map purl ecosystem → platform label
    $purl_platform = function(string $purl): string {
        if (str_starts_with($purl, 'pkg:npm'))     return 'nodejs';
        if (str_starts_with($purl, 'pkg:maven'))   return 'java';
        if (str_starts_with($purl, 'pkg:pypi'))    return 'python';
        if (str_starts_with($purl, 'pkg:nuget'))   return 'dotnet';
        if (str_starts_with($purl, 'pkg:gem'))     return 'ruby';
        if (str_starts_with($purl, 'pkg:cargo'))   return 'rust';
        if (str_starts_with($purl, 'pkg:composer'))return 'php';
        if (str_starts_with($purl, 'pkg:golang'))  return 'go';
        if (str_starts_with($purl, 'pkg:apk'))     return 'alpine';
        if (str_starts_with($purl, 'pkg:deb'))     return 'linux';
        if (str_starts_with($purl, 'pkg:rpm'))     return 'linux';
        return '';
    };

    $rows = [];
    foreach ($components as $c) {
        if (!is_array($c)) continue;

        $name = trim($c['name'] ?? '');
        if (!$name) continue;

        // Qualify name with group if present (e.g. org.springframework / spring-core)
        $group = trim($c['group'] ?? '');

        // Vendor: prefer publisher, fall back to supplier.name, then author
        $vendor = trim(
            $c['publisher']
            ?? ($c['supplier']['name'] ?? '')
            ?? ($c['author'] ?? '')
            ?? $group
        );

        $purl     = trim($c['purl'] ?? '');
        $platform = $purl ? $purl_platform($purl) : '';

        $rows[] = [
            'software_name' => substr($name, 0, 255),
            'vendor'        => substr(sanitize_text_field($vendor), 0, 255),
            'version'       => substr(sanitize_text_field($c['version'] ?? ''), 0, 100),
            'file_type'     => substr(sanitize_text_field($c['type']    ?? ''), 0, 50),
            'platform'      => substr($platform, 0, 20),
            'parent_app'    => substr(sanitize_text_field($parent_app), 0, 255),
            'scan_date'     => $scan_date,
            // Fields not present in SBOMs — left empty
            'hostname_hash' => '',
            'filename'      => $group ? substr("$group/$name", 0, 255) : substr($name, 0, 255),
            'filepath'      => substr($purl, 0, 1024),
        ];

        if (count($rows) >= SVRT_UPLOAD_LIMIT) break;
    }

    return $rows;
}

// ── SPDX JSON parser ──────────────────────────────────────────────────────────

function svrt_parse_spdx(array $doc): array|WP_Error {
    $packages = $doc['packages'] ?? [];
    if (empty($packages) || !is_array($packages)) {
        return new WP_Error('no_packages', 'SPDX document contains no packages.', ['status' => 422]);
    }

    // Scan date from document creation info
    $scan_date = '';
    if (!empty($doc['documentCreationInfo']['created'])) {
        $scan_date = substr($doc['documentCreationInfo']['created'], 0, 10);
    } elseif (!empty($doc['creationInfo']['created'])) {
        $scan_date = substr($doc['creationInfo']['created'], 0, 10);
    }

    // Identify the root "describes" package as parent app (skip it from components)
    $describes_ids = [];
    foreach ($doc['relationships'] ?? [] as $rel) {
        if (($rel['relationshipType'] ?? '') === 'DESCRIBES') {
            $describes_ids[] = $rel['relatedSpdxElement'] ?? '';
        }
    }

    $rows = [];
    foreach ($packages as $pkg) {
        if (!is_array($pkg)) continue;

        // Skip the root document package itself
        $spdx_id = $pkg['SPDXID'] ?? '';
        if (in_array($spdx_id, $describes_ids, true)) continue;

        $name = trim($pkg['name'] ?? '');
        if (!$name) continue;

        // Vendor: prefer originator, fall back to supplier (strip "Organization:" prefix)
        $raw_vendor = $pkg['originator'] ?? $pkg['supplier'] ?? '';
        $vendor     = preg_replace('/^(Organization|Person|Tool):\s*/i', '', $raw_vendor);

        // Map primaryPackagePurpose to file_type
        $purpose  = strtolower($pkg['primaryPackagePurpose'] ?? '');
        $file_type = match($purpose) {
            'library'       => 'library',
            'framework'     => 'framework',
            'application'   => 'application',
            'operating-system' => 'os',
            'container'     => 'container',
            'firmware'      => 'firmware',
            default         => $purpose ?: 'library',
        };

        // Extract purl if present in externalRefs (for platform detection)
        $purl     = '';
        $platform = '';
        foreach ($pkg['externalRefs'] ?? [] as $ref) {
            if (($ref['referenceType'] ?? '') === 'purl') {
                $purl = $ref['referenceLocator'] ?? '';
                break;
            }
        }
        if ($purl) {
            if (str_starts_with($purl, 'pkg:npm'))     $platform = 'nodejs';
            elseif (str_starts_with($purl, 'pkg:maven'))   $platform = 'java';
            elseif (str_starts_with($purl, 'pkg:pypi'))    $platform = 'python';
            elseif (str_starts_with($purl, 'pkg:nuget'))   $platform = 'dotnet';
            elseif (str_starts_with($purl, 'pkg:gem'))     $platform = 'ruby';
            elseif (str_starts_with($purl, 'pkg:cargo'))   $platform = 'rust';
            elseif (str_starts_with($purl, 'pkg:composer'))$platform = 'php';
            elseif (str_starts_with($purl, 'pkg:golang'))  $platform = 'go';
        }

        $rows[] = [
            'software_name' => substr($name, 0, 255),
            'vendor'        => substr(sanitize_text_field($vendor), 0, 255),
            'version'       => substr(sanitize_text_field($pkg['versionInfo'] ?? ''), 0, 100),
            'file_type'     => substr($file_type, 0, 50),
            'platform'      => substr($platform, 0, 20),
            'parent_app'    => '',
            'scan_date'     => $scan_date,
            'hostname_hash' => '',
            'filename'      => substr($name, 0, 255),
            'filepath'      => substr($purl, 0, 1024),
        ];

        if (count($rows) >= SVRT_UPLOAD_LIMIT) break;
    }

    return $rows;
}

// ============================================================
// JOB PROCESSING  (WordPress cron action)
// ============================================================

add_action('svrt_process_job', 'svrt_process_job');

function svrt_process_job(int $job_id, int $time_limit = 20): void {
    global $wpdb;
    $start = microtime(true);

    $job = $wpdb->get_row($wpdb->prepare(
        "SELECT * FROM {$wpdb->prefix}svrt_upload_jobs WHERE id = %d",
        $job_id
    ), ARRAY_A);

    // Accept pending OR already in-progress (allows chunked continuation across pings)
    if (!$job || !in_array($job['status'], ['pending', 'processing'], true)) return;

    // Mark in-progress
    $wpdb->update(
        "{$wpdb->prefix}svrt_upload_jobs",
        ['status' => 'processing'],
        ['id'     => $job_id]
    );

    // Only fetch rows not yet processed. '' is the explicit "unprocessed" sentinel
    // set at insert time. After a lookup (matched or not), eol_status is always
    // set to a non-empty value ('supported','eol','unknown', etc.), so these rows
    // are never re-processed on subsequent pings.
    $rows = $wpdb->get_results($wpdb->prepare(
        "SELECT * FROM {$wpdb->prefix}svrt_inventory_rows
         WHERE job_id = %d AND eol_status = ''
         LIMIT 500",
        $job_id
    ), ARRAY_A);

    $matched = (int) ($job['matched_count'] ?? 0);
    $eol     = (int) ($job['eol_count']     ?? 0);
    $done    = true;

    foreach ($rows as $row) {
        // Stop processing if we're approaching the time limit (leave 3s buffer)
        if ((microtime(true) - $start) > ($time_limit - 3)) {
            $done = false;
            break;
        }

        $result = svrt_lookup_reference($row['software_name'], $row['vendor'], $row['version']);

        $update = [
            'eol_status'        => 'unknown',
            'eol_date'          => '',
            'latest_version'    => '',
            'latest_source_url' => '',
            'confidence'        => 0,
            'ref_source'        => '',
            'ref_notes'         => '',
        ];

        if ($result) {
            $update = array_merge($update, $result);
            if ($result['eol_status'] === 'eol') $eol++;
        }

        // Count every looked-up row toward progress (matched = processed, not
        // just "found in reference"). This keeps the progress bar moving even
        // when most results come back as 'unknown' on a sparse reference DB.
        $matched++;

        $wpdb->update(
            "{$wpdb->prefix}svrt_inventory_rows",
            $update,
            ['id' => $row['id']]
        );
    }

    // Check if ALL rows are now processed
    $remaining = (int) $wpdb->get_var($wpdb->prepare(
        "SELECT COUNT(*) FROM {$wpdb->prefix}svrt_inventory_rows
         WHERE job_id = %d AND eol_status = ''",
        $job_id
    ));

    // If no unprocessed rows remain, mark complete; otherwise stay in-progress for next ping
    if ($remaining === 0) {
        // Generate a 24-hour signed report token for the email link
        $report_token   = bin2hex(random_bytes(16));
        $token_expires  = gmdate('Y-m-d H:i:s', time() + 24 * HOUR_IN_SECONDS);

        $wpdb->update(
            "{$wpdb->prefix}svrt_upload_jobs",
            [
                'status'               => 'complete',
                'matched_count'        => $matched,
                'eol_count'            => $eol,
                'completed_at'         => gmdate('Y-m-d H:i:s'),
                'report_token'         => $report_token,
                'report_token_expires' => $token_expires,
            ],
            ['id' => $job_id]
        );

        // Send report-ready email to the subscriber
        $owner = get_user_by('ID', (int) $job['user_id']);
        if ($owner && $owner->user_email) {
            $updated_job = array_merge($job, [
                'matched_count' => $matched,
                'eol_count'     => $eol,
            ]);
            svrt_send_report_email($owner->user_email, $job['uuid'], $report_token, $updated_job);
        }
    } else {
        // Save progress so far; UptimeRobot will continue it on next ping
        $wpdb->update(
            "{$wpdb->prefix}svrt_upload_jobs",
            [
                'matched_count' => $matched,
                'eol_count'     => $eol,
            ],
            ['id' => $job_id]
        );
    }
}

// ── Reference DB lookup ──────────────────────────────────────

/**
 * Normalise a version string so PHP's version_compare() can handle it.
 * Strips leading 'v'/'V', extracts the leading numeric.numeric... portion,
 * and ignores build metadata / pre-release suffixes.
 * e.g. "v10.0.19041.1234-beta" → "10.0.19041.1234"
 */
function svrt_normalize_version(string $v): string {
    $v = ltrim(trim($v), 'vV');
    // Extract leading numeric dotted portion only
    if (preg_match('/^[\d]+(?:\.[\d]+)*/', $v, $m)) {
        return $m[0];
    }
    return $v;
}

function svrt_lookup_reference(string $name, string $vendor, string $version): ?array {
    global $wpdb;

    // Build lookup key (same algorithm as Pi agent — vendor:product:major)
    $major = preg_match('/^(\d+)/', $version, $m) ? $m[1] : '';
    $raw   = strtolower(trim($vendor)) . ':' . strtolower(trim($name)) . ':' . $major;
    $key   = substr(hash('sha256', $raw), 0, 16) . ':' . strtolower(substr($name, 0, 40));

    $ref = $wpdb->get_row($wpdb->prepare(
        "SELECT * FROM {$wpdb->prefix}svrt_reference WHERE lookup_key = %s",
        $key
    ), ARRAY_A);

    // Fuzzy fallback: search by lowercase software_name
    if (!$ref) {
        $ref = $wpdb->get_row($wpdb->prepare(
            "SELECT * FROM {$wpdb->prefix}svrt_reference WHERE LOWER(software_name) = %s LIMIT 1",
            strtolower(trim($name))
        ), ARRAY_A);
    }

    if (!$ref) return null;

    // Increment hit count
    $wpdb->query($wpdb->prepare(
        "UPDATE {$wpdb->prefix}svrt_reference SET hit_count = hit_count + 1 WHERE id = %d",
        $ref['id']
    ));

    // ── Outdated detection ──────────────────────────────────────────────────
    // If the reference DB says the product is still supported/LTS but we have
    // a newer version available, flag the inventory row as 'outdated' so the
    // user knows to upgrade even though support hasn't ended yet.
    $eol_status = $ref['eol_status'];
    if (
        in_array($eol_status, ['supported', 'lts'], true) &&
        !empty($ref['latest_version']) &&
        $version !== ''
    ) {
        $inv_ver = svrt_normalize_version($version);
        $lat_ver = svrt_normalize_version($ref['latest_version']);
        if ($inv_ver !== '' && $lat_ver !== '' && version_compare($inv_ver, $lat_ver, '<')) {
            $eol_status = 'outdated';
        }
    }

    return [
        'eol_status'        => $eol_status,
        'eol_date'          => $ref['eol_date'],
        'latest_version'    => $ref['latest_version'],
        'latest_source_url' => $ref['latest_source_url'],
        'confidence'        => (int) $ref['confidence'],
        'ref_source'        => $ref['ref_source'],
        'ref_notes'         => $ref['notes'],
    ];
}

// ============================================================
// JOB STATUS + REPORT ENDPOINTS
// ============================================================

function svrt_api_job_status(WP_REST_Request $req): WP_REST_Response|WP_Error {
    global $wpdb;
    $uuid   = sanitize_text_field($req->get_param('uuid'));
    $rtoken = sanitize_text_field($req->get_param('rtoken') ?? '');

    if (is_user_logged_in()) {
        // Authenticated user — must own the job
        $job = $wpdb->get_row($wpdb->prepare(
            "SELECT * FROM {$wpdb->prefix}svrt_upload_jobs WHERE uuid = %s AND user_id = %d",
            $uuid, get_current_user_id()
        ), ARRAY_A);
    } elseif ($rtoken) {
        // Report-link token — validate token and expiry (no user_id check)
        $job = $wpdb->get_row($wpdb->prepare(
            "SELECT * FROM {$wpdb->prefix}svrt_upload_jobs
             WHERE uuid = %s AND report_token = %s AND report_token_expires > %s",
            $uuid, $rtoken, gmdate('Y-m-d H:i:s')
        ), ARRAY_A);
    } else {
        return new WP_Error('unauthorized', 'Authentication required.', ['status' => 401]);
    }

    if (!$job) {
        return new WP_Error('not_found', 'Job not found or link has expired.', ['status' => 404]);
    }

    $progress = $job['row_count'] > 0
        ? round((int) $job['matched_count'] / (int) $job['row_count'] * 100)
        : 0;

    return new WP_REST_Response([
        'uuid'          => $job['uuid'],
        'status'        => $job['status'],
        'row_count'     => (int) $job['row_count'],
        'matched_count' => (int) $job['matched_count'],
        'eol_count'     => (int) $job['eol_count'],
        'progress_pct'  => min(100, $progress),
        'filename'      => $job['filename'],
        'created_at'    => $job['created_at'],
        'completed_at'  => $job['completed_at'],
        'error_msg'     => $job['error_msg'],
    ], 200);
}

function svrt_api_job_report(WP_REST_Request $req): WP_REST_Response|WP_Error {
    global $wpdb;
    $uuid   = sanitize_text_field($req->get_param('uuid'));
    $rtoken = sanitize_text_field($req->get_param('rtoken') ?? '');

    if (is_user_logged_in()) {
        $job = $wpdb->get_row($wpdb->prepare(
            "SELECT * FROM {$wpdb->prefix}svrt_upload_jobs WHERE uuid = %s AND user_id = %d",
            $uuid, get_current_user_id()
        ), ARRAY_A);
    } elseif ($rtoken) {
        $job = $wpdb->get_row($wpdb->prepare(
            "SELECT * FROM {$wpdb->prefix}svrt_upload_jobs
             WHERE uuid = %s AND report_token = %s AND report_token_expires > %s",
            $uuid, $rtoken, gmdate('Y-m-d H:i:s')
        ), ARRAY_A);
    } else {
        return new WP_Error('unauthorized', 'Authentication required.', ['status' => 401]);
    }

    if (!$job) {
        return new WP_Error('not_found', 'Job not found or link has expired.', ['status' => 404]);
    }
    if ($job['status'] !== 'complete') {
        return new WP_Error('not_ready', 'Report not ready yet. Poll /job/' . $uuid . ' for status.', ['status' => 202]);
    }

    // Get filter param: all | eol | unknown | supported
    $filter = sanitize_text_field($req->get_param('filter') ?? 'all');
    $where  = $wpdb->prepare("WHERE job_id = %d", $job['id']);
    if (in_array($filter, ['eol', 'unknown', 'supported', 'lts', 'no_patch'], true)) {
        $where .= $wpdb->prepare(" AND eol_status = %s", $filter);
    }

    $rows = $wpdb->get_results(
        "SELECT software_name, vendor, version, platform, file_type, parent_app,
                eol_status, eol_date, latest_version, latest_source_url,
                confidence, ref_source, ref_notes, hostname_hash, scan_date
         FROM {$wpdb->prefix}svrt_inventory_rows
         $where
         ORDER BY eol_status ASC, software_name ASC",
        ARRAY_A
    );

    // Summary stats
    $stats = $wpdb->get_results($wpdb->prepare(
        "SELECT eol_status, COUNT(*) as count
         FROM {$wpdb->prefix}svrt_inventory_rows
         WHERE job_id = %d
         GROUP BY eol_status",
        $job['id']
    ), ARRAY_A);
    $summary = array_column($stats, 'count', 'eol_status');

    return new WP_REST_Response([
        'uuid'       => $uuid,
        'filename'   => $job['filename'],
        'row_count'  => (int) $job['row_count'],
        'summary'    => [
            'eol'       => (int) ($summary['eol']       ?? 0),
            'supported' => (int) ($summary['supported'] ?? 0),
            'lts'       => (int) ($summary['lts']       ?? 0),
            'no_patch'  => (int) ($summary['no_patch']  ?? 0),
            'unknown'   => (int) ($summary['unknown']   ?? 0),
        ],
        'items'      => $rows,
    ], 200);
}

// ── My jobs list ─────────────────────────────────────────────────────────────

function svrt_api_my_jobs(WP_REST_Request $req): WP_REST_Response {
    global $wpdb;
    $user_id = get_current_user_id();

    $jobs = $wpdb->get_results($wpdb->prepare(
        "SELECT uuid, status, filename, row_count, matched_count, eol_count, created_at, completed_at
         FROM {$wpdb->prefix}svrt_upload_jobs
         WHERE user_id = %d
         ORDER BY created_at DESC
         LIMIT 50",
        $user_id
    ), ARRAY_A) ?: [];

    return new WP_REST_Response($jobs, 200);
}

// ── Delete job ───────────────────────────────────────────────────────────────

function svrt_api_delete_job(WP_REST_Request $req): WP_REST_Response|WP_Error {
    global $wpdb;
    $uuid    = sanitize_text_field($req->get_param('uuid'));
    $user_id = get_current_user_id();

    $job = $wpdb->get_row($wpdb->prepare(
        "SELECT * FROM {$wpdb->prefix}svrt_upload_jobs WHERE uuid = %s AND user_id = %d",
        $uuid, $user_id
    ), ARRAY_A);

    if (!$job) {
        return new WP_Error('not_found', 'Job not found.', ['status' => 404]);
    }

    // Delete inventory rows first (FK-safe), then the job
    $wpdb->delete("{$wpdb->prefix}svrt_inventory_rows", ['job_id' => $job['id']], ['%d']);
    $wpdb->delete("{$wpdb->prefix}svrt_upload_jobs",    ['id'     => $job['id']], ['%d']);

    return new WP_REST_Response(['message' => 'Scan deleted.', 'uuid' => $uuid], 200);
}

// ── Resend report email ───────────────────────────────────────────────────────

function svrt_api_resend_report(WP_REST_Request $req): WP_REST_Response|WP_Error {
    global $wpdb;
    $uuid = sanitize_text_field($req->get_param('uuid'));

    $job = $wpdb->get_row($wpdb->prepare(
        "SELECT * FROM {$wpdb->prefix}svrt_upload_jobs WHERE uuid = %s AND user_id = %d",
        $uuid, get_current_user_id()
    ), ARRAY_A);

    if (!$job) {
        return new WP_Error('not_found', 'Job not found.', ['status' => 404]);
    }
    if ($job['status'] !== 'complete') {
        return new WP_Error('not_ready', 'Report is not complete yet.', ['status' => 409]);
    }

    // Refresh token + expiry
    $report_token  = bin2hex(random_bytes(16));
    $token_expires = gmdate('Y-m-d H:i:s', time() + 24 * HOUR_IN_SECONDS);

    $wpdb->update(
        "{$wpdb->prefix}svrt_upload_jobs",
        ['report_token' => $report_token, 'report_token_expires' => $token_expires],
        ['id' => $job['id']]
    );

    $user = wp_get_current_user();
    svrt_send_report_email($user->user_email, $uuid, $report_token, $job);

    return new WP_REST_Response(['message' => 'Report link re-sent to ' . $user->user_email], 200);
}

// ============================================================
// REFERENCE DB ENDPOINTS
// ============================================================

function svrt_api_reference_db(WP_REST_Request $req): WP_REST_Response {
    global $wpdb;

    $page     = max(1, (int) ($req->get_param('page') ?? 1));
    $per_page = min(500, max(10, (int) ($req->get_param('per_page') ?? 100)));
    $offset   = ($page - 1) * $per_page;
    $status   = sanitize_text_field($req->get_param('status') ?? '');

    $where = '';
    if (in_array($status, ['eol', 'supported', 'lts', 'unknown', 'no_patch'], true)) {
        $where = $wpdb->prepare("WHERE eol_status = %s", $status);
    }

    $total = (int) $wpdb->get_var(
        "SELECT COUNT(*) FROM {$wpdb->prefix}svrt_reference $where"
    );

    $rows = $wpdb->get_results(
        "SELECT software_name, vendor, version, platform, eol_status, eol_date,
                latest_version, latest_source_url, confidence, ref_source, hit_count, checked_at
         FROM {$wpdb->prefix}svrt_reference
         $where
         ORDER BY hit_count DESC, software_name ASC
         LIMIT $per_page OFFSET $offset",
        ARRAY_A
    );

    return new WP_REST_Response([
        'total'    => $total,
        'page'     => $page,
        'per_page' => $per_page,
        'pages'    => (int) ceil($total / $per_page),
        'items'    => $rows,
    ], 200);
}

function svrt_api_reference_search(WP_REST_Request $req): WP_REST_Response|WP_Error {
    global $wpdb;

    $q = sanitize_text_field($req->get_param('q') ?? '');
    if (strlen($q) < 2) {
        return new WP_Error('query_too_short', 'Search query must be at least 2 characters.', ['status' => 400]);
    }

    $like = '%' . $wpdb->esc_like($q) . '%';
    $rows = $wpdb->get_results($wpdb->prepare(
        "SELECT software_name, vendor, version, platform, eol_status, eol_date,
                latest_version, latest_source_url, confidence, ref_source, hit_count
         FROM {$wpdb->prefix}svrt_reference
         WHERE software_name LIKE %s OR vendor LIKE %s
         ORDER BY hit_count DESC
         LIMIT 50",
        $like, $like
    ), ARRAY_A);

    return new WP_REST_Response(['items' => $rows, 'count' => count($rows)], 200);
}

// ============================================================
// STATS ENDPOINT (public)
// ============================================================

function svrt_api_stats(WP_REST_Request $req): WP_REST_Response {
    global $wpdb;

    $ref_total = (int) $wpdb->get_var("SELECT COUNT(*) FROM {$wpdb->prefix}svrt_reference");
    $ref_eol   = (int) $wpdb->get_var("SELECT COUNT(*) FROM {$wpdb->prefix}svrt_reference WHERE eol_status='eol'");
    $ref_supp  = (int) $wpdb->get_var("SELECT COUNT(*) FROM {$wpdb->prefix}svrt_reference WHERE eol_status='supported'");
    $subs      = (int) $wpdb->get_var("SELECT COUNT(*) FROM {$wpdb->prefix}svrt_subscribers");
    $jobs      = (int) $wpdb->get_var("SELECT COUNT(*) FROM {$wpdb->prefix}svrt_upload_jobs WHERE status='complete'");

    return new WP_REST_Response([
        'reference_entries'   => $ref_total,
        'eol_entries'         => $ref_eol,
        'supported_entries'   => $ref_supp,
        'contributors'        => $subs,
        'scans_completed'     => $jobs,
        'format_version'      => '1.0',
        'last_updated'        => get_option('svrt_last_reference_import', ''),
    ], 200);
}

// ============================================================
// ADMIN: IMPORT REFERENCE DB FROM PI SYNC
// ============================================================

function svrt_api_admin_import_reference(WP_REST_Request $req): WP_REST_Response|WP_Error {
    global $wpdb;

    // Expects JSON body: array of reference objects from the Pi's CSV/DB export
    $body = $req->get_json_params();
    if (empty($body) || !is_array($body)) {
        return new WP_Error('invalid_body', 'Expected JSON array of reference entries.', ['status' => 400]);
    }

    $imported = 0;
    $skipped  = 0;

    foreach ($body as $entry) {
        if (empty($entry['lookup_key']) || empty($entry['software_name'])) {
            $skipped++;
            continue;
        }
        $result = $wpdb->query($wpdb->prepare(
            "INSERT INTO {$wpdb->prefix}svrt_reference
                (lookup_key, software_name, vendor, version, platform,
                 eol_status, eol_date, latest_version, latest_source_url,
                 confidence, ref_source, notes, hit_count, checked_at, expires_at)
             VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%d,%s,%s,0,%s,%s)
             ON DUPLICATE KEY UPDATE
                eol_status=VALUES(eol_status),
                eol_date=VALUES(eol_date),
                latest_version=VALUES(latest_version),
                latest_source_url=VALUES(latest_source_url),
                confidence=VALUES(confidence),
                ref_source=VALUES(ref_source),
                notes=VALUES(notes),
                checked_at=VALUES(checked_at),
                expires_at=VALUES(expires_at)",
            $entry['lookup_key'],
            $entry['software_name'],
            $entry['vendor']            ?? '',
            $entry['version']           ?? '',
            $entry['platform']          ?? '',
            $entry['eol_status']        ?? 'unknown',
            $entry['eol_date']          ?? '',
            $entry['latest_version']    ?? '',
            $entry['latest_source_url'] ?? '',
            (int) ($entry['confidence'] ?? 0),
            $entry['ref_source']        ?? '',
            $entry['notes']             ?? '',
            $entry['checked_at']        ?? current_time('mysql'),
            $entry['expires_at']        ?? null,
        ));
        if ($result !== false) $imported++;
        else $skipped++;
    }

    update_option('svrt_last_reference_import', current_time('mysql'));

    return new WP_REST_Response([
        'imported' => $imported,
        'skipped'  => $skipped,
        'total'    => count($body),
    ], 200);
}

// ============================================================
// ADMIN: JOBS + SUBSCRIBERS LIST
// ============================================================

function svrt_api_admin_jobs(WP_REST_Request $req): WP_REST_Response {
    global $wpdb;
    $limit = min(100, max(10, (int) ($req->get_param('limit') ?? 50)));

    $jobs = $wpdb->get_results(
        "SELECT j.*, u.user_email
         FROM {$wpdb->prefix}svrt_upload_jobs j
         LEFT JOIN {$wpdb->users} u ON j.user_id = u.ID
         ORDER BY j.created_at DESC
         LIMIT $limit",
        ARRAY_A
    );
    return new WP_REST_Response(['jobs' => $jobs, 'count' => count($jobs)], 200);
}

function svrt_api_admin_subscribers(WP_REST_Request $req): WP_REST_Response {
    global $wpdb;

    $subs = $wpdb->get_results(
        "SELECT s.*, u.user_email, u.first_name, u.last_name, u.display_name
         FROM {$wpdb->prefix}svrt_subscribers s
         LEFT JOIN {$wpdb->users} u ON s.user_id = u.ID
         ORDER BY s.created_at DESC",
        ARRAY_A
    );
    return new WP_REST_Response(['subscribers' => $subs, 'count' => count($subs)], 200);
}

// ============================================================
// PUBLIC INDUSTRY DASHBOARD
// ============================================================

function svrt_api_dashboard(WP_REST_Request $req): WP_REST_Response {
    // Cache for 60 minutes — aggregate queries are expensive.
    // Pass ?refresh=1&secret=<queue_secret> to flush and rebuild immediately.
    $wants_refresh = (bool) $req->get_param('refresh');
    if ($wants_refresh) {
        $secret = sanitize_text_field($req->get_param('secret') ?? '');
        $stored = get_option('svrt_process_secret', '');
        if ($stored && $secret === $stored) {
            delete_transient('svrt_dashboard_cache');
        }
    }

    $cached = get_transient('svrt_dashboard_cache');
    if ($cached !== false) {
        return new WP_REST_Response(array_merge($cached, ['cached' => true]), 200);
    }

    global $wpdb;
    $ir = "{$wpdb->prefix}svrt_inventory_rows";
    $uj = "{$wpdb->prefix}svrt_upload_jobs";

    // Only count rows from completed jobs (avoid partial-scan skew)
    $completed_ids_sql = "SELECT id FROM {$uj} WHERE status = 'complete'";

    // ── Overall summary ──────────────────────────────────────
    $summary_row = $wpdb->get_row(
        "SELECT
            COUNT(DISTINCT job_id)                                           AS total_scans,
            COUNT(*)                                                         AS total_items,
            COUNT(DISTINCT LOWER(TRIM(software_name)))                       AS unique_products,
            SUM(CASE WHEN eol_status = 'eol'       THEN 1 ELSE 0 END)       AS eol,
            SUM(CASE WHEN eol_status = 'outdated'  THEN 1 ELSE 0 END)       AS outdated,
            SUM(CASE WHEN eol_status = 'no_patch'  THEN 1 ELSE 0 END)       AS no_patch,
            SUM(CASE WHEN eol_status = 'supported' THEN 1 ELSE 0 END)       AS supported,
            SUM(CASE WHEN eol_status = 'lts'       THEN 1 ELSE 0 END)       AS lts,
            SUM(CASE WHEN eol_status = 'unknown'   THEN 1 ELSE 0 END)       AS unknown_count
         FROM $ir
         WHERE job_id IN ($completed_ids_sql)
           AND software_name != ''",
        ARRAY_A
    ) ?: [];

    $total_items = max(1, (int) ($summary_row['total_items'] ?? 1));

    $summary = [
        'total_scans'     => (int) ($summary_row['total_scans']    ?? 0),
        'total_items'     => (int) ($summary_row['total_items']    ?? 0),
        'unique_products' => (int) ($summary_row['unique_products'] ?? 0),
        'eol'             => (int) ($summary_row['eol']            ?? 0),
        'outdated'        => (int) ($summary_row['outdated']       ?? 0),
        'no_patch'        => (int) ($summary_row['no_patch']       ?? 0),
        'supported'       => (int) ($summary_row['supported']      ?? 0),
        'lts'             => (int) ($summary_row['lts']            ?? 0),
        'unknown'         => (int) ($summary_row['unknown_count']  ?? 0),
        'eol_pct'         => round((int) ($summary_row['eol'] ?? 0) / $total_items * 100, 1),
    ];

    // ── Top 20 EOL software across all uploads ───────────────
    $top_eol = $wpdb->get_results(
        "SELECT
            software_name,
            vendor,
            MAX(eol_date)       AS eol_date,
            MAX(latest_version) AS latest_version,
            COUNT(DISTINCT hostname_hash) AS machines,
            COUNT(*)                      AS occurrences
         FROM $ir
         WHERE eol_status = 'eol'
           AND job_id IN ($completed_ids_sql)
           AND software_name != ''
         GROUP BY LOWER(TRIM(software_name)), LOWER(TRIM(vendor))
         ORDER BY machines DESC
         LIMIT 20",
        ARRAY_A
    ) ?: [];

    foreach ($top_eol as &$row) {
        $row['machines']    = (int) $row['machines'];
        $row['occurrences'] = (int) $row['occurrences'];
    }
    unset($row);

    // ── Platform breakdown ───────────────────────────────────
    $platform_rows = $wpdb->get_results(
        "SELECT
            COALESCE(NULLIF(TRIM(platform), ''), 'unknown') AS platform,
            COUNT(*)                                         AS total,
            SUM(CASE WHEN eol_status IN ('eol', 'outdated', 'no_patch') THEN 1 ELSE 0 END) AS eol_count
         FROM $ir
         WHERE job_id IN ($completed_ids_sql)
         GROUP BY LOWER(TRIM(platform))
         ORDER BY total DESC
         LIMIT 12",
        ARRAY_A
    ) ?: [];

    $platforms = array_map(function ($r) {
        $total = max(1, (int) $r['total']);
        $eol   = (int) $r['eol_count'];
        return [
            'platform'  => $r['platform'],
            'total'     => $total,
            'eol_count' => $eol,
            'eol_pct'   => round($eol / $total * 100, 1),
        ];
    }, $platform_rows);

    // ── Scan activity — completed scans per day, last 30 days ─
    $activity = $wpdb->get_results(
        "SELECT DATE(completed_at) AS day, COUNT(*) AS scans
         FROM {$uj}
         WHERE status = 'complete'
           AND completed_at >= DATE_SUB(UTC_TIMESTAMP(), INTERVAL 30 DAY)
         GROUP BY DATE(completed_at)
         ORDER BY day ASC",
        ARRAY_A
    ) ?: [];

    foreach ($activity as &$row) {
        $row['scans'] = (int) $row['scans'];
    }
    unset($row);

    // ── Top 15 unique software by frequency (all statuses) ───
    $top_software = $wpdb->get_results(
        "SELECT
            software_name,
            vendor,
            CASE MIN(CASE eol_status
                WHEN 'eol'       THEN 1
                WHEN 'no_patch'  THEN 2
                WHEN 'outdated'  THEN 3
                WHEN 'supported' THEN 4
                WHEN 'lts'       THEN 5
                ELSE 6 END)
                WHEN 1 THEN 'eol'
                WHEN 2 THEN 'no_patch'
                WHEN 3 THEN 'outdated'
                WHEN 4 THEN 'supported'
                WHEN 5 THEN 'lts'
                ELSE 'unknown' END AS eol_status,
            COUNT(*)            AS instances,
            COUNT(DISTINCT CONCAT(LOWER(TRIM(software_name)), ':', version)) AS version_count
         FROM $ir
         WHERE job_id IN ($completed_ids_sql)
           AND software_name != ''
         GROUP BY LOWER(TRIM(software_name))
         ORDER BY instances DESC
         LIMIT 15",
        ARRAY_A
    ) ?: [];

    foreach ($top_software as &$row) {
        $row['instances']     = (int) $row['instances'];
        $row['version_count'] = (int) $row['version_count'];
    }
    unset($row);

    // ── Reference DB + Pi research agent stats ───────────────
    $ref_tbl = "{$wpdb->prefix}svrt_reference";
    $ref_row = $wpdb->get_row(
        "SELECT
            COUNT(*)                                                                    AS total,
            SUM(CASE WHEN eol_status = 'eol'     THEN 1 ELSE 0 END)                   AS eol_count,
            SUM(CASE WHEN checked_at >= DATE_SUB(UTC_TIMESTAMP(), INTERVAL 24 HOUR)
                     THEN 1 ELSE 0 END)                                                AS updated_24h,
            SUM(CASE WHEN checked_at >= DATE_SUB(UTC_TIMESTAMP(), INTERVAL 7 DAY)
                     THEN 1 ELSE 0 END)                                                AS updated_7d,
            SUM(CASE WHEN expires_at IS NOT NULL
                      AND expires_at <= DATE_ADD(UTC_TIMESTAMP(), INTERVAL 7 DAY)
                     THEN 1 ELSE 0 END)                                                AS expiring_soon,
            MAX(checked_at)                                                             AS last_checked_at
         FROM $ref_tbl",
        ARRAY_A
    ) ?: [];

    $ref_total       = (int) ($ref_row['total']        ?? 0);
    $unique_products = $summary['unique_products']      ?? 0;
    $coverage_pct    = $unique_products > 0
        ? round(min(100, $ref_total / $unique_products * 100))
        : 0;

    $payload = [
        'summary'       => $summary,
        'top_eol'       => $top_eol,
        'top_software'  => $top_software,
        'platforms'     => $platforms,
        'scan_activity' => $activity,
        'reference'     => [
            'total'         => $ref_total,
            'eol_entries'   => (int) ($ref_row['eol_count']     ?? 0),
            'updated_24h'   => (int) ($ref_row['updated_24h']   ?? 0),
            'updated_7d'    => (int) ($ref_row['updated_7d']    ?? 0),
            'expiring_soon' => (int) ($ref_row['expiring_soon'] ?? 0),
            'last_sync'     => get_option('svrt_last_reference_import', null),
            'last_checked_at' => $ref_row['last_checked_at'] ?? null,
            'coverage_pct'  => $coverage_pct,
        ],
        'cached'        => false,
        'generated_at'  => gmdate('Y-m-d H:i:s'),
    ];

    set_transient('svrt_dashboard_cache', $payload, HOUR_IN_SECONDS);

    return new WP_REST_Response($payload, 200);
}

function svrt_api_admin_queue(WP_REST_Request $req): WP_REST_Response|WP_Error {
    $secret = sanitize_text_field($req->get_param('secret') ?? '');
    $stored = get_option('svrt_process_secret', '');
    if ($stored && $secret !== $stored) {
        return new WP_Error('forbidden', 'Invalid queue secret.', ['status' => 403]);
    }

    global $wpdb;
    $now = new DateTime('now', new DateTimeZone('UTC'));

    // ── Active: pending + processing ─────────────────────────
    $active = $wpdb->get_results(
        "SELECT j.uuid, j.status, j.filename, j.row_count, j.matched_count,
                j.eol_count, j.created_at, j.error_msg, u.user_email
         FROM {$wpdb->prefix}svrt_upload_jobs j
         LEFT JOIN {$wpdb->users} u ON j.user_id = u.ID
         WHERE j.status IN ('pending', 'processing')
         ORDER BY j.created_at ASC",
        ARRAY_A
    ) ?: [];

    // ── Recent: completed/failed in last 4 hours ─────────────
    $recent = $wpdb->get_results(
        "SELECT j.uuid, j.status, j.filename, j.row_count, j.matched_count,
                j.eol_count, j.created_at, j.completed_at, j.error_msg, u.user_email
         FROM {$wpdb->prefix}svrt_upload_jobs j
         LEFT JOIN {$wpdb->users} u ON j.user_id = u.ID
         WHERE j.status IN ('complete', 'failed')
           AND j.completed_at >= DATE_SUB(UTC_TIMESTAMP(), INTERVAL 4 HOUR)
         ORDER BY j.completed_at DESC
         LIMIT 30",
        ARRAY_A
    ) ?: [];

    // Enrich with progress_pct + elapsed
    $enrich = function (array &$jobs, bool $calc_elapsed) use ($now): void {
        foreach ($jobs as &$job) {
            $rc = (int) $job['row_count'];
            $mc = (int) $job['matched_count'];
            $job['row_count']     = $rc;
            $job['matched_count'] = $mc;
            $job['eol_count']     = (int) $job['eol_count'];
            $job['progress_pct']  = $rc > 0 ? min(100, (int) round($mc / $rc * 100)) : 0;
            $job['elapsed_secs']  = 0;
            if ($calc_elapsed && !empty($job['created_at'])) {
                try {
                    $created = new DateTime($job['created_at'], new DateTimeZone('UTC'));
                    $job['elapsed_secs'] = max(0, $now->getTimestamp() - $created->getTimestamp());
                } catch (\Exception $e) { /* ignore */ }
            }
        }
        unset($job);
    };

    $enrich($active, true);
    $enrich($recent, false);

    // ── All-time summary counts ───────────────────────────────
    $counts = $wpdb->get_row(
        "SELECT
            SUM(CASE WHEN status = 'pending'    THEN 1 ELSE 0 END) AS pending,
            SUM(CASE WHEN status = 'processing' THEN 1 ELSE 0 END) AS processing,
            SUM(CASE WHEN status = 'complete'   THEN 1 ELSE 0 END) AS complete_total,
            SUM(CASE WHEN status = 'failed'     THEN 1 ELSE 0 END) AS failed_total
         FROM {$wpdb->prefix}svrt_upload_jobs",
        ARRAY_A
    ) ?: [];

    // ── Raspberry Pi research agent stats ─────────────────────
    $ref = "{$wpdb->prefix}svrt_reference";
    $ir  = "{$wpdb->prefix}svrt_inventory_rows";
    $uj  = "{$wpdb->prefix}svrt_upload_jobs";

    $ref_stats = $wpdb->get_row(
        "SELECT
            COUNT(*)                                                                     AS total,
            SUM(CASE WHEN eol_status = 'eol'       THEN 1 ELSE 0 END)                  AS eol_count,
            SUM(CASE WHEN eol_status = 'unknown'   THEN 1 ELSE 0 END)                  AS unknown_count,
            SUM(CASE WHEN checked_at >= DATE_SUB(UTC_TIMESTAMP(), INTERVAL 24 HOUR)
                     THEN 1 ELSE 0 END)                                                 AS updated_24h,
            SUM(CASE WHEN checked_at >= DATE_SUB(UTC_TIMESTAMP(), INTERVAL 7 DAY)
                     THEN 1 ELSE 0 END)                                                 AS updated_7d,
            SUM(CASE WHEN expires_at IS NOT NULL
                      AND expires_at <= DATE_ADD(UTC_TIMESTAMP(), INTERVAL 7 DAY)
                     THEN 1 ELSE 0 END)                                                 AS expiring_soon,
            SUM(CASE WHEN expires_at IS NOT NULL
                      AND expires_at < UTC_TIMESTAMP()
                     THEN 1 ELSE 0 END)                                                 AS expired,
            MAX(checked_at)                                                              AS last_checked_at
         FROM $ref",
        ARRAY_A
    ) ?: [];

    // Unique software products seen across all scans (Pi research backlog gauge)
    $unique_in_scans = (int) $wpdb->get_var(
        "SELECT COUNT(DISTINCT LOWER(TRIM(software_name)))
         FROM $ir
         WHERE software_name != ''
           AND job_id IN (SELECT id FROM $uj WHERE status = 'complete')"
    );

    $ref_total    = (int) ($ref_stats['total'] ?? 0);
    $researched   = max(0, min($ref_total, $unique_in_scans)); // capped for display
    $backlog      = max(0, $unique_in_scans - $ref_total);
    $coverage_pct = $unique_in_scans > 0 ? round($researched / $unique_in_scans * 100) : 0;

    $pi_stats = [
        'last_sync'       => get_option('svrt_last_reference_import', null),
        'last_checked_at' => $ref_stats['last_checked_at'] ?? null,
        'ref_total'       => $ref_total,
        'eol_count'       => (int) ($ref_stats['eol_count']     ?? 0),
        'unknown_count'   => (int) ($ref_stats['unknown_count'] ?? 0),
        'updated_24h'     => (int) ($ref_stats['updated_24h']   ?? 0),
        'updated_7d'      => (int) ($ref_stats['updated_7d']    ?? 0),
        'expiring_soon'   => (int) ($ref_stats['expiring_soon'] ?? 0),
        'expired'         => (int) ($ref_stats['expired']       ?? 0),
        'unique_in_scans' => $unique_in_scans,
        'backlog'         => $backlog,
        'coverage_pct'    => $coverage_pct,
    ];

    return new WP_REST_Response([
        'summary' => [
            'pending'        => (int) ($counts['pending']        ?? 0),
            'processing'     => (int) ($counts['processing']     ?? 0),
            'complete_total' => (int) ($counts['complete_total'] ?? 0),
            'failed_total'   => (int) ($counts['failed_total']   ?? 0),
        ],
        'active'      => $active,
        'recent'      => $recent,
        'pi_stats'    => $pi_stats,
        'server_time' => gmdate('Y-m-d H:i:s'),
    ], 200);
}

// ============================================================
// EXPORT UNKNOWN SOFTWARE FOR PI RESEARCH QUEUE
// Returns a CSV of unique software names the Pi hasn't researched yet.
// Pi imports this with: python3 agent/svrt_agent.py --import-csv <file>
// ============================================================

function svrt_api_unknown_software(WP_REST_Request $req): void {
    $secret = sanitize_text_field($req->get_param('secret') ?? '');
    $stored = get_option('svrt_process_secret', '');
    if ($stored && $secret !== $stored) {
        status_header(403);
        echo json_encode(['error' => 'Forbidden']);
        exit;
    }

    global $wpdb;

    // Unique unknown software from completed jobs, ordered by frequency
    // (most-seen unknowns first so Pi prioritises the most impactful ones)
    $limit = min(10000, max(100, (int) ($req->get_param('limit') ?? 10000)));

    $rows = $wpdb->get_results(
        "SELECT
            ir.software_name,
            ir.vendor,
            ir.version,
            ir.platform,
            ir.hostname_hash,
            ir.scan_date,
            COUNT(*) AS frequency
         FROM {$wpdb->prefix}svrt_inventory_rows ir
         INNER JOIN {$wpdb->prefix}svrt_upload_jobs j ON ir.job_id = j.id
         WHERE ir.eol_status = 'unknown'
           AND ir.software_name != ''
           AND j.status = 'complete'
         GROUP BY LOWER(TRIM(ir.software_name)), LOWER(TRIM(ir.vendor)), ir.version
         ORDER BY frequency DESC
         LIMIT $limit",
        ARRAY_A
    ) ?: [];

    // Stream as CSV — same column format the Pi's import_csv() expects
    header('Content-Type: text/csv; charset=utf-8');
    header('Content-Disposition: attachment; filename="svrt_unknown_software.csv"');

    $out = fopen('php://output', 'w');
    fputcsv($out, ['software_name', 'vendor', 'version', 'platform', 'hostname_hash', 'scan_date']);
    foreach ($rows as $row) {
        fputcsv($out, [
            $row['software_name'],
            $row['vendor']       ?? '',
            $row['version']      ?? '',
            $row['platform']     ?? '',
            $row['hostname_hash'] ?? '',
            $row['scan_date']    ?? '',
        ]);
    }
    fclose($out);
    exit;
}

// ============================================================
// RE-ENRICH UNKNOWN ROWS (triggered manually or by UptimeRobot)
// Finds inventory rows that were previously 'unknown' and re-runs
// them against the reference DB now that it has grown. Safe to
// run repeatedly — only touches rows still marked 'unknown'.
// ============================================================

function svrt_api_reenrich(WP_REST_Request $req): WP_REST_Response {
    $secret = sanitize_text_field($req->get_param('secret') ?? '');
    $stored = get_option('svrt_process_secret', '');
    if ($stored && $secret !== $stored) {
        return new WP_REST_Response(['error' => 'Forbidden'], 403);
    }

    global $wpdb;
    $start      = microtime(true);
    $time_limit = 20; // seconds — safe for shared hosting
    $batch      = 500;

    // Only re-check rows from completed jobs that are still 'unknown'.
    // ORDER BY RAND() ensures each run samples different rows so the entire
    // table is covered over multiple calls rather than always hitting the
    // same leading rows that MySQL returns without an explicit order.
    $rows = $wpdb->get_results(
        "SELECT ir.id, ir.software_name, ir.vendor, ir.version
         FROM {$wpdb->prefix}svrt_inventory_rows ir
         INNER JOIN {$wpdb->prefix}svrt_upload_jobs j ON ir.job_id = j.id
         WHERE ir.eol_status = 'unknown'
           AND j.status = 'complete'
         ORDER BY RAND()
         LIMIT $batch",
        ARRAY_A
    );

    $updated  = 0;
    $resolved = 0;

    foreach ($rows as $row) {
        if ((microtime(true) - $start) > ($time_limit - 2)) break;

        $result = svrt_lookup_reference($row['software_name'], $row['vendor'], $row['version']);
        $updated++;

        if ($result && $result['eol_status'] !== 'unknown') {
            $wpdb->update(
                "{$wpdb->prefix}svrt_inventory_rows",
                $result,
                ['id' => $row['id']]
            );
            $resolved++;
        }
        // Leave genuine 'unknown' rows alone — no point rewriting same value.
        // They'll be retried on the next UptimeRobot ping until the reference
        // DB grows enough to cover them.
    }

    // Still-unknown rows remaining
    $remaining = (int) $wpdb->get_var(
        "SELECT COUNT(*)
         FROM {$wpdb->prefix}svrt_inventory_rows ir
         INNER JOIN {$wpdb->prefix}svrt_upload_jobs j ON ir.job_id = j.id
         WHERE ir.eol_status = 'unknown'
           AND j.status = 'complete'"
    );

    // Flush dashboard cache so charts reflect new statuses immediately
    if ($resolved > 0) {
        delete_transient('svrt_dashboard_cache');
    }

    return new WP_REST_Response([
        'checked'   => $updated,
        'resolved'  => $resolved,
        'remaining' => $remaining,
        'elapsed'   => round(microtime(true) - $start, 2),
    ], 200);
}

// ============================================================
// PROCESS QUEUE ENDPOINT (cron trigger / UptimeRobot ping)
// ============================================================

function svrt_api_process_queue(WP_REST_Request $req): WP_REST_Response {
    // Simple secret key check to prevent public abuse
    $secret = sanitize_text_field($req->get_param('secret') ?? '');
    $stored = get_option('svrt_process_secret', '');
    if ($stored && $secret !== $stored) {
        return new WP_REST_Response(['error' => 'Forbidden'], 403);
    }

    global $wpdb;
    // Pick up both pending and in-progress (chunked jobs continue across pings)
    $pending = $wpdb->get_results(
        "SELECT id FROM {$wpdb->prefix}svrt_upload_jobs
         WHERE status IN ('pending','processing')
         ORDER BY created_at ASC LIMIT 3",
        ARRAY_A
    );

    $processed = 0;
    foreach ($pending as $job) {
        svrt_process_job((int) $job['id'], 20);
        $processed++;
    }

    return new WP_REST_Response([
        'processed' => $processed,
        'timestamp' => current_time('mysql'),
    ], 200);
}

// ============================================================
// ADMIN MENU — basic settings page
// ============================================================

add_action('admin_menu', function () {
    add_menu_page(
        'SVRT',
        'SVRT',
        'manage_options',
        'svrt-admin',
        'svrt_admin_page',
        'dashicons-database',
        30
    );
});

function svrt_admin_page(): void {
    global $wpdb;
    $ref_count  = (int) $wpdb->get_var("SELECT COUNT(*) FROM {$wpdb->prefix}svrt_reference");
    $sub_count  = (int) $wpdb->get_var("SELECT COUNT(*) FROM {$wpdb->prefix}svrt_subscribers");
    $job_count  = (int) $wpdb->get_var("SELECT COUNT(*) FROM {$wpdb->prefix}svrt_upload_jobs");
    $eol_count  = (int) $wpdb->get_var("SELECT COUNT(*) FROM {$wpdb->prefix}svrt_reference WHERE eol_status='eol'");
    $last_import = get_option('svrt_last_reference_import', 'Never');

    // Handle secret key save
    if (isset($_POST['svrt_save_secret']) && check_admin_referer('svrt_settings')) {
        $secret = sanitize_text_field($_POST['svrt_process_secret'] ?? '');
        update_option('svrt_process_secret', $secret);
        echo '<div class="notice notice-success"><p>Settings saved.</p></div>';
    }
    $current_secret = get_option('svrt_process_secret', '');
    ?>
    <div class="wrap">
        <h1>SVRT — Software Version Reference Tool</h1>
        <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:16px;margin:20px 0">
            <?php foreach ([
                ['Reference Entries', $ref_count, '#2271b1'],
                ['EOL Entries',       $eol_count, '#d63638'],
                ['Contributors',       $sub_count, '#00a32a'],
                ['Total Scans',       $job_count, '#996800'],
            ] as [$label, $val, $col]): ?>
            <div style="background:#fff;border:1px solid #ddd;border-top:4px solid <?php echo $col ?>;padding:16px;border-radius:4px">
                <div style="font-size:28px;font-weight:700;color:<?php echo $col ?>"><?php echo number_format($val) ?></div>
                <div style="color:#666;font-size:13px"><?php echo $label ?></div>
            </div>
            <?php endforeach; ?>
        </div>

        <p><strong>Last reference import:</strong> <?php echo esc_html($last_import) ?></p>
        <p><strong>API namespace:</strong> <code>/wp-json/svrt/v1/</code></p>

        <h2>Settings</h2>
        <form method="post">
            <?php wp_nonce_field('svrt_settings') ?>
            <table class="form-table">
                <tr>
                    <th>Process Queue Secret</th>
                    <td>
                        <input type="text" name="svrt_process_secret"
                               value="<?php echo esc_attr($current_secret) ?>" class="regular-text">
                        <p class="description">
                            Used to authenticate the <code>/wp-json/svrt/v1/process?secret=KEY</code> endpoint
                            (UptimeRobot ping URL). Generate a random string and keep it private.
                        </p>
                    </td>
                </tr>
            </table>
            <p><input type="submit" name="svrt_save_secret" class="button-primary" value="Save Settings"></p>
        </form>

        <h2>Quick Links</h2>
        <ul>
            <li><a href="<?php echo rest_url('svrt/v1/stats') ?>" target="_blank">Stats endpoint (public)</a></li>
            <li><a href="<?php echo rest_url('svrt/v1/admin/subscribers') ?>" target="_blank">Contributors list</a></li>
            <li><a href="<?php echo rest_url('svrt/v1/admin/jobs') ?>" target="_blank">Recent jobs</a></li>
        </ul>
    </div>
    <?php
}
