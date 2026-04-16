"""Claude 智能模块 — 通过 CLI 调用 Claude 提供智能分析能力。"""

import subprocess
import json
import sys
import io

if sys.platform == "win32":
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    except Exception:
        pass

CLAUDE_EXE = r"C:\Users\xuqin\.local\bin\claude.exe"


def ask_claude(prompt: str, timeout: int = 120) -> str:
    """调用 Claude CLI 获取回答。"""
    try:
        result = subprocess.run(
            [CLAUDE_EXE, "--bare", "-p", prompt],
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
        )
        if result.returncode != 0:
            print(f"  [Claude ERR] exit={result.returncode}: {result.stderr[:100]}")
            return ""
        answer = result.stdout.strip()
        # 检测 AI 拒绝回复
        refusal_patterns = [
            "I'm sorry", "I cannot assist", "I can't assist",
            "I apologize", "I'm unable to", "I cannot help",
            "请提供", "请补充", "无法核实", "无法验证",
        ]
        if any(p.lower() in answer.lower() for p in refusal_patterns):
            print(f"  [Claude REFUSAL] detected, returning empty")
            return ""
        return answer
    except subprocess.TimeoutExpired:
        print(f"  [Claude TIMEOUT] {timeout}s")
        return ""
    except Exception as e:
        print(f"  [Claude ERR] {e}")
        return ""


def interpret_emoji_tweet(emoji_text: str, player_name: str) -> str:
    """解读纯 emoji / 标签推文的含义。"""
    prompt = (
        f"NBA player {player_name} posted this tweet: \"{emoji_text}\"\n"
        f"Please interpret what this tweet means in the context of NBA basketball. "
        f"Reply in Chinese (2-3 sentences max). Be concise and insightful. "
        f"Consider the player's personality and current NBA events."
    )
    return ask_claude(prompt, timeout=30)


def enrich_retweet(original_content: str, retweeter: str, original_author: str = "") -> str:
    """为转推/引用推文生成上下文解说。"""
    prompt = (
        f"NBA player {retweeter} retweeted/quoted this content:\n"
        f"\"{original_content}\"\n"
        f"{'Original author: ' + original_author if original_author else ''}\n"
        f"Please provide a brief Chinese commentary (2-3 sentences) explaining "
        f"why this retweet is significant and what context NBA fans should know."
    )
    return ask_claude(prompt, timeout=30)


def improve_translation(english: str, machine_translation: str, player_name: str) -> str:
    """用 Claude 优化机器翻译质量。"""
    prompt = (
        f"NBA player {player_name} tweeted: \"{english}\"\n"
        f"Machine translation: \"{machine_translation}\"\n"
        f"Please provide a better Chinese translation that:\n"
        f"1. Fixes any errors (especially NBA terminology and player names)\n"
        f"2. Sounds natural in Chinese\n"
        f"3. Keeps the original tone and meaning\n"
        f"Reply with ONLY the improved Chinese translation, nothing else."
    )
    return ask_claude(prompt, timeout=30)


def suggest_music(content: str, player_name: str) -> str:
    """推荐最适合的背景音乐风格。"""
    prompt = (
        f"NBA content from {player_name}: \"{content[:200]}\"\n"
        f"Suggest the most suitable background music mood for a short video of this tweet.\n"
        f"Reply with exactly ONE word: chill, hype, or emotional"
    )
    result = ask_claude(prompt, timeout=15)
    result = result.strip().lower()
    if result in ("chill", "hype", "emotional"):
        return result
    return "chill"


def generate_event_narration(tweets: list[dict]) -> str:
    """为一组相关推文生成串联解说词。"""
    tweet_summaries = []
    for t in tweets:
        name = t.get("player_name", "?")
        content = t.get("content", "")[:150]
        cn = (t.get("content_cn") or "")[:100]
        tweet_summaries.append(f"- @{name}: {content}\n  (翻译: {cn})")

    tweets_text = "\n".join(tweet_summaries)
    prompt = (
        f"These NBA tweets are related to the same event/topic:\n{tweets_text}\n\n"
        f"Please generate a cohesive Chinese narration (4-6 sentences) that:\n"
        f"1. Connects these tweets into a story\n"
        f"2. Provides context for Chinese NBA fans\n"
        f"3. Is engaging and suitable for a short video voiceover\n"
        f"Reply with ONLY the Chinese narration."
    )
    return ask_claude(prompt, timeout=45)


def group_related_tweets(tweets: list[dict]) -> list[list[dict]]:
    """将推文按事件/话题分组。"""
    if len(tweets) <= 3:
        return [tweets]

    # 提取推文摘要给 Claude 分组
    summaries = []
    for i, t in enumerate(tweets):
        name = t.get("player_name", "?")
        content = t.get("content", "")[:100]
        date = t.get("tweet_date", "")[:10]
        summaries.append(f"{i}: [{date}] @{name}: {content}")

    summaries_text = "\n".join(summaries)
    prompt = (
        f"Group these NBA tweets by related events/topics. Tweets about the "
        f"same game, same player event, or same topic should be grouped together.\n\n"
        f"{summaries_text}\n\n"
        f"Reply in this JSON format ONLY (no other text):\n"
        f'[["0","1","3"], ["2","4"], ["5","6","7"]]\n'
        f"Each inner array contains tweet indices that belong to the same group."
    )

    result = ask_claude(prompt, timeout=30)

    # 解析分组结果
    try:
        # 尝试从回复中提取 JSON
        import re
        json_match = re.search(r'\[.*\]', result, re.DOTALL)
        if json_match:
            groups_raw = json.loads(json_match.group())
            groups = []
            used = set()
            for group in groups_raw:
                indices = [int(idx) for idx in group if int(idx) < len(tweets)]
                group_tweets = [tweets[i] for i in indices if i not in used]
                for i in indices:
                    used.add(i)
                if group_tweets:
                    groups.append(group_tweets)
            # 添加未分组的
            for i, t in enumerate(tweets):
                if i not in used:
                    groups.append([t])
            return groups
    except Exception:
        pass

    # 降级：按日期分组
    from collections import defaultdict
    by_date = defaultdict(list)
    for t in tweets:
        day = t.get("tweet_date", "")[:10]
        by_date[day].append(t)
    return list(by_date.values())


if __name__ == "__main__":
    # 简单测试
    print("=== Claude Intelligence Module Test ===\n")

    print("1. Emoji interpretation:")
    result = interpret_emoji_tweet("🤞🏾♾🪶⏰", "Kyrie Irving")
    print(f"   {result}\n")

    print("2. Translation improvement:")
    result = improve_translation(
        "Wow! What a chip Rory on 17!! 😱🔥🔥",
        "哇！ 17岁的罗里真是太棒了！",
        "LeBron James"
    )
    print(f"   {result}\n")

    print("3. Music suggestion:")
    result = suggest_music("PLAYOFFS BOUND ‼️", "CJ McCollum")
    print(f"   {result}\n")

    print("Done!")
