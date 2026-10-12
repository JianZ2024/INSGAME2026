# Publishing INSGAME2026 to GitHub

This guide uploads source code. It does not publish a running website or copy existing classroom data. The repository root should be the directory containing `app.py` and `README.md`.

## 1. Use the clean source package

Extract `INSGAME2026-github.zip` to a new working directory and open the extracted `INSGAME2026` folder in VS Code. Upload the extracted files, not just the ZIP file. Keep the dotfiles and dot-directories: `.gitignore`, `.gitattributes`, `.github/`, and `.vscode/launch.json`.

The package includes application code, the MIT `LICENSE`, tests, rules, README, a generated example, and development helpers. It intentionally excludes:

- `data/`, teacher passwords, SQLite databases, classroom exports, and backups.
- Personal `PROJECT_HANDOFF.md` notes and their machine paths/classroom codes, and the local `PUBLICATION_AUDIT.md` report.
- Old preview screenshots, Python environments, bytecode, logs, and build output.
- The original Excel workbook and legacy-analysis files, which are not needed at runtime.

`MANIFEST.sha256` records the packaged file hashes. It describes this archive; it is not a runtime dependency and does not update automatically when you edit extracted files.

## 2. Publish with VS Code

1. Install Git if VS Code cannot find it, then reopen VS Code.
2. Open **Source Control** and choose **Initialize Repository**.
3. Review the changed-file list. It should contain source and documentation, with no runtime data, passwords, or database files.
4. Stage those files, enter a message such as `Initial INSGAME2026 source release`, and choose **Commit**.
5. Choose **Publish Branch**, sign in to GitHub, and select **Publish to GitHub private repository**. Use `INSGAME2026` as the repository name if available.
6. On GitHub, check that `README.md` renders on the repository home page, its relative links work, and the **Actions** tab shows the configured checks.

A private repository is a convenient starting point for a teaching project. No repository has been created or uploaded by the source packaging script.

## 3. Command-line alternative

Create an empty GitHub repository without an automatically generated README, license, or `.gitignore`. In the extracted project directory, run the following. Replace `YOUR_USERNAME` and the repository name with your own values before adding the remote.

```sh
git init -b main
git status --short
git add .
git status --short
git commit -m "Initial INSGAME2026 source release"
git remote add origin https://github.com/YOUR_USERNAME/INSGAME2026.git
git push -u origin main
```

The `git add .` command above assumes you are in the clean extracted package and have reviewed the status output. Do not force-add ignored runtime data from your original working directory. GitHub authentication is handled by Git or your credential manager; do not embed tokens in commands or source files.

`.gitignore` prevents new ignored files from being added normally; it does not remove files already committed or erase Git history. If real credentials have previously been uploaded, rotate them and review that repository's history before making it public.

## 4. Future updates

Work from the same Git repository for future changes. When changing machines, pull the latest code before editing. Test locally, review the diff, commit the source changes, and push to the branch used by your deployment.

```sh
python -m unittest discover -s tests -v
python examples/demo_round.py --check
```

Optional frontend checks:

```sh
node tests/test_dashboard.cjs
node tests/test_market.cjs
```

If a rules change deliberately alters the example, run `python examples/demo_round.py --write` and review the updated README and example result file before committing.

GitHub Actions runs the included checks on pushes and pull requests. The workflow is configured, but its remote execution is only verified once you see it pass in your repository's Actions tab. Official references: [Python setup](https://github.com/actions/setup-python), [Node setup](https://github.com/actions/setup-node), and [checkout](https://github.com/actions/checkout).

## 5. Relationship to Railway

Uploading to GitHub is a separate step from hosting the running application. A Railway service can later connect to this repository. The application currently supports explicit `--host`, `--port`, and `--data-dir` arguments and `INSGAME_ADMIN_KEY`, but the current source is documented for local/trusted-LAN use; public-hosting adaptations are listed in the README.

For a future Railway deployment, keep the application database on a persistent volume, choose one service instance, and keep live credentials out of GitHub. Source updates must not upload a local test database over the cloud classroom database. Back up cloud data before changing rules or database migrations. A rollback of program code does not undo a database migration.

There is no public deployment URL or one-click deployment claim in this package. GitHub Pages cannot execute `app.py`.
