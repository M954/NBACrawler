"""生成推文演示数据，用于展示和测试。"""

import json
import random
from datetime import datetime, timezone, timedelta
from pathlib import Path

OUTPUT_DIR = Path(__file__).resolve().parent / "output"

# 球星推文种子数据
PLAYER_TWEETS = {
    "KingJames": {
        "name": "LeBron James",
        "tweets": [
            "What a W tonight! 40 points and the dub 💪🏾 #LakeShow",
            "Year 22 and still going strong. Built different 👑",
            "Game day vibes! Let's get this win tonight 🏀",
            "Shoutout to the young guys stepping up. That's what it's about 💯",
            "Another day another opportunity to be great. Blessed 🙏🏾",
            "Playoff mode activated 🔥 This is what we live for",
            "Great team win! Everyone contributed tonight 💜💛",
            "Recovery day. Ice bath and film study 📺",
            "Love this game. 22 years and the passion hasn't changed ❤️",
            "To the best fans in the world, thank you! #LakerNation"
        ]
    },
    "StephenCurry30": {
        "name": "Stephen Curry",
        "tweets": [
            "Night night 😴 Another splash party at the Chase Center 💦",
            "3-point record keeps growing. God is good 🙏",
            "Game day! Let's cook tonight 🍳 #DubNation",
            "Ayesha's dinner > everything. Family first always ❤️",
            "12 threes tonight! New season high 🎯",
            "Underrated is overrated. Just keep working 💪",
            "Great practice today. Feeling locked in for the playoffs 🔒",
            "Blessed to do what I love every single day 🏀",
            "Bay Area love is unmatched! #Warriors",
            "Back-to-back wins! Let's keep this energy going 🔥"
        ]
    },
    "KDTrey5": {
        "name": "Kevin Durant",
        "tweets": [
            "Hooping is life. Simple as that 🏀",
            "35 tonight. Just another day at the office 💼",
            "People talk too much. Let the game speak 🤫",
            "Midrange is an art form. Don't let them tell you otherwise",
            "Great win on the road. Tough team we got 💪",
            "Film session at 6am. Greatness doesn't sleep 📽️",
            "Grateful for every moment on this court 🙏",
            "The game never lies. Put in the work 💯",
            "Phoenix rising 🌅 #ValleyBoys",
            "Another chapter, same dedication. Book ain't finished yet 📖"
        ]
    },
    "Giannis_An34": {
        "name": "Giannis Antetokounmpo",
        "tweets": [
            "From Sepolia to the NBA. Never stop dreaming 🇬🇷",
            "Triple double tonight! God is great 🙏",
            "Smoothie time after the game! Recovery is key 🥤",
            "Bucks in 6! Always believe 🦌",
            "Hard work beats talent when talent doesn't work hard 💪",
            "Family day with the boys. Best feeling ever ❤️",
            "40 and 15 tonight! Let's gooooo 🔥",
            "Thank you Milwaukee. This city is home 🏠",
            "Every day I wake up and try to be better than yesterday",
            "Playoff time is the best time. Let's compete 🏆"
        ]
    },
    "jaytatum0": {
        "name": "Jayson Tatum",
        "tweets": [
            "Championship mentality every single day 🏆 #Celtics",
            "Deuce is my biggest motivation 💚 Dad life",
            "50 piece tonight! St. Louis built different 🎯",
            "Green runs deep in this city. #BleedGreen ☘️",
            "Team basketball at its finest. Everyone ate tonight 🍽️",
            "Early morning workout. No days off 💪",
            "Banner 18 is the only goal. Everything else is noise",
            "Grateful for this journey. From Duke to Boston 🙏",
            "Big game Friday! TD Garden is going to be rocking 🔊",
            "Defense wins championships. We locked them up tonight 🔒"
        ]
    },
    "JoelEmbiid": {
        "name": "Joel Embiid",
        "tweets": [
            "Trust the process since day 1. Still trusting 🙏",
            "MVP mode activated 🏀 #HereTheyCome",
            "Philly love is different. This city rides with me 💙",
            "Cameroon to the NBA. Dreams do come true 🇨🇲",
            "40 and 13 tonight. Just getting started 🔥",
            "Recovery day. Knee feeling good 💪",
            "Shoutout to my guy Maxey for that game winner!",
            "We're building something special here in Philly",
            "Game face on. It's showtime 🎭",
            "Blessed beyond measure. Thank you God 🙏"
        ]
    },
    "JaMorant": {
        "name": "Ja Morant",
        "tweets": [
            "Point god activities 🏀 Too quick for you",
            "Memphis stand up! Grizz nation is the best 🐻",
            "Highlight reel every night. That's just how I play 🎬",
            "Young king on a mission 👑 #GritGrind",
            "Dunk of the year? Maybe 😤",
            "Family over everything. Mom and dad sacrificed so much ❤️",
            "30 and 10 tonight! PG things 💯",
            "We young but we dangerous. Watch out 🔥",
            "Beale Street built different. Memphis forever 🎵",
            "Just a kid from Dalzell, SC living his dream"
        ]
    },
    "DevinBooker": {
        "name": "Devin Booker",
        "tweets": [
            "Mamba mentality forever 🐍 Rest in peace Kobe",
            "70 once, and I'll do it again if needed 🎯",
            "Valley love 🌵 #Suns #RallyTheValley",
            "Smooth operator on and off the court 😎",
            "Another 40 piece. Scorers score 🏀",
            "Playoff Book is a different animal 🔥",
            "Grateful for the opportunity to compete every night 🙏",
            "Footwork and fundamentals. The basics never get old",
            "Phoenix is home. This city deserves a championship 🏆",
            "Late night gym session. The work doesn't stop 💪"
        ]
    },
    "Dame_Lillard": {
        "name": "Damian Lillard",
        "tweets": [
            "Dame Time ⌚ You know what time it is",
            "Oakland to the league. Never forget where I came from 🏙️",
            "Logo Lillard from 35 feet. BANG! 🎯",
            "New chapter in Milwaukee. Excited for what's ahead 🦌",
            "Music dropping soon! Studio session was fire tonight 🎤",
            "Loyalty is everything. Real ones know 💯",
            "50 tonight! When the clock strikes Dame Time ⏰",
            "Big shot DNA. I was born for these moments 🧬",
            "Working on my craft every single day. No shortcuts",
            "Blessed to play this game at the highest level 🙏"
        ]
    },
    "JimmyButler": {
        "name": "Jimmy Butler",
        "tweets": [
            "Playoff Jimmy is inevitable 🔥 #HimSZN",
            "Big Face Coffee open for business ☕ $20 a cup",
            "Work ethic over talent. Every single time 💪",
            "They didn't want me. Now they can't stop me 😤",
            "Fashion week vibes 👗 Style is everything",
            "Great win! Team played with heart tonight ❤️",
            "From Tomball, Texas to the big stage. God's plan 🙏",
            "No days off. The gym is my second home 🏋️",
            "Warriors chapter begins. Let's get to work 🏀",
            "Emo Jimmy era continues 🖤 Vibes."
        ]
    },
}

def generate_demo_tweets():
    """生成演示推文数据。"""
    tweets = []
    now = datetime.now(timezone.utc)

    for handle, data in PLAYER_TWEETS.items():
        for i, content in enumerate(data["tweets"]):
            tweet_id = str(random.randint(1800000000000000000, 1899999999999999999))
            tweet_date = now - timedelta(hours=random.randint(1, 168), minutes=random.randint(0, 59))

            tweet = {
                "tweet_id": tweet_id,
                "player_name": data["name"],
                "player_handle": handle,
                "content": content,
                "content_cn": None,  # 稍后翻译
                "url": f"https://x.com/{handle}/status/{tweet_id}",
                "media_urls": [],
                "cover_image_path": None,
                "retweet_count": random.randint(500, 50000),
                "like_count": random.randint(2000, 200000),
                "reply_count": random.randint(100, 10000),
                "tweet_type": random.choices(
                    ["original", "retweet", "quote", "reply"],
                    weights=[70, 10, 10, 10]
                )[0],
                "tweet_date": tweet_date.isoformat(),
                "scraped_at": now.isoformat(),
                "translation_status": "pending",
            }
            tweets.append(tweet)

    return tweets


def main():
    tweets = generate_demo_tweets()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = OUTPUT_DIR / "tweets.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(tweets, f, ensure_ascii=False, indent=2)
    print(f"已生成 {len(tweets)} 条演示推文 -> {output_path}")

    # 尝试翻译
    try:
        import asyncio
        from translator.google_translator import DeepTranslatorBackend
        from config.glossary import expand_twitter_slang, TWITTER_POST_FIXES, POST_TRANSLATION_FIXES

        async def translate_all():
            backend = DeepTranslatorBackend()
            for i, tweet in enumerate(tweets):
                try:
                    text = expand_twitter_slang(tweet["content"])
                    cn = await backend.translate(text)
                    for wrong, right in TWITTER_POST_FIXES.items():
                        cn = cn.replace(wrong, right)
                    for wrong, right in POST_TRANSLATION_FIXES.items():
                        cn = cn.replace(wrong, right)
                    tweet["content_cn"] = cn
                    tweet["translation_status"] = "completed"
                    if (i + 1) % 10 == 0:
                        print(f"  翻译进度: {i+1}/{len(tweets)}")
                except Exception as e:
                    tweet["translation_status"] = "failed"
                    print(f"  翻译失败 [{tweet['player_handle']}]: {e}")

            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(tweets, f, ensure_ascii=False, indent=2)
            completed = sum(1 for t in tweets if t["translation_status"] == "completed")
            print(f"翻译完成: {completed}/{len(tweets)}")

        asyncio.run(translate_all())
    except Exception as e:
        print(f"翻译跳过: {e}")


if __name__ == "__main__":
    main()
