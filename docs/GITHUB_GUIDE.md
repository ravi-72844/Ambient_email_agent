# Step-by-step: run the project and upload it to GitHub

Commands are written for **Windows (PowerShell / VS Code terminal)**. macOS/Linux differences are shown in *italics*.

---

## Part A — One-time setup on your laptop

### Step 1. Install the tools
| Tool | Link | Check it works |
|---|---|---|
| Python 3.11 or newer | <https://www.python.org/downloads/> (tick **"Add Python to PATH"**) | `python --version` |
| Git | <https://git-scm.com/download/win> | `git --version` |
| VS Code (optional) | <https://code.visualstudio.com/> | — |

### Step 2. Tell Git who you are (once per laptop)
```powershell
git config --global user.name "Ravi Kumawat"
git config --global user.email "your-github-email@example.com"
```
Use the **same email as your GitHub account**, so the commits show up on your profile.

---

## Part B — Run the project locally

### Step 3. Unzip the project
Unzip `ambient-email-agent.zip`, e.g. to `D:\projects\ambient-email-agent`, and open that folder in VS Code
(**File → Open Folder**) or in a terminal:
```powershell
cd D:\projects\ambient-email-agent
```

### Step 4. Create a virtual environment and install packages
```powershell
python -m venv .venv
.venv\Scripts\activate            # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
```
You should now see `(.venv)` at the start of the terminal line.
> If PowerShell says *"running scripts is disabled"*, run once:
> `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` and try again.

### Step 5. Add your API keys
```powershell
copy .env.example .env            # macOS/Linux: cp .env.example .env
```
Open `.env` and fill in:
- `GOOGLE_API_KEY` → <https://aistudio.google.com/> → **Get API key**
- `GEMINI_MODEL` → the model name that works for you (the one in your `hello.py`)
- `LANGSMITH_TRACING=true` and `LANGSMITH_API_KEY` → <https://smith.langchain.com> → Settings → API Keys

### Step 6. Check everything works
```powershell
python scripts\hello_gemini.py     # should print a hello line from Gemini
pytest -q                          # 9 passed (offline tests)
python main.py e29                 # agent checks the calendar, then asks you Approve / Edit / Deny
streamlit run app.py               # opens the UI in your browser (http://localhost:8501)
```

### Step 7. Generate your real results (with Gemini)
```powershell
python -m evals.triage_accuracy --delay 4
python -m evals.quality --delay 4
python -m evals.hitl_trajectory --delay 4
python -m evals.memory_adaptation
python -m evals.langsmith_eval          # optional: experiment in LangSmith
```
Copy the numbers into the **Evaluation** table in `README.md` (replace the `_fill in_` cells).
Take a screenshot of a LangSmith trace that shows the **interrupt** and save it in `docs/screenshots/` — mentors like seeing it.

---

## Part C — Upload to GitHub

### Step 8. Create an empty repository on GitHub
1. Go to <https://github.com/new>
2. **Repository name:** `ambient-email-agent`
3. **Description:** `Ambient email assistant agent with LangGraph, Gemini, human-in-the-loop and memory (Infosys Springboard)`
4. **Public**
5. ❗ Do **NOT** tick "Add a README", ".gitignore" or "license" — the project already has them.
6. Click **Create repository** and keep the page open (it shows the repo URL).

### Step 9. Make sure secrets will NOT be uploaded
```powershell
git init
git status
```
In the list, you must **NOT** see `.env`, `credentials.json`, `token.json`, `.venv/` or any `.db` file.
They are blocked by `.gitignore`. You **should** see `.env.example`.
To double-check one file: `git check-ignore -v .env` → prints the `.gitignore` rule that blocks it.

> ⚠️ If you ever push a real key by mistake: delete/regenerate that key immediately in AI Studio / LangSmith.
> Removing the file in a later commit is NOT enough — it stays in the history.

### Step 10. Fill in your username in README
Open `README.md` and replace both `YOUR_USERNAME` with your GitHub username (badge + clone URL).

### Step 11. First commit and push
```powershell
git add .
git commit -m "Ambient email agent: triage, ReAct, HITL, memory, Gmail, evaluation, UI"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/ambient-email-agent.git
git push -u origin main
```
The first push opens a browser window to log in to GitHub — approve it.
(If it asks for a password in the terminal: GitHub no longer accepts passwords — create a
**Personal Access Token** at GitHub → Settings → Developer settings → Tokens (classic), scope `repo`,
and paste it as the password.)

### Step 12. Check the repository page
Refresh the GitHub page. You should see:
- the README with the workflow diagram rendered (GitHub draws the `mermaid` block automatically) and screenshots,
- the **Actions** tab → workflow **tests** running → green ✅ after ~1 minute (it runs offline, no keys needed),
- the green **tests passing** badge at the top of the README.

### Step 13. Make the repo look professional (2 minutes)
On the repo page → ⚙️ next to **About**:
- **Topics:** `langgraph` `langchain` `gemini` `ai-agents` `human-in-the-loop` `gmail-api` `langsmith` `streamlit` `infosys-springboard`
- Tick **Use your GitHub Pages / website** only if you deploy the UI (optional).
Pin the repo on your GitHub profile: profile → **Customize your pins**.

---

## Part D — Every later change

```powershell
git status                      # see what changed
git add .
git commit -m "Short description of what you changed"
git push
```
Good commit messages: `Add LangSmith screenshots`, `Update README with Gemini results`, `Improve triage prompt`.

---

## Part E — Optional extras

**Deploy the UI for free (Streamlit Community Cloud)** — <https://share.streamlit.io> → *New app* → pick this repo,
main file `app.py` → *Advanced settings → Secrets*:
```toml
GOOGLE_API_KEY = "..."
GEMINI_MODEL = "gemini-3.8-flash"
EMAIL_BACKEND = "mock"
```
Keep `EMAIL_BACKEND = "mock"` for a public demo — never put your Gmail credentials on a public deployment.

**Connect your real Gmail** — see [GMAIL_SETUP.md](GMAIL_SETUP.md).

---

## Common errors
| Error | Fix |
|---|---|
| `'python' is not recognized` | Reinstall Python with **Add to PATH**, or use `py` instead of `python`. |
| `ModuleNotFoundError: agent` | Run commands from the project root folder, with `(.venv)` active. |
| `429 RESOURCE_EXHAUSTED` from Gemini | Free-tier rate limit — use `--delay 6` or wait a minute. |
| `404 model not found` | Change `GEMINI_MODEL` in `.env` to a model your key supports. |
| `remote origin already exists` | `git remote set-url origin https://github.com/YOUR_USERNAME/ambient-email-agent.git` |
| `failed to push some refs` | You created the repo *with* a README. Run `git pull origin main --allow-unrelated-histories`, then push again. |
| `.env` shows up in `git status` | Make sure the file is named exactly `.gitignore` (not `gitignore.txt`) and is in the project root. |
