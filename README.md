# Scholar Scout

A tool to monitor Google Scholar alerts and classify research papers using Gemini 3.8 Flash LOW.

## Features
- Connects to Gmail to fetch Google Scholar alert emails
- Resolves source abstracts before classifying papers with verified contribution evidence
- Supports multiple research topics with explicit classification scopes
- Sends notifications to Slack

## Setup
1. Clone the repository
2. Create a virtual environment: `python -m venv .venv`
3. Activate the virtual environment: `source .venv/bin/activate` (Unix) or `.venv\Scripts\activate` (Windows)
4. Install dependencies: `pip install -r requirements.txt`
5. Create `.env` using the example below and fill in your credentials
6. Copy `config/config.example.yml` to `config/config.yml` and customize settings, including [topics](#configuring-topics)

## Configuration
Create a `.env` file with:
```
GMAIL_USERNAME=your.email@gmail.com
GMAIL_APP_PASSWORD=your-app-specific-password
GEMINI_API_KEY=your-gemini-api-key
SLACK_API_TOKEN=your-slack-api-token
IEEE_API_KEY=your-ieee-api-key
SEMANTIC_SCHOLAR_API_KEY=your-semantic-scholar-api-key
```

IEEE and Semantic Scholar keys are optional; IEEE retrieval requires its key.
In GitHub Actions, use the `GOOGLE_CREDENTIALS` secret for Gemini and
add `IEEE_API_KEY` and `SEMANTIC_SCHOLAR_API_KEY` if using those services.

### Gmail Setup

1. Enable 2-Step Verification on your Google Account, then create an [App Password](https://support.google.com/accounts/answer/185833) for Scholar Scout.
2. Set `GMAIL_USERNAME` to your Gmail address and `GMAIL_APP_PASSWORD` to that app password in `.env`. Do not use your normal Google password or commit credentials to Git.
3. Create a dedicated Gmail label, such as `Google Scholar Alerts`, and [create a filter](https://support.google.com/mail/answer/6579) for `scholaralerts-noreply@google.com` that applies this label. Apply the label to existing alerts too if you want them included.
4. Set the matching folder name in `config/config.yml`:

```yaml
email:
  username: ${GMAIL_USERNAME}
  password: ${GMAIL_APP_PASSWORD}
  folder: "Google Scholar Alerts"
```

Use a dedicated label: normal runs clean up emails older than four weeks in this folder. If App Passwords are unavailable, check your account's security settings or ask your Workspace administrator; this client requires IMAP access with an app password.

For GitHub Actions, add `GMAIL_USERNAME` and `GMAIL_APP_PASSWORD` as repository secrets. Set the folder in `config/config.example.yml`, which the workflow copies on each run.

### Adding Users to Track
1. Go to [Google Scholar](https://scholar.google.com/)
2. Search for the researcher you want to track
3. Click on their profile
4. Click the "Follow" button (bell icon) to receive email alerts for new papers
5. Route these alerts to the Gmail label configured above
6. Update `config/config.yml` to include any Slack users to notify:

```yaml
research_topics:
  - name: "LLM Inference"
    slack_users:
      - "@user1"
      - "@user2"
    slack_channel: "#llm-papers"  # optional
```

### Configuring Topics

Edit `config/topic_policy.json` to change classification scopes or add topics. In `config/config.yml`, configure each topic's subscribers and Slack channel using the same topic name. For GitHub Actions, edit `config/config.example.yml` instead.

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
python scripts/run_classifier.py
```

`--dry-run` to read mail without changing it, skip Slack, and work on a temporary copy of the saved state. It still calls external services.

`--debug` only enables detailed application logs; on its own, it runs the normal production workflow.

Before the first GitHub Actions run, prepare the branch and pending-queue file specified under `state_storage` in the configuration.

## Testing

Unit tests run in GitHub Actions using simulated services; no API keys are needed.

### Integration Tests

For live checks, set Gmail and Gemini credentials in `tests/.env.test` and the matching folder in `tests/test_config.yml`, then run:

```bash
make test-live
```

Live tests are skipped by default. They check read-only Gmail retrieval and classify a real reference paper using abstract and model services, with temporary state and no Slack messages. CI runs them on main updates or manual dispatch. The Weekly Scholar Classifier workflow is a production run, not a test; it can delete old emails and send notifications.

## License
MIT
