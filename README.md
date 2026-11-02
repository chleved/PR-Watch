# Rainmeter PR Watch Widget

![PR Watch Widget Preview](preview.png) <!-- TODO: Add a real preview screenshot here and name it preview.png -->

The **PR Watch Rainmeter Widget** is a sleek, modern desktop skin that monitors your GitHub pull requests in real time. It displays review decisions, CI statuses, unread comments, commit deltas, and releases ahead directly on your desktop!

## Features

* **Automated Background Updates:** A headless background skin (`Updater.ini`) automatically runs a lightweight Python fetcher every 15 minutes, refreshing the widget silently.
* **Instant Manual Refresh:** Right-click the widget and click **Fetch now** to pull the latest PR status immediately.
* **Comprehensive PR Status Badges:** Displays clear color-coded status chips for every PR state:
  * `APPROVED`, `CHANGES`, `CONFLICT`, `CI-FAIL`, `CI-RUNNING`, `WAITING`, `DRAFT`, `MERGED`, `CLOSED`.
* **Unread Message & Review Counter:** A dedicated chip tracks unread review comments and issue comments since your last visit. Clicking a PR row opens the pull request in your default browser and instantly clears the chip counter to `0`.
* **Behind & Ahead Deltas:** Shows how many commits your branch is behind the base branch (`+X COMMITS`) and how many GitHub releases have been published since the PR was created (`+Y RELEASES`).
* **Mouse Wheel Scrolling:** Smoothly scroll through up to 20 pull requests with your mouse wheel. The panel height dynamically adapts to your active PR count.
* **Owner Avatar Caching:** Automatically downloads and caches repository owners' avatars as crisp icons, refreshing them weekly.
* **Quick List Editing:** Right-click the widget and select **Edit PR list** to quickly add or remove pull requests.

## Requirements

* **[Rainmeter](https://www.rainmeter.net/)** (v4.5 or newer)
* **Python 3.x**
  * Verify your installation in a terminal:
    ```cmd
    python --version
    ```
* **[GitHub CLI](https://cli.github.com/) (`gh`)**
  * Install via winget:
    ```cmd
    winget install GitHub.cli
    ```
  * Authenticate with your GitHub account:
    ```cmd
    gh auth login
    ```

## Installation

1. Open your terminal and navigate to your Rainmeter Skins folder:
   ```cmd
   cd %USERPROFILE%\Documents\Rainmeter\Skins\
   ```
2. Clone this repository (or extract the downloaded ZIP here):
   ```cmd
   git clone https://github.com/chleved/PR-Watch.git PRWidget
   ```
   **Important:** Ensure your final folder structure looks like this:
   ```text
   ...\Documents\Rainmeter\Skins\PRWidget\
   │   .gitignore
   │   README.md
   ├───@Resources\
   │   │   state.inc
   │   ├───fetcher\
   │   │   │   fetch_prs.py
   │   │   │   pr_status.jq
   │   │   │   prs.txt
   │   │   └───data\
   │   └───tools\
   │           make_skin.py
   ├───Updater\
   │       Updater.ini
   └───Widget\
           Widget.ini
   ```
3. Open Rainmeter Manage (right-click Rainmeter tray icon -> **Manage**).
4. Click **Refresh all** in the bottom-left corner.
5. Expand `PRWidget` and load:
   * `Widget\Widget.ini` (the visible desktop widget)
   * `Updater\Updater.ini` (the background timer that keeps your data fresh)

## Configuration

### Adding Pull Requests
Add pull requests by editing `@Resources\fetcher\prs.txt` (or right-click the widget and select **Edit PR list**).

Add one pull request per line as either a full URL or `owner/repo#number`:
```text
https://github.com/facebook/react/pull/12345
vercel/next.js#54321
```
Lines starting with `;` or `//` are treated as comments and ignored.

### Customizing Dimensions & Rows
The skin's meters are generated via `@Resources\tools\make_skin.py`. You can regenerate the widget with custom row counts or width:

```cmd
cd %USERPROFILE%\Documents\Rainmeter\Skins\PRWidget\@Resources\tools\
python make_skin.py --rows 10 --width 400 --out ..\..\Widget\Widget.ini
```

* `--rows`: Maximum visible rows at once (default `8`, supports up to `20`).
* `--width`: Width of the widget in pixels (minimum `380`).

After regenerating, right-click the widget and click **Refresh skin**.
