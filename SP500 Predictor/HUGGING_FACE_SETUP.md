# HUGGING FACE SETUP GUIDE

## DO YOU NEED AN ACCOUNT?

### Short Answer: **NO** ✅

You **do NOT need** a Hugging Face account for this project. The models download automatically and run locally.

### Why No Account Needed:

**Hugging Face Transformers** library allows you to:
- Download pre-trained models directly
- Run them locally on your machine
- No API keys required
- No rate limits
- Completely free

**Only need an account if you:**
- Want to upload your own models
- Need private model access
- Want to use Hugging Face Inference API (cloud-hosted)

**For this project:**
- Models run **locally on your computer**
- First run downloads models (~500MB-1GB)
- Subsequent runs use cached models (instant)

---

## TECHNICAL DETAILS

### What Happens on First Run:

```python
from transformers import pipeline

# First time you run this:
sentiment = pipeline("sentiment-analysis", model="ProsusAI/finbert")

# Behind the scenes:
# 1. Downloads model from huggingface.co
# 2. Saves to: ~/.cache/huggingface/hub/
# 3. Future runs use cached version (no download)
```

**First Run:**
- Downloads ~400MB (FinBERT model)
- Takes 2-5 minutes depending on internet speed
- Shows progress bar

**Subsequent Runs:**
- Loads from cache (~2 seconds)
- No internet required

---

## MODELS USED IN THIS PROJECT

### 1. FinBERT (ProsusAI/finbert)
**Purpose:** Analyze Fed speeches for dovish vs hawkish sentiment

**Details:**
- Size: ~440MB
- Speed: ~0.3 seconds per analysis
- Trained on: 4.9M financial sentences
- Best for: Fed statements, earnings calls, financial news

**Example:**
```python
from transformers import pipeline

finbert = pipeline("sentiment-analysis", model="ProsusAI/finbert")

text = "The Federal Reserve will maintain rates at current levels"
result = finbert(text)[0]

# Output: {'label': 'neutral', 'score': 0.89}
# Interpretation: Neutral (neither dovish nor hawkish)
```

### 2. BART Zero-Shot (facebook/bart-large-mnli)
**Purpose:** Classify news headlines without training

**Details:**
- Size: ~1.6GB
- Speed: ~0.5 seconds per classification
- Can classify into any labels you provide
- Best for: News headline sentiment

**Example:**
```python
from transformers import pipeline

classifier = pipeline("zero-shot-classification", model="facebook/bart-large-mnli")

headline = "Bitcoin ETF approval imminent, sources say"
labels = ["bullish", "bearish", "neutral"]

result = classifier(headline, labels)

# Output: 
# {
#   'labels': ['bullish', 'neutral', 'bearish'],
#   'scores': [0.89, 0.08, 0.03]
# }
```

### 3. DistilBERT NER (dslim/bert-base-NER)
**Purpose:** Extract names, dates, numbers from text

**Details:**
- Size: ~260MB
- Speed: ~0.2 seconds per extraction
- Best for: Parsing Fed announcements

**Example:**
```python
from transformers import pipeline

ner = pipeline("ner", model="dslim/bert-base-NER", aggregation_strategy="simple")

text = "Jerome Powell announced rates will hold at 5.25%"
entities = ner(text)

# Output:
# [
#   {'entity_group': 'PER', 'word': 'Jerome Powell'},
#   {'entity_group': 'MISC', 'word': '5.25%'}
# ]
```

---

## HARDWARE REQUIREMENTS

### Minimum Specs:
- **CPU:** Any modern processor (2015+)
- **RAM:** 8GB minimum, 16GB recommended
- **Storage:** 3GB free space for models
- **Internet:** For initial download only

### Performance:
| Hardware | FinBERT Speed | BART Speed | Total Validation Time |
|----------|--------------|------------|----------------------|
| **Laptop (8GB RAM)** | 0.5s | 1s | ~1.5s per trade |
| **Desktop (16GB RAM)** | 0.3s | 0.5s | ~0.8s per trade |
| **With GPU** | 0.05s | 0.1s | ~0.15s per trade |

**Note:** GPU is **not required**. CPU-only is fine for this use case.

---

## OPTIONAL: HUGGING FACE ACCOUNT BENEFITS

If you **do** create a free account (optional), you get:

### Benefits:
1. **Private models** - Can save your fine-tuned models privately
2. **Spaces** - Host Gradio/Streamlit apps for free
3. **Datasets** - Upload/share datasets
4. **Higher download speeds** - Faster model downloads

### To Create Account (Optional):
1. Go to https://huggingface.co/join
2. Sign up with email (free)
3. Get an access token: https://huggingface.co/settings/tokens
4. Add to `.env`:
   ```bash
   HF_TOKEN=hf_xxxxxxxxxxxxx
   ```

**For this project:** You can skip this entirely. It's only needed for advanced features.

---

## STORAGE & CACHING

### Where Models Are Stored:

**Default cache location:**
```
# Linux/Mac
~/.cache/huggingface/hub/

# Windows
C:\Users\YourName\.cache\huggingface\hub\
```

**Disk usage:**
```
models--ProsusAI--finbert/           440 MB
models--facebook--bart-large-mnli/   1.6 GB
models--dslim--bert-base-NER/        260 MB
────────────────────────────────────────────
Total:                              ~2.3 GB
```

### Managing Cache:

**Clear cache (if needed):**
```bash
# Linux/Mac
rm -rf ~/.cache/huggingface/hub/

# Windows
rmdir /s %USERPROFILE%\.cache\huggingface\hub
```

**View cache:**
```python
from transformers import scan_cache_dir

cache_info = scan_cache_dir()
print(cache_info)
```

---

## INSTALLATION

### Step 1: Install Dependencies

```bash
pip install transformers torch sentencepiece
```

**Package sizes:**
- `transformers`: ~10MB (library only)
- `torch`: ~800MB (PyTorch)
- `sentencepiece`: ~5MB

**Total initial install:** ~815MB

### Step 2: First Run (Downloads Models)

```bash
python -c "
from transformers import pipeline

print('Downloading FinBERT...')
pipeline('sentiment-analysis', model='ProsusAI/finbert')

print('Downloading BART...')
pipeline('zero-shot-classification', model='facebook/bart-large-mnli')

print('Downloading NER...')
pipeline('ner', model='dslim/bert-base-NER')

print('All models cached! ✅')
"
```

**First run:** 5-10 minutes (downloads ~2.3GB)
**Future runs:** Instant (uses cache)

### Step 3: Verify Installation

```python
from src.sentiment_filter import SentimentFilter

sf = SentimentFilter()

# Test FinBERT
result = sf.analyze_fed_statement("The Fed will maintain accommodative policy")
print(f"FinBERT: {result}")

# Test Zero-Shot
result = sf.classify_news_headline("Bitcoin surges to new high")
print(f"Zero-Shot: {result}")

# Test NER
result = sf.extract_entities("Jerome Powell announced rates at 5.25%")
print(f"NER: {result}")
```

---

## COST COMPARISON: HUGGING FACE vs GEMINI

### Scenario: 100 trade validations per day

**Without Hugging Face (Gemini only):**
```
100 trades/day × 30 days = 3,000 Gemini API calls/month
Free tier: 15 RPM = ~21,600 calls/month

Cost: $0 (under free tier)
```

**With Hugging Face Pre-Filter:**
```
100 trades/day × 30% escalated = 30 Gemini calls/day
30 calls/day × 30 days = 900 Gemini calls/month

Cost: $0 (well under free tier)
Margin: 24x more headroom before hitting limits
```

### Benefits:
1. **Speed:** 70% faster (local models vs API calls)
2. **Reliability:** No dependency on Gemini API uptime
3. **Scalability:** Can handle 10x more trades before hitting limits
4. **Privacy:** Sensitive Fed analysis stays local (not sent to Google)

---

## OFFLINE CAPABILITY

### Can This Work Offline?

**YES** ✅ (after initial download)

Once models are cached:
- FinBERT: ✅ Fully offline
- BART: ✅ Fully offline
- NER: ✅ Fully offline
- Gemini: ❌ Requires internet (only called 30% of time)

**Practical use:**
- Hugging Face validates 70% of trades offline
- Only 30% require internet (Gemini escalation)
- If internet down, can still get 70% of validations

---

## TROUBLESHOOTING

### Issue: "torch not found"
```bash
# Solution: Install PyTorch
pip install torch --index-url https://download.pytorch.org/whl/cpu
```

### Issue: "Model download too slow"
```bash
# Solution: Use mirror (if outside US/EU)
export HF_ENDPOINT=https://hf-mirror.com
pip install transformers
```

### Issue: "Out of memory"
```python
# Solution: Use smaller batch size
# In sentiment_filter.py, change:
result = self.finbert(text[:512])  # Already limited to 512 tokens
```

### Issue: "Models taking up too much space"
```bash
# Solution: Use quantized (smaller) versions
# In sentiment_filter.py, change model names to:
# "distilbert-base-uncased-finetuned-sst-2-english"  (67MB, 3x smaller)
```

---

## COMPARISON: LOCAL vs CLOUD

| Feature | Local (Hugging Face) | Cloud (Gemini API) |
|---------|---------------------|-------------------|
| **Cost** | Free forever | Free tier then $$ |
| **Speed** | 0.3s | 2s |
| **Privacy** | Fully private | Sent to Google |
| **Internet** | Only first time | Always required |
| **Rate Limits** | None | 15 RPM |
| **Accuracy (Fed)** | ⭐⭐⭐⭐⭐ (trained on finance) | ⭐⭐⭐⭐ (general purpose) |
| **Accuracy (General)** | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ |

**Best of both worlds:**
- Use Hugging Face for 70% (fast, local, financial-specific)
- Use Gemini for 30% (complex edge cases, general reasoning)

---

## FINAL SETUP CHECKLIST

### Do You Need to Set Up Anything?

- [ ] ❌ Hugging Face account (not needed)
- [ ] ❌ API keys (not needed)
- [ ] ❌ Cloud credits (not needed)
- [ ] ✅ Install packages: `pip install transformers torch sentencepiece`
- [ ] ✅ Download models on first run (automatic)
- [ ] ✅ Verify 3GB free disk space

### That's It!

The Hugging Face integration is **completely self-contained** and requires zero external setup. Just install the packages and let it download models on first run.

---

## RECOMMENDED: PRE-DOWNLOAD MODELS

To avoid waiting during first validation:

```bash
# Create a setup script: scripts/download_models.py
from transformers import pipeline

print("📦 Downloading Hugging Face models...")
print("This will take 5-10 minutes on first run.")
print("Future runs will use cached models (instant).")
print()

print("1/3 Downloading FinBERT (440MB)...")
pipeline("sentiment-analysis", model="ProsusAI/finbert")

print("2/3 Downloading BART (1.6GB)...")
pipeline("zero-shot-classification", model="facebook/bart-large-mnli")

print("3/3 Downloading NER (260MB)...")
pipeline("ner", model="dslim/bert-base-NER", aggregation_strategy="simple")

print()
print("✅ All models downloaded and cached!")
print("You can now run the system with no delays.")
```

Run once:
```bash
python scripts/download_models.py
```

Then forget about it. Models are cached forever (until you manually delete them).

---

## SUMMARY

**Setup Required:**
1. Install packages (1 command)
2. Let models download on first run (automatic)
3. Done

**Cost:**
- $0 forever (no API keys, no subscriptions)

**Performance:**
- 70% of validations = instant (local)
- 30% of validations = 2s (Gemini API)
- Net result: 2x faster than Gemini-only

**Bottom Line:**
Hugging Face is **zero setup** beyond installing packages. No accounts, no API keys, no configuration. Just works.
