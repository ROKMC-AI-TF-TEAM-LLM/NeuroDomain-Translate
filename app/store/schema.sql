-- 런타임 저장소 DDL — 계획서 §5.4
-- 폐쇄망에서 앱이 처음 뜰 때 생성한다. 반입 대상이 아니다.

PRAGMA journal_mode = WAL;      -- 동시 읽기/쓰기 허용
PRAGMA synchronous = NORMAL;
PRAGMA busy_timeout = 5000;

CREATE TABLE IF NOT EXISTS term_candidates (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    text        TEXT NOT NULL,
    direction   TEXT NOT NULL,
    freq        INTEGER NOT NULL DEFAULT 1,
    first_seen  TEXT NOT NULL,            -- ISO8601
    last_seen   TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'pending',   -- pending|accepted|rejected
    UNIQUE (text, direction)
);

CREATE TABLE IF NOT EXISTS translation_logs (
    id              TEXT PRIMARY KEY,      -- UUID
    created_at      TEXT NOT NULL,
    direction       TEXT NOT NULL,
    src             TEXT NOT NULL,
    tgt             TEXT NOT NULL,
    terms_applied   TEXT,                  -- JSON 문자열
    violations      TEXT,                  -- JSON 문자열
    backend         TEXT NOT NULL,
    prompt_version  TEXT NOT NULL,
    glossary_version INTEGER,
    chunks          INTEGER,
    retries         INTEGER,
    elapsed_ms      INTEGER
);

CREATE INDEX IF NOT EXISTS idx_logs_created ON translation_logs(created_at);
CREATE INDEX IF NOT EXISTS idx_logs_backend ON translation_logs(backend, prompt_version);
CREATE INDEX IF NOT EXISTS idx_cand_status ON term_candidates(status, freq DESC);
