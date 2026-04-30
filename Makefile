.PHONY: install test run deploy push

install:
	python3 -m venv .venv
	.venv/bin/pip install -r requirements.txt

test:
	.venv/bin/pytest tests/ -v

# Run the bot locally via polling. Reads .env automatically. No Vercel
# involved. Prompts before touching an already-registered webhook.
run:
	@test -f .env || { echo "ERROR: .env not found. Copy .env.example to .env first."; exit 1; }
	.venv/bin/python run_local.py

deploy:
	vercel --prod

# Push every variable from .env to Vercel production AND register the
# Telegram webhook. Two independent steps:
#
#   1. Env vars:  prompts "Update Vercel env vars? [y/N]". If yes, pushes
#      every KEY=VALUE from .env to Vercel production, upserting in place
#      via `vercel env add --force`. If no, skips the push and moves on.
#
#   2. Webhook:   registers the Telegram webhook at <PROD_URL>/api/webhook.
#      Runs regardless of the answer to step 1, so you can re-register
#      the webhook without re-pushing env vars.
#
# REQUIRED: PROD_URL must be set in .env. `make push` refuses to run
# without it — there is no safe default, and a default would risk
# accidentally pushing to the wrong production bot. If you haven't
# deployed yet, run `vercel --prod` first to get a URL, then add it:
#     PROD_URL=https://<your-bot-name>.vercel.app
#
# SAFETY: `make push` is additive/upsert only. It NEVER deletes Vercel
# env vars. Variables that exist on Vercel but are absent (or commented)
# from .env are left untouched. To remove a var from Vercel, use
# `vercel env rm NAME production --yes` directly.
#
# PROD_URL itself is local-only — it is NOT pushed to Vercel. Blank and
# comment lines in .env are ignored. Surrounding quotes are stripped.
push:
	@test -f .env || { echo "ERROR: .env not found. Copy .env.example to .env first."; exit 1; }
	@command -v vercel >/dev/null 2>&1 || { echo "ERROR: vercel CLI not installed. Run: npm i -g vercel"; exit 1; }
	@command -v curl >/dev/null 2>&1 || { echo "ERROR: curl not installed."; exit 1; }
	@grep -qE '^[[:space:]]*PROD_URL[[:space:]]*=.*[^[:space:]]' .env || { \
		echo "ERROR: PROD_URL is not set (or is empty) in .env."; \
		echo ""; \
		echo "Add a line like this to .env before running 'make push':"; \
		echo "    PROD_URL=https://<your-bot-name>.vercel.app"; \
		echo ""; \
		echo "PROD_URL is required so 'make push' knows which Vercel deployment"; \
		echo "to register the Telegram webhook against. Without it there is no"; \
		echo "safe default — refusing to run prevents accidentally pushing to"; \
		echo "the wrong production bot."; \
		exit 1; \
	}
	@printf "Update Vercel env vars from .env? [y/N] "; read push_ans; case "$$push_ans" in y|Y|yes|YES) push_envs=1 ;; *) push_envs=0 ;; esac; \
	count=0; failed=0; webhook_failed=0; tg_token=""; wh_secret=""; prod_url=""; \
	if [ "$$push_envs" = "1" ]; then \
		echo ""; \
		echo "Pushing .env to Vercel production (existing values will be OVERWRITTEN)..."; \
	else \
		echo ""; \
		echo "Skipping env var update."; \
	fi; \
	while IFS= read -r line || [ -n "$$line" ]; do \
		line=$$(printf '%s' "$$line" | sed 's/^[[:space:]]*//;s/[[:space:]]*$$//'); \
		case "$$line" in ''|\#*) continue ;; esac; \
		key=$${line%%=*}; value=$${line#*=}; \
		key=$$(printf '%s' "$$key" | sed 's/[[:space:]]*$$//'); \
		value=$$(printf '%s' "$$value" | sed 's/^[[:space:]]*//'); \
		case "$$value" in \
			\"*\") value=$${value#\"}; value=$${value%\"} ;; \
			\'*\') value=$${value#\'}; value=$${value%\'} ;; \
		esac; \
		if [ -z "$$value" ]; then continue; fi; \
		case "$$key" in \
			TELEGRAM_BOT_TOKEN) tg_token="$$value" ;; \
			WEBHOOK_SECRET) wh_secret="$$value" ;; \
			PROD_URL) prod_url="$$value"; continue ;; \
		esac; \
		if [ "$$push_envs" = "1" ]; then \
			printf "  %-30s ... " "$$key"; \
			if vercel env add "$$key" production --force --yes --value "$$value" </dev/null >/dev/null 2>&1; then \
				echo "ok"; \
				count=$$((count+1)); \
			else \
				echo "FAILED"; \
				failed=$$((failed+1)); \
			fi; \
		fi; \
	done < .env; \
	if [ "$$push_envs" = "1" ]; then \
		echo ""; \
		echo "Pushed $$count variable(s). $$failed failed."; \
	fi; \
	echo ""; \
	if [ -z "$$tg_token" ]; then \
		echo "ERROR: TELEGRAM_BOT_TOKEN not set in .env — cannot register webhook."; \
		webhook_failed=1; \
	elif [ -z "$$prod_url" ]; then \
		echo "ERROR: PROD_URL is empty after parsing .env — cannot register webhook."; \
		webhook_failed=1; \
	else \
		prod_url=$${prod_url%/}; \
		webhook_url="$$prod_url/api/webhook"; \
		printf "Registering Telegram webhook → %s ... " "$$webhook_url"; \
		if [ -n "$$wh_secret" ]; then \
			response=$$(curl -s -X POST "https://api.telegram.org/bot$$tg_token/setWebhook" \
				--data-urlencode "url=$$webhook_url" \
				--data-urlencode "secret_token=$$wh_secret"); \
		else \
			response=$$(curl -s -X POST "https://api.telegram.org/bot$$tg_token/setWebhook" \
				--data-urlencode "url=$$webhook_url"); \
		fi; \
		case "$$response" in \
			*'"ok":true'*) echo "ok" ;; \
			*) echo "FAILED"; echo "  Telegram response: $$response"; webhook_failed=1 ;; \
		esac; \
	fi; \
	if [ "$$push_envs" = "1" ]; then \
		echo ""; \
		echo "Run 'make deploy' to redeploy production with the new values."; \
	fi; \
	if [ "$$failed" -ne 0 ] || [ "$$webhook_failed" -ne 0 ]; then exit 1; fi
