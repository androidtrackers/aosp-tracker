#!/usr/bin/env python
# /// script
# requires-python = ">=3.12"
# dependencies = [
#   "beautifulsoup4",
#   "requests",
# ]
# ///
"""AOSP tracker."""

import argparse
import os
import re
import subprocess
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from time import sleep

from bs4 import BeautifulSoup
from requests import Response, Session
from requests.exceptions import RequestException


@dataclass(frozen=True, slots=True)
class Settings:
    refs_url: str = "https://android.googlesource.com/platform/frameworks/base/+refs"
    refs_base_url: str = "https://android.googlesource.com/platform/frameworks/base/+"
    bulletin_index_url: str = "https://source.android.com/docs/security/bulletin"
    telegram_chat: str = "@aosptracker"
    bot_token: str = ""
    git_oauth_token: str = ""
    request_timeout: int = 30
    retry_attempts: int = 3
    retry_delay_seconds: int = 2


@dataclass(frozen=True, slots=True)
class SecurityBulletinInfo:
    latest: str
    link: str
    patch: str


class UpstreamUnavailableError(RuntimeError):
    pass


def read_lines(file_path: Path) -> list[str]:
    if not file_path.exists():
        return []
    return [line.strip() for line in file_path.read_text().splitlines() if line.strip()]


def write_lines(file_path: Path, lines: list[str]) -> None:
    text = "\n".join(lines)
    if text:
        text += "\n"
    file_path.write_text(text)


def fetch_url(session: Session, url: str, cfg: Settings) -> Response:
    last_error: Exception | None = None
    for attempt in range(1, cfg.retry_attempts + 1):
        try:
            response = session.get(url, timeout=cfg.request_timeout)
            response.raise_for_status()
            return response
        except RequestException as error:
            last_error = error
            if attempt < cfg.retry_attempts:
                sleep(cfg.retry_delay_seconds * attempt)
    raise UpstreamUnavailableError(
        f"GET {url} failed after {cfg.retry_attempts} attempts: {last_error}"
    )


def fetch_refs(session: Session, cfg: Settings) -> tuple[list[str], list[str]]:
    page = BeautifulSoup(fetch_url(session, cfg.refs_url, cfg).content, "html.parser")
    branches: list[str] = []
    tags: list[str] = []
    for section in page.find_all("div", {"class": "RefList"}):
        title = section.find("h3", {"class": "RefList-title"})
        if title is None:
            continue
        values = [item.get_text(strip=True) for item in section.find_all("li")]
        if "Branches" in title.get_text():
            branches.extend(values)
        elif "Tags" in title.get_text():
            tags.extend(values)
    if not branches or not tags:
        raise RuntimeError("Failed to parse refs page (empty branches or tags)")
    return branches, tags


def post_to_telegram(session: Session, message: str, cfg: Settings) -> None:
    if not cfg.bot_token:
        raise RuntimeError("bottoken is required")
    params = (
        ("chat_id", cfg.telegram_chat),
        ("text", message),
        ("parse_mode", "Markdown"),
        ("disable_web_page_preview", "yes"),
    )
    telegram_url = f"https://api.telegram.org/bot{cfg.bot_token}/sendMessage"
    response = session.post(telegram_url, params=params, timeout=cfg.request_timeout)
    response.raise_for_status()


def update_refs_files(
    session: Session,
    refs_name: str,
    values: list[str],
    cfg: Settings,
    send_telegram: bool,
    max_telegram_messages: int,
) -> None:
    current_path = Path(refs_name)
    old_path = Path(f"{refs_name}_old")
    changes_path = Path(f"{refs_name}_changes")

    previous_values = read_lines(current_path)
    if current_path.exists():
        current_path.replace(old_path)
    elif not old_path.exists():
        old_path.write_text("")

    write_lines(current_path, values)
    previous_values_set = set(previous_values)
    changes = [value for value in values if value and value not in previous_values_set]
    write_lines(changes_path, changes)

    if not send_telegram:
        return
    if len(changes) > max_telegram_messages:
        print(
            f"Skipped Telegram for {refs_name}: {len(changes)} changes exceeds cap ({max_telegram_messages})"
        )
        return

    ref_type = "branch" if refs_name == "branches" else "tag"
    for ref_name in changes:
        message = f"New {ref_type} detected! `{ref_name}` [Check Here]({cfg.refs_base_url}/{ref_name})"
        post_to_telegram(session, message, cfg)


def fetch_security_bulletin(session: Session, cfg: Settings) -> SecurityBulletinInfo:
    bulletin_page = BeautifulSoup(
        fetch_url(session, cfg.bulletin_index_url, cfg).content, "html.parser"
    )
    bulletin_links: list[tuple[str, str]] = []
    for item in bulletin_page.find_all("a", href=True):
        href_attr = item.get("href")
        if not isinstance(href_attr, str):
            continue
        href = href_attr
        match = re.search(r"^/docs/security/bulletin/\d{4}/(\d{4}-\d{2}-\d{2})/?$", href)
        if match:
            bulletin_links.append((match.group(1), href))
    if not bulletin_links:
        raise RuntimeError("Failed to parse security bulletin links")

    latest, latest_path = max(bulletin_links)
    link = (
        latest_path
        if latest_path.startswith("http")
        else f"https://source.android.com{latest_path}"
    )
    detail_text = BeautifulSoup(
        fetch_url(session, link, cfg).content, "html.parser"
    ).get_text(" ", strip=True)
    patch_levels = sorted(set(re.findall(r"\b\d{4}-\d{2}-(?:01|05)\b", detail_text)))
    patch = " | ".join(patch_levels) if patch_levels else latest
    return SecurityBulletinInfo(latest=latest, link=link, patch=patch)


def fetch_bulletin_links(session: Session, cfg: Settings, bulletin_date: str) -> list[str]:
    bulletin_page = BeautifulSoup(
        fetch_url(session, cfg.bulletin_index_url, cfg).content, "html.parser"
    )
    return sorted(
        {
            f"https://source.android.com{href}"
            for item in bulletin_page.find_all("a", href=True)
            if isinstance((href := item.get("href")), str)
            and re.search(rf"^/docs/security/bulletin(?:/[^/]+)?/\d{{4}}/{re.escape(bulletin_date)}/?$", href)
        }
    )


def update_security_patch(
    session: Session, bulletin: SecurityBulletinInfo, cfg: Settings, send_telegram: bool
) -> None:
    current_path = Path("security_patch")
    old_path = Path("security_patch_old")

    if not current_path.exists():
        current_path.write_text(bulletin.latest)
        return

    previous_value = current_path.read_text().strip()
    current_path.replace(old_path)
    current_path.write_text(bulletin.latest)

    if bulletin.latest == previous_value:
        return
    if not send_telegram:
        return

    bulletin_links = "\n".join(f"- {url}" for url in fetch_bulletin_links(session, cfg, bulletin.latest))
    message = (
        f"New Security Patch detected! [{bulletin.latest}]({bulletin.link})\n"
        f"__Patch__: {bulletin.patch}\n"
        f"__Bulletins__:\n{bulletin_links}\n"
    )
    post_to_telegram(session, message, cfg)


def git_commit_push(cfg: Settings) -> None:
    today = str(date.today())
    tracked_files = ["branches", "tags", "security_patch"]
    subprocess.run(["git", "add", *tracked_files], check=True)
    staged_diff = subprocess.run(
        ["git", "diff", "--cached", "--quiet", "--", *tracked_files], check=False
    )
    if staged_diff.returncode == 0:
        print("No tracked changes to commit")
        return
    if staged_diff.returncode != 1:
        raise RuntimeError("Failed to inspect staged git changes")
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=XiaomiFirmwareUpdater",
            "-c",
            "user.email=xiaomifirmwareupdater@gmail.com",
            "commit",
            "-m",
            f"[skip ci] sync: {today}",
        ],
        check=True,
    )
    if cfg.git_oauth_token:
        push_command = [
            "git",
            "push",
            "-q",
            f"https://{cfg.git_oauth_token}@github.com/androidtrackers/aosp-tracker.git",
            "HEAD:master",
        ]
    elif os.environ.get("GITHUB_ACTIONS") == "true":
        push_command = ["git", "push", "-q", "origin", "HEAD:master"]
    else:
        raise RuntimeError("XFU is required outside GitHub Actions")
    subprocess.run(push_command, check=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--parse-only", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--send-telegram", action="store_true")
    parser.add_argument("--push", action="store_true")
    parser.add_argument("--max-telegram-messages", type=int, default=20)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    cfg = Settings(
        bot_token=os.environ.get("bottoken", ""),
        git_oauth_token=os.environ.get("XFU", ""),
    )

    send_telegram = args.send_telegram and not args.dry_run
    push = args.push and not args.dry_run

    with Session() as session:
        try:
            branches, tags = fetch_refs(session, cfg)
            bulletin = fetch_security_bulletin(session, cfg)
            if args.parse_only:
                print(
                    f"Parsed branches={len(branches)} tags={len(tags)} latest_security_patch={bulletin.latest}"
                )
                return 0
            update_refs_files(
                session,
                "branches",
                branches,
                cfg,
                send_telegram,
                args.max_telegram_messages,
            )
            update_refs_files(
                session, "tags", tags, cfg, send_telegram, args.max_telegram_messages
            )
            update_security_patch(session, bulletin, cfg, send_telegram)
            if push:
                git_commit_push(cfg)
            return 0
        except UpstreamUnavailableError as error:
            print(f"Run skipped due to upstream outage: {error}")
            if os.environ.get("GITHUB_ACTIONS") == "true":
                return 0
            return 1
        except Exception as error:
            print(f"Run failed safely: {error}")
            return 1


if __name__ == "__main__":
    raise SystemExit(main())
