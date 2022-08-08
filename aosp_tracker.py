#!/usr/bin/env python3.7
"""AOSP tracker"""

import difflib
from datetime import date
from itertools import groupby
from os import environ, rename, path, system

from bs4 import BeautifulSoup
from requests import get, post

URL = "https://android.googlesource.com/platform/frameworks/base/+refs"

TG_CHAT = "@aosptracker"
BOT_TOKEN = environ["bottoken"]
GIT_OAUTH_TOKEN = environ["XFU"]
BRANCHES = []
TAGS = []


def fetch():
    """
    fetch latest info
    """
    response = get(URL)
    page = BeautifulSoup(response.content, "html.parser")
    data = page.findAll("div", {"class": "RefList"})
    for section in data:
        title = section.find("h3", {"class": "RefList-title"})
        values = section.find_all("li")
        if "Branches" in title.text:
            for value in values:
                BRANCHES.append(value.text)
        elif "Tags" in title.text:
            for value in values:
                TAGS.append(value.text)


def diff_files():
    """
    diff
    """
    # diff
    types = {"branches": BRANCHES, "tags": TAGS}
    for key, value in types.items():
        if path.exists(str(key)):
            rename(str(key), str(key) + "_old")
        # save to file
        with open(str(key), "w") as out:
            for i in value:
                out.write(i + "\n")
        with open(str(key) + "_old", "r") as old, open(str(key), "r") as new:
            diff = difflib.unified_diff(
                old.readlines(),
                new.readlines(),
                fromfile=str(key) + "_old",
                tofile=str(key),
            )
        changes = []
        for line in diff:
            if line.startswith("+"):
                changes.append(str(line))
        new = "".join(changes[1:]).replace("+", "")
        with open(str(key) + "_changes", "w") as out:
            out.write(new)
        # post to tg
        with open(str(key) + "_changes", "r") as changes:
            for line in changes:
                if key == "branches":
                    type_ = "branch"
                elif key == "tags":
                    type_ = "tag"
                telegram_message = "New {0} detected! `{1}`" "[Check Here]({2})".format(
                    type_, line, URL.split("/+")[0] + "/+/" + line
                )
                post_to_tg(telegram_message)


def post_to_tg(telegram_message):
    """
    post new devices to telegram channel
    """
    params = (
        ("chat_id", TG_CHAT),
        ("text", telegram_message),
        ("parse_mode", "Markdown"),
        ("disable_web_page_preview", "yes"),
    )
    telegram_url = "https://api.telegram.org/bot" + BOT_TOKEN + "/sendMessage"
    telegram_req = post(telegram_url, params=params)
    telegram_status = telegram_req.status_code
    if telegram_status == 200:
        print("Telegram Message sent")
    else:
        print("Telegram Error")


def git_commit_push():
    """
        git add - git commit - git push
    ="""
    today = str(date.today())
    system(
        'git add branches tags security_patch && git -c "user.name=XiaomiFirmwareUpdater" '
        '-c "user.email=xiaomifirmwareupdater@gmail.com"'
        ' commit -m "[skip ci] sync: {0}" && '
        " \
           "
        "git push -q https://{1}@github.com/androidtrackers/aosp-tracker.git HEAD:master".format(
            today, GIT_OAUTH_TOKEN
        )
    )


def security_bulletin():
    """
    Android Security Bulletins
    """
    data = (
        BeautifulSoup(
            get("https://source.android.com/security/bulletin").content, "html.parser"
        )
        .find("table")
        .findAll("tr")[1]
    )
    latest = data.findAll("td")[0].text
    link = "https://source.android.com/" + data.findAll("td")[0].a["href"]
    patch = data.findAll("td")[-1].text.replace(" ", "").replace("\n", " | ")
    sbl_patches = ""
    sbl_response = get(f"{link}?partial=1")
    if sbl_response.ok and sbl_response.text.startswith("["):
        sbl_data = [
            i for i in sbl_response.json() if i and isinstance(i, str) and "CVE" in i
        ]
        page = BeautifulSoup(sbl_data[0].strip(), "html.parser")
        patches = page.select('td a[href*="android.googlesource.com"]')
        patches_groups = [
            list(item)
            for _, item in groupby(
                sorted(patches, key=lambda x: x["href"]),
                lambda x: "_".join(x.get("href", "").split("+")[0].split("/")[3:-1]),
            )
        ]
        for patches_group in patches_groups:
            sbl_patches += f'\n`{"_".join(patches_group[0].get("href", "").split("+")[0].split("/")[3:-1])}`:\n'
            sbl_patches += " - ".join(
                f"[{patch.text.strip()}]({patch.get('href')})"
                for patch in patches_group
            )

    if path.exists("security_patch"):
        rename("security_patch", "security_patch_old")
    with open("security_patch", "w") as out:
        out.write(latest)
    with open("security_patch_old", "r") as old_file:
        old = old_file.read()
    if latest != old:
        message = (
            f"New Security Patch detected! [{latest}]({link})\n"
            f"__Patch__: {patch}\n\n"
        )
        if sbl_patches:
            message += "**Security Patch Commits:**"
            message += sbl_patches
        post_to_tg(message)
    else:
        return


def main():
    """
    Main scraping script
    """
    fetch()
    diff_files()
    security_bulletin()
    git_commit_push()


if __name__ == "__main__":
    main()
