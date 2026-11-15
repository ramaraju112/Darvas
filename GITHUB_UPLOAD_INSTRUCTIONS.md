# Darvas V7.4 — GitHub-ready ZIP

This ZIP is organized for your EXISTING GitHub repository `ramaraju112/Darvas`.

## Easiest: upload through the GitHub website
1. Extract this ZIP on Windows.
2. Open your existing repository on GitHub and switch to the intended branch (`main`).
3. Select **Add file > Upload files**.
4. Drag the extracted **v7_4** folder onto the upload page. Verify the file paths begin `v7_4/` and preserve the `static/` subfolder.
5. Commit changes. Do not upload any `.env`, `data/`, personal portfolio CSV or API tokens.
6. On any Windows laptop, select **Code > Download ZIP**, extract it, open the `v7_4` folder, and run `START_DARVAS.bat`.

If GitHub's browser upload does not preserve the folder hierarchy, use Git (below).

## Reliable alternative: Git command line
```bat
git clone https://github.com/ramaraju112/Darvas.git
cd Darvas
```
Copy the extracted `v7_4` folder into this cloned `Darvas` folder, then run:
```bat
git add v7_4
git commit -m "Add Darvas V7.4 browser MVP"
git push origin main
```
GitHub may prompt you to sign in. Do not embed passwords or tokens in scripts.

## Data migration
GitHub syncs code, not your local SQLite database. To move saved research/portfolio/history, stop the app and transfer `v7_4/data/` securely between laptops; NEVER commit it to GitHub. You can also redownload market prices on the new laptop.

## Important
This is the existing integrated MVP, not a fully validated live scanner. See `v7_4/README.md` for limitations and setup. The repo screenshot showed Public visibility: do not upload private data.
