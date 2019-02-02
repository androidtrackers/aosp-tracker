import difflib
from datetime import date
from bs4 import BeautifulSoup
from os import environ, rename, path, system
from requests import get, post

today = str(date.today())
telegram_chat = "@aosptracker"
bottoken = environ['bottoken']
GIT_OAUTH_TOKEN = environ['XFU']

url = 'https://android.googlesource.com/platform/frameworks/base/+refs'
response = get(url)
page = BeautifulSoup(response.content, 'html.parser')
data = page.findAll("div", {"class": "RefList"})
branches = []
tags = []
for section in data:
    title = section.find("h3", {"class": "RefList-title"})
    values = section.find_all("li")
    if "Branches" in title.text:
        for value in values:
            branches.append(value.text)
    elif "Tags" in title.text:
        for value in values:
            tags.append(value.text)

types = {'branches': branches, 'tags': tags}
for key, value in types.items():
    if path.exists(str(key)):
        rename(str(key), str(key) + '_old')
    # save to file
    with open(str(key), 'w') as o:
        for i in value:
            o.write(i + '\n')
    # diff
    with open(str(key) + '_old', 'r') as old, open(str(key), 'r') as new:
        o = old.readlines()
        n = new.readlines()
    diff = difflib.unified_diff(o, n, fromfile=str(key) + '_old', tofile=str(key))
    changes = []
    for line in diff:
        if line.startswith('+'):
            changes.append(str(line))
    new = ''.join(changes[1:]).replace("+", "")
    with open(str(key) + '_changes', 'w') as o:
        o.write(new)
    # post to tg
    with open(str(key) + '_changes', 'r') as c:
        for line in c:
            if key is 'branches':
                t = 'branch'
            elif key is 'tags':
                t = 'tag'
            telegram_message = "New {0} detected!: `{1}`" \
                               "[Check Here]({2})".format(t, line, url.split('/+')[0] + '/+/' + line)
            params = (
                ('chat_id', telegram_chat),
                ('text', telegram_message),
                ('parse_mode', "Markdown"),
                ('disable_web_page_preview', "yes")
            )
            telegram_url = "https://api.telegram.org/bot" + bottoken + "/sendMessage"
            telegram_req = post(telegram_url, params=params)
            telegram_status = telegram_req.status_code
            if telegram_status == 200:
                print("{0}: Telegram Message sent".format(line))
            else:
                print("Telegram Error")
# commit and push
system("git add branches tags && git -c \"user.name=XiaomiFirmwareUpdater\" "
       "-c \"user.email=xiaomifirmwareupdater@gmail.com\" commit -m \"[skip ci] sync: {0}\" && "" \
       ""git push -q https://{1}@github.com/yshalsager/aosp-tracker.git HEAD:master"
       .format(today, GIT_OAUTH_TOKEN))
