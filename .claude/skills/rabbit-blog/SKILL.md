---
name: rabbit-blog
description: Add a post to the owner's Rabbit build log (rabbit0.dev, source in ~/projects/rabbit/workspaces/blog) from a dictated message, notes or session results, in Russian and English, with media, then build and publish it. Use when the owner says "добавь в блог", "запиши в блог", dictates a post, or asks to publish a blog entry.
---

# Posting to the blog

The blog lives in this repo at `workspaces/blog` (imported with its history from `seralexeev/rabbit0` on 2026-10-03) and is served at https://rabbit0.dev (English) and https://rabbit0.dev/ru (Russian). GitHub Pages deploys it: `.github/workflows/blog.yml` runs on every push to `main` that touches `workspaces/blog/**`, rebuilds the pages (`node src/index.ts`, thumbnails with cwebp/ffmpeg) and publishes `static/`. Until the DNS switch in `docs/open-issues.md` Q16 is done, rabbit0.dev is still served by Cloudflare Pages from the `seralexeev/rabbit0` mirror, so also run `scripts/blog.sh publish` after pushing. Never edit `~/projects/rabbit0` or push to it directly.

**A dictated post is the order to publish.** Write it, build it and push it without asking again. Ask first only if the text names third parties, or looks private (addresses, faces, passwords, family).

## Files

| File | What |
|---|---|
| `README.ru.md` | Russian posts. The source |
| `README.md` | English posts, same ids |
| `README.bunnyfleet.md` | a separate feed; don't touch |
| `static/media/` | media named `<id>-<n>.jpg` / `.mp4`; thumbnails are generated into `static/media/thumbnails/` |
| `static/index.html`, `static/ru.html` | built pages, committed |

## Post format

Posts are separated by a line `---`, so a post body must never contain a `---` line. Each post:

````markdown
---

```yaml
id: 187
date: 03-10-2026
media:
    - 187-1.jpg
```

Text in Markdown.
````

- **id:** the last id in `README.ru.md` + 1. Check with `grep "^id:" README.ru.md | tail -1`.
- **date:** today in Sydney time, `DD-MM-YYYY`: `TZ=Australia/Sydney date +%d-%m-%Y`.
- **media:** optional. Leave out the key when there is none.

Append the post to the end of both `README.ru.md` and `README.md`. Write the English version yourself. The build would otherwise call OpenAI to translate it, and it runs with a dummy key.

## Turning dictation into a post

The owner dictates by voice: the message has filler words ("э", "вот", "uh") and broken sentences.

- **Keep the meaning, the jokes and the conclusion.** Remove the filler. Don't add facts the owner didn't say, unless they ask you to.
- **Voice.** Write in the first person, as the owner: short, concrete, with a little self-irony. Before writing, read the last 5–10 posts (`tail -80 README.ru.md`) and match them.
- **Simple style.**
  - plain past tense ("перенес", "сделал");
  - no headings;
  - a bullet list only when there are several separate facts;
  - numbers with units (`30 cm`, `2.4 s`, `12 W`).
- **Session details.** If the post is about work done in this session, add one or two real numbers or facts from it (the log is in `~/projects/rabbit/docs/log/`). It's a blog, not a report, so keep it short.
- **What goes in.** Only cool or cardinal things: a new capability, a funny failure, a surprising root cause, a big decision. Never write meta about the blog or about documenting.

## Media

- **Images must be real:**
  - a HUD screenshot (claude-in-chrome on https://localhost:3005 or https://jetson.rabbit);
  - a camera frame;
  - a plot with clearly readable data.

  No near-empty charts.
- **Labels in English.** Chart labels, titles and legends are in English even in Russian posts. Blur people.
- **Files.**
  - Resize JPEGs to at most 1600 px: `sips -Z 1600 in.jpg --out static/media/187-1.jpg`.
  - A video needs H.264: `./transcode.sh <file>` writes `static/media/<file>.mp4`; rename the result to `<id>-<n>.mp4`.
  - Thumbnails need `cwebp` and `ffmpeg` (both via Homebrew).

## Build and publish

```sh
cd ~/projects/rabbit
scripts/blog.sh build      # npm ci on first use; refuses if a README lost posts vs HEAD; prints the post counts
B=workspaces/blog
git add $B/README.md $B/README.ru.md $B/static/index.html $B/static/ru.html $B/static/media/<id>-* $B/static/media/thumbnails/<id>-*
git commit -m "feat(blog): post <id> on <topic>"
git push origin main
gh run watch $(gh run list --workflow blog.yml -L 1 --json databaseId --jq '.[0].databaseId') --exit-status   # GitHub Pages deploy, ~2 min
scripts/blog.sh publish    # only until Q16 (DNS switch) is done: pushes the rabbit0 mirror that Cloudflare still serves
```

All paths in this skill below are relative to `workspaces/blog`.

- **Check before committing:**
  - `grep -c "^id:" README.ru.md README.md` grew by exactly the number of new posts, and `git diff --numstat README.md README.ru.md` shows 0 deleted lines. On 2026-10-03 an append that opened the file for writing before reading it wiped posts 1–186 from the live blog. Read the whole file first, or append with `>>`;
  - every post starts with a `---` line (the build's own dump of `README.md` drops it before the first post only);
  - the build printed `⚪ <id>` for the new id, not `🟢 … translating`;
  - `grep -c "<a distinctive word>" static/ru.html static/index.html` finds the new text in both pages.
- **Registry.** The npm registry must be the public one. The default in `~/.npmrc` is a work registry, which fails with 401.
- **What to stage.** Stage only these paths: the repo holds other uncommitted work. `publish` refuses while `workspaces/blog` has uncommitted changes.
- **Reply.** Answer the owner with the post text and the link https://rabbit0.dev/ru. The page updates a minute or two after `publish`; check with `curl -sL https://rabbit0.dev/ru | grep -c '<a distinctive word>'` (`/ru.html` redirects, so follow redirects).
