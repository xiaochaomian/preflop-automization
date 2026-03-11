"""Debug script: connect to a PokerNow game and dump DOM structure for cards/stacks.

Usage: python debug_dom.py --url <game_url>
"""

import asyncio
import argparse
import json
from playwright.async_api import async_playwright


async def dump_dom(url: str) -> None:
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=False)
    page = await browser.new_page()
    await page.goto(url, wait_until="domcontentloaded")

    print("Page loaded. Waiting 8s for game to render...")
    await asyncio.sleep(8)

    # Massive DOM dump to find the right selectors
    data = await page.evaluate(r"""() => {
        const result = {};

        // Dump ALL elements with 'card' in class name
        result.cardElements = [];
        document.querySelectorAll('[class*="card"]').forEach(el => {
            result.cardElements.push({
                tag: el.tagName,
                className: el.className,
                id: el.id,
                text: el.textContent?.trim()?.substring(0, 100),
                dataAttrs: Object.fromEntries(
                    [...el.attributes].filter(a => a.name.startsWith('data-')).map(a => [a.name, a.value])
                ),
                parentClass: el.parentElement?.className || '',
                childCount: el.children.length,
                innerHTML: el.innerHTML?.substring(0, 300),
            });
        });

        // Dump ALL elements with 'player' in class name
        result.playerElements = [];
        document.querySelectorAll('[class*="player"]').forEach(el => {
            result.playerElements.push({
                tag: el.tagName,
                className: el.className,
                text: el.textContent?.trim()?.substring(0, 200),
                dataAttrs: Object.fromEntries(
                    [...el.attributes].filter(a => a.name.startsWith('data-')).map(a => [a.name, a.value])
                ),
            });
        });

        // Dump elements with 'pot' or 'stack' in class
        result.potStack = [];
        document.querySelectorAll('[class*="pot"], [class*="stack"], [class*="chips"], [class*="bet"]').forEach(el => {
            result.potStack.push({
                tag: el.tagName,
                className: el.className,
                text: el.textContent?.trim()?.substring(0, 100),
            });
        });

        // Dump elements with 'dealer' or 'button' in class
        result.dealer = [];
        document.querySelectorAll('[class*="dealer"], [class*="button"], [class*="btn"]').forEach(el => {
            result.dealer.push({
                tag: el.tagName,
                className: el.className,
                text: el.textContent?.trim()?.substring(0, 100),
            });
        });

        // Dump the game log area
        result.logElements = [];
        document.querySelectorAll('[class*="log"], [class*="history"], [class*="message"], [class*="chat"]').forEach(el => {
            if (el.children.length < 50) {
                result.logElements.push({
                    tag: el.tagName,
                    className: el.className,
                    text: el.textContent?.trim()?.substring(0, 300),
                });
            }
        });

        // Try to find the "you" player specifically
        result.youPlayer = [];
        document.querySelectorAll('[class*="you"], [class*="self"], [class*="me-"], [class*="my-"]').forEach(el => {
            result.youPlayer.push({
                tag: el.tagName,
                className: el.className,
                text: el.textContent?.trim()?.substring(0, 200),
                innerHTML: el.innerHTML?.substring(0, 500),
            });
        });

        // Dump elements with suit-related content (hearts, spades, etc)
        result.suitElements = [];
        document.querySelectorAll('[class*="suit"], [class*="heart"], [class*="spade"], [class*="club"], [class*="diamond"]').forEach(el => {
            result.suitElements.push({
                tag: el.tagName,
                className: el.className,
                text: el.textContent?.trim()?.substring(0, 100),
                innerHTML: el.innerHTML?.substring(0, 300),
            });
        });

        // Dump elements with rank-related content
        result.rankElements = [];
        document.querySelectorAll('[class*="rank"], [class*="value"]').forEach(el => {
            result.rankElements.push({
                tag: el.tagName,
                className: el.className,
                text: el.textContent?.trim()?.substring(0, 100),
            });
        });

        // Dump the full body class list and first-level structure
        result.bodyClasses = document.body.className;
        result.topLevelDivs = [];
        document.body.querySelectorAll(':scope > div, :scope > main, :scope > section').forEach(el => {
            result.topLevelDivs.push({
                tag: el.tagName,
                className: el.className,
                id: el.id,
            });
        });

        return result;
    }""")

    # Write to file
    with open("/Users/michaeljiao/Desktop/pokerbot/dom_dump.json", "w") as f:
        json.dump(data, f, indent=2)

    print(f"DOM dump saved to dom_dump.json")
    print(f"\nCard elements found: {len(data.get('cardElements', []))}")
    print(f"Player elements found: {len(data.get('playerElements', []))}")
    print(f"Pot/Stack elements found: {len(data.get('potStack', []))}")
    print(f"Suit elements found: {len(data.get('suitElements', []))}")
    print(f"Rank elements found: {len(data.get('rankElements', []))}")
    print(f"You-player elements found: {len(data.get('youPlayer', []))}")
    print(f"Log elements found: {len(data.get('logElements', []))}")

    # Print summaries
    for section in ['cardElements', 'playerElements', 'suitElements', 'youPlayer']:
        items = data.get(section, [])
        if items:
            print(f"\n--- {section} ---")
            for item in items[:15]:
                print(f"  <{item['tag']}> class=\"{item.get('className','')}\" text=\"{item.get('text','')}\"")

    print("\nBrowser staying open. Press Ctrl+C to quit.")
    try:
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        await browser.close()
        await pw.stop()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    args = parser.parse_args()
    asyncio.run(dump_dom(args.url))
