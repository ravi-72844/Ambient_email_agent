# Connecting the agent to a real Gmail inbox + Google Calendar

> Use a **test Gmail account** first. The agent never sends anything without your approval, but archiving and
> starring happen automatically for `ignore` / `notify_human` emails.

## 1. Create a Google Cloud project
1. Open <https://console.cloud.google.com/> and sign in with the Gmail account you want the agent to manage.
2. Top bar → project picker → **New Project** → name it `ambient-email-agent` → **Create**.

## 2. Enable the APIs
**APIs & Services → Library**, search and **Enable** both:
- **Gmail API**
- **Google Calendar API**

## 3. Configure the OAuth consent screen
**APIs & Services → OAuth consent screen** (may be called *Google Auth Platform*):
1. User type **External** → fill app name, your email as support + developer contact → Save.
2. **Audience / Test users** → **Add users** → add your own Gmail address. (While the app is in *Testing*, only test users can log in.)

## 4. Create the OAuth client
**APIs & Services → Credentials → Create credentials → OAuth client ID**
- Application type: **Desktop app** → Create → **Download JSON**.
- Rename the downloaded file to **`credentials.json`** and put it in the project root (next to `app.py`).
- `credentials.json` and `token.json` are in `.gitignore` — **never push them to GitHub.**

## 5. Switch the agent to Google
In `.env`:
```
EMAIL_BACKEND=google
TIMEZONE=Asia/Kolkata
```

## 6. First login
```bash
python ambient.py --once
```
A browser opens → choose your account → you will see "Google hasn't verified this app" → **Continue** (it is your own app)
→ allow Gmail + Calendar. A `token.json` is saved, so next time no login is needed.

## 7. Run it
```bash
python ambient.py          # keeps watching the inbox every POLL_SECONDS (default 60)
streamlit run app.py       # Pending approvals page: approve / edit / deny the drafted replies
```
Send a test email to the account from another address (e.g. "Are you free for a call on Wednesday?") and watch it
appear under **Pending approvals**.

### Troubleshooting
| Problem | Fix |
|---|---|
| `access_denied` / app not verified | Add your address under **Test users** (step 3). |
| `invalid_grant` / token expired | Delete `token.json` and log in again. |
| `insufficient authentication scopes` | You changed scopes → delete `token.json`. |
| `credentials.json not found` | File must be in the project root with exactly that name. |
