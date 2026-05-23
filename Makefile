.PHONY: install test run deploy-pa

install:
	python3 -m venv .venv
	.venv/bin/pip install -r requirements.txt

test:
	.venv/bin/pytest tests/ -v

# Run the bot locally via polling. Reads .env automatically.
# Prompts before touching an already-registered webhook.
run:
	@test -f .env || { echo "ERROR: .env not found. Copy .env.example to .env first."; exit 1; }
	.venv/bin/python run_local.py

# One-command PA deploy from your laptop. Reads .env for PA_USERNAME,
# PA_API_TOKEN, TELEGRAM_BOT_TOKEN, AI_API_KEY (and any optional vars).
# Idempotent — safe to re-run for recovery or to push a fresh .env.
deploy-pa:
	@test -f .env || { echo "ERROR: .env not found. Copy .env.example to .env first."; exit 1; }
	./scripts/pa_deploy.sh
