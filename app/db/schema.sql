-- Схема базы. Применяется идемпотентно при каждом старте.

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

-- --- Курс ----------------------------------------------------------------

CREATE TABLE IF NOT EXISTS topics (
    id      TEXT PRIMARY KEY,
    ord     INTEGER NOT NULL,
    title   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS lessons (
    id            TEXT PRIMARY KEY,
    topic_id      TEXT NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
    ord           INTEGER NOT NULL,
    title         TEXT NOT NULL,
    theory_md     TEXT NOT NULL,
    examples_json TEXT NOT NULL DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS tasks (
    id           TEXT PRIMARY KEY,
    lesson_id    TEXT NOT NULL REFERENCES lessons(id) ON DELETE CASCADE,
    ord          INTEGER NOT NULL,
    -- static: написано разработчиком; template: с подстановками;
    -- generated: сгенерировано учителем под ошибку и осевшее в банке
    kind         TEXT NOT NULL DEFAULT 'static',
    statement_md TEXT NOT NULL,
    starter_code TEXT NOT NULL DEFAULT '',
    solution     TEXT NOT NULL DEFAULT '',
    tests_json   TEXT NOT NULL DEFAULT '[]',
    params_json  TEXT NOT NULL DEFAULT '{}',
    difficulty   INTEGER NOT NULL DEFAULT 1,
    is_final     INTEGER NOT NULL DEFAULT 0  -- итоговое задание темы
);

CREATE INDEX IF NOT EXISTS idx_lessons_topic ON lessons(topic_id, ord);
CREATE INDEX IF NOT EXISTS idx_tasks_lesson ON tasks(lesson_id, ord);

-- --- Прогресс ученика ----------------------------------------------------

CREATE TABLE IF NOT EXISTS progress (
    lesson_id    TEXT PRIMARY KEY REFERENCES lessons(id) ON DELETE CASCADE,
    status       TEXT NOT NULL DEFAULT 'not_started',  -- not_started|in_progress|done
    score        INTEGER,
    completed_at TEXT
);

-- Каждая попытка сдать задание. Это же — сырьё для карточки ученика
-- и для отчёта о том, какие уроки написаны плохо.
CREATE TABLE IF NOT EXISTS attempts (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id    TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    ts         TEXT NOT NULL DEFAULT (datetime('now')),
    code       TEXT NOT NULL,
    verdict    TEXT NOT NULL,           -- pass|fail|error
    stdout     TEXT NOT NULL DEFAULT '',
    stderr     TEXT NOT NULL DEFAULT '',
    error_type TEXT,                    -- SyntaxError, NameError, ...
    hint_level INTEGER NOT NULL DEFAULT 0,
    llm_used   INTEGER NOT NULL DEFAULT 0,
    tokens_in  INTEGER NOT NULL DEFAULT 0,
    tokens_out INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_attempts_task ON attempts(task_id, ts);

-- Что ученик освоил, а что шатается. Заполняется детерминированно
-- из attempts, без обращения к модели.
CREATE TABLE IF NOT EXISTS concepts (
    name           TEXT PRIMARY KEY,
    status         TEXT NOT NULL DEFAULT 'not_seen',  -- not_seen|shaky|mastered
    evidence_count INTEGER NOT NULL DEFAULT 0,
    updated_at     TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Карточка ученика: один JSON, который уходит в промпт вместо истории чата.
CREATE TABLE IF NOT EXISTS profile (
    id         INTEGER PRIMARY KEY CHECK (id = 1),
    json       TEXT NOT NULL DEFAULT '{}',
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

INSERT OR IGNORE INTO profile (id, json) VALUES (1, '{}');

-- --- Служебное -----------------------------------------------------------

-- Ответы модели на идентичные запросы: дешёвая страховка от повторов.
CREATE TABLE IF NOT EXISTS llm_cache (
    prompt_hash   TEXT PRIMARY KEY,
    response_json TEXT NOT NULL,
    ts            TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Каждое обращение к модели с посчитанной ценой. Отдельно от attempts:
-- вопрос учителю можно задать и вне задания. Цена считается и хранится
-- в момент вызова, чтобы прошлые траты не поехали при смене тарифов.
CREATE TABLE IF NOT EXISTS spend (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    ts         TEXT NOT NULL DEFAULT (datetime('now')),
    model      TEXT NOT NULL,
    purpose    TEXT NOT NULL,   -- hint|question|review|profile
    tokens_in  INTEGER NOT NULL DEFAULT 0,
    cached_in  INTEGER NOT NULL DEFAULT 0,
    tokens_out INTEGER NOT NULL DEFAULT 0,
    cost_usd   REAL NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_spend_ts ON spend(ts);

-- Где ученик застрял. Отдельно от attempts, потому что простой и нажатие
-- «Не понимаю» — это не попытка сдать задание.
CREATE TABLE IF NOT EXISTS friction (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    ts      TEXT NOT NULL DEFAULT (datetime('now')),
    task_id TEXT,
    kind    TEXT NOT NULL,   -- help_request|idle|repeated_error|gave_up
    detail  TEXT NOT NULL DEFAULT ''
);

-- Текущее состояние сессии: на чём остановились, какой уровень подсказки.
CREATE TABLE IF NOT EXISTS session_state (
    id         INTEGER PRIMARY KEY CHECK (id = 1),
    lesson_id  TEXT,
    task_id    TEXT,
    stage      TEXT NOT NULL DEFAULT 'theory',
    hint_level INTEGER NOT NULL DEFAULT 0,
    draft_code TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

INSERT OR IGNORE INTO session_state (id) VALUES (1);
