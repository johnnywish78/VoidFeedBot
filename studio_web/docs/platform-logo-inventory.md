# VoidFeed Studio — Official Platform Logo Inventory

All marks live in `studio_web/icons/platforms/`. Source: Wikimedia Commons uploads of
official brand artwork; trademarks belong to their owners; use per each platform's brand
guidelines. `platformMarkHTML(id)` / `themedLogo(p)` are the single shared helpers used by
Profile, Connections and the editor's target-network chips/variants.

| Platform  | Asset (dark)          | Asset (light)         | Source (Wikimedia file)          | Notes |
|-----------|-----------------------|-----------------------|----------------------------------|-------|
| Telegram  | telegram.svg          | telegram.svg          | File:Telegram_logo.svg           | official plane-paper mark |
| Instagram | instagram.svg         | instagram.svg         | File:Instagram_logo_2016.svg     | official camera mark |
| Facebook  | facebook.svg          | facebook.svg          | File:Facebook_f_logo_(2019).svg  | official f mark |
| YouTube   | youtube.svg           | youtube.svg           | File:YouTube_full-color_icon_(2017).svg | official play-button |
| X        | x-white.svg            | x.svg                 | File:X_logo_2023_(white).svg / File:X_logo_2023.svg | theme-aware white/black |
| TikTok    | tiktok-symbol.svg     | tiktok-symbol.svg     | File:TikTok_logo.svg (glyph paths extracted; cyan #00F2EA / red #FF004F) | symbol only, no wordmark |
| Quora    | quora.svg             | quora.svg             | File:Quora_logo.svg              | official mark |
| Discord   | discord.svg             | discord.svg             | Extracted verbatim from the official Discord logo (en.wikipedia File:Discord logo.svg, sourced from discord.com/branding); Clyde symbol-only, blurple #5865f2 | official symbol (Clyde) |
| Clubhouse | clubhouse.svg           | clubhouse.svg           | Commons File:Clubhouse App Logo.svg (from official press kit, clubhouse.com/press) | official mark |

Usage rules:
- Never redraw/recolor/reinterpret official marks; X white/black variants are official files.
- Never render the wide TikTok wordmark — only the official musical-note symbol.
- logos are displayed inside a consistent 40×40 frame (`.p-logo`) / 36px optical height for `.plat-logo`.
- Discord now uses the standalone Clyde symbol (wordmark text stripped); Clubhouse uses its official mark. Both fit the 40×40 frame via box-fit.
