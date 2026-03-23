#!/bin/bash
# PhD Milestone: Automated Model Sync via git-xet
# This script helps push local LightGBM models to Hugging Face Hub.

REPO_URL="https://huggingface.co/KevinSigey/Kalshi-LightGBM"
CLONE_DIR="/tmp/hf_repo_sync"
LOCAL_MODELS_DIR="model/"

echo "🚀 Starting Hugging Face Model Sync (git-xet)..."

# 1. Install git-xet if not installed (User should have done this once)
if ! git xet --version &> /dev/null; then
    echo "⚠️ git-xet not found. Installing..."
    git xet install || { echo "❌ Failed to install git-xet. Please run 'brew install git-xet' manually."; exit 1; }
fi

# 2. Check for HF Token
if [ -z "$HF_TOKEN" ]; then
    echo "ℹ️  HF_TOKEN not found in environment. You may be prompted for your Hugging Face password/token during push."
    echo "💡 PRO TIP: Run 'export HF_TOKEN=your_token' to bypass the prompt."
fi

# 3. Cleanup old clone
rm -rf "$CLONE_DIR"

# 4. Clone the repo
echo "📡 Cloning $REPO_URL..."
git clone "$REPO_URL" "$CLONE_DIR" || { echo "❌ Clone failed. Check your internet connection and repo visibility."; exit 1; }

# 5. Copy local models to the repo
echo "📂 Copying models from $LOCAL_MODELS_DIR to $CLONE_DIR..."
mkdir -p "$CLONE_DIR/models"
cp "$LOCAL_MODELS_DIR"/*.pkl "$CLONE_DIR/models/" 2>/dev/null && echo "✅ Copied .pkl models."
cp "$LOCAL_MODELS_DIR"/*.txt "$CLONE_DIR/models/" 2>/dev/null && echo "✅ Copied .txt models."
cp "$LOCAL_MODELS_DIR"/*.json "$CLONE_DIR/models/" 2>/dev/null && echo "✅ Copied .json models."

# 6. Commit and Push
cd "$CLONE_DIR" || exit
git add .
git commit -m "Update models from Kalshi Edge Tracker [$(date)]" || echo "ℹ️ No changes to commit."

echo "⬆️ Pushing to Hugging Face..."
if [ -n "$HF_TOKEN" ]; then
    # Use token for authentication if available
    git push "https://KevinSigey:$HF_TOKEN@huggingface.co/KevinSigey/Kalshi-LightGBM"
else
    git push
fi

if [ $? -eq 0 ]; then
    echo "✅ Sync complete! Models are now live on Hugging Face."
else
    echo "❌ Push failed. Possible reasons:"
    echo "   1. Incorrect credentials/token."
    echo "   2. Large file issues (ensure git-xet is correctly tracking .pkl)."
    echo "   3. Rate limiting."
fi
