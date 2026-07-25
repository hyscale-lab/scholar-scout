# Scholar Scout

A tool to monitor Google Scholar alerts and classify research papers using Perplexity AI.

## Features
- Connects to Gmail to fetch Google Scholar alert emails
- Uses Perplexity AI to parse and extract paper information
- Supports multiple research topics and keywords
- Sends notifications to Slack

## Setup
1. Clone the repository
2. Create a virtual environment: `python -m venv .venv`
3. Activate the virtual environment: `source .venv/bin/activate` (Unix) or `.venv\Scripts\activate` (Windows)
4. Install dependencies: `pip install -r requirements.txt`
5. Copy `.env.example` to `.env` and fill in your credentials
6. Copy `config.example.yml` to `config.yml` and customize settings

## Configuration
Create a `.env` file with:
```
GMAIL_USERNAME=your.email@gmail.com
GMAIL_APP_PASSWORD=your-app-specific-password
GEMINI_API_KEY=your-gemini-api-key
SLACK_API_TOKEN=your-slack-api-token
```

### Adding Users to Track
1. Go to [Google Scholar](https://scholar.google.com/)
2. Search for the researcher you want to track
3. Click on their profile
4. Click the "Follow" button (bell icon) to receive email alerts for new papers
5. In Gmail, create a filter to move these alerts to your designated Scholar folder
6. Update your `config.yml` to include any Slack users to notify:

```yaml
research_topics:
  - name: "LLM Inference"
    description: "Papers about large language model inference, optimization, and deployment"
    keywords:
      - "language model inference"
      - "LLM serving"
      - "model optimization"
    slack_users:
      - "@user1"
      - "@user2"
    slack_channel: "#llm-papers"  # optional
```

### HyScale Scholar Account
To add researchers to the HyScale Scholar tracking:
1. Email the admin (hyscale.ntu@gmail.com) with:
   - Researcher's name and Google Scholar profile link
   - Your Slack username to receive notifications
   - Any specific keywords you want to track
2. The admin will:
   - Set up the Google Scholar alert
   - Update the configuration
   - Confirm once tracking is active

## Usage
Run the main script:
```bash
python scholar_classifier.py
```

## Testing

### Integration Tests
To run the integration tests under the root directory:
```bash
python -m unittest tests/test_integration.py -v
```

The integration tests require a `test_config.yml` file in the `tests/` directory with your Gmail credentials and settings. Example structure:

```yaml
email:
  username: your.email@gmail.com
  password: your-app-specific-password  # Gmail App Password, not your regular password
  folder: "Inbox"      # IMAP folder where Scholar alerts are stored
```

Note: 
- You'll need to [create an App Password](https://support.google.com/accounts/answer/185833) for Gmail
- The tests expect Google Scholar alert emails from January 5th, 2025 in the specified folder
- Make sure your Scholar alerts are being properly filtered to the specified folder, namely provide the correct path to the folder in the `config.yml` file

Engineering Additions in the local-nomic-and-deduplication branch

This pipeline has been upgraded to solve issues and add features, described in detail below:

1. Local AI Migration

The embedding stage was migrated from the paid Gemini API to locally hosted nomic-embed-text embeddings served through our self-hosted Tailscale infrastructure (instance-lcscfv). This removes recurring embedding API costs while keeping the pipeline entirely under our control.

2. Algorithmic Validation & Threshold Optimisation

Migrating to a new embedding model required recalibrating the classification boundary. Rather than selecting a similarity threshold heuristically, a benchmarking framework (scripts/benchmark_thresholds.py) was developed.

Silver Ground Truth

A 35B-parameter Qwen model was used as a strict multi-label "Silver Judge" to generate high-confidence reference classifications.

Multi-Label Evaluation

Cosine similarity thresholds between 0.40 and 0.85 were evaluated using strict multi-label metrics, accounting for both:

False Positives (hallucinated categories)
False Negatives (missed categories)

The optimal global threshold was selected by maximising the F1 score, balancing precision and recall.

Engineering Decision

A single global threshold was intentionally chosen instead of category-specific thresholds.

While per-category tuning could provide marginal gains on the current benchmark, it would introduce a significant risk of overfitting given the limited number of labelled examples available for several research areas.

The current design prioritises robustness and generalisation while remaining easy to maintain.

Future Flexibility

The benchmarking framework is intentionally modular.

As the historical database grows, the pipeline can naturally evolve towards:

category-specific thresholds
sharper confidence calibration
richer evaluation metrics

without requiring architectural changes.

3. Persistent Historical Database & Deduplication

Scholar Scout now maintains a persistent historical database of classified papers using data/classified_papers.json.

Each newly classified paper is automatically assigned an ingestion timestamp (YYYY-MM-DD) before being appended to the database.

The monthly GitHub Actions workflow commits these updates back to the repository, allowing the pipeline to naturally:

preserve historical classifications
avoid duplicate processing
classify only newly discovered papers each month

The historical database serves as the main source for downstream analytics.

Monthly Trend Analytics

The pipeline includes a deterministic analytics engine (trend_analyzer.py) that automatically analyses historical classifications to generate an executive summary of research trends.

Rather than storing monthly summaries, every report is recomputed directly from the historical paper database, ensuring that statistics always reflect the latest classification history.

The generated report includes:

dominant research topics
category growth and decline
newly emerging research areas
disappearing topics
topic co-occurrence analysis

The final report is automatically formatted as Slack markdown and delivered directly to the project Slack workspace.

Automated Monthly Reporting

The GitHub Actions workflow executes automatically on the 1st day of every month.

During each run the analytics engine:

loads the historical paper database, groups papers according to their ingestion timestamps, compares the current reporting period with the previous month, recomputes all statistics, generates a deterministic executive summary and publishes the report to Slack

Because every statistic is recomputed from the historical database, no separate monthly report files need to be stored or maintained.

Manual Historical Comparisons:

The analytics engine also supports ad-hoc historical comparisons for arbitrary reporting periods.

Example:

python scripts/trend_analyzer.py --current 2026-07 --previous 2026-03

This generates a deterministic comparison between any two months without modifying the historical database or affecting the automated monthly workflow.

Design Principles

The current architecture follows several guiding principles:

Deterministic analytics – reports are generated using explicit statistical rules rather than LLM-generated summaries.

Single source of truth – all analytics are derived from the persistent historical paper database.

Modular design – discovery, enrichment, classification, persistence, analytics, and notification remain independent pipeline stages.

Extensible evaluation – the benchmarking framework can accommodate future threshold optimisation strategies without redesigning the pipeline.

## License
MIT
# scholar-scout
