#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_NAME="quant-agentic-trading-core"
PYTHON_REQUIRED="3.11"
VAULT_VERSION="1.18.1"
VAULT_ADDR="${VAULT_ADDR:-http://127.0.0.1:8200}"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

log_info()  { echo -e "${CYAN}[INFO]${NC}  $1"; }
log_ok()    { echo -e "${GREEN}[OK]${NC}    $1"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC}  $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

cleanup() {
    log_info "Cleaning up..."
}
trap cleanup EXIT

check_python() {
    log_info "Checking Python version..."
    local py_cmd=""
    for cmd in python3.11 python3; do
        if command -v "$cmd" &>/dev/null; then
            local ver
            ver=$("$cmd" --version 2>&1 | awk '{print $2}')
            if [[ "$ver" == "$PYTHON_REQUIRED"* ]]; then
                py_cmd="$cmd"
                break
            fi
        fi
    done
    if [[ -z "$py_cmd" ]]; then
        log_error "Python $PYTHON_REQUIRED not found. Install it first."
        log_info "Ubuntu 24.04: sudo apt install python3.11 python3.11-venv python3.11-dev"
        exit 1
    fi
    PYTHON="$py_cmd"
    log_ok "Python $("$PYTHON" --version) at $(command -v "$PYTHON")"
}

setup_venv() {
    log_info "Setting up virtual environment..."
    if [[ -d "$PROJECT_DIR/.venv" ]]; then
        log_warn ".venv already exists. Skipping creation."
    else
        "$PYTHON" -m venv "$PROJECT_DIR/.venv"
        log_ok "Virtual environment created."
    fi
    source "$PROJECT_DIR/.venv/bin/activate"
    log_ok "Virtual environment activated."
}

install_deps() {
    log_info "Installing Python dependencies..."
    pip install --upgrade pip setuptools wheel
    pip install -r "$PROJECT_DIR/requirements.txt"
    log_ok "Dependencies installed."
}

install_vault() {
    log_info "Checking Vault..."
    if command -v vault &>/dev/null; then
        log_ok "Vault already installed: $(vault version)"
        return
    fi
    log_info "Downloading Vault $VAULT_VERSION..."
    local arch
    arch=$(uname -m)
    local url="https://releases.hashicorp.com/vault/${VAULT_VERSION}/vault_${VAULT_VERSION}_linux_amd64.zip"
    if [[ "$arch" == "aarch64" ]]; then
        url="https://releases.hashicorp.com/vault/${VAULT_VERSION}/vault_${VAULT_VERSION}_linux_arm64.zip"
    fi
    local tmp_dir
    tmp_dir=$(mktemp -d)
    wget -q "$url" -O "$tmp_dir/vault.zip"
    sudo unzip -o "$tmp_dir/vault.zip" -d /usr/local/bin/ >/dev/null 2>&1
    sudo chmod +x /usr/local/bin/vault
    rm -rf "$tmp_dir"
    log_ok "Vault $VAULT_VERSION installed."
}

ensure_vault_env() {
    if [[ -z "${VAULT_TOKEN:-}" ]]; then
        log_warn "VAULT_TOKEN not set. Checking for existing dev server..."
        if curl -sf "$VAULT_ADDR/v1/sys/health" >/dev/null 2>&1; then
            log_warn "Vault server running but VAULT_TOKEN not exported."
            log_info "Run: export VAULT_TOKEN=\"hvs...\" (from vault server -dev output)"
        else
            log_info "Starting Vault dev server in background..."
            nohup vault server -dev -dev-listen-address=127.0.0.1:8200 \
                > "$PROJECT_DIR/vault.log" 2>&1 &
            local pid=$!
            echo "$pid" > "$PROJECT_DIR/vault.pid"
            sleep 2
            local token
            token=$(grep "Root Token" "$PROJECT_DIR/vault.log" | awk '{print $NF}')
            if [[ -n "$token" ]]; then
                export VAULT_TOKEN="$token"
                echo "export VAULT_TOKEN=$token" > "$PROJECT_DIR/.vault_env"
                log_ok "Vault dev server started. Token exported."
            else
                log_error "Failed to extract Vault token from logs."
                exit 1
            fi
        fi
    fi
    log_ok "Vault accessible at $VAULT_ADDR"
}

seed_vault() {
    log_info "Checking if secrets already seeded..."
    if vault kv get secret/quant-trade >/dev/null 2>&1; then
        log_ok "Secrets already present in secret/quant-trade."
        return
    fi
    log_warn "No secrets found. Please inject credentials:"
    echo -e "\n${YELLOW}Run the following commands manually:${NC}"
    echo -e "  vault kv put secret/quant-trade \\"
    echo -e "    TELEGRAM_BOT_TOKEN=\"your_bot_token\" \\"
    echo -e "    CLOB_PRIVATE_KEY=\"0x...\" \\"
    echo -e "    GROQ_API_KEY=\"gsk_...\""
    echo ""
    echo -e "${CYAN}Then derive CLOB credentials and inject them:${NC}"
    echo -e "  source .venv/bin/activate"
    echo -e '  python -c "from utils.derive_clob_creds import derive_clob_credentials; import json; c = derive_clob_credentials(\"0x...\"); vault kv patch secret/quant-trade CLOB_API_KEY=\$c[\"CLOB_API_KEY\"] CLOB_API_SECRET=\$c[\"CLOB_API_SECRET\"] CLOB_API_PASSPHRASE=\$c[\"CLOB_API_PASSPHRASE\"]"'
}

setup_pm2() {
    log_info "Configuring PM2..."
    if ! command -v pm2 &>/dev/null; then
        log_info "Installing PM2 via npm..."
        if ! command -v npm &>/dev/null; then
            log_info "Installing Node.js and npm..."
            curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash - >/dev/null 2>&1
            sudo apt-get install -y nodejs >/dev/null 2>&1
        fi
        sudo npm install -g pm2 >/dev/null 2>&1
    fi
    local ecosystem="$PROJECT_DIR/ecosystem.config.js"
    if [[ ! -f "$ecosystem" ]]; then
        log_warn "ecosystem.config.js not found. Creating..."
        cat > "$ecosystem" << 'PM2EOF'
module.exports = {
    apps: [{
        name: "quant-agentic-core",
        script: "main_agentic_clob.py",
        cwd: __dirname,
        interpreter: ".venv/bin/python",
        instances: 1,
        exec_mode: "fork",
        max_restarts: 10,
        restart_delay: 5000,
        max_memory_restart: "4G",
        error_file: "logs/pm2-error.log",
        out_file: "logs/pm2-out.log",
        log_date_format: "YYYY-MM-DD HH:mm:ss Z",
        merge_logs: true,
        autorestart: true,
        env: {
            NODE_ENV: "production",
            PYTHONUNBUFFERED: "1",
        },
    }],
};
PM2EOF
        log_ok "ecosystem.config.js created."
    fi
    log_ok "PM2 configured."
}

setup_systemd() {
    log_info "Creating systemd service..."
    local service_file="/etc/systemd/system/${PROJECT_NAME}.service"
    if [[ -f "$service_file" ]]; then
        log_ok "systemd service already exists."
        return
    fi
    local user
    user=$(whoami)
    local service_content="[Unit]
Description=Quant-Agentic Trading Core (Polymarket CLOB)
Documentation=https://github.com/anomalyco/opencode
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$user
WorkingDirectory=$PROJECT_DIR
Environment=PYTHONUNBUFFERED=1
Environment=VAULT_ADDR=http://127.0.0.1:8200
ExecStart=$PROJECT_DIR/.venv/bin/python $PROJECT_DIR/main_agentic_clob.py
Restart=always
RestartSec=10
StandardOutput=append:$PROJECT_DIR/logs/systemd-out.log
StandardError=append:$PROJECT_DIR/logs/systemd-err.log

[Install]
WantedBy=multi-user.target
"
    echo "$service_content" | sudo tee "$service_file" >/dev/null
    sudo systemctl daemon-reload
    log_ok "systemd service created: $service_file"
}

create_logs_dir() {
    mkdir -p "$PROJECT_DIR/logs"
    chmod 750 "$PROJECT_DIR/logs"
}

generate_env() {
    if [[ ! -f "$PROJECT_DIR/.vault_env" ]]; then
        cat > "$PROJECT_DIR/.vault_env" << 'EOF'
# Vault environment - source this file to set VAULT_ADDR and VAULT_TOKEN
# export VAULT_ADDR="http://127.0.0.1:8200"
# export VAULT_TOKEN="hvs..."
EOF
        chmod 600 "$PROJECT_DIR/.vault_env"
    fi
}

print_summary() {
    echo ""
    echo -e "${GREEN}============================================${NC}"
    echo -e "${GREEN}  $PROJECT_NAME setup complete${NC}"
    echo -e "${GREEN}============================================${NC}"
    echo ""
    echo -e "  Python:    $("$PYTHON" --version)"
    echo -e "  Vault:     $(vault version 2>/dev/null || echo 'not found')"
    echo -e "  PM2:       $(pm2 --version 2>/dev/null || echo 'not found')"
    echo -e "  Venv:      $PROJECT_DIR/.venv"
    echo -e ""
    echo -e "  ${CYAN}Usage:${NC}"
    echo -e "  source .venv/bin/activate && python main_agentic_clob.py"
    echo -e "  pm2 start ecosystem.config.js"
    echo -e "  sudo systemctl start ${PROJECT_NAME}"
    echo ""
}

main() {
    echo ""
    echo -e "${CYAN}═══ $PROJECT_NAME — Production Setup ═══${NC}"
    echo ""

    check_python
    setup_venv
    create_logs_dir
    generate_env
    install_deps
    install_vault
    ensure_vault_env
    seed_vault
    setup_pm2
    setup_systemd
    print_summary
}

main "$@"
