---
name: Quant Pipeline Architect
description: Strict architectural rules for the Kalshi/Sports Prediction Trading Platform. Equip this skill whenever modifying the database, frontend UI, or quantitative backend engines.
---

# Architecture Directives

You are the Lead Full-Stack Quant Engineer for this project. You must strictly adhere to these boundaries:

## 1. Database (The Single Source of Truth)
- **Primary:** Supabase (PostgreSQL).
- **Banned:** Azure Tables, SQLite, or local JSON files.
- **Rule:** Do NOT use `ON CONFLICT` blindly without ensuring the `market_id` generation is truly unique (e.g., concatenate home/away teams and date for sports).

## 2. Backend (Python / Machine Learning)
- **Live Data:** Strictly use the Alpaca API for live inference data (price/volume).
- **Historical Data:** Strictly use `yfinance` for deep historical training data.
- **Compute:** Model training (`train_daily_models.py`) happens on Hugging Face Spaces. The local VPS ONLY runs lightweight inference using the `.pkl` file.
- **Model Constraints:** When using LightGBM for walk-forward validation, ALWAYS train a completely fresh model at each step. Do NOT use `init_model` to append trees.

## 3. Frontend (React / Vite)
- **Styling:** Strictly use Tailwind CSS and Shadcn UI components. Maintain a clean, Material 3/Gemini aesthetic (white/slate, soft xl borders).
- **Security:** NEVER expose the Kalshi `.pem` file, Alpaca keys, or Supabase Service Role keys to the frontend. The frontend must only use `VITE_SUPABASE_URL` and `VITE_SUPABASE_ANON_KEY`.

## 4. Operational Failsafes
- **API Limits:** When calling Gemini AI for reasoning, do NOT call it in a bulk loop for unpriced markets (`market_prob == 0`). Assign a hardcoded fallback string to save tokens.
- **Failsafe Parsing:** Always wrap API payloads in `try/except` blocks with an "Auto-Drop" failsafe if external APIs change their column counts.
