# Google Maps List Scraper - GitHub Actions + n8n Integration

This setup allows you to run a Selenium-based Google Maps scraper via GitHub Actions, triggered from n8n Cloud.

## Repository Structure

```
your-repo/
├── .github/
│   └── workflows/
│       └── scrape_google_maps.yml    # GitHub Actions workflow
├── output/                            # Scraped data saved here
├── google_maps_list_scraper.py       # Main scraper script
└── README.md
```

## Setup Instructions

### 1. Create a GitHub Repository

1. Create a new **private** repository on GitHub
2. Upload both files:
   - `google_maps_list_scraper.py` (the scraper script)
   - `.github/workflows/scrape_google_maps.yml` (the workflow)
3. Create an empty `output/` folder (add a `.gitkeep` file inside)

### 2. Create a GitHub Personal Access Token

1. Go to GitHub → Settings → Developer settings → Personal access tokens → Tokens (classic)
2. Click "Generate new token (classic)"
3. Give it a name like `n8n-scraper`
4. Select scopes:
   - `repo` (full control of private repositories)
   - `workflow` (update GitHub Action workflows)
5. Copy the token - you'll need it for n8n

### 3. Configure n8n Workflow

#### Node 1: HTTP Request (Trigger GitHub Action)

**Method:** `POST`

**URL:** 
```
https://api.github.com/repos/YOUR_USERNAME/YOUR_REPO/actions/workflows/scrape_google_maps.yml/dispatches
```

**Authentication:** Header Auth
- Name: `Authorization`
- Value: `Bearer YOUR_GITHUB_TOKEN`

**Headers:**
- `Accept`: `application/vnd.github.v3+json`
- `X-GitHub-Api-Version`: `2022-11-28`

**Body (JSON):**
```json
{
  "ref": "main",
  "inputs": {
    "list_url": "{{ $json.url }}",
    "output_filename": "{{ $json.filename }}"
  }
}
```

#### Node 2: Wait

Add a **Wait** node: 60-120 seconds (depending on list size)

#### Node 3: HTTP Request (Get Workflow Runs)

**Method:** `GET`

**URL:**
```
https://api.github.com/repos/YOUR_USERNAME/YOUR_REPO/actions/runs?per_page=1
```

**Authentication:** Same as above

#### Node 4: HTTP Request (Download Artifact)

**Method:** `GET`

**URL:**
```
https://api.github.com/repos/YOUR_USERNAME/YOUR_REPO/actions/artifacts
```

Then fetch the artifact download URL and retrieve the JSON file.

---

## Alternative: Fetch Results from Repo

Instead of artifacts, the workflow commits results to the `output/` folder. You can fetch directly:

**URL:**
```
https://raw.githubusercontent.com/YOUR_USERNAME/YOUR_REPO/main/output/google_maps_places.json
```

---

## n8n Workflow Summary

```
┌─────────────────┐
│ Manual Trigger  │
└────────┬────────┘
         │
         ▼
┌─────────────────────────┐
│ Workflow Configuration  │  ← Define list URLs here
└────────┬────────────────┘
         │
         ▼
┌─────────────────┐
│ Split List URLs │
└────────┬────────┘
         │
         ▼
┌─────────────────────────────┐
│ HTTP Request                │  ← Trigger GitHub Action
│ POST /actions/workflows/... │
└────────┬────────────────────┘
         │
         ▼
┌─────────────────┐
│ Wait (90 sec)   │
└────────┬────────┘
         │
         ▼
┌─────────────────────────────┐
│ HTTP Request                │  ← Fetch results from repo
│ GET raw.githubusercontent   │
└────────┬────────────────────┘
         │
         ▼
┌─────────────────┐
│ Parse JSON      │
└────────┬────────┘
         │
         ▼
┌─────────────────────┐
│ Add to Google Sheet │
└─────────────────────┘
```

---

## Usage Limits

GitHub Actions free tier includes:
- **2,000 minutes/month** for private repos
- **Unlimited** for public repos

Each scrape typically takes 1-3 minutes depending on list size.

---

## Troubleshooting

### Workflow not triggering?
- Ensure the token has `repo` and `workflow` scopes
- Check the repository name and workflow filename are correct

### Scraper timing out?
- Increase `--scroll-pause` for slower connections
- Increase the Wait node duration in n8n

### Empty results?
- Ensure the Google Maps list is set to **public**
- Check the URL format is correct

---

## Testing Manually

You can test the GitHub Action manually:
1. Go to your repo → Actions → "Scrape Google Maps List"
2. Click "Run workflow"
3. Enter a Google Maps list URL
4. Check the output in the `output/` folder or download the artifact
