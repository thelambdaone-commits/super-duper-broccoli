const fs = require("fs");
const path = require("path");

function loadDotEnv(filePath) {
    if (!fs.existsSync(filePath)) {
        return {};
    }
    return fs
        .readFileSync(filePath, "utf8")
        .split(/\r?\n/)
        .reduce((env, line) => {
            const trimmed = line.trim();
            if (!trimmed || trimmed.startsWith("#") || !trimmed.includes("=")) {
                return env;
            }
            const index = trimmed.indexOf("=");
            const key = trimmed.slice(0, index).trim();
            const value = trimmed
                .slice(index + 1)
                .trim()
                .replace(/^["']|["']$/g, "");
            env[key] = value;
            return env;
        }, {});
}

const envFile = loadDotEnv(path.join(__dirname, ".env"));
const env = (key, fallback = undefined) => process.env[key] || envFile[key] || fallback;
const envBool = (key, fallback = "false") => String(env(key, fallback)).trim().toLowerCase() === "true";
const realEnabled = envBool("REAL", "false") || String(env("EXECUTION_MODE", "")).trim().toUpperCase() === "PROD";
const paperEnabled = envBool("PAPER", realEnabled ? "false" : "true");
const forceProd = envBool("FORCE_PROD", realEnabled ? "true" : "false");

module.exports = {
    apps: [{
        // Core trading runtime. Keep a single forked process because the bot owns
        // Telegram polling locks, DuckDB/ledger handles, and execution-mode state.
        // Quick start: pm2 start ecosystem.config.js --only quant-agentic-core
        // Logs:        pm2 logs quant-agentic-core
        // Restart:     pm2 restart quant-agentic-core --update-env
        name: "quant-agentic-core",
        script: "main_agentic_clob.py",
        cwd: __dirname,
        interpreter: ".venv/bin/python",
        instances: 1,
        exec_mode: "fork",
        // Restart policy favors long-lived PAPER operation while preventing tight
        // crash loops from hiding repeated startup failures.
        max_restarts: 25,
        min_uptime: "10s",
        restart_delay: 1000,
        exp_backoff_restart_delay: 1000,
        kill_timeout: 3000,
        max_memory_restart: "4G",
        error_file: "logs/pm2-error.log",
        out_file: "logs/pm2-out.log",
        log_date_format: "YYYY-MM-DD HH:mm:ss Z",
        merge_logs: true,
        autorestart: true,
        env: {
            NODE_ENV: "production",
            PYTHONUNBUFFERED: "1",
            CHAT_ID: env("CHAT_ID"),
            TARGET_CHANNEL: env("TARGET_CHANNEL", "Lobstar"),
            TELEGRAM_CHANNEL_CHAT_ID: env("TELEGRAM_CHANNEL_CHAT_ID"),
            TELEGRAM_CHANNEL_ID: env("TELEGRAM_CHANNEL_ID"),
            TELEGRAM_BROADCASTER_CHANNEL_ID: env("TELEGRAM_BROADCASTER_CHANNEL_ID"),
            TELEGRAM_PRIVATE_CHAT_IDS: env("TELEGRAM_PRIVATE_CHAT_IDS"),
            TELEGRAM_ADMIN_CHAT_IDS: env("TELEGRAM_ADMIN_CHAT_IDS"),
            TELEGRAM_SIGNALS: env("TELEGRAM_SIGNALS", "true"),
            TELEGRAM_BROADCAST_ENABLED: env("TELEGRAM_BROADCAST_ENABLED", "1"),
            TELEGRAM_BROADCAST_EDGE_THRESHOLD: env("TELEGRAM_BROADCAST_EDGE_THRESHOLD", "0.07"),
            TELEGRAM_BROADCAST_MAX_PER_MINUTE: env("TELEGRAM_BROADCAST_MAX_PER_MINUTE", "3"),
            TELEGRAM_BROADCAST_TICKERS: env("TELEGRAM_BROADCAST_TICKERS", "SOL,BTC,ETH"),
            POLYMARKET_ONCHAIN_MONITOR_ENABLED: env("POLYMARKET_ONCHAIN_MONITOR_ENABLED", "0"),
            SECRET_SOURCE: env("SECRET_SOURCE", "auto"),
            VAULT_ADDR: env("VAULT_ADDR", "false"),
            VAULT_TOKEN: env("VAULT_TOKEN"),
            EXECUTION_MODE: env("EXECUTION_MODE", realEnabled ? "PROD" : "PAPER"),
            MODE: env("MODE", realEnabled ? "PRD" : "PAPER"),
            REAL: realEnabled ? "true" : "false",
            PAPER: paperEnabled ? "true" : "false",
            FORCE_PROD: forceProd ? "true" : "false",
            AUTONOMOUS_FORCE_PROD: env("AUTONOMOUS_FORCE_PROD", forceProd ? "true" : "false"),
            AUTONOMOUS_REAL_EXECUTION_ENABLED: env("AUTONOMOUS_REAL_EXECUTION_ENABLED", "0"),
            STRICT_SIGNAL_FUSION: env("STRICT_SIGNAL_FUSION", "false"),
            PROD_SECOND_FACTOR_SECRET: env("PROD_SECOND_FACTOR_SECRET"),
            LOBSTAR_PROD_CONFIRM_SECRET: env("LOBSTAR_PROD_CONFIRM_SECRET"),
        },
    }, {
        // MCP/API integration server. This process is read/write API surface; keep
        // a separate feature-store file to avoid unnecessary contention with the
        // core runtime.
        // Quick start: pm2 start ecosystem.config.js --only quant-agentic-api
        name: "quant-agentic-api",
        script: ".venv/bin/uvicorn",
        args: "api.api_server:app --host 127.0.0.1 --port 8000 --log-level info",
        cwd: __dirname,
        interpreter: ".venv/bin/python",
        instances: 1,
        exec_mode: "fork",
        max_restarts: 25,
        min_uptime: "10s",
        restart_delay: 5000,
        exp_backoff_restart_delay: 1000,
        error_file: "logs/pm2-api-error.log",
        out_file: "logs/pm2-api-out.log",
        log_date_format: "YYYY-MM-DD HH:mm:ss Z",
        merge_logs: true,
        autorestart: true,
        env: {
            NODE_ENV: "production",
            PYTHONUNBUFFERED: "1",
            SECRET_SOURCE: env("SECRET_SOURCE", "auto"),
            VAULT_ADDR: env("VAULT_ADDR", "false"),
            VAULT_TOKEN: env("VAULT_TOKEN"),
            API_FEATURE_STORE_PATH: "data/api_feature_store.duckdb",
        },
    }]
};
