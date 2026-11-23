#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""skill-radar —— 每日从 GitHub 筛「好玩 / 有趣 / 好用」的 Agent Skill 与工具，生成中文日报。

只依赖 Python 标准库。无 token 也能跑（GitHub 搜索 API 未认证限速 10 次/分钟）。

用法:
    python radar.py                # 跑一轮，写 reports/YYYY-MM-DD.md + latest.md
    python radar.py --days 7 --top 10 --min-score 45
    python radar.py --no-seen      # 忽略已推送记录，重新排一遍（调试用）

可选 LLM 复评（OpenAI 兼容接口）:
    set RADAR_LLM_BASE=https://api.deepseek.com/v1
    set RADAR_LLM_KEY=sk-xxx
    set RADAR_LLM_MODEL=deepseek-chat

可选 GitHub token 提高限额（5000 次/小时）:
    set GITHUB_TOKEN=ghp_xxx
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sqlite3
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
REPORTS = ROOT / "reports"
DATA.mkdir(exist_ok=True)
REPORTS.mkdir(exist_ok=True)

UA = "skill-radar/1.0 (+https://localhost)"

# ---------------------------------------------------------------------------
# 词表：决定「好玩有趣」的口味。改这里就能调口味。
# ---------------------------------------------------------------------------
# 关键词以 * 结尾表示「前缀/子串匹配」，否则按整词匹配（避免 sing 命中 using、art 命中 start）
WOW_WORDS = {
    "game*": "游戏", "gomoku": "五子棋", "chess": "棋类", "sudoku": "数独",
    "minesweeper": "扫雷", "pixel*": "像素画", "ascii": "字符画", "tui": "终端界面",
    "terminal": "终端", "retro": "复古", "emulator*": "模拟器", "demo*": "演示项目",
    "music*": "音乐", "midi": "MIDI", "karaoke": "卡拉OK", "vinyl": "唱片",
    "voice*": "语音", "tts": "语音合成", "stt": "语音识别", "singing": "唱歌", "song*": "歌曲",
    "art": "绘画", "draw*": "绘图", "paint*": "作画", "animat*": "动画",
    "gif": "动图", "video*": "视频", "3d": "3D", "blender": "Blender",
    "minecraft": "我的世界", "cute": "可爱", "fun*": "好玩", "toy": "玩具",
    "creativ*": "创意", "visuali*": "可视化", "chart*": "图表", "map*": "地图",
    "weather": "天气", "robot*": "机器人", "arduino": "Arduino", "esp32": "ESP32",
    "hardware": "硬件", "drone*": "无人机", "plot*": "绘图", "story*": "故事",
    "comic*": "漫画", "novel*": "小说", "poem*": "写诗", "meme*": "表情包",
    "emoji*": "emoji", "sticker*": "贴纸", "print*": "打印", "badge*": "徽章",
    "svg": "矢量图", "poster": "海报", "comic*": "漫画", "sprite*": "精灵图",
    "voxel*": "体素", "shader*": "着色器", "audio*": "音频", "song*": "歌曲",
}

USE_WORDS = {
    "ocr": "OCR 识别", "pdf": "PDF 处理", "excel": "表格", "xlsx": "表格",
    "ppt": "幻灯片", "docx": "文档", "screenshot*": "截屏", "browser*": "浏览器",
    "scrap*": "抓取", "crawl*": "爬取", "rss": "RSS",
    "notion": "Notion", "obsidian": "Obsidian", "anki": "Anki", "email": "邮件",
    "calendar": "日历", "git": "Git", "review*": "代码评审", "refactor*": "重构",
    "test*": "测试", "sql": "SQL", "database*": "数据库", "docker": "容器",
    "kubernetes": "K8s", "api": "接口", "cli": "命令行", "mcp": "MCP",
    "automat*": "自动化", "workflow*": "工作流", "translat*": "翻译",
    "summar*": "摘要", "search*": "检索", "memory": "记忆", "rag": "RAG",
    "agent*": "Agent", "skill*": "Skill", "prompt*": "提示词",
}

_WORD_RE_CACHE: dict[str, re.Pattern] = {}


def hit(blob: str, key: str) -> bool:
    """按词表口径匹配：`game*` 前缀匹配，`gamoku` 整词匹配。"""
    if key.endswith("*"):
        return key[:-1] in blob
    pat = _WORD_RE_CACHE.get(key)
    if pat is None:
        pat = re.compile(r"(?<![a-z0-9])" + re.escape(key) + r"s?(?![a-z0-9])")
        _WORD_RE_CACHE[key] = pat
    return bool(pat.search(blob))


def match_words(blob: str, table: dict[str, str]) -> list[str]:
    out: list[str] = []
    for k, zh in table.items():
        if hit(blob, k) and zh not in out:
            out.append(zh)
    return out

# 扣分：垃圾 / 蹭流量 / 纯目录
NOISE_WORDS = [
    "awesome-list", "curated list", "collection of links", "合集", "资源大全",
    "free api", "免费api", "白嫖", "破解版", "限时免费", "免费节点", "订阅节点",
    "proxy pool", "机场节点", "挂机", "刷量", "薅羊毛", "0元购",
]
LISTWORDS = ["awesome", "curated", "list of", "collection", "工具集", "导航站"]

SEARCH_QUERIES = [
    ("topic:agent-skills", "agent-skills"),
    ("topic:claude-skills", "claude-skills"),
    ("topic:claude-code-skill", "claude-code-skill"),
    ("topic:ai-skills", "ai-skills"),
    ('"SKILL.md" in:readme skill', "skill-md"),
    ("topic:mcp-server claude skill", "mcp+skill"),
    ("topic:agent-skill", "agent-skill"),
]


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------
def gh_get(url: str, token: str | None) -> dict:
    req = urllib.request.Request(url)
    req.add_header("User-Agent", UA)
    req.add_header("Accept", "application/vnd.github+json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def search_repos(query: str, days: int, token: str | None, per_page: int = 50) -> list[dict]:
    since = (dt.date.today() - dt.timedelta(days=days)).isoformat()
    q = f"{query} pushed:>={since} stars:>=3 archived:false fork:false"
    url = (
        "https://api.github.com/search/repositories?q="
        + urllib.parse.quote(q)
        + f"&sort=updated&order=desc&per_page={per_page}"
    )
    # 未认证搜索限速 10 次/分钟：退避最多 2 次，拿不到就跳过这一路，不拖死整轮
    for attempt in range(2):
        try:
            data = gh_get(url, token)
            return data.get("items", [])
        except urllib.error.HTTPError as e:
            if e.code in (403, 429):
                wait = 25 * (attempt + 1)
                print(f"  ! 被限速 ({e.code})，等 {wait}s 重试", file=sys.stderr)
                time.sleep(wait)
                continue
            print(f"  ! {query} -> HTTP {e.code}", file=sys.stderr)
            return []
        except Exception as e:  # 网络抖动
            print(f"  ! {query} -> {e}", file=sys.stderr)
            time.sleep(5)
    print(f"  ! {query} -> 放弃（限速）", file=sys.stderr)
    return []


# ---------------------------------------------------------------------------
# 打分
# ---------------------------------------------------------------------------
def age_days(iso: str) -> float:
    t = dt.datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)
    return max((dt.datetime.now(dt.timezone.utc) - t).total_seconds() / 86400.0, 0.1)


def score_repo(r: dict) -> dict:
    blob = " ".join(
        [
            (r.get("name") or ""),
            (r.get("description") or ""),
            " ".join(r.get("topics") or []),
        ]
    ).lower()

    s = 0.0
    tags: list[str] = []
    why: list[str] = []

    # 1) 好玩 / 有用 关键词
    wow = match_words(blob, WOW_WORDS)
    use = match_words(blob, USE_WORDS)
    s += min(len(set(wow)) * 7, 21)
    s += min(len(set(use)) * 2.5, 10)
    tags = list(dict.fromkeys(wow + use))[:4]
    if wow:
        why.append("好玩度：" + "、".join(sorted(set(wow))[:3]))

    # 2) 是不是 Skill
    topics = {t.lower() for t in (r.get("topics") or [])}
    skill_topics = {"agent-skills", "claude-skills", "claude-code-skill", "ai-skills", "agent-skill", "skills"}
    if topics & skill_topics or "skill" in blob:
        s += 12
        why.append("原生 Skill 形态（SKILL.md 可直接装）")
    if (r.get("language") or "").lower() in ("python", "typescript", "javascript", "go", "rust"):
        s += 3

    # 3) 动量：star / 天
    stars = r.get("stargazers_count") or 0
    forks = r.get("forks_count") or 0
    age = age_days(r.get("created_at") or r.get("pushed_at"))
    vel = stars / age
    if vel >= 50:
        s += 15
    elif vel >= 20:
        s += 12
    elif vel >= 10:
        s += 8
    elif vel >= 3:
        s += 5
    elif vel >= 1:
        s += 2
    why.append(f"⭐{stars}（≈{vel:.0f}/天）")

    # 4) 新鲜度
    pd = age_days(r.get("pushed_at"))
    if pd <= 3:
        s += 8
    elif pd <= 14:
        s += 4
    if age <= 30:
        s += 6

    # 5) 质量门
    if r.get("license"):
        s += 6
    else:
        s -= 4
    if len(r.get("description") or "") >= 40:
        s += 4
    else:
        s -= 6
    if stars and forks / max(stars, 1) > 0.05:
        s += 4
        why.append("社区真在用（fork 比例高）")

    # 6) 降噪
    for w in NOISE_WORDS:
        if w in blob:
            s -= 18
            why.append(f"扣分：命中噪音词「{w}」")
            break
    if any(w in blob for w in LISTWORDS):
        s -= 14
        why.append("扣分：更像目录/合集，不是能直接用的工具")
    if stars > 1500 and age < 7:
        s -= 25
        why.append("扣分：新库 star 异常高，疑似刷榜")

    s = max(0.0, min(100.0, s))
    return {"score": round(s, 1), "tags": tags, "why": why, "velocity": round(vel, 1), "age": round(age, 1)}


# ---------------------------------------------------------------------------
# 可选 LLM 复评（没有 key 就跳过，不影响出日报）
# ---------------------------------------------------------------------------
def llm_judge(cands: list[dict], top: int) -> dict[str, str]:
    base = os.environ.get("RADAR_LLM_BASE")
    key = os.environ.get("RADAR_LLM_KEY")
    model = os.environ.get("RADAR_LLM_MODEL", "gpt-4o-mini")
    if not (base and key):
        return {}
    briefs = [
        {
            "i": i,
            "name": c["full_name"],
            "desc": (c.get("description") or "")[:300],
            "topics": c.get("topics") or [],
            "stars": c.get("stargazers_count"),
        }
        for i, c in enumerate(cands[:top])
    ]
    prompt = (
        "你是 GitHub 猎手。下面是候选仓库，请挑出『真正好玩、有趣、有创意，或确实好用』的，"
        "给每个 0-10 的趣味分（fun）和 0-10 的实用分（useful），并写一句中文点评（28 字内，"
        "要具体说它把什么玩出了花，不要空话）。纯目录合集/刷榜/流量内容给低分。"
        '只输出 JSON：{"items":[{"i":0,"fun":9,"useful":6,"note":"..."}]}'
    )
    body = json.dumps(
        {
            "model": model,
            "temperature": 0.3,
            "messages": [
                {"role": "system", "content": prompt},
                {"role": "user", "content": json.dumps(briefs, ensure_ascii=False)},
            ],
        }
    ).encode("utf-8")
    req = urllib.request.Request(base.rstrip("/") + "/chat/completions", data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", f"Bearer {key}")
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            txt = json.loads(r.read().decode("utf-8"))["choices"][0]["message"]["content"]
        txt = re.sub(r"^```(?:json)?|```$", "", txt.strip(), flags=re.M).strip()
        items = json.loads(txt).get("items", [])
        return {cands[it["i"]]["full_name"]: it for it in items if "i" in it and it["i"] < len(cands)}
    except Exception as e:
        print(f"  ! LLM 复评失败（忽略）：{e}", file=sys.stderr)
        return {}


# ---------------------------------------------------------------------------
# 存储
# ---------------------------------------------------------------------------
def db() -> sqlite3.Connection:
    con = sqlite3.connect(DATA / "seen.sqlite3")
    con.execute(
        "CREATE TABLE IF NOT EXISTS seen(full_name TEXT PRIMARY KEY, first_seen TEXT, score REAL)"
    )
    return con


def auto_note(r: dict, sc: dict) -> str:
    desc = (r.get("description") or "").strip().rstrip(".")
    # 有中文描述就优先用中文首句（更适合直接读）
    m = re.search(r"[\u4e00-\u9fff][^。!?！？|｜]{0,90}", desc)
    if m:
        desc = m.group(0)
    elif len(desc) > 110:
        desc = desc[:108] + "…"
    tag = ("／".join(sc["tags"][:3])) or "工具"
    return f"{desc}（{tag}）"


def push_feishu(md_text: str) -> None:
    """可选：设置 RADAR_FEISHU_WEBHOOK=飞书自定义机器人 webhook 即可推送到群。"""
    hook = os.environ.get("RADAR_FEISHU_WEBHOOK")
    if not hook:
        return
    body = json.dumps({"msg_type": "text", "content": {"text": md_text[:4000]}}).encode("utf-8")
    req = urllib.request.Request(hook, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            print(f"  -> 飞书推送 HTTP {r.status}")
    except Exception as e:
        print(f"  ! 飞书推送失败：{e}", file=sys.stderr)


def render(day: str, scanned: int, kept: list[dict], meta: dict) -> str:
    L = [f"# Skill Radar · {day}", ""]
    L.append(f"> 扫描 {scanned} 个候选仓库 · 初筛通过 {meta['passed']} · 本轮推送 {len(kept)}")
    L.append("")
    if not kept:
        L.append("_今天没有新东西，调低 `--min-score` 或放宽 `--days` 再看看。_")
    for i, c in enumerate(kept, 1):
        r, sc = c["repo"], c["score"]
        L.append(f"## {i}. [{r['full_name']}]({r['html_url']})  ·  {sc['score']} 分")
        L.append("")
        note = c.get("llm_note") or auto_note(r, sc)
        L.append(f"- **一句话**：{note}")
        if c.get("llm_fun") is not None:
            L.append(f"- **LLM 打分**：好玩 {c['llm_fun']}/10 · 实用 {c['llm_useful']}/10")
        L.append("- **为什么值得看**：" + "；".join(sc["why"]))
        L.append(
            f"- **信号**：⭐{r.get('stargazers_count')} · 语言 {r.get('language') or '—'} · "
            f"最近推送 {(r.get('pushed_at') or '')[:10]} · 许可 {(r.get('license') or {}).get('spdx_id') or '无'}"
        )
        L.append(f"- **装法**：`git clone {r['clone_url']}`，看仓库里的 `SKILL.md`")
        L.append("")
    L.append("---")
    L.append(f"生成于 {dt.datetime.now().strftime('%Y-%m-%d %H:%M')} · 由 `radar.py` 自动产出")
    return "\n".join(L)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7, help="只看最近 N 天活跃的仓库，默认 7")
    ap.add_argument("--top", type=int, default=8, help="日报推送几条，默认 8")
    ap.add_argument("--min-score", type=float, default=45.0, help="入选门槛，默认 45")
    ap.add_argument("--no-seen", action="store_true", help="忽略已推送历史（调试用）")
    ap.add_argument("--no-llm", action="store_true", help="强制跳过 LLM 复评")
    args = ap.parse_args()

    token = os.environ.get("GITHUB_TOKEN")
    print(f"== skill-radar {dt.date.today()} | days={args.days} top={args.top} 门槛={args.min_score}")

    pool: dict[str, dict] = {}
    gap = 0.7 if token else 6.5  # 未认证时把 7 路查询摊到 1 分钟窗口外，避免连续 403
    for q, label in SEARCH_QUERIES:
        items = search_repos(q, args.days, token)
        print(f"  [{label}] {len(items)} 条")
        for it in items:
            pool[it["full_name"]] = it
        time.sleep(gap)

    print(f"  去重后候选 {len(pool)}")

    con = db()
    seen = set() if args.no_seen else {r[0] for r in con.execute("SELECT full_name FROM seen")}

    scored = []
    for name, r in pool.items():
        if not (r.get("description") or "").strip():
            continue
        sc = score_repo(r)
        scored.append({"repo": r, "score": sc})
    scored.sort(key=lambda x: x["score"]["score"], reverse=True)

    passed = [c for c in scored if c["score"]["score"] >= args.min_score]

    # 同一作者最多留 2 条，避免一个组织刷屏
    per_owner: dict[str, int] = {}
    fresh: list[dict] = []
    for c in passed:
        if c["repo"]["full_name"] in seen:
            continue
        owner = c["repo"]["owner"]["login"]
        if per_owner.get(owner, 0) >= 2:
            continue
        per_owner[owner] = per_owner.get(owner, 0) + 1
        fresh.append(c)
        if len(fresh) >= args.top * 3:
            break

    if fresh and not args.no_llm:
        judged = llm_judge([c["repo"] for c in fresh], args.top * 3)
        for c in fresh:
            j = judged.get(c["repo"]["full_name"])
            if j:
                c["llm_note"] = j.get("note")
                c["llm_fun"] = j.get("fun")
                c["llm_useful"] = j.get("useful")
                c["score"]["score"] = round(
                    c["score"]["score"] * 0.6 + (j.get("fun", 0) * 6 + j.get("useful", 0) * 4) * 0.4, 1
                )
        fresh.sort(key=lambda x: x["score"]["score"], reverse=True)

    kept = fresh[: args.top]

    day = dt.date.today().isoformat()
    md = render(day, len(pool), kept, {"passed": len(passed)})
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M")
    (REPORTS / f"{day}_{stamp}.md").write_text(md, encoding="utf-8")  # 每轮留档
    (REPORTS / f"{day}.md").write_text(md, encoding="utf-8")          # 当日最新
    (REPORTS / "latest.md").write_text(md, encoding="utf-8")          # 全局最新

    now = dt.datetime.now().isoformat(timespec="seconds")
    for c in kept:
        con.execute(
            "INSERT OR REPLACE INTO seen(full_name, first_seen, score) VALUES (?,?,?)",
            (c["repo"]["full_name"], now, c["score"]["score"]),
        )
    con.commit()

    (DATA / "last_run.json").write_text(
        json.dumps(
            {
                "at": now,
                "scanned": len(pool),
                "passed": len(passed),
                "pushed": [c["repo"]["full_name"] for c in kept],
                "report": str(REPORTS / f"{day}.md"),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print(f"== 入选 {len(kept)} 条 -> {REPORTS / (day + '.md')}")
    for c in kept:
        print(f"   {c['score']['score']:>5}  {c['repo']['full_name']}")
    if kept:
        push_feishu(md)
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
